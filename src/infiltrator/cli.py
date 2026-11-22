"""infiltrator: point it at a pile of arcade files, get a shelf of games."""

import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Annotated

import click
import typer

from infiltrator.catalogue import connect
from infiltrator.catalogue.arrivals import arrived_since, window_start
from infiltrator.catalogue.games import sync_games
from infiltrator.catalogue.issues import list_issues, log_issue
from infiltrator.catalogue.tuning import set_tuning
from infiltrator.catalogue.tv import demo_since, end_demo, set_tv_persona, start_demo, tv_persona
from infiltrator.config import Settings, load_settings
from infiltrator.dat import DEFAULT_EMULATOR, Dat
from infiltrator.dats import default_wanted, load_dats
from infiltrator.library import move_flat_library
from infiltrator.metadata import load_metadata
from infiltrator.names import title
from infiltrator.personas import (
    GAMEPAD,
    LIGHT_GUN,
    SPINNERS,
    Persona,
    list_personas,
    load_persona,
    save_persona,
)
from infiltrator.safety import DropFolderBusy
from infiltrator.shelf import (
    add,
    build_shelf,
    current_shelf,
    demo_shelf,
    drop,
    fill_demo_shelf,
    fill_shelf,
    rotate,
)
from infiltrator.sieve import SieveReport, run_sieve
from infiltrator.tv import preflight, publish_tv, tell_romm

app = typer.Typer(help="Slip into the stack, make it work, sneak back out.", no_args_is_help=True)
persona_app = typer.Typer(help="Who's playing.", no_args_is_help=True)
shelf_app = typer.Typer(help="What's on the shelf.", no_args_is_help=True)
issue_app = typer.Typer(help="Note a game that misbehaved.", no_args_is_help=True)
tune_app = typer.Typer(help="Save what it took to make a game play right.", no_args_is_help=True)
app.add_typer(persona_app, name="persona")
app.add_typer(shelf_app, name="shelf")
app.add_typer(issue_app, name="issue")
app.add_typer(tune_app, name="tune")

TRY_AGAIN = "Try again later!"
BUSY_EXIT = 75  # EX_TEMPFAIL: still copying in; the service treats it as success
SETTLE_SECONDS = 5.0  # how long the drop folder must sit still before the sieve trusts it
INPUT_CHOICES = {1: GAMEPAD, 2: GAMEPAD | SPINNERS, 3: GAMEPAD | SPINNERS | LIGHT_GUN}

Verbose = Annotated[bool, typer.Option("--verbose", "-v", help="Show the nerd stuff.")]
New = Annotated[
    bool, typer.Option("--new", help="Only the games that arrived in the last 24 hours.")
]
Days = Annotated[
    int | None,
    typer.Option("--days", min=1, help="With --new: look back this many days instead of one."),
]


def _settings() -> Settings:
    return load_settings()


def _mame_dat(settings: Settings) -> Dat:
    """The MAME 2003-Plus set list: the only emulator the pipeline builds for so far."""
    return load_dats(settings)[DEFAULT_EMULATOR]


def _library_ready(settings: Settings) -> None:
    """Before anything reads or writes the library: move an old flat one into place."""
    move_flat_library(settings.library_dir)


def _db(settings: Settings) -> sqlite3.Connection:
    return connect(settings.db_path)


def _sync(settings: Settings, dats: Mapping[str, Dat], conn: sqlite3.Connection) -> int:
    # The metadata files are keyed by MAME names, replayed from MAME 0.78's: MAME's DAT only.
    meta = load_metadata(settings.metadata_dir, dats[DEFAULT_EMULATOR])
    return sync_games(conn, settings.library_dir, dats, meta)


def _give_up(err: Exception, verbose: bool, code: int = 1) -> typer.Exit:
    """The person sees one line; --verbose shows why."""
    typer.echo(TRY_AGAIN)
    if verbose:
        typer.echo(f"  ({type(err).__name__}: {err})")
    return typer.Exit(code)


@contextmanager
def _or_try_again_later(verbose: bool) -> Iterator[None]:
    try:
        yield
    except typer.Exit:
        raise
    except Exception as err:
        raise _give_up(err, verbose) from err


def _sync_tv(settings: Settings, dat: Dat, conn: sqlite3.Connection) -> None:
    """Fill the TV shelf's empty slots, publish it, and tell RomM anything it missed.

    Every sieve runs this, new games or not, so a publish or a RomM call that
    failed last time is retried until the TV matches the shelf.
    """
    persona = tv_persona(conn)
    if persona is None:
        return
    _top_up(settings, conn, load_persona(conn, persona))
    publish_tv(settings, dat, conn)
    tell_romm(settings, conn)


def _top_up(settings: Settings, conn: sqlite3.Connection, who: Persona) -> None:
    """Fill the TV shelf's empty slots; during a demo, only with games new since it began."""
    since = demo_since(conn)
    if since is None:
        fill_shelf(conn, who, settings.shelf_size)
    else:
        fill_demo_shelf(
            conn, who, settings.shelf_size, arrived_since(conn, DEFAULT_EMULATOR, since)
        )


def _tell_romm_or_shrug(settings: Settings, conn: sqlite3.Connection, verbose: bool) -> None:
    """At a shell, the change is made already; RomM catching up is the sieve timer's job."""
    try:
        tell_romm(settings, conn)
    except Exception as err:
        typer.echo("The TV will catch up shortly.")
        if verbose:
            typer.echo(f"  ({type(err).__name__}: {err})")


def _label(emulator: str, set_name: str) -> str:
    """A set as the nerd output names it: bare for MAME 2003-Plus, as it always was."""
    return set_name if emulator == DEFAULT_EMULATOR else f"{emulator}/{set_name}"


def _new_titles(dat: Dat, set_names: list[str]) -> dict[str, list[str]]:
    """One line per game, not per version: two Heavy Barrels are one new game."""
    by_family: dict[str, list[str]] = {}
    for name in set_names:
        by_family.setdefault(dat.family(dat.games[name]), []).append(name)
    titles: dict[str, list[str]] = {}
    for family, names in by_family.items():
        root = dat.games.get(family) or dat.games[names[0]]
        titles.setdefault(title(root.description), []).extend(
            _label(dat.emulator, n) for n in names
        )
    return titles


def _all_new_titles(dats: Mapping[str, Dat], report: SieveReport) -> dict[str, list[str]]:
    """New games of every emulator; one title is one line, whichever emulators it came in."""
    titles: dict[str, list[str]] = {}
    for emulator, names in report.new_games.items():
        for game_title, labels in _new_titles(dats[emulator], names).items():
            titles.setdefault(game_title, []).extend(labels)
    return titles


def _echo_sieved(dats: Mapping[str, Dat], report: SieveReport, verbose: bool) -> None:
    """Titles for the person; with --verbose, every file and set the sieve touched."""
    for game_title, names in _all_new_titles(dats, report).items():
        line = f"New: {game_title}"
        typer.echo(f"{line}  [{', '.join(names)}]" if verbose else line)
    if not any(report.new_games.values()):
        typer.echo("Nothing new.")
    rars = [p for p in report.left_alone if p.suffix.lower() == ".rar"]
    if rars:
        typer.echo(f"Left alone: {len(rars)} .rar file(s), not supported yet.")
    if verbose:
        _echo_sieve_details(report)


def _echo_sieve_details(report: SieveReport) -> None:
    for path in report.deleted:
        typer.echo(f"  deleted {path}")
    for path in report.left_alone:
        typer.echo(f"  left alone {path}")
    for path, emulators in report.held.items():
        typer.echo(f"  held for {', '.join(emulators)}: {path} has chips no library set holds")
    for emulator, names in report.new_bios.items():
        for name in names:
            typer.echo(f"  bios {_label(emulator, name)}")
    for emulator, names in report.blocked.items():
        for name in names:
            typer.echo(
                f"  not overwritten: {_label(emulator, name)}.zip is in the library "
                "but isn't this set"
            )


@app.command()
def sieve(verbose: Verbose = False) -> None:
    """Keep the real games from the drop folder; delete the rest."""
    settings = _settings()
    try:
        _library_ready(settings)
    except Exception as err:
        raise _give_up(err, verbose) from err
    dats = load_dats(settings)
    dat = dats[DEFAULT_EMULATOR]
    conn = _db(settings)
    try:
        report = run_sieve(
            settings,
            dats,
            wanted=default_wanted(dats),  # FBNeo: nothing yet; the next step asks tuning
            settle_seconds=SETTLE_SECONDS,
            on_library_changed=lambda: _sync(settings, dats, conn),
        )
    except DropFolderBusy as err:
        raise _give_up(err, verbose, BUSY_EXIT) from err
    except Exception as err:
        raise _give_up(err, verbose) from err
    _echo_sieved(dats, report, verbose)
    with _or_try_again_later(verbose):
        _sync_tv(settings, dat, conn)


@app.command()
def rescan() -> None:
    """Rebuild the game list from the library."""
    settings = _settings()
    _library_ready(settings)
    count = _sync(settings, load_dats(settings), _db(settings))
    typer.echo(f"{count} games in the library.")


@persona_app.command("add")
def persona_add(name: str) -> None:
    """Answer a few questions about who's playing."""
    language = typer.prompt("Language (or 'any')", default="English")
    kids = typer.confirm("Is anyone playing under 18?", default=False)
    players = typer.prompt(
        "Solo, together, or any?",
        default="any",
        type=click.Choice(["solo", "together", "any"]),
        show_choices=False,
    )
    plugged = typer.prompt(
        "What's plugged in? 1) a gamepad or joystick  2) also a spinner or trackball  "
        "3) also a light gun",
        default=1,
        type=click.IntRange(1, 3),
    )
    one_handed = typer.confirm("One hand or one button only?", default=False)
    favourites = typer.prompt("Favourite games, comma-separated", default="", show_default=False)
    persona = Persona(
        name=name,
        language=None if language.strip().lower() == "any" else language.strip(),
        mature_ok=not kids,
        players=players,
        controls=INPUT_CHOICES[plugged],
        one_handed=one_handed,
        must_haves=tuple(t.strip() for t in favourites.split(",") if t.strip()),
    )
    save_persona(_db(_settings()), persona)
    typer.echo(f"Saved {name}.")


@persona_app.command("list")
def persona_list() -> None:
    for name in list_personas(_db(_settings())):
        typer.echo(name)


def _persona(conn: sqlite3.Connection, name: str) -> Persona:
    try:
        return load_persona(conn, name)
    except KeyError as err:
        typer.echo(f"No one called {name} yet. Try: infiltrator persona add {name}")
        raise typer.Exit(1) from err


@app.command()
def play(persona: str, new: New = False, days: Days = None, verbose: Verbose = False) -> None:
    """Put this persona's shelf on the TV."""
    if days is not None and not new:
        raise typer.BadParameter("goes with --new.", param_hint="--days")
    if new:
        _play_new(persona, days or 1, verbose)
        return
    settings = _settings()
    conn = _db(settings)
    who = _persona(conn, persona)
    with _or_try_again_later(verbose):
        _library_ready(settings)
        dat = _mame_dat(settings)
        preflight(settings)
        set_tv_persona(conn, persona)
        fill_shelf(conn, who, settings.shelf_size)
        publish_tv(settings, dat, conn)
    _tell_romm_or_shrug(settings, conn, verbose)
    shelf_show(persona)


def _window_words(days: int) -> str:
    return "the last 24 hours" if days == 1 else f"the last {days} days"


def _play_new(persona: str, days: int, verbose: bool) -> None:
    """Put the last *days* of arrivals on the TV as this persona's shelf, until a normal play."""
    settings = _settings()
    conn = _db(settings)
    who = _persona(conn, persona)
    since = window_start(days)
    with _or_try_again_later(verbose):
        _library_ready(settings)
        dat = _mame_dat(settings)
        preflight(settings)
        if not demo_shelf(
            conn, who, settings.shelf_size, arrived_since(conn, DEFAULT_EMULATOR, since)
        ):
            typer.echo(f"Nothing new for {persona} in {_window_words(days)}.")
            return
        set_tv_persona(conn, persona)
        start_demo(conn, since)
        publish_tv(settings, dat, conn)
    _tell_romm_or_shrug(settings, conn, verbose)
    shelf_show(persona)


@contextmanager
def _changing_shelf(settings: Settings, conn: sqlite3.Connection, persona: str) -> Iterator[None]:
    """Around a shelf change: refuse before it if the TV can't follow, publish after it."""
    on_tv = tv_persona(conn) == persona
    with _or_try_again_later(verbose=False):
        _library_ready(settings)
        dat = _mame_dat(settings) if on_tv else None
        if on_tv:
            preflight(settings)
        yield
        if on_tv:
            end_demo(conn)
            publish_tv(settings, dat, conn)


@shelf_app.command("show")
def shelf_show(persona: str) -> None:
    conn = _db(_settings())
    _persona(conn, persona)
    rows = current_shelf(conn, persona)
    if not rows:
        typer.echo("The shelf is empty. Try: infiltrator shelf build " + persona)
    for row in rows:
        typer.echo(row["title"])


@shelf_app.command("build")
def shelf_build(persona: str) -> None:
    settings = _settings()
    conn = _db(settings)
    who = _persona(conn, persona)
    with _changing_shelf(settings, conn, persona):
        build_shelf(conn, who, settings.shelf_size)
    _tell_romm_or_shrug(settings, conn, verbose=False)
    shelf_show(persona)


@shelf_app.command("rotate")
def shelf_rotate(persona: str, count: Annotated[int, typer.Option(min=1)] = 1) -> None:
    """Swap the longest-shelved games for fresh ones."""
    settings = _settings()
    conn = _db(settings)
    who = _persona(conn, persona)
    with _changing_shelf(settings, conn, persona):
        out, incoming = rotate(conn, who, settings.shelf_size, count)
    if not incoming:
        typer.echo("Nothing new to rotate in.")
    _echo_moves(conn, out, incoming)
    _tell_romm_or_shrug(settings, conn, verbose=False)


def _mame_titles(conn: sqlite3.Connection) -> dict[str, str]:
    """Set name → title, for the MAME 2003-Plus sets: the only ones a shelf holds so far."""
    rows = conn.execute("SELECT set_name, title FROM games WHERE emulator = ?", (DEFAULT_EMULATOR,))
    return {r["set_name"]: r["title"] for r in rows}


def _echo_moves(conn: sqlite3.Connection, out: list[str], incoming: list[str]) -> None:
    """One line per game that left or arrived, by title."""
    titles = _mame_titles(conn)
    for name in out:
        typer.echo(f"Out: {titles.get(name, name)}")
    for name in incoming:
        typer.echo(f"In: {titles.get(name, name)}")


@shelf_app.command("drop")
def shelf_drop(persona: str, title: str) -> None:
    """Take a game off the shelf and keep it off until you add it back."""
    settings = _settings()
    conn = _db(settings)
    who = _persona(conn, persona)
    with _changing_shelf(settings, conn, persona):
        dropped = drop(conn, who, title)
    typer.echo(f"Out: {dropped}")
    _tell_romm_or_shrug(settings, conn, verbose=False)


@shelf_app.command("add")
def shelf_add(persona: str, title: str) -> None:
    """Put a game on the shelf. On a full shelf, the longest-shelved game makes room."""
    settings = _settings()
    conn = _db(settings)
    who = _persona(conn, persona)
    with _changing_shelf(settings, conn, persona):
        out, incoming = add(conn, who, title, settings.shelf_size)
    _echo_moves(conn, out, incoming)
    _tell_romm_or_shrug(settings, conn, verbose=False)


def _set_for_title(conn: sqlite3.Connection, game_title: str) -> str | None:
    """The MAME 2003-Plus set a person means by this title: shelved, then parent, then name."""
    rows = conn.execute(
        "SELECT g.set_name, g.parent, EXISTS(SELECT 1 FROM shelf s "
        "WHERE s.emulator = g.emulator AND s.set_name = g.set_name) AS shelved "
        "FROM games g WHERE g.emulator = ? AND g.title = ? COLLATE NOCASE",
        (DEFAULT_EMULATOR, game_title),
    ).fetchall()
    if not rows:
        return None
    best = min(rows, key=lambda r: (not r["shelved"], r["parent"] is not None, r["set_name"]))
    return best["set_name"]


@issue_app.command("log")
def issue_log(
    game: str,
    device: Annotated[str, typer.Option(help="Which TV or box.")],
    note: Annotated[str, typer.Option(help="What happened.")],
) -> None:
    conn = _db(_settings())
    set_name = _set_for_title(conn, game)
    if set_name is None:
        typer.echo(f"Couldn't find {game}.")
        raise typer.Exit(1)
    log_issue(conn, DEFAULT_EMULATOR, set_name, device, note)
    typer.echo("Noted.")


@issue_app.command("list")
def issue_list(verbose: Verbose = False) -> None:
    conn = _db(_settings())
    rows = conn.execute("SELECT emulator, set_name, title FROM games")
    titles = {(r["emulator"], r["set_name"]): r["title"] for r in rows}
    for row in list_issues(conn):
        name = titles.get((row["emulator"], row["set_name"]), row["set_name"])
        extra = f" [{row['set_name']}]" if verbose else ""
        typer.echo(f"{row['at'][:10]}  {name}{extra} on {row['device']}: {row['note']}")


@tune_app.command("set")
def tune_set(
    game: str,
    device: Annotated[str, typer.Option(help="Which TV or box.")],
    settings: Annotated[str, typer.Option(help="The remap or settings that fixed it.")],
) -> None:
    """A tuned game counts as playable on that pad, whatever MAME lists its control as."""
    conn = _db(_settings())
    set_name = _set_for_title(conn, game)
    if set_name is None:
        typer.echo(f"Couldn't find {game}.")
        raise typer.Exit(1)
    set_tuning(conn, DEFAULT_EMULATOR, set_name, device, settings)
    typer.echo("Saved.")

"""infiltrator: point it at a pile of arcade files, get a shelf of games."""

import sqlite3
from typing import Annotated

import click
import typer

from infiltrator.catalogue import connect
from infiltrator.catalogue.games import sync_games
from infiltrator.catalogue.issues import list_issues, log_issue
from infiltrator.config import Settings, load_settings
from infiltrator.dat import Dat, load_dat
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
from infiltrator.shelf import build_shelf, current_shelf, rotate
from infiltrator.sieve import run_sieve

app = typer.Typer(help="Slip into the stack, make it work, sneak back out.", no_args_is_help=True)
persona_app = typer.Typer(help="Who's playing.", no_args_is_help=True)
shelf_app = typer.Typer(help="What's on the shelf.", no_args_is_help=True)
issue_app = typer.Typer(help="Note a game that misbehaved.", no_args_is_help=True)
app.add_typer(persona_app, name="persona")
app.add_typer(shelf_app, name="shelf")
app.add_typer(issue_app, name="issue")

TRY_AGAIN = "Try again later!"
SETTLE_SECONDS = 5.0  # how long the drop folder must sit still before the sieve trusts it
INPUT_CHOICES = {1: GAMEPAD, 2: GAMEPAD | SPINNERS, 3: GAMEPAD | SPINNERS | LIGHT_GUN}

Verbose = Annotated[bool, typer.Option("--verbose", "-v", help="Show the nerd stuff.")]


def _settings() -> Settings:
    return load_settings()


def _db(settings: Settings) -> sqlite3.Connection:
    return connect(settings.db_path)


def _sync(settings: Settings, dat: Dat, conn: sqlite3.Connection) -> int:
    meta = load_metadata(settings.metadata_dir, dat)
    return sync_games(conn, settings.library_dir, dat, meta)


def _new_titles(dat: Dat, set_names: list[str]) -> dict[str, list[str]]:
    """One line per game, not per version: two Heavy Barrels are one new game."""
    by_family: dict[str, list[str]] = {}
    for name in set_names:
        by_family.setdefault(dat.family(dat.games[name]), []).append(name)
    titles: dict[str, list[str]] = {}
    for family, names in by_family.items():
        root = dat.games.get(family) or dat.games[names[0]]
        titles.setdefault(title(root.description), []).extend(names)
    return titles


@app.command()
def sieve(verbose: Verbose = False) -> None:
    """Keep the real games from the drop folder; delete the rest."""
    settings = _settings()
    dat = load_dat(settings.dat_path)
    conn = _db(settings)
    try:
        report = run_sieve(
            settings,
            dat,
            settle_seconds=SETTLE_SECONDS,
            on_library_changed=lambda: _sync(settings, dat, conn),
        )
    except Exception as err:  # the person sees one line; --verbose shows why
        typer.echo(TRY_AGAIN)
        if verbose:
            typer.echo(f"  ({type(err).__name__}: {err})")
        raise typer.Exit(1) from err
    for game_title, names in _new_titles(dat, report.new_games).items():
        line = f"New: {game_title}"
        typer.echo(f"{line}  [{', '.join(names)}]" if verbose else line)
    if not report.new_games:
        typer.echo("Nothing new.")
    rars = [p for p in report.left_alone if p.suffix.lower() == ".rar"]
    if rars:
        typer.echo(f"Left alone: {len(rars)} .rar file(s), not supported yet.")
    if verbose:
        for path in report.deleted:
            typer.echo(f"  deleted {path}")
        for path in report.left_alone:
            typer.echo(f"  left alone {path}")
        for name in report.new_bios:
            typer.echo(f"  bios {name}")
        for name in report.blocked:
            typer.echo(f"  not overwritten: {name}.zip is in the library but isn't this set")


@app.command()
def rescan() -> None:
    """Rebuild the game list from the library."""
    settings = _settings()
    count = _sync(settings, load_dat(settings.dat_path), _db(settings))
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
    build_shelf(conn, _persona(conn, persona), settings.shelf_size)
    shelf_show(persona)


@shelf_app.command("rotate")
def shelf_rotate(persona: str, count: Annotated[int, typer.Option(min=1)] = 1) -> None:
    """Swap the longest-shelved games for fresh ones."""
    settings = _settings()
    conn = _db(settings)
    out, incoming = rotate(conn, _persona(conn, persona), settings.shelf_size, count)
    if not incoming:
        typer.echo("Nothing new to rotate in.")
    titles = {r["set_name"]: r["title"] for r in conn.execute("SELECT set_name, title FROM games")}
    for name in out:
        typer.echo(f"Out: {titles.get(name, name)}")
    for name in incoming:
        typer.echo(f"In: {titles.get(name, name)}")


def _set_for_title(conn: sqlite3.Connection, game_title: str) -> str | None:
    rows = conn.execute(
        "SELECT g.set_name, g.parent, EXISTS(SELECT 1 FROM shelf s WHERE s.set_name = g.set_name) "
        "AS shelved FROM games g WHERE g.title = ? COLLATE NOCASE",
        (game_title,),
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
    log_issue(conn, set_name, device, note)
    typer.echo("Noted.")


@issue_app.command("list")
def issue_list(verbose: Verbose = False) -> None:
    conn = _db(_settings())
    titles = {r["set_name"]: r["title"] for r in conn.execute("SELECT set_name, title FROM games")}
    for row in list_issues(conn):
        name = titles.get(row["set_name"], row["set_name"])
        extra = f" [{row['set_name']}]" if verbose else ""
        typer.echo(f"{row['at'][:10]}  {name}{extra} on {row['device']}: {row['note']}")

"""Rebuild the games table from the verified library. Human tables are untouched.

One row per set per emulator, from that emulator's library folder and DAT. The columns that come
from MAME-only data (the metadata files, and the DAT's players, control and buttons, which
FBNeo's list lacks) are MAME 2003-Plus's. An FBNeo set stands in for a MAME game: it is
catalogued under that game's family and borrows its title and those columns from the game's MAME
row, so a person sees one game whichever emulator runs it. An FBNeo set that shares no ROM with
any MAME game keeps its own family and leaves those columns empty.
"""

import sqlite3
from collections.abc import Mapping
from pathlib import Path

from infiltrator.catalogue import utcnow
from infiltrator.catalogue.arrivals import record_arrivals
from infiltrator.dat import DEFAULT_EMULATOR, Dat, Game
from infiltrator.library import emulator_dir
from infiltrator.metadata import SetMeta
from infiltrator.names import title
from infiltrator.rebuild import bios_ready, set_is_valid
from infiltrator.standins import stands_in_for

IDENTITY_COLUMNS = (
    "emulator, set_name, parent, family, description, title, year, manufacturer, is_bios, path, "
    "synced_at"
)
PLAY_COLUMNS = (
    "language, mature, genre, players, control, buttons, quality_tier, "
    "a11y_one_button, a11y_stick_only"
)


def verified_sets(folder: Path, dat: Dat) -> list[Game]:
    """The sets in one emulator's folder that its DAT recognises, whole, with their BIOS."""
    games = []
    for path in sorted(folder.glob("*.zip")):
        game = dat.games.get(path.stem)
        if (
            game is not None
            and set_is_valid(path, dat.required_roms(game))
            and bios_ready(game, dat, folder)
        ):
            games.append(game)
    return games


def _identity(game: Game, dat: Dat, path: Path, now: str, family: str | None = None) -> tuple:
    return (
        dat.emulator,
        game.name,
        game.cloneof,
        family or dat.family(game),
        game.description,
        title(game.description),
        game.year,
        game.manufacturer,
        int(game.is_bios),
        str(path),
        now,
    )


def _play(game: Game, meta: SetMeta) -> tuple:
    """Who and what can play it, from MAME 2003-Plus's DAT and the metadata files."""
    joystick = (game.control or "").startswith("joy")
    players = meta.players or (f"{game.players}P" if game.players else None)
    return (
        meta.language,
        None if meta.mature is None else int(meta.mature),
        meta.genre,
        players,
        game.control,
        game.buttons,
        meta.quality_tier,
        int(joystick and game.buttons <= 1),
        int(joystick and game.buttons == 0),
    )


def _insert(conn: sqlite3.Connection, columns: str, rows: list[tuple]) -> None:
    marks = ", ".join("?" * len(columns.split(",")))
    conn.executemany(f"INSERT INTO games ({columns}) VALUES ({marks})", rows)


def _sync_mame(
    conn: sqlite3.Connection, folder: Path, dat: Dat, meta: Mapping[str, SetMeta], now: str
) -> list[Game]:
    games = verified_sets(folder, dat)
    rows = [
        _identity(g, dat, folder / f"{g.name}.zip", now) + _play(g, meta.get(g.name, SetMeta()))
        for g in games
    ]
    _insert(conn, f"{IDENTITY_COLUMNS}, {PLAY_COLUMNS}", rows)
    return games


BORROWED = ("title", *(c.strip() for c in PLAY_COLUMNS.split(",")))
NOTHING_BORROWED = (None,) * (len(BORROWED) - 1)


def _mame_row(conn: sqlite3.Connection, family: str) -> sqlite3.Row | None:
    """A MAME game's own row: the family's parent if it is in the library, else its lowest name."""
    return conn.execute(
        f"SELECT {', '.join(BORROWED)} FROM games "
        "WHERE emulator = ? AND family = ? AND is_bios = 0 "
        "ORDER BY set_name = family DESC, set_name LIMIT 1",
        (DEFAULT_EMULATOR, family),
    ).fetchone()


def _standing_in(conn: sqlite3.Connection, identity: tuple, family: str | None) -> tuple:
    """A set's row, with the title and play columns of the MAME game it stands in for, if any."""
    donor = None if family is None else _mame_row(conn, family)
    if donor is None:
        return identity + NOTHING_BORROWED
    title_at = IDENTITY_COLUMNS.split(", ").index("title")
    borrowed = identity[:title_at] + (donor["title"],) + identity[title_at + 1 :]
    return borrowed + tuple(donor[c] for c in BORROWED[1:])


def _sync_other(
    conn: sqlite3.Connection, folder: Path, dat: Dat, now: str, mame: Dat | None
) -> list[Game]:
    """Each set under the MAME family it stands in for, after the MAME rows are in."""
    games = verified_sets(folder, dat)
    family_of = stands_in_for(mame, dat) if games and mame is not None else {}
    rows = []
    for g in games:
        family = family_of.get(g.name)  # never a BIOS: those stand in for nothing
        identity = _identity(g, dat, folder / f"{g.name}.zip", now, family)
        rows.append(_standing_in(conn, identity, family))
    _insert(conn, f"{IDENTITY_COLUMNS}, {PLAY_COLUMNS}", rows)
    return games


def _mame_first(dats: Mapping[str, Dat]) -> list[str]:
    """Other emulators' rows borrow from MAME 2003-Plus's, so those go in first."""
    return sorted(dats, key=lambda emulator: emulator != DEFAULT_EMULATOR)


def sync_games(
    conn: sqlite3.Connection,
    library: Path,
    dats: Mapping[str, Dat],
    meta: Mapping[str, SetMeta],
) -> int:
    """Replace the games table with every verified set of every emulator; returns the count.

    `meta` is the MAME 2003-Plus metadata (see `metadata.load_metadata`).
    """
    now = utcnow()
    count = 0
    with conn:
        conn.execute("DELETE FROM games")
        for emulator in _mame_first(dats):
            dat, folder = dats[emulator], emulator_dir(library, emulator)
            if emulator == DEFAULT_EMULATOR:
                games = _sync_mame(conn, folder, dat, meta, now)
            else:
                games = _sync_other(conn, folder, dat, now, dats.get(DEFAULT_EMULATOR))
            record_arrivals(conn, emulator, {g.name: folder / f"{g.name}.zip" for g in games})
            count += len(games)
    return count

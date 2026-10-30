"""Rebuild the games table from the verified library. Human tables are untouched."""

import sqlite3
from pathlib import Path

from infiltrator.catalogue import utcnow
from infiltrator.dat import Dat, Game
from infiltrator.metadata import SetMeta
from infiltrator.names import title
from infiltrator.rebuild import bios_ready, set_is_valid

COLUMNS = (
    "set_name, parent, family, description, title, year, manufacturer, is_bios, path, "
    "language, mature, genre, players, control, buttons, quality_tier, "
    "a11y_one_button, a11y_stick_only, synced_at"
)


def verified_sets(library: Path, dat: Dat) -> list[Game]:
    games = []
    for path in sorted(library.glob("*.zip")):
        game = dat.games.get(path.stem)
        if (
            game is not None
            and set_is_valid(path, dat.required_roms(game))
            and bios_ready(game, dat, library)
        ):
            games.append(game)
    return games


def _row(game: Game, dat: Dat, meta: SetMeta, path: Path, now: str) -> tuple:
    joystick = (game.control or "").startswith("joy")
    players = meta.players or (f"{game.players}P" if game.players else None)
    return (
        game.name,
        game.cloneof,
        dat.family(game),
        game.description,
        title(game.description),
        game.year,
        game.manufacturer,
        int(game.is_bios),
        str(path),
        meta.language,
        None if meta.mature is None else int(meta.mature),
        meta.genre,
        players,
        game.control,
        game.buttons,
        meta.quality_tier,
        int(joystick and game.buttons <= 1),
        int(joystick and game.buttons == 0),
        now,
    )


def sync_games(conn: sqlite3.Connection, library: Path, dat: Dat, meta: dict[str, SetMeta]) -> int:
    now = utcnow()
    games = verified_sets(library, dat)
    rows = [
        _row(g, dat, meta.get(g.name, SetMeta()), library / f"{g.name}.zip", now) for g in games
    ]
    placeholders = ", ".join("?" * len(COLUMNS.split(",")))
    with conn:
        conn.execute("DELETE FROM games")
        conn.executemany(f"INSERT INTO games ({COLUMNS}) VALUES ({placeholders})", rows)
    return len(rows)

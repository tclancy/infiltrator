"""Which emulator each game runs on: MAME 2003-Plus unless a person chose another."""

import sqlite3

from infiltrator.catalogue import utcnow
from infiltrator.dat import DEFAULT_EMULATOR


def choose_emulator(conn: sqlite3.Connection, family: str, emulator: str) -> None:
    """Run this game on this emulator from now on; MAME 2003-Plus simply forgets the choice."""
    with conn:
        if emulator == DEFAULT_EMULATOR:
            conn.execute("DELETE FROM game_emulators WHERE family = ?", (family,))
            return
        conn.execute(
            "INSERT INTO game_emulators (family, emulator, at) VALUES (?, ?, ?) "
            "ON CONFLICT(family) DO UPDATE SET emulator = excluded.emulator, at = excluded.at",
            (family, emulator, utcnow()),
        )


def families_on(conn: sqlite3.Connection, emulator: str) -> set[str]:
    """The games someone chose to run on this emulator."""
    rows = conn.execute("SELECT family FROM game_emulators WHERE emulator = ?", (emulator,))
    return {r["family"] for r in rows}

"""Per-game control tuning: what it took to make a game play right on a device."""

import sqlite3

from infiltrator.catalogue import utcnow


def set_tuning(
    conn: sqlite3.Connection, emulator: str, set_name: str, device: str, settings: str
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO control_tuning (emulator, set_name, device, settings, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(emulator, set_name, device) DO UPDATE SET "
            "settings = excluded.settings, updated_at = excluded.updated_at",
            (emulator, set_name, device, settings, utcnow()),
        )


def tuned_sets(conn: sqlite3.Connection, emulator: str) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT set_name FROM control_tuning WHERE emulator = ?", (emulator,)
    )
    return {r["set_name"] for r in rows}

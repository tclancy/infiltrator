"""Per-game control tuning: what it took to make a game play right on a device."""

import sqlite3

from infiltrator.catalogue import utcnow


def set_tuning(conn: sqlite3.Connection, set_name: str, device: str, settings: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO control_tuning (set_name, device, settings, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(set_name, device) DO UPDATE SET "
            "settings = excluded.settings, updated_at = excluded.updated_at",
            (set_name, device, settings, utcnow()),
        )


def tuned_sets(conn: sqlite3.Connection) -> set[str]:
    return {r["set_name"] for r in conn.execute("SELECT DISTINCT set_name FROM control_tuning")}

"""Whose shelf the TV shows."""

import sqlite3

from infiltrator.catalogue import utcnow


def tv_persona(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT persona FROM tv WHERE id = 1").fetchone()
    return row["persona"] if row else None


def set_tv_persona(conn: sqlite3.Connection, persona: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO tv (id, persona, at) VALUES (1, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET persona = excluded.persona, at = excluded.at",
            (persona, utcnow()),
        )


def romm_pending(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT romm_pending FROM tv WHERE id = 1").fetchone()
    return bool(row and row["romm_pending"])


def set_romm_pending(conn: sqlite3.Connection, pending: bool) -> None:
    with conn:
        conn.execute("UPDATE tv SET romm_pending = ? WHERE id = 1", (int(pending),))

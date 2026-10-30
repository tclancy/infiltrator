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

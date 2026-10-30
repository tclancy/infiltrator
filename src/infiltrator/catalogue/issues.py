"""Hand-logged problems: "this game crashed on this device"."""

import sqlite3

from infiltrator.catalogue import utcnow


def log_issue(conn: sqlite3.Connection, set_name: str, device: str, note: str) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO issues (set_name, device, note, at) VALUES (?, ?, ?, ?)",
            (set_name, device, note, utcnow()),
        )
    return cur.lastrowid


def list_issues(conn: sqlite3.Connection, set_name: str | None = None) -> list[sqlite3.Row]:
    if set_name is None:
        return conn.execute("SELECT * FROM issues ORDER BY at").fetchall()
    return conn.execute(
        "SELECT * FROM issues WHERE set_name = ? ORDER BY at", (set_name,)
    ).fetchall()

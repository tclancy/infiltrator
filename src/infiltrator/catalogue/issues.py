"""Hand-logged problems: "this game crashed on this device"."""

import sqlite3

from infiltrator.catalogue import utcnow


def log_issue(
    conn: sqlite3.Connection, emulator: str, set_name: str, device: str, note: str
) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO issues (emulator, set_name, device, note, at) VALUES (?, ?, ?, ?, ?)",
            (emulator, set_name, device, note, utcnow()),
        )
    return cur.lastrowid


def list_issues(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM issues ORDER BY at").fetchall()


def issues_for(conn: sqlite3.Connection, emulator: str, set_name: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM issues WHERE emulator = ? AND set_name = ? ORDER BY at",
        (emulator, set_name),
    ).fetchall()

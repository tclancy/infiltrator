"""When each set first arrived in the library, and what counts as today."""

import sqlite3
from datetime import UTC, datetime
from datetime import time as midnight
from pathlib import Path


def mtime_utc(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()


def record_arrivals(conn: sqlite3.Connection, paths: dict[str, Path]) -> None:
    """First sighting wins: a set already recorded keeps its arrival."""
    conn.executemany(
        "INSERT OR IGNORE INTO arrivals (set_name, arrived_at) VALUES (?, ?)",
        [(name, mtime_utc(path)) for name, path in paths.items()],
    )


def arrived_since(conn: sqlite3.Connection, since: str) -> set[str]:
    start = datetime.fromisoformat(since)
    rows = conn.execute("SELECT set_name, arrived_at FROM arrivals")
    return {r["set_name"] for r in rows if datetime.fromisoformat(r["arrived_at"]) >= start}


def start_of_local_day(now: datetime | None = None) -> str:
    """Local midnight of today, as a UTC instant. Naive astimezone() applies DST for that date."""
    today = (now or datetime.now(UTC)).astimezone().date()
    return datetime.combine(today, midnight()).astimezone().astimezone(UTC).isoformat()

"""When each set first arrived in the library, and what counts as new."""

import sqlite3
from datetime import UTC, datetime, timedelta
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


def window_start(days: int, now: datetime | None = None) -> str:
    """The UTC instant *days* × 24 hours before now: a rolling window, so midnight means nothing."""
    return ((now or datetime.now(UTC)) - timedelta(days=days)).astimezone(UTC).isoformat()

"""The SQLite catalogue: open it, migrated to the latest schema."""

import sqlite3
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _migrations() -> list[tuple[int, str]]:
    folder = resources.files("infiltrator.catalogue") / "migrations"
    found = []
    for entry in folder.iterdir():
        if entry.name.endswith(".sql"):
            found.append((int(entry.name.split("_", 1)[0]), entry.read_text()))
    return sorted(found)


def _migrate(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, sql in _migrations():
        if version <= current:
            continue
        with conn:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn)
    return conn

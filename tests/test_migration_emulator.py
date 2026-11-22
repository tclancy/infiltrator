"""Migration 0006: every table that names a set learns which emulator the set is for."""

import sqlite3

import pytest

from infiltrator.catalogue import _migrate

MAME = "mame2003-plus"

# Rows as a version-5 catalogue held them: one in every table, set-naming or not.
V5_ROWS = {
    "personas": [("tom", "{}")],
    "must_haves": [("tom", "Heavy Barrel")],
    "games": [("hbarrel", "hbarrel", 0, "library/hbarrel.zip", "2026-11-01T00:00:00+00:00")],
    "shelf": [("tom", "hbarrel", "2026-11-01T00:00:00+00:00")],
    "shelf_history": [(1, "tom", "hbarrel", "on", "2026-11-01T00:00:00+00:00")],
    "shelf_drops": [("tom", "tekken", "2026-11-02T00:00:00+00:00")],
    "arrivals": [("hbarrel", "2026-10-01T00:00:00+00:00")],
    "control_tuning": [("hbarrel", "sabrina", "remap", "2026-11-01T00:00:00+00:00")],
    "issues": [(1, "hbarrel", "sabrina", "froze", "2026-11-01T00:00:00+00:00")],
    "tv": [(1, "tom", "2026-11-01T00:00:00+00:00", 0, None)],
}
V5_COLUMNS = {
    "personas": "name, data",
    "must_haves": "persona, title",
    "games": "set_name, family, is_bios, path, synced_at",
    "shelf": "persona, set_name, placed_at",
    "shelf_history": "id, persona, set_name, action, at",
    "shelf_drops": "persona, family, at",
    "arrivals": "set_name, arrived_at",
    "control_tuning": "set_name, device, settings, updated_at",
    "issues": "id, set_name, device, note, at",
    "tv": "id, persona, at, romm_pending, demo_since",
}
NAMES_A_SET = ("games", "shelf", "shelf_history", "arrivals", "control_tuning", "issues")


def open_db(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def insert(conn, table, row):
    columns = V5_COLUMNS[table]
    marks = ", ".join("?" * len(row))
    conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", row)


@pytest.fixture
def v5(tmp_path):
    conn = open_db(tmp_path / "c.db")
    _migrate(conn, up_to=5)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    with conn:
        for table, rows in V5_ROWS.items():
            for row in rows:
                insert(conn, table, row)
    return conn


def rows(conn, table):
    columns = V5_COLUMNS[table]
    return [tuple(r) for r in conn.execute(f"SELECT {columns} FROM {table} ORDER BY 1")]


def primary_key(conn, table) -> list[str]:
    info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r["name"] for r in sorted((r for r in info if r["pk"]), key=lambda r: r["pk"])]


def test_every_row_survives_the_migration(v5):
    _migrate(v5)
    assert v5.execute("PRAGMA user_version").fetchone()[0] == 6
    for table, expected in V5_ROWS.items():
        assert rows(v5, table) == expected, table


def test_everything_recorded_before_is_mame_2003_plus(v5):
    _migrate(v5)
    for table in NAMES_A_SET:
        found = {r["emulator"] for r in v5.execute(f"SELECT emulator FROM {table}")}
        assert found == {MAME}, table


def test_tables_that_name_no_set_are_untouched(v5):
    before = {t: primary_key(v5, t) for t in ("personas", "must_haves", "shelf_drops", "tv")}
    _migrate(v5)
    for table, key in before.items():
        assert primary_key(v5, table) == key
        columns = {r["name"] for r in v5.execute(f"PRAGMA table_info({table})")}
        assert "emulator" not in columns, table


def test_the_emulator_joins_each_primary_key(v5):
    _migrate(v5)
    assert primary_key(v5, "games") == ["emulator", "set_name"]
    assert primary_key(v5, "shelf") == ["persona", "emulator", "set_name"]
    assert primary_key(v5, "arrivals") == ["emulator", "set_name"]
    assert primary_key(v5, "control_tuning") == ["emulator", "set_name", "device"]


SECOND_HBARREL = {
    "games": (
        "INSERT INTO games (emulator, set_name, family, is_bios, path, synced_at) "
        "VALUES (?, 'hbarrel', 'hbarrel', 0, 'x.zip', 'now')"
    ),
    "shelf": "INSERT INTO shelf (persona, emulator, set_name, placed_at) "
    "VALUES ('tom', ?, 'hbarrel', 'now')",
    "arrivals": "INSERT INTO arrivals (emulator, set_name, arrived_at) "
    "VALUES (?, 'hbarrel', 'now')",
    "control_tuning": "INSERT INTO control_tuning (emulator, set_name, device, settings, "
    "updated_at) VALUES (?, 'hbarrel', 'sabrina', 'x', 'now')",
}


@pytest.mark.parametrize("table", sorted(SECOND_HBARREL))
def test_both_emulators_hbarrel_fit_where_the_old_key_allowed_one(v5, table):
    with pytest.raises(sqlite3.IntegrityError):  # version 5: one hbarrel, whatever it is
        insert(v5, table, V5_ROWS[table][0])
    _migrate(v5)
    with v5:
        v5.execute(SECOND_HBARREL[table], ("fbneo",))
    assert {r["emulator"] for r in v5.execute(f"SELECT emulator FROM {table}")} == {MAME, "fbneo"}
    with pytest.raises(sqlite3.IntegrityError):
        v5.execute(SECOND_HBARREL[table], (MAME,))


def test_a_deleted_persona_still_takes_its_shelf_with_it(v5):
    _migrate(v5)
    with v5:
        v5.execute("DELETE FROM personas WHERE name = 'tom'")
    assert rows(v5, "shelf") == [] and rows(v5, "must_haves") == []

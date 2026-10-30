from infiltrator.catalogue import connect
from infiltrator.catalogue.issues import list_issues, log_issue

TABLES = {
    "games",
    "personas",
    "must_haves",
    "shelf",
    "shelf_history",
    "issues",
    "control_tuning",
}


def _tables(conn) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r["name"] for r in rows}


def test_fresh_db_migrates_to_latest(tmp_path):
    conn = connect(tmp_path / "c.db")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert _tables(conn) == TABLES


def test_connect_twice_is_idempotent(tmp_path):
    connect(tmp_path / "c.db").close()
    conn = connect(tmp_path / "c.db")
    assert _tables(conn) == TABLES


def test_issue_survives_game_row_deletion(tmp_path):
    conn = connect(tmp_path / "c.db")
    with conn:
        conn.execute(
            "INSERT INTO games (set_name, family, is_bios, path, synced_at) "
            "VALUES ('x', 'x', 0, 'x.zip', 'now')"
        )
    log_issue(conn, "x", "sabrina", "froze on stage 2")
    with conn:
        conn.execute("DELETE FROM games WHERE set_name = 'x'")
    assert [r["note"] for r in list_issues(conn, "x")] == ["froze on stage 2"]


def test_timestamps_are_utc(tmp_path):
    conn = connect(tmp_path / "c.db")
    log_issue(conn, "x", "sabrina", "n")
    assert list_issues(conn)[0]["at"].endswith("+00:00")

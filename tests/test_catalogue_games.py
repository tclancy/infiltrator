import zipfile

import pytest
from conftest import chips_for, make_zip

from infiltrator.catalogue import connect
from infiltrator.catalogue.games import sync_games
from infiltrator.catalogue.issues import list_issues, log_issue
from infiltrator.config import Settings
from infiltrator.dat import load_dat
from infiltrator.metadata import SetMeta
from infiltrator.sieve import run_sieve


@pytest.fixture
def lib(tmp_path, synthetic_dat):
    library = tmp_path / "library"
    library.mkdir()
    return library, load_dat(synthetic_dat), connect(tmp_path / "c.db")


def row(conn, name):
    return conn.execute("SELECT * FROM games WHERE set_name = ?", (name,)).fetchone()


def test_sync_inserts_rows_with_title_and_meta(lib):
    library, dat, conn = lib
    make_zip(library / "alphab.zip", chips_for("alphab"))
    meta = {"alphab": SetMeta(language="Japanese", quality_tier=7, players="2P alt")}
    assert sync_games(conn, library, dat, meta) == 1
    r = row(conn, "alphab")
    assert (r["title"], r["parent"], r["family"]) == ("Alpha Blaster", "alpha", "alpha")
    assert (r["language"], r["quality_tier"], r["players"]) == ("Japanese", 7, "2P alt")
    assert r["synced_at"].endswith("+00:00")


def test_players_falls_back_to_dat(lib):
    library, dat, conn = lib
    make_zip(library / "alpha.zip", chips_for("alpha"))
    sync_games(conn, library, dat, {})
    assert row(conn, "alpha")["players"] == "2P"


def test_removed_file_removes_game_row_but_keeps_issue(lib):
    library, dat, conn = lib
    make_zip(library / "alpha.zip", chips_for("alpha"))
    sync_games(conn, library, dat, {})
    log_issue(conn, "alpha", "sabrina", "crashed")
    (library / "alpha.zip").unlink()
    assert sync_games(conn, library, dat, {}) == 0
    assert row(conn, "alpha") is None
    assert len(list_issues(conn, "alpha")) == 1


def test_a11y_flags_from_dat_input(lib):
    library, dat, conn = lib
    make_zip(library / "alpha.zip", chips_for("alpha"))  # joy4way, no buttons
    make_zip(library / "alphab.zip", chips_for("alphab"))  # joy8way, 1 button
    make_zip(library / "delta.zip", chips_for("delta"))  # joy4way, 1 button
    sync_games(conn, library, dat, {})
    assert (row(conn, "alpha")["a11y_one_button"], row(conn, "alpha")["a11y_stick_only"]) == (1, 1)
    assert (row(conn, "alphab")["a11y_one_button"], row(conn, "alphab")["a11y_stick_only"]) == (
        1,
        0,
    )


def test_unverified_zip_not_catalogued(lib):
    library, dat, conn = lib
    with zipfile.ZipFile(library / "alpha.zip", "w") as zf:
        zf.writestr("a1.bin", b"wrong bytes")
    (library / "mystery.zip").write_bytes(b"not a set")
    assert sync_games(conn, library, dat, {}) == 0


def test_bios_is_catalogued_and_flagged(lib):
    library, dat, conn = lib
    make_zip(library / "biosx.zip", chips_for("biosx"))
    sync_games(conn, library, dat, {})
    assert row(conn, "biosx")["is_bios"] == 1


def test_sieve_end_to_end_populates_games(tmp_path, synthetic_dat):
    drop = tmp_path / "drop"
    drop.mkdir()
    settings = Settings(drop, tmp_path / "library", tmp_path / "c.db", synthetic_dat, tmp_path)
    dat, conn = load_dat(synthetic_dat), connect(settings.db_path)
    make_zip(drop / "alpha.zip", chips_for("alpha"))
    run_sieve(
        settings,
        dat,
        settle_seconds=0,
        sleep=lambda _s: None,
        on_library_changed=lambda: sync_games(conn, settings.library_dir, dat, {}),
    )
    assert row(conn, "alpha")["title"] == "Alpha Blaster"


def test_game_with_missing_bios_not_catalogued(lib):
    library, dat, conn = lib
    make_zip(library / "beta.zip", {"b1.bin": chips_for("beta")["b1.bin"]})
    assert sync_games(conn, library, dat, {}) == 0
    make_zip(library / "biosx.zip", chips_for("biosx"))
    assert sync_games(conn, library, dat, {}) == 2

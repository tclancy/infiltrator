import os
import time
from datetime import UTC, datetime

import pytest
from conftest import chips_for, make_zip

from infiltrator.catalogue import connect
from infiltrator.catalogue.arrivals import arrived_since, start_of_local_day
from infiltrator.catalogue.games import sync_games
from infiltrator.dat import load_dat

A_MONTH_AGO = datetime(2026, 10, 12, 12, 0, tzinfo=UTC).timestamp()


@pytest.fixture
def lib(tmp_path, synthetic_dat):
    library = tmp_path / "library"
    library.mkdir()
    return library, load_dat(synthetic_dat), connect(tmp_path / "c.db")


@pytest.fixture
def new_york(monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def arrived_at(conn, name):
    return conn.execute("SELECT arrived_at FROM arrivals WHERE set_name = ?", (name,)).fetchone()[0]


def test_a_new_set_arrives_at_its_zip_mtime_in_utc(lib):
    library, dat, conn = lib
    zip_path = make_zip(library / "alpha.zip", chips_for("alpha"))
    os.utime(zip_path, (A_MONTH_AGO, A_MONTH_AGO))
    sync_games(conn, library, dat, {})
    assert arrived_at(conn, "alpha") == "2026-10-12T12:00:00+00:00"


def test_a_rescan_never_moves_an_arrival(lib):
    library, dat, conn = lib
    zip_path = make_zip(library / "alpha.zip", chips_for("alpha"))
    os.utime(zip_path, (A_MONTH_AGO, A_MONTH_AGO))
    sync_games(conn, library, dat, {})
    os.utime(zip_path)  # rewritten "now"
    sync_games(conn, library, dat, {})
    assert arrived_at(conn, "alpha") == "2026-10-12T12:00:00+00:00"


def test_a_game_that_leaves_and_returns_keeps_its_first_arrival(lib):
    library, dat, conn = lib
    zip_path = make_zip(library / "alpha.zip", chips_for("alpha"))
    os.utime(zip_path, (A_MONTH_AGO, A_MONTH_AGO))
    sync_games(conn, library, dat, {})
    zip_path.unlink()
    sync_games(conn, library, dat, {})
    make_zip(library / "alpha.zip", chips_for("alpha"))
    sync_games(conn, library, dat, {})
    assert arrived_at(conn, "alpha") == "2026-10-12T12:00:00+00:00"


def test_arrived_since_compares_instants_not_strings(lib):
    library, dat, conn = lib
    old = make_zip(library / "alpha.zip", chips_for("alpha"))
    os.utime(old, (A_MONTH_AGO, A_MONTH_AGO))
    make_zip(library / "delta.zip", chips_for("delta"))
    sync_games(conn, library, dat, {})
    # Same instant as "2026-11-01T00:00:00+00:00", written in another zone.
    assert arrived_since(conn, "2026-10-31T20:00:00-04:00") == {"delta"}


def test_start_of_local_day_is_local_midnight_in_utc(new_york):
    nine_pm_nov_12_local = datetime(2026, 11, 13, 2, 0, tzinfo=UTC)
    assert start_of_local_day(nine_pm_nov_12_local) == "2026-11-12T05:00:00+00:00"


def test_start_of_local_day_follows_dst(new_york):
    # 2026-11-01 is the day New York falls back; its midnight was still EDT (-04:00).
    assert start_of_local_day(datetime(2026, 11, 1, 18, 0, tzinfo=UTC)) == (
        "2026-11-01T04:00:00+00:00"
    )

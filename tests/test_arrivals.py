import os
from datetime import UTC, datetime, timedelta

import pytest
from conftest import chips_for, make_zip

from infiltrator.catalogue import connect
from infiltrator.catalogue.arrivals import arrived_since, window_start
from infiltrator.catalogue.games import sync_games
from infiltrator.dat import load_dat

A_MONTH_AGO = datetime(2026, 10, 12, 12, 0, tzinfo=UTC).timestamp()


@pytest.fixture
def lib(tmp_path, synthetic_dat):
    library = tmp_path / "library"
    library.mkdir()
    return library, load_dat(synthetic_dat), connect(tmp_path / "c.db")


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


NOW = datetime(2026, 11, 13, 5, 10, tzinfo=UTC)  # 00:10 in New York


def arrive(conn, name, when):
    conn.execute(
        "INSERT INTO arrivals (set_name, arrived_at) VALUES (?, ?)", (name, when.isoformat())
    )


def test_the_window_is_the_last_24_hours(lib):
    _, _, conn = lib
    arrive(conn, "alpha", NOW - timedelta(hours=23))
    arrive(conn, "beta", NOW - timedelta(hours=25))
    assert arrived_since(conn, window_start(1, NOW)) == {"alpha"}


def test_midnight_doesnt_reset_the_window(lib):
    _, _, conn = lib
    arrive(conn, "alpha", NOW - timedelta(minutes=20))  # 23:50 local, the day before
    assert arrived_since(conn, window_start(1, NOW)) == {"alpha"}


def test_days_widens_the_window(lib):
    _, _, conn = lib
    arrive(conn, "alpha", NOW - timedelta(hours=70))
    assert arrived_since(conn, window_start(1, NOW)) == set()
    assert arrived_since(conn, window_start(3, NOW)) == {"alpha"}


def test_the_window_start_is_utc(lib):
    assert window_start(1, NOW) == "2026-11-12T05:10:00+00:00"

import zipfile

import pytest
from conftest import chips_for, fbneo_chips_for, make_zip

from infiltrator.catalogue import connect
from infiltrator.catalogue.games import sync_games
from infiltrator.catalogue.issues import issues_for, log_issue
from infiltrator.config import Settings
from infiltrator.dat import DEFAULT_EMULATOR, FBNEO, load_dat, load_optional_roms
from infiltrator.metadata import SetMeta
from infiltrator.sieve import run_sieve


def sync(conn, folder, dat, meta):
    """Sync a library whose only emulator folder is `folder`, which holds `dat`'s sets."""
    return sync_games(conn, folder.parent, {dat.emulator: dat}, meta)


@pytest.fixture
def lib(tmp_path, synthetic_dat):
    library = tmp_path / "library" / DEFAULT_EMULATOR
    library.mkdir(parents=True)
    return library, load_dat(synthetic_dat), connect(tmp_path / "c.db")


def row(conn, name, emulator=DEFAULT_EMULATOR):
    return conn.execute(
        "SELECT * FROM games WHERE emulator = ? AND set_name = ?", (emulator, name)
    ).fetchone()


def test_sync_inserts_rows_with_title_and_meta(lib):
    library, dat, conn = lib
    make_zip(library / "alphab.zip", chips_for("alphab"))
    meta = {"alphab": SetMeta(language="Japanese", quality_tier=7, players="2P alt")}
    assert sync(conn, library, dat, meta) == 1
    r = row(conn, "alphab")
    assert (r["title"], r["parent"], r["family"]) == ("Alpha Blaster", "alpha", "alpha")
    assert (r["language"], r["quality_tier"], r["players"]) == ("Japanese", 7, "2P alt")
    assert r["synced_at"].endswith("+00:00")


def test_players_falls_back_to_dat(lib):
    library, dat, conn = lib
    make_zip(library / "alpha.zip", chips_for("alpha"))
    sync(conn, library, dat, {})
    assert row(conn, "alpha")["players"] == "2P"


def test_removed_file_removes_game_row_but_keeps_issue(lib):
    library, dat, conn = lib
    make_zip(library / "alpha.zip", chips_for("alpha"))
    sync(conn, library, dat, {})
    log_issue(conn, DEFAULT_EMULATOR, "alpha", "sabrina", "crashed")
    (library / "alpha.zip").unlink()
    assert sync(conn, library, dat, {}) == 0
    assert row(conn, "alpha") is None
    assert len(issues_for(conn, DEFAULT_EMULATOR, "alpha")) == 1


def test_a11y_flags_from_dat_input(lib):
    library, dat, conn = lib
    make_zip(library / "alpha.zip", chips_for("alpha"))  # joy4way, no buttons
    make_zip(library / "alphab.zip", chips_for("alphab"))  # joy8way, 1 button
    make_zip(library / "delta.zip", chips_for("delta"))  # joy4way, 1 button
    sync(conn, library, dat, {})
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
    assert sync(conn, library, dat, {}) == 0


def test_bios_is_catalogued_and_flagged(lib):
    library, dat, conn = lib
    make_zip(library / "biosx.zip", chips_for("biosx"))
    sync(conn, library, dat, {})
    assert row(conn, "biosx")["is_bios"] == 1


def test_sieve_end_to_end_populates_games(tmp_path, synthetic_dat):
    drop = tmp_path / "drop"
    drop.mkdir()
    settings = Settings(drop, tmp_path / "library", tmp_path / "c.db", synthetic_dat, tmp_path)
    dat, conn = load_dat(synthetic_dat), connect(settings.db_path)
    make_zip(drop / "alpha.zip", chips_for("alpha"))
    run_sieve(
        settings,
        {DEFAULT_EMULATOR: dat},
        settle_seconds=0,
        sleep=lambda _s: None,
        on_library_changed=lambda: sync_games(
            conn, settings.library_dir, {DEFAULT_EMULATOR: dat}, {}
        ),
    )
    assert row(conn, "alpha")["title"] == "Alpha Blaster"


def test_game_with_missing_bios_not_catalogued(lib):
    library, dat, conn = lib
    make_zip(library / "beta.zip", {"b1.bin": chips_for("beta")["b1.bin"]})
    assert sync(conn, library, dat, {}) == 0
    make_zip(library / "biosx.zip", chips_for("biosx"))
    assert sync(conn, library, dat, {}) == 2


@pytest.fixture
def both(tmp_path, synthetic_dat, disagreeing_fbneo_dat, fbneo_optional_json):
    """A library with a folder per emulator, and both set lists, which disagree."""
    library = tmp_path / "library"
    dats = {
        DEFAULT_EMULATOR: load_dat(synthetic_dat),
        FBNEO: load_dat(
            disagreeing_fbneo_dat,
            emulator=FBNEO,
            optional_roms=load_optional_roms(fbneo_optional_json),
        ),
    }
    return library, dats, connect(tmp_path / "c.db")


def keys(conn):
    return sorted(tuple(r) for r in conn.execute("SELECT emulator, set_name FROM games"))


def test_each_emulators_folder_is_catalogued_by_its_own_set_list(both):
    library, dats, conn = both
    make_zip(library / DEFAULT_EMULATOR / "alpha.zip", chips_for("alpha"))
    make_zip(library / FBNEO / "alpha.zip", fbneo_chips_for("alpha"))
    alphaua = {k: v for k, v in fbneo_chips_for("alphaua").items() if k != "ua-prom.bin"}
    make_zip(library / FBNEO / "alphaua.zip", alphaua)
    meta = {"alpha": SetMeta(language="English", quality_tier=8)}
    assert sync_games(conn, library, dats, meta) == 3
    assert keys(conn) == [(FBNEO, "alpha"), (FBNEO, "alphaua"), (DEFAULT_EMULATOR, "alpha")]
    ua = row(conn, "alphaua", FBNEO)
    assert (ua["title"], ua["parent"], ua["family"]) == ("Alpha Blaster", "alpha", "alpha")
    assert ua["path"] == str(library / FBNEO / "alphaua.zip")
    assert row(conn, "alpha")["path"] == str(library / DEFAULT_EMULATOR / "alpha.zip")


def test_fbneo_rows_leave_the_mame_only_columns_empty(both):
    library, dats, conn = both
    make_zip(library / DEFAULT_EMULATOR / "alpha.zip", chips_for("alpha"))
    make_zip(library / FBNEO / "alpha.zip", fbneo_chips_for("alpha"))
    meta = {"alpha": SetMeta(language="English", mature=False, genre="Shooter", quality_tier=8)}
    sync_games(conn, library, dats, meta)
    mame_only = (
        "language",
        "mature",
        "genre",
        "players",
        "control",
        "buttons",
        "quality_tier",
        "a11y_one_button",
        "a11y_stick_only",
    )
    fbneo = row(conn, "alpha", FBNEO)
    assert {c: fbneo[c] for c in mame_only} == dict.fromkeys(mame_only)
    mame = row(conn, "alpha")
    assert (mame["language"], mame["quality_tier"], mame["control"]) == ("English", 8, "joy4way")


def test_a_set_in_the_wrong_emulators_folder_is_not_catalogued(both):
    library, dats, conn = both
    make_zip(library / FBNEO / "alpha.zip", chips_for("alpha"))  # MAME's alpha, not FBNeo's
    make_zip(library / DEFAULT_EMULATOR / "fbonly.zip", fbneo_chips_for("fbonly"))
    assert sync_games(conn, library, dats, {}) == 0


def test_arrivals_are_recorded_per_emulator(both):
    library, dats, conn = both
    make_zip(library / FBNEO / "fbonly.zip", fbneo_chips_for("fbonly"))
    make_zip(library / DEFAULT_EMULATOR / "alpha.zip", chips_for("alpha"))
    sync_games(conn, library, dats, {})
    arrived = sorted(tuple(r) for r in conn.execute("SELECT emulator, set_name FROM arrivals"))
    assert arrived == [(FBNEO, "fbonly"), (DEFAULT_EMULATOR, "alpha")]


def test_an_fbneo_bios_counts_only_from_the_fbneo_folder(both):
    library, dats, conn = both
    make_zip(library / DEFAULT_EMULATOR / "biosx.zip", chips_for("biosx"))
    make_zip(library / FBNEO / "betafb.zip", {"fb-b1.bin": fbneo_chips_for("betafb")["fb-b1.bin"]})
    sync_games(conn, library, dats, {})
    assert keys(conn) == [(DEFAULT_EMULATOR, "biosx")]
    make_zip(library / FBNEO / "biosx.zip", fbneo_chips_for("biosx"))
    sync_games(conn, library, dats, {})
    assert (FBNEO, "betafb") in keys(conn)


def test_a_shelf_never_takes_an_fbneo_set_yet(both):
    from infiltrator.personas import Persona, save_persona
    from infiltrator.shelf import build_shelf, current_shelf

    library, dats, conn = both
    make_zip(library / FBNEO / "fbonly.zip", fbneo_chips_for("fbonly"))
    make_zip(library / FBNEO / "alpha.zip", fbneo_chips_for("alpha"))
    make_zip(library / DEFAULT_EMULATOR / "delta.zip", chips_for("delta"))
    sync_games(conn, library, dats, {})
    anyone = Persona("tom", language=None, mature_ok=True, must_haves=("Only In FBNeo",))
    save_persona(conn, anyone)
    build_shelf(conn, anyone, 6)
    assert [(g["emulator"], g["set_name"]) for g in current_shelf(conn, "tom")] == [
        (DEFAULT_EMULATOR, "delta")
    ]

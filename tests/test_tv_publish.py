import dataclasses
import os
from urllib.error import HTTPError

import pytest
from conftest import chips_for, fbneo_chips_for, make_zip
from test_personas import add_game
from test_romm import FakeRomm

from infiltrator.catalogue import connect
from infiltrator.catalogue.tv import romm_pending, set_tv_persona
from infiltrator.config import Settings
from infiltrator.dat import DEFAULT_EMULATOR, FBNEO, load_dat
from infiltrator.personas import Persona, save_persona
from infiltrator.publish import PublishError
from infiltrator.romm import RommClient, RommError
from infiltrator.shelf import build_shelf
from infiltrator.tv import bios_needed, preflight, publish_tv, shown_emulators, tell_romm


class Spy:
    def __init__(self, fail=False, failing=()):
        self.refreshed, self.fail, self.failing = [], fail, set(failing)

    def refresh_platform(self, slug):
        if self.fail or slug in self.failing:
            raise OSError("RomM is down")
        self.refreshed.append(slug)


def show_on_tv(settings, dat, conn, client):
    result = publish_tv(settings, {dat.emulator: dat}, conn)
    tell_romm(settings, conn, client)
    return result


@pytest.fixture
def world(tmp_path, synthetic_dat):
    # The games folder's name is RomM's platform: `arcade`, as before emulators.
    library, shelf, bios = (tmp_path / n for n in ("library", "arcade", "bios"))
    for folder in (library, shelf, bios):
        folder.mkdir()
    for name in ("alpha", "beta", "biosx"):
        make_zip(library / DEFAULT_EMULATOR / f"{name}.zip", chips_for(name))
    settings = Settings(
        drop_dir=tmp_path / "drop",
        library_dir=library,
        db_path=tmp_path / "c.db",
        dat_path=synthetic_dat,
        metadata_dir=tmp_path / "meta",
        shelf_size=6,
        shelf_dir=shelf,
        bios_dir=bios,
    )
    conn = connect(settings.db_path)
    add_game(conn, "alpha")
    add_game(conn, "beta")
    save_persona(conn, Persona("tom", language=None))
    build_shelf(conn, Persona("tom", language=None), 6)
    return settings, load_dat(synthetic_dat), conn


def test_bios_needed_follows_the_romof_chain(synthetic_dat):
    dat = load_dat(synthetic_dat)
    assert bios_needed(dat, ["alpha", "betab", "beta"]) == ["biosx"]


def test_nothing_is_published_without_a_tv_persona(world):
    settings, dat, conn = world
    spy = Spy()
    assert show_on_tv(settings, dat, conn, spy) is None
    assert list(settings.shelf_dir.iterdir()) == [] and spy.refreshed == []


def test_nothing_is_published_without_romm_folders(world):
    settings, dat, conn = world
    set_tv_persona(conn, "tom")
    bare = dataclasses.replace(settings, shelf_dir=None, bios_dir=None)
    assert show_on_tv(bare, dat, conn, Spy()) is None


def test_publishes_the_tv_shelf_with_its_bios_and_tells_romm_once(world):
    settings, dat, conn = world
    set_tv_persona(conn, "tom")
    spy = Spy()
    show_on_tv(settings, dat, conn, spy)
    assert sorted(p.name for p in settings.shelf_dir.iterdir()) == ["alpha.zip", "beta.zip"]
    assert [p.name for p in settings.bios_dir.iterdir()] == ["biosx.zip"]
    assert spy.refreshed == ["arcade"]
    show_on_tv(settings, dat, conn, spy)
    assert spy.refreshed == ["arcade"]


def test_a_failed_romm_call_is_retried_by_the_next_run(world):
    settings, dat, conn = world
    set_tv_persona(conn, "tom")
    with pytest.raises(OSError):
        show_on_tv(settings, dat, conn, Spy(fail=True))
    spy = Spy()
    show_on_tv(settings, dat, conn, spy)
    assert spy.refreshed == ["arcade"]
    show_on_tv(settings, dat, conn, spy)
    assert spy.refreshed == ["arcade"]


# One folder pair per emulator.


@pytest.fixture
def both(tmp_path, synthetic_dat, disagreeing_fbneo_dat):
    """MAME alpha and FBNeo betafb on tom's shelf; each emulator with its own folders."""
    library = tmp_path / "library"
    names = ("roms-mame", "bios-mame", "roms-fbneo", "bios-fbneo")
    folders = {n: tmp_path.joinpath(*n.split("-")) for n in names}  # roms/mame and so on
    for folder in folders.values():
        folder.mkdir(parents=True)
    make_zip(library / DEFAULT_EMULATOR / "alpha.zip", chips_for("alpha"))
    make_zip(library / DEFAULT_EMULATOR / "biosx.zip", chips_for("biosx"))
    make_zip(library / FBNEO / "betafb.zip", fbneo_chips_for("betafb"))
    make_zip(library / FBNEO / "biosx.zip", fbneo_chips_for("biosx"))
    settings = Settings(
        drop_dir=tmp_path / "drop",
        library_dir=library,
        db_path=tmp_path / "c.db",
        dat_path=synthetic_dat,
        metadata_dir=tmp_path / "meta",
        shelf_dir=folders["roms-mame"],
        bios_dir=folders["bios-mame"],
        fbneo_dat_path=disagreeing_fbneo_dat,
        fbneo_shelf_dir=folders["roms-fbneo"],
        fbneo_bios_dir=folders["bios-fbneo"],
    )
    dats = {
        DEFAULT_EMULATOR: load_dat(synthetic_dat),
        FBNEO: load_dat(disagreeing_fbneo_dat, FBNEO),
    }
    conn = connect(settings.db_path)
    add_game(conn, "alpha")
    add_game(conn, "betafb", emulator=FBNEO, family="beta")
    save_persona(conn, Persona("tom", language=None))
    with conn:
        conn.executemany(
            "INSERT INTO shelf (persona, emulator, set_name, placed_at) VALUES ('tom', ?, ?, 'x')",
            [(DEFAULT_EMULATOR, "alpha"), (FBNEO, "betafb")],
        )
    set_tv_persona(conn, "tom")
    return settings, dats, conn, folders


def contents(folder):
    return sorted(p.name for p in folder.iterdir())


def same_file(a, b):
    return os.stat(a).st_ino == os.stat(b).st_ino


def test_each_emulators_entries_go_to_its_own_folders_with_its_own_bios(both):
    settings, dats, conn, folders = both
    publish_tv(settings, dats, conn)
    assert contents(folders["roms-mame"]) == ["alpha.zip"]
    assert contents(folders["bios-mame"]) == []  # alpha needs no BIOS
    assert contents(folders["roms-fbneo"]) == ["betafb.zip"]
    assert contents(folders["bios-fbneo"]) == ["biosx.zip"]
    fbneo_library = settings.library_dir / FBNEO
    # FBNeo's own biosx, from FBNeo's library folder, not MAME's biosx.
    assert same_file(folders["bios-fbneo"] / "biosx.zip", fbneo_library / "biosx.zip")
    assert same_file(folders["roms-fbneo"] / "betafb.zip", fbneo_library / "betafb.zip")


@pytest.mark.parametrize("stranger_in", ["roms-fbneo", "bios-fbneo", "roms-mame", "bios-mame"])
def test_a_stranger_in_any_folder_stops_every_folder_changing(both, stranger_in):
    settings, dats, conn, folders = both
    (folders[stranger_in] / "hand-placed.zip").write_bytes(b"not ours")
    with pytest.raises(PublishError):
        preflight(settings)
    with pytest.raises(PublishError):
        publish_tv(settings, dats, conn)
    for name, folder in folders.items():
        assert contents(folder) == (["hand-placed.zip"] if name == stranger_in else [])


def test_without_fbneo_folders_only_mames_are_published(both):
    settings, dats, conn, folders = both
    mame_only = dataclasses.replace(settings, fbneo_shelf_dir=None, fbneo_bios_dir=None)
    publish_tv(mame_only, dats, conn)
    assert contents(folders["roms-mame"]) == ["alpha.zip"]
    assert contents(folders["roms-fbneo"]) == []


def test_fbneo_folders_alone_publish_fbneos_entries(both):
    settings, dats, conn, folders = both
    fbneo_only = dataclasses.replace(settings, shelf_dir=None, bios_dir=None)
    publish_tv(fbneo_only, dats, conn)
    assert contents(folders["roms-mame"]) == []
    assert contents(folders["roms-fbneo"]) == ["betafb.zip"]


def test_the_tv_shows_fbneo_only_with_fbneo_folders(both):
    settings = both[0]
    assert shown_emulators(settings) == {DEFAULT_EMULATOR, FBNEO}
    mame_only = dataclasses.replace(settings, fbneo_shelf_dir=None, fbneo_bios_dir=None)
    assert shown_emulators(mame_only) == {DEFAULT_EMULATOR}
    nothing = dataclasses.replace(mame_only, shelf_dir=None, bios_dir=None)
    assert shown_emulators(nothing) == {DEFAULT_EMULATOR}


def test_romm_hears_once_per_emulator_on_the_platform_named_after_its_folder(both):
    settings, dats, conn, _folders = both
    spy = Spy()
    published = publish_tv(settings, dats, conn)
    assert published.changed
    tell_romm(settings, conn, spy)
    assert spy.refreshed == ["mame", "fbneo"]
    assert not romm_pending(conn)


def test_romm_still_pending_when_one_platform_fails_and_every_one_is_tried(both):
    settings, dats, conn, _folders = both
    publish_tv(settings, dats, conn)
    spy = Spy(failing={"mame"})
    with pytest.raises(OSError):
        tell_romm(settings, conn, spy)
    assert spy.refreshed == ["fbneo"]
    assert romm_pending(conn)
    retry = Spy()
    tell_romm(settings, conn, retry)
    assert retry.refreshed == ["mame", "fbneo"] and not romm_pending(conn)


def test_without_fbneo_folders_romm_hears_about_mames_platform_only(both):
    settings, dats, conn, _folders = both
    mame_only = dataclasses.replace(settings, fbneo_shelf_dir=None, fbneo_bios_dir=None)
    publish_tv(mame_only, dats, conn)
    spy = Spy()
    tell_romm(mame_only, conn, spy)
    assert spy.refreshed == ["mame"]


# With `romm_collection`: the whole library in RomM's folders, the shelf as a collection.

COLLECTION = "On the shelf"


def collecting(settings):
    """The same install with the shelf as a RomM collection."""
    return dataclasses.replace(
        settings, romm_url="http://romm:8080", romm_token="rmm_t", romm_collection=COLLECTION
    )


@pytest.fixture
def library(both):
    """`both`, with sets nobody shelved: MAME delta and FBNeo fbonly, and each one's BIOS row."""
    settings, dats, conn, folders = both
    make_zip(settings.library_dir / DEFAULT_EMULATOR / "delta.zip", chips_for("delta"))
    make_zip(settings.library_dir / FBNEO / "fbonly.zip", fbneo_chips_for("fbonly"))
    add_game(conn, "delta")
    add_game(conn, "fbonly", emulator=FBNEO)
    add_game(conn, "biosx", is_bios=1)
    add_game(conn, "biosx", emulator=FBNEO, is_bios=1)
    return settings, dats, conn, folders


def test_with_a_collection_every_verified_set_is_published_bios_sets_to_the_bios_folders(library):
    settings, dats, conn, folders = library
    publish_tv(collecting(settings), dats, conn)
    assert contents(folders["roms-mame"]) == ["alpha.zip", "delta.zip"]
    assert contents(folders["bios-mame"]) == ["biosx.zip"]
    assert contents(folders["roms-fbneo"]) == ["betafb.zip", "fbonly.zip"]
    assert contents(folders["bios-fbneo"]) == ["biosx.zip"]
    for emulator, bios in ((DEFAULT_EMULATOR, "bios-mame"), (FBNEO, "bios-fbneo")):
        assert same_file(folders[bios] / "biosx.zip", settings.library_dir / emulator / "biosx.zip")


def test_without_a_collection_only_the_shelf_is_published_as_before(library):
    settings, dats, conn, folders = library
    publish_tv(settings, dats, conn)
    assert contents(folders["roms-mame"]) == ["alpha.zip"]
    assert contents(folders["bios-mame"]) == []
    assert contents(folders["roms-fbneo"]) == ["betafb.zip"]
    assert contents(folders["bios-fbneo"]) == ["biosx.zip"]


def test_with_a_collection_a_set_that_left_the_library_is_unlinked(library):
    settings, dats, conn, folders = library
    publish_tv(collecting(settings), dats, conn)
    with conn:
        conn.execute("DELETE FROM games WHERE set_name = 'delta'")
    result = publish_tv(collecting(settings), dats, conn)
    assert result.removed == ["delta"]
    assert contents(folders["roms-mame"]) == ["alpha.zip"]
    assert (settings.library_dir / DEFAULT_EMULATOR / "delta.zip").exists()


def test_with_a_collection_only_emulators_with_folders_are_published(library):
    settings, dats, conn, folders = library
    mame_only = dataclasses.replace(settings, fbneo_shelf_dir=None, fbneo_bios_dir=None)
    publish_tv(collecting(mame_only), dats, conn)
    assert contents(folders["roms-mame"]) == ["alpha.zip", "delta.zip"]
    assert contents(folders["roms-fbneo"]) == [] and contents(folders["bios-fbneo"]) == []


@pytest.mark.parametrize("stranger_in", ["roms-fbneo", "bios-mame"])
def test_with_a_collection_a_stranger_in_any_folder_still_stops_every_folder(library, stranger_in):
    settings, dats, conn, folders = library
    (folders[stranger_in] / "hand-placed.zip").write_bytes(b"not ours")
    with pytest.raises(PublishError):
        publish_tv(collecting(settings), dats, conn)
    for name, folder in folders.items():
        assert contents(folder) == (["hand-placed.zip"] if name == stranger_in else [])


MAME_ID, FBNEO_ID = 1, 2


def fake_romm(published, **kw):
    """A RomM whose `mame` and `fbneo` platforms read RomM's folders when scanned."""
    reads = {MAME_ID: published["roms-mame"], FBNEO_ID: published["roms-fbneo"]}
    kw.setdefault("folders", reads)
    platforms = [{"id": MAME_ID, "fs_slug": "mame"}, {"id": FBNEO_ID, "fs_slug": "fbneo"}]
    return FakeRomm(platforms=platforms, **kw)


def romm_client(fake):
    return RommClient("http://romm:8080", "rmm_t", request=fake, sleep=lambda s: None)


def collect(settings, dats, conn, fake):
    """Publish, then tell RomM: one sieve's or one command's worth of TV work."""
    publish_tv(settings, dats, conn)
    tell_romm(settings, conn, romm_client(fake))


def ids(fake, *entries):
    """RomM's ids for these (platform id, set name) pairs."""
    return {fake.rom_id(pid, f"{name}.zip") for pid, name in entries}


def shelve_only(conn, *entries):
    """Make tom's shelf exactly these (emulator, set name) entries."""
    with conn:
        conn.execute("DELETE FROM shelf")
        conn.executemany(
            "INSERT INTO shelf (persona, emulator, set_name, placed_at) VALUES ('tom', ?, ?, 'x')",
            entries,
        )


def shelf_rows(conn):
    return sorted(tuple(r) for r in conn.execute("SELECT emulator, set_name FROM shelf"))


def test_the_collection_is_created_public_and_holds_exactly_the_shelf(library):
    settings, dats, conn, folders = library
    fake = fake_romm(folders)
    collect(collecting(settings), dats, conn, fake)
    assert len(fake.roms) == 4  # the whole library is in RomM
    assert fake.members(COLLECTION) == ids(fake, (MAME_ID, "alpha"), (FBNEO_ID, "betafb"))
    assert [(c["name"], c["is_public"]) for c in fake.collections] == [(COLLECTION, True)]
    assert not romm_pending(conn)


def test_a_collection_of_that_name_is_reused(library):
    settings, dats, conn, folders = library
    mine = {"id": 50, "name": COLLECTION, "rom_ids": [999], "is_public": False}
    fake = fake_romm(folders, collections=[mine])
    collect(collecting(settings), dats, conn, fake)
    assert [c["id"] for c in fake.collections] == [50]
    assert not [u for m, u, _b in fake.calls if m == "POST" and u.endswith("/api/collections")]
    assert fake.members(COLLECTION) == ids(fake, (MAME_ID, "alpha"), (FBNEO_ID, "betafb"))


def test_a_shelf_change_alone_reaches_the_collection_and_moves_no_file(library):
    settings, dats, conn, folders = library
    settings, fake = collecting(settings), fake_romm(folders)
    collect(settings, dats, conn, fake)
    before = {name: contents(folder) for name, folder in folders.items()}
    shelve_only(conn, (DEFAULT_EMULATOR, "delta"), (FBNEO, "betafb"))
    assert not publish_tv(settings, dats, conn).changed
    assert romm_pending(conn)
    tell_romm(settings, conn, romm_client(fake))
    assert fake.members(COLLECTION) == ids(fake, (MAME_ID, "delta"), (FBNEO_ID, "betafb"))
    assert {name: contents(folder) for name, folder in folders.items()} == before
    assert not romm_pending(conn)


def test_an_unchanged_shelf_asks_romm_nothing(library):
    settings, dats, conn, folders = library
    settings, fake = collecting(settings), fake_romm(folders)
    collect(settings, dats, conn, fake)
    asked = len(fake.calls)
    collect(settings, dats, conn, fake)
    assert len(fake.calls) == asked


def test_with_a_collection_romm_is_never_asked_to_purge_missing_roms(library):
    settings, dats, conn, folders = library
    settings, fake = collecting(settings), fake_romm(folders)
    collect(settings, dats, conn, fake)
    shelve_only(conn, (DEFAULT_EMULATOR, "delta"))
    collect(settings, dats, conn, fake)
    with conn:
        conn.execute("DELETE FROM games WHERE set_name = 'fbonly'")  # a file leaves RomM's folder
    collect(settings, dats, conn, fake)
    assert sum(u.endswith("/api/tasks/scan") for _m, u, _b in fake.calls) == 6
    assert fake.cleanups() == []
    assert any(r["fs_name"] == "fbonly.zip" and r["missing_from_fs"] for r in fake.roms)


def test_without_a_collection_the_purge_still_runs_per_platform(library):
    settings, dats, conn, folders = library
    fake = fake_romm(folders)
    collect(settings, dats, conn, fake)
    assert fake.cleanups() == [{"platform_ids": [MAME_ID]}, {"platform_ids": [FBNEO_ID]}]
    assert fake.collections == []


def test_an_fbneo_set_is_found_on_fbneos_platform_not_as_mames_namesake(library):
    settings, dats, conn, folders = library
    # MAME 2003-Plus alpha and FBNeo alpha: one name, two different sets.
    make_zip(settings.library_dir / FBNEO / "alpha.zip", fbneo_chips_for("alpha"))
    add_game(conn, "alpha", emulator=FBNEO)
    shelve_only(conn, (FBNEO, "alpha"), (FBNEO, "betafb"))
    fake = fake_romm(folders)
    collect(collecting(settings), dats, conn, fake)
    mame_alpha, fbneo_alpha = ids(fake, (MAME_ID, "alpha")), ids(fake, (FBNEO_ID, "alpha"))
    assert mame_alpha != fbneo_alpha
    assert fake.members(COLLECTION) == fbneo_alpha | ids(fake, (FBNEO_ID, "betafb"))


def test_a_shelved_set_romm_does_not_list_is_named_and_the_collection_is_left_alone(library):
    settings, dats, conn, folders = library
    mine = {"id": 50, "name": COLLECTION, "rom_ids": [999]}
    fake = fake_romm(folders, folders={MAME_ID: folders["roms-mame"]}, collections=[mine])
    with pytest.raises(RommError, match="fbneo/betafb"):
        collect(collecting(settings), dats, conn, fake)
    assert fake.members(COLLECTION) == {999}
    assert not [u for _m, u, _b in fake.calls if "/api/collections" in u]
    assert romm_pending(conn)


def test_a_failed_scan_leaves_the_collection_alone(library):
    settings, dats, conn, folders = library
    fake = fake_romm(folders, scan_states=("started", "failed"))
    with pytest.raises(RommError, match="failed"):
        collect(collecting(settings), dats, conn, fake)
    assert not [u for _m, u, _b in fake.calls if "/api/collections" in u]
    assert romm_pending(conn)


@pytest.mark.parametrize("forbidden", ["/api/roms", "/api/collections"])
def test_a_token_without_the_new_scopes_changes_nothing_until_it_has_them(library, forbidden):
    settings, dats, conn, folders = library
    settings, fake = collecting(settings), fake_romm(folders, forbid={forbidden})
    shelf = shelf_rows(conn)
    with pytest.raises(HTTPError):
        collect(settings, dats, conn, fake)
    assert romm_pending(conn) and shelf_rows(conn) == shelf
    assert fake.members(COLLECTION) == set()
    fake.forbid.clear()
    collect(settings, dats, conn, fake)
    assert fake.members(COLLECTION) == ids(fake, (MAME_ID, "alpha"), (FBNEO_ID, "betafb"))
    assert not romm_pending(conn) and shelf_rows(conn) == shelf

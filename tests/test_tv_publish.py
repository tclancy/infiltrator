import dataclasses
import os

import pytest
from conftest import chips_for, fbneo_chips_for, make_zip
from test_personas import add_game

from infiltrator.catalogue import connect
from infiltrator.catalogue.tv import set_tv_persona
from infiltrator.config import Settings
from infiltrator.dat import DEFAULT_EMULATOR, FBNEO, load_dat
from infiltrator.personas import Persona, save_persona
from infiltrator.publish import PublishError
from infiltrator.shelf import build_shelf
from infiltrator.tv import bios_needed, preflight, publish_tv, shown_emulators, tell_romm


class Spy:
    def __init__(self, fail=False):
        self.refreshed, self.fail = [], fail

    def refresh_platform(self, slug):
        if self.fail:
            raise OSError("RomM is down")
        self.refreshed.append(slug)


def show_on_tv(settings, dat, conn, client):
    result = publish_tv(settings, {dat.emulator: dat}, conn)
    tell_romm(settings, conn, client)
    return result


@pytest.fixture
def world(tmp_path, synthetic_dat):
    library, shelf, bios = (tmp_path / n for n in ("library", "shelf", "bios"))
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

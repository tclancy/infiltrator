import dataclasses

import pytest
from conftest import chips_for, make_zip
from test_personas import add_game

from infiltrator.catalogue import connect
from infiltrator.catalogue.tv import set_tv_persona
from infiltrator.config import Settings
from infiltrator.dat import load_dat
from infiltrator.personas import Persona, save_persona
from infiltrator.shelf import build_shelf
from infiltrator.tv import bios_needed, publish_tv, tell_romm


class Spy:
    def __init__(self, fail=False):
        self.refreshed, self.fail = [], fail

    def refresh_platform(self, slug):
        if self.fail:
            raise OSError("RomM is down")
        self.refreshed.append(slug)


def show_on_tv(settings, dat, conn, client):
    result = publish_tv(settings, dat, conn)
    tell_romm(settings, conn, client)
    return result


@pytest.fixture
def world(tmp_path, synthetic_dat):
    library, shelf, bios = (tmp_path / n for n in ("library", "shelf", "bios"))
    for folder in (library, shelf, bios):
        folder.mkdir()
    for name in ("alpha", "beta", "biosx"):
        make_zip(library / f"{name}.zip", chips_for(name))
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

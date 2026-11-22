"""The sieve with FBNeo's set list loaded beside MAME 2003-Plus's, which disagrees with it."""

import zipfile
from pathlib import Path

import pytest
from conftest import chips_for, fbneo_chips_for, label_bytes, make_zip

from infiltrator.config import Settings
from infiltrator.dat import DEFAULT_EMULATOR, FBNEO
from infiltrator.dats import load_dats
from infiltrator.rebuild import ChipPool, set_is_valid
from infiltrator.scan import fingerprint
from infiltrator.sieve import run_sieve

MAME = DEFAULT_EMULATOR


@pytest.fixture
def env(tmp_path, synthetic_dat, disagreeing_fbneo_dat, fbneo_optional_json):
    drop = tmp_path / "drop"
    drop.mkdir()
    settings = Settings(
        drop_dir=drop,
        library_dir=tmp_path / "library",
        db_path=tmp_path / "c.db",
        dat_path=synthetic_dat,
        metadata_dir=tmp_path / "meta",
        fbneo_dat_path=disagreeing_fbneo_dat,
        fbneo_optional_path=fbneo_optional_json,
    )
    return settings, load_dats(settings)


def sieve(env, fbneo=frozenset(), **kw):
    settings, dats = env
    wanted = {MAME: None, FBNEO: fbneo}
    return run_sieve(settings, dats, wanted=wanted, settle_seconds=0, sleep=lambda _s: None, **kw)


def folder(env, emulator) -> Path:
    return env[0].library_dir / emulator


def members(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as zf:
        return set(zf.namelist())


def drop_files(env) -> set[str]:
    drop = env[0].drop_dir
    return {str(p.relative_to(drop)) for p in drop.rglob("*") if p.is_file()}


def valid(env, emulator, name) -> bool:
    dat = env[1][emulator]
    return set_is_valid(folder(env, emulator) / f"{name}.zip", dat.required_roms(dat.games[name]))


# Nothing wanted from FBNeo: the sieve behaves as it does without it.


def test_with_nothing_wanted_from_fbneo_a_mame_zip_is_sieved_as_before(env):
    make_zip(env[0].drop_dir / "alpha.zip", chips_for("alpha"))
    report = sieve(env)
    assert report.new_games == {MAME: ["alpha"], FBNEO: []}
    assert members(folder(env, MAME) / "alpha.zip") == {"a1.bin", "a2.bin"}
    assert not folder(env, FBNEO).exists()
    assert drop_files(env) == set() and report.held == {}


def test_a_chip_only_fbneo_knows_keeps_its_source_in_the_drop_folder(env):
    world = make_zip(env[0].drop_dir / "world.zip", fbneo_chips_for("alpha"))  # a1 and aw2
    report = sieve(env)
    assert report.new_games == {MAME: [], FBNEO: []}
    assert report.held == {world: [FBNEO]}
    assert world in report.left_alone and world not in report.deleted
    assert drop_files(env) == {"world.zip"}


def test_a_held_source_goes_once_an_fbneo_set_takes_its_chip(env):
    world = make_zip(env[0].drop_dir / "world.zip", fbneo_chips_for("alpha"))
    sieve(env)
    report = sieve(env, fbneo={"alpha"})
    assert report.new_games == {MAME: [], FBNEO: ["alpha"]}
    assert report.held == {} and report.deleted == [world]
    assert members(folder(env, FBNEO) / "alpha.zip") == {"a1.bin", "aw2.bin"}


def test_a_chip_already_in_a_library_zip_holds_nothing(env):
    make_zip(folder(env, FBNEO) / "alpha.zip", fbneo_chips_for("alpha"))
    world = make_zip(env[0].drop_dir / "world.zip", fbneo_chips_for("alpha"))
    report = sieve(env)
    assert report.held == {} and report.deleted == [world]


def test_a_chip_of_a_size_only_fbneo_lists_is_found_by_the_scan(env):
    # fb1's size is in no MAME set: a scan that hashed only MAME's sizes would see nothing here,
    # and the zip, named like no set, would be left without being known to hold a chip.
    mystery = make_zip(env[0].drop_dir / "mystery.zip", {"x.bin": label_bytes("fb1")})
    assert sieve(env).held == {mystery: [FBNEO]}
    report = sieve(env, fbneo={"fbonly"})
    assert report.new_games[FBNEO] == ["fbonly"]
    assert members(folder(env, FBNEO) / "fbonly.zip") == {"fbo.bin"}
    assert drop_files(env) == set()


def test_a_zip_named_like_an_fbneo_set_holding_nothing_known_is_judged_like_a_mame_one(env):
    make_zip(env[0].drop_dir / "fbonly.zip", {"readme.txt": b"not a chip"})
    sieve(env)
    assert drop_files(env) == set()


# The same name meaning different games.


def test_both_emulators_alpha_live_side_by_side_with_different_contents(env):
    make_zip(env[0].drop_dir / "alpha.zip", chips_for("alpha"))
    make_zip(env[0].drop_dir / "world.zip", fbneo_chips_for("alpha"))
    report = sieve(env, fbneo={"alpha"})
    assert report.new_games == {MAME: ["alpha"], FBNEO: ["alpha"]}
    assert members(folder(env, MAME) / "alpha.zip") == {"a1.bin", "a2.bin"}
    assert members(folder(env, FBNEO) / "alpha.zip") == {"a1.bin", "aw2.bin"}
    assert valid(env, MAME, "alpha") and valid(env, FBNEO, "alpha")
    mame, fbneo = env[1][MAME], env[1][FBNEO]
    fbneo_alpha = fbneo.required_roms(fbneo.games["alpha"])
    mame_alpha = mame.required_roms(mame.games["alpha"])
    assert not set_is_valid(folder(env, MAME) / "alpha.zip", fbneo_alpha)
    assert not set_is_valid(folder(env, FBNEO) / "alpha.zip", mame_alpha)
    assert drop_files(env) == set()


# FBNeo sets made from what the library already holds.


def test_an_fbneo_set_is_built_from_chips_in_mame_library_zips(env):
    make_zip(folder(env, MAME) / "alpha.zip", chips_for("alpha"))
    report = sieve(env, fbneo={"alphaua"})
    assert report.new_games == {MAME: [], FBNEO: ["alphaua"]}
    assert members(folder(env, FBNEO) / "alphaua.zip") == {"ua-1.rom", "ua-2.rom"}
    assert valid(env, FBNEO, "alphaua")


def test_an_optional_rom_goes_in_when_the_pool_has_it(env):
    make_zip(folder(env, MAME) / "alpha.zip", chips_for("alpha"))
    prom = make_zip(env[0].drop_dir / "prom.zip", {"p.bin": label_bytes("aprom")})
    report = sieve(env, fbneo={"alphaua"})
    built = folder(env, FBNEO) / "alphaua.zip"
    assert members(built) == {"ua-1.rom", "ua-2.rom", "ua-prom.bin"}
    with zipfile.ZipFile(built) as zf:
        assert zf.read("ua-prom.bin") == label_bytes("aprom")
    assert report.deleted == [prom]  # its chip lives in the library now


def test_only_the_wanted_fbneo_sets_are_built(env):
    make_zip(folder(env, MAME) / "alpha.zip", chips_for("alpha"))
    make_zip(env[0].drop_dir / "fbonly.zip", fbneo_chips_for("fbonly"))
    report = sieve(env, fbneo={"alphaua"})
    assert report.new_games[FBNEO] == ["alphaua"]
    assert sorted(p.name for p in folder(env, FBNEO).iterdir()) == ["alphaua.zip"]
    assert drop_files(env) == {"fbonly.zip"}


def test_a_wanted_fbneo_game_brings_its_bios_first(env):
    make_zip(env[0].drop_dir / "biosx.zip", chips_for("biosx"))
    make_zip(env[0].drop_dir / "b1.zip", {"b1.bin": chips_for("beta")["b1.bin"]})
    report = sieve(env, fbneo={"betafb"})
    assert report.new_bios == {MAME: ["biosx"], FBNEO: ["biosx"]}
    assert report.new_games == {MAME: ["beta"], FBNEO: ["betafb"]}
    assert members(folder(env, FBNEO) / "betafb.zip") == {"fb-b1.bin"}
    assert members(folder(env, FBNEO) / "biosx.zip") == {"bx-std.bin", "bx-fix.bin"}


def test_bios_readiness_is_judged_in_the_emulators_own_folder(env):
    mame_bios = {"bx-std.bin": label_bytes("bx-std"), "bx-fix.bin": label_bytes("bx-fix")}
    make_zip(folder(env, MAME) / "biosx.zip", mame_bios)
    stranger = make_zip(folder(env, FBNEO) / "biosx.zip", {"bx-std.bin": b"another core's"})
    before = stranger.read_bytes()
    make_zip(env[0].drop_dir / "b1.zip", {"b1.bin": chips_for("beta")["b1.bin"]})
    report = sieve(env, fbneo={"betafb"})
    assert report.new_games == {MAME: ["beta"], FBNEO: []}
    assert report.blocked == {MAME: [], FBNEO: ["biosx"]}
    assert valid(env, MAME, "biosx") and not valid(env, FBNEO, "biosx")
    assert stranger.read_bytes() == before
    assert not (folder(env, FBNEO) / "betafb.zip").exists()


# Never overwritten, never deleted on a guess.


def test_a_stranger_at_an_fbneo_name_keeps_the_sources_that_feed_it(env):
    stranger = make_zip(folder(env, FBNEO) / "alphaua.zip", {"ua-1.rom": b"someone else's"})
    before = stranger.read_bytes()
    make_zip(env[0].drop_dir / "alpha.zip", chips_for("alpha"))
    report = sieve(env, fbneo={"alphaua"})
    assert report.blocked == {MAME: [], FBNEO: ["alphaua"]}
    assert report.new_games[MAME] == ["alpha"]
    assert stranger.read_bytes() == before
    assert drop_files(env) == {"alpha.zip"}


def test_a_stranger_at_an_fbneo_name_nobody_wants_blocks_nothing(env):
    make_zip(folder(env, FBNEO) / "alphaua.zip", {"ua-1.rom": b"someone else's"})
    make_zip(env[0].drop_dir / "alpha.zip", chips_for("alpha"))
    report = sieve(env)
    assert report.blocked == {MAME: [], FBNEO: []}
    assert drop_files(env) == set()


def test_an_fbneo_file_with_the_right_names_and_sizes_but_wrong_crcs_is_not_that_set(env):
    fbneo = env[1][FBNEO]
    roms = fbneo.required_roms(fbneo.games["alphaua"])
    fake = {r.name: bytes(r.size) for r in roms}  # zeros: right size, wrong CRC
    path = make_zip(folder(env, FBNEO) / "alphaua.zip", fake)
    assert all(r.sha1 is None for r in roms)  # size and CRC are all FBNeo gives
    assert not set_is_valid(path, roms)
    labels = {"ua-1.rom": "a1", "ua-2.rom": "a2"}
    make_zip(path, {r.name: label_bytes(labels[r.name]) for r in roms})
    assert set_is_valid(path, roms)


def test_an_fbneo_set_name_fbneo_does_not_have_stops_the_sieve_before_it_deletes(env):
    make_zip(env[0].drop_dir / "alpha.zip", chips_for("alpha"))
    with pytest.raises(ValueError, match="nosuchset"):
        sieve(env, fbneo={"nosuchset"})
    assert drop_files(env) == {"alpha.zip"}


def test_wanting_an_emulator_with_no_set_list_loaded_is_refused(env):
    settings, dats = env
    with pytest.raises(ValueError, match="fbneo"):
        run_sieve(settings, {MAME: dats[MAME]}, wanted={MAME: None, FBNEO: frozenset()})


def test_without_fbneo_loaded_its_chips_are_nothing_special(env):
    settings, dats = env
    make_zip(settings.drop_dir / "world.zip", fbneo_chips_for("alpha"))  # a1 is MAME's too
    report = run_sieve(settings, {MAME: dats[MAME]}, settle_seconds=0, sleep=lambda _s: None)
    assert report.held == {} and drop_files(env) == set()


# One pool, two ways of naming a chip.


def test_one_scanned_chip_answers_to_mames_sha1_and_to_fbneos_size_and_crc(env):
    mame, fbneo = env[1][MAME], env[1][FBNEO]
    pool = ChipPool()
    pool.add(fingerprint(label_bytes("a2"), lambda: label_bytes("a2")))
    by_sha1 = next(r for r in mame.games["alpha"].roms if r.name == "a2.bin")
    by_crc = next(r for r in fbneo.games["alphaua"].roms if r.name == "ua-2.rom")
    assert by_sha1.key != by_crc.key
    assert pool.find(by_sha1) is pool.find(by_crc) is not None

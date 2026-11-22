"""Which FBNeo sets stand in for a MAME game: shared ROMs, by content, never by name."""

import pytest

from infiltrator import standins as standins_module
from infiltrator.dat import DEFAULT_EMULATOR, FBNEO, Dat, Game, Rom, load_dat, load_optional_roms
from infiltrator.standins import fbneo_wanted, standins, stands_in_for, with_bios


@pytest.fixture
def dats(synthetic_dat, disagreeing_fbneo_dat, fbneo_optional_json):
    optional = load_optional_roms(fbneo_optional_json)
    return load_dat(synthetic_dat), load_dat(disagreeing_fbneo_dat, FBNEO, optional)


def rom(name, size, crc):
    return Rom(name, size, crc, None, None, None, "good")


def game(name, *roms, cloneof=None, romof=None, is_bios=False):
    return Game(
        name, name.title(), None, None, cloneof, romof, is_bios, roms, False, None, None, 0, None
    )


def dat(emulator, *games):
    return Dat({g.name: g for g in games}, emulator=emulator)


def test_an_fbneo_set_sharing_a_rom_with_any_set_of_a_family_stands_in_for_it(dats):
    mame, fbneo = dats
    found = standins(mame, fbneo)
    # FBNeo's alpha shares a1 with MAME's alpha; alphaua is MAME's alpha under other names.
    assert found["alpha"] == {"alpha", "alphaua"}
    assert found["beta"] == {"betafb"}  # b1 only: its BIOS chips do not count


def test_a_set_that_shares_nothing_stands_in_for_nothing(dats):
    mame, fbneo = dats
    assert "fbonly" not in {name for names in standins(mame, fbneo).values() for name in names}
    assert "fbonly" not in stands_in_for(mame, fbneo)


def test_bios_sets_never_stand_in(dats):
    mame, fbneo = dats
    assert "biosx" not in {name for names in standins(mame, fbneo).values() for name in names}
    assert "biosx" not in standins(mame, fbneo)  # nor are they a family that is stood in for


def test_a_rom_a_bios_holds_does_not_make_two_games_one():
    shared = rom("bios.bin", 64, "0000beef")
    mame = dat(DEFAULT_EMULATOR, game("bios", shared, is_bios=True), game("one", shared))
    fbneo = dat(FBNEO, game("other", rom("b.bin", 64, "0000beef")))
    assert standins(mame, fbneo) == {}


def test_a_rom_only_the_fbneo_bios_holds_does_not_count_either():
    shared = rom("x.bin", 64, "0000beef")
    mame = dat(DEFAULT_EMULATOR, game("one", shared, rom("o.bin", 8, "00000001")))
    fbneo = dat(FBNEO, game("fbios", shared, is_bios=True), game("other", shared))
    assert standins(mame, fbneo) == {}


def test_the_same_crc_at_another_size_is_another_rom():
    mame = dat(DEFAULT_EMULATOR, game("one", rom("a", 64, "0000beef")))
    fbneo = dat(FBNEO, game("other", rom("a", 32, "0000beef")))
    assert standins(mame, fbneo) == {}


def test_clones_count_for_their_family():
    mame = dat(
        DEFAULT_EMULATOR,
        game("root", rom("r", 8, "00000001")),
        game("clone", rom("c", 8, "00000002"), cloneof="root"),
    )
    fbneo = dat(FBNEO, game("fbset", rom("x", 8, "00000002")))
    assert standins(mame, fbneo) == {"root": {"fbset"}}
    assert stands_in_for(mame, fbneo) == {"fbset": "root"}


def test_the_inverse_picks_the_family_sharing_the_most_roms():
    mame = dat(
        DEFAULT_EMULATOR,
        game("few", rom("1", 8, "00000001")),
        game("many", rom("2", 8, "00000002"), rom("3", 8, "00000003")),
    )
    fbneo = dat(FBNEO, game("fb", *(rom(n, 8, f"0000000{n}") for n in "123")))
    assert standins(mame, fbneo) == {"few": {"fb"}, "many": {"fb"}}
    assert stands_in_for(mame, fbneo) == {"fb": "many"}


def test_the_inverse_breaks_a_tie_by_family_name():
    mame = dat(
        DEFAULT_EMULATOR,
        game("zeta", rom("1", 8, "00000001")),
        game("eta", rom("2", 8, "00000002")),
    )
    fbneo = dat(FBNEO, game("fb", rom("1", 8, "00000001"), rom("2", 8, "00000002")))
    assert stands_in_for(mame, fbneo) == {"fb": "eta"}


def test_standins_can_be_asked_for_some_families_only(dats):
    mame, fbneo = dats
    assert standins(mame, fbneo, {"beta"}) == {"beta": {"betafb"}}
    assert standins(mame, fbneo, set()) == {}


def test_what_to_build_for_a_family_brings_each_stand_ins_bios(dats):
    mame, fbneo = dats
    assert fbneo_wanted(mame, fbneo, {"beta"}) == {"betafb", "biosx"}
    assert fbneo_wanted(mame, fbneo, {"alpha"}) == {"alpha", "alphaua"}
    assert fbneo_wanted(mame, fbneo, set()) == frozenset()
    assert with_bios(fbneo, ["fbonly"]) == {"fbonly"}


def test_every_set_is_read_once_however_many_families_there_are(dats, monkeypatch):
    mame, fbneo = dats
    read = []
    real = standins_module.rom_keys

    def counting(g):
        read.append(g.name)
        return real(g)

    monkeypatch.setattr(standins_module, "rom_keys", counting)
    stands_in_for(mame, fbneo)
    # Once per set of each list, not once per pair of sets.
    assert sorted(read) == sorted([*mame.games, *fbneo.games])

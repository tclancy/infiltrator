import os
from pathlib import Path

import pytest

from infiltrator.dat import load_dat

REAL_DAT = os.environ.get("INFILTRATOR_REAL_DAT")


def _names(roms) -> list[str]:
    return sorted(r.name for r in roms)


def test_parses_games_and_flags(synthetic_dat):
    dat = load_dat(synthetic_dat)
    g = dat.games
    assert g["alphab"].cloneof == "alpha"
    assert g["biosx"].is_bios
    assert g["gamma"].has_disk
    assert (g["alpha"].players, g["alpha"].control) == (2, "joy4way")


def test_missing_buttons_means_zero(synthetic_dat):
    assert load_dat(synthetic_dat).games["alpha"].buttons == 0


def test_required_roms_skip_nodump(synthetic_dat):
    dat = load_dat(synthetic_dat)
    assert _names(dat.required_roms(dat.games["alpha"])) == ["a1.bin", "a2.bin"]


def test_clone_needs_shared_chips_under_its_own_names(synthetic_dat):
    dat = load_dat(synthetic_dat)
    assert _names(dat.required_roms(dat.games["alphab"])) == ["a1.bin", "ab2.bin", "ab3.bin"]


def test_bios_chips_excluded_from_game_even_without_bios_attr(synthetic_dat):
    dat = load_dat(synthetic_dat)
    assert _names(dat.required_roms(dat.games["beta"])) == ["b1.bin"]


def test_bios_reached_through_parent(synthetic_dat):
    dat = load_dat(synthetic_dat)
    betab = dat.games["betab"]
    assert dat.bios_of(betab).name == "biosx"
    assert _names(dat.required_roms(betab)) == ["b1.bin", "bb2.bin"]


def test_bios_set_requires_default_bios_and_unattributed_chips(synthetic_dat):
    dat = load_dat(synthetic_dat)
    assert _names(dat.required_roms(dat.games["biosx"])) == ["bx-fix.bin", "bx-std.bin"]


def test_lookup_shared_chip_hits_parent_and_clone(synthetic_dat):
    dat = load_dat(synthetic_dat)
    a2 = next(r for r in dat.games["alpha"].roms if r.name == "a2.bin")
    hits = {(g.name, r.name) for g, r in dat.lookup(a2.sha1, a2.size, a2.crc)}
    assert hits == {("alpha", "a2.bin"), ("alphab", "ab2.bin")}


def test_rom_without_sha1_matches_on_size_and_crc(synthetic_dat):
    dat = load_dat(synthetic_dat)
    d1 = dat.games["delta"].roms[0]
    assert d1.sha1 is None
    assert dat.lookup("not-a-sha", d1.size, d1.crc)[0][0].name == "delta"


def test_family_is_cloneof_root(synthetic_dat):
    dat = load_dat(synthetic_dat)
    assert dat.family(dat.games["alphab"]) == "alpha"
    assert dat.family(dat.games["alpha"]) == "alpha"


@pytest.mark.skipif(not REAL_DAT, reason="set INFILTRATOR_REAL_DAT to the MAME 2003-Plus xml")
def test_real_dat_shape():
    dat = load_dat(Path(REAL_DAT).expanduser())
    assert len(dat.games) == 5715
    assert sum(g.is_bios for g in dat.games.values()) == 20
    neogeo = dat.games["neogeo"]
    assert {"sp-s2.sp1", "sfix.sfx", "mame.sm1", "mamelo.lo"} <= set(
        _names(dat.required_roms(neogeo))
    )
    assert "uni-bios_4_0.rom" not in _names(dat.required_roms(neogeo))
    assert dat.bios_of(dat.games["2020bbh"]).name == "neogeo"
    assert not any(
        r.name in {"sp-s2.sp1", "sfix.sfx"} for r in dat.required_roms(dat.games["2020bbh"])
    )
    pacman = dat.games["pacman"]
    assert dat.family(pacman) == "puckman"
    assert len(dat.required_roms(pacman)) == 10

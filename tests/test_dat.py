import json
import os
from pathlib import Path

import pytest

from infiltrator.dat import load_dat, load_optional_roms

REAL_DAT = os.environ.get("INFILTRATOR_REAL_DAT")
REAL_FBNEO_DAT = os.environ.get("INFILTRATOR_REAL_FBNEO_DAT")


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


# Requirement A: Dat.emulator field
def test_dat_emulator_field_defaults_to_mame2003_plus(synthetic_dat):
    dat = load_dat(synthetic_dat)
    assert dat.emulator == "mame2003-plus"


def test_dat_emulator_field_can_be_set_to_fbneo(synthetic_fbneo_dat):
    dat = load_dat(synthetic_fbneo_dat, emulator="fbneo")
    assert dat.emulator == "fbneo"


def test_dat_rejects_unknown_emulator(synthetic_dat):
    with pytest.raises(ValueError, match="Unknown emulator.*mame2003-plus.*fbneo"):
        load_dat(synthetic_dat, emulator="unknown")


# Requirement B: FBNeo BIOS recognition
def test_fbneo_recognizes_bios_from_isbios_attribute(synthetic_fbneo_dat):
    dat = load_dat(synthetic_fbneo_dat, emulator="fbneo")
    assert dat.games["biosx"].is_bios


def test_fbneo_bios_of_works_correctly(synthetic_fbneo_dat):
    dat = load_dat(synthetic_fbneo_dat, emulator="fbneo")
    betab = dat.games["betab"]
    assert dat.bios_of(betab).name == "biosx"


def test_fbneo_required_roms_excludes_bios_held_roms(synthetic_fbneo_dat):
    dat = load_dat(synthetic_fbneo_dat, emulator="fbneo")
    assert _names(dat.required_roms(dat.games["beta"])) == ["b1.bin"]


# Requirement C: Fallback to size+crc when no sha1
def test_fbneo_lookup_works_without_sha1(synthetic_fbneo_dat):
    dat = load_dat(synthetic_fbneo_dat, emulator="fbneo")
    a1 = next(r for r in dat.games["alpha"].roms if r.name == "a1.bin")
    assert a1.sha1 is None
    # Should still be found via (size, crc) key
    hits = dat.lookup("ignored", a1.size, a1.crc)
    assert len(hits) > 0
    assert hits[0][0].name == "alpha"


def test_fbneo_all_roms_lack_sha1(synthetic_fbneo_dat):
    dat = load_dat(synthetic_fbneo_dat, emulator="fbneo")
    for game in dat.games.values():
        for rom in game.roms:
            assert rom.sha1 is None, f"ROM {rom.name} in {game.name} should not have sha1"


# Requirement D: optional_roms parameter
def test_optional_roms_marks_roms_as_optional(synthetic_fbneo_dat):
    optional = {"alpha": frozenset(["a1b7c8d9"])}  # crc of a1
    # Create correct CRCs
    dat = load_dat(synthetic_fbneo_dat, emulator="fbneo")
    a1_rom = next(r for r in dat.games["alpha"].roms if r.name == "a1.bin")
    actual_crc = a1_rom.crc
    optional = {"alpha": frozenset([actual_crc])}
    dat = load_dat(synthetic_fbneo_dat, emulator="fbneo", optional_roms=optional)
    a1 = next(r for r in dat.games["alpha"].roms if r.name == "a1.bin")
    assert a1.optional is True


def test_optional_roms_not_included_in_required(synthetic_fbneo_dat):
    dat = load_dat(synthetic_fbneo_dat, emulator="fbneo")
    a1_rom = next(r for r in dat.games["alpha"].roms if r.name == "a1.bin")
    actual_crc = a1_rom.crc
    optional = {"alpha": frozenset([actual_crc])}
    dat = load_dat(synthetic_fbneo_dat, emulator="fbneo", optional_roms=optional)
    required = _names(dat.required_roms(dat.games["alpha"]))
    assert "a1.bin" not in required


def test_optional_roms_work_correctly_per_set(synthetic_fbneo_dat):
    dat = load_dat(synthetic_fbneo_dat, emulator="fbneo")
    a1_rom = next(r for r in dat.games["alpha"].roms if r.name == "a1.bin")
    actual_crc = a1_rom.crc
    # Optional only for alpha, not alphab
    optional = {"alpha": frozenset([actual_crc])}
    dat = load_dat(synthetic_fbneo_dat, emulator="fbneo", optional_roms=optional)
    # a1.bin in alphab should NOT be optional
    a1_in_alphab = next(r for r in dat.games["alphab"].roms if r.name == "a1.bin")
    assert a1_in_alphab.optional is False


def test_unknown_set_in_optional_roms_ignored(synthetic_fbneo_dat):
    optional = {"unknown_set": frozenset(["12345678"])}
    dat = load_dat(synthetic_fbneo_dat, emulator="fbneo", optional_roms=optional)
    # Should not raise, just ignore unknown set
    assert dat.games["alpha"]


def test_unknown_crc_in_optional_roms_ignored(synthetic_fbneo_dat):
    optional = {"alpha": frozenset(["ffffffff"])}
    dat = load_dat(synthetic_fbneo_dat, emulator="fbneo", optional_roms=optional)
    # Should not raise, just ignore unknown CRC
    for rom in dat.games["alpha"].roms:
        assert rom.optional is False


# Requirement E: BIOS sets without biosset element
def test_fbneo_bios_set_requires_non_nodump_non_optional_roms(synthetic_fbneo_dat):
    dat = load_dat(synthetic_fbneo_dat, emulator="fbneo")
    bios_required = dat.required_roms(dat.games["biosx"])
    # Should have all roms except nodump
    assert "bx-std.bin" in _names(bios_required)
    assert "bx-alt.bin" in _names(bios_required)
    assert "bx-fix.bin" in _names(bios_required)


def test_fbneo_bios_set_respects_optional_roms(synthetic_fbneo_dat):
    dat = load_dat(synthetic_fbneo_dat, emulator="fbneo")
    bx_std = next(r for r in dat.games["biosx"].roms if r.name == "bx-std.bin")
    optional = {"biosx": frozenset([bx_std.crc])}
    dat = load_dat(synthetic_fbneo_dat, emulator="fbneo", optional_roms=optional)
    bios_required = dat.required_roms(dat.games["biosx"])
    assert "bx-std.bin" not in _names(bios_required)
    assert "bx-fix.bin" in _names(bios_required)


# Requirement F: load_optional_roms function
def test_load_optional_roms_from_json(tmp_path):
    optional_file = tmp_path / "optional.json"
    data = {"alpha": ["a1b7c8d9", "a2d3e4f5"], "beta": ["b1c2d3e4"]}
    optional_file.write_text(json.dumps(data))
    result = load_optional_roms(optional_file)
    assert result == {
        "alpha": frozenset(["a1b7c8d9", "a2d3e4f5"]),
        "beta": frozenset(["b1c2d3e4"]),
    }


def test_load_optional_roms_lowercases_crcs(tmp_path):
    optional_file = tmp_path / "optional.json"
    data = {"alpha": ["A1B7C8D9", "a2d3e4f5"]}
    optional_file.write_text(json.dumps(data))
    result = load_optional_roms(optional_file)
    assert result["alpha"] == frozenset(["a1b7c8d9", "a2d3e4f5"])


def test_load_optional_roms_rejects_non_object(tmp_path):
    optional_file = tmp_path / "optional.json"
    optional_file.write_text(json.dumps(["not", "an", "object"]))
    with pytest.raises(ValueError, match="must be a JSON object"):
        load_optional_roms(optional_file)


def test_load_optional_roms_rejects_non_list_values(tmp_path):
    optional_file = tmp_path / "optional.json"
    optional_file.write_text(json.dumps({"alpha": "not a list"}))
    with pytest.raises(ValueError, match="values must be lists"):
        load_optional_roms(optional_file)


def test_load_optional_roms_rejects_bad_crc_format(tmp_path):
    optional_file = tmp_path / "optional.json"
    optional_file.write_text(json.dumps({"alpha": ["not_valid"]}))
    with pytest.raises(ValueError, match="8-hex string"):
        load_optional_roms(optional_file)


def test_load_optional_roms_rejects_crc_too_short(tmp_path):
    optional_file = tmp_path / "optional.json"
    optional_file.write_text(json.dumps({"alpha": ["1234567"]}))
    with pytest.raises(ValueError, match="8-hex string"):
        load_optional_roms(optional_file)


def test_load_optional_roms_rejects_crc_too_long(tmp_path):
    optional_file = tmp_path / "optional.json"
    optional_file.write_text(json.dumps({"alpha": ["123456789"]}))
    with pytest.raises(ValueError, match="8-hex string"):
        load_optional_roms(optional_file)


def test_load_optional_roms_rejects_non_hex_crc(tmp_path):
    optional_file = tmp_path / "optional.json"
    optional_file.write_text(json.dumps({"alpha": ["zzzzzzzz"]}))
    with pytest.raises(ValueError, match="8-hex string"):
        load_optional_roms(optional_file)


# Requirement G: Existing tests still pass (implicit in all test_* above)


@pytest.mark.skipif(not REAL_FBNEO_DAT, reason="set INFILTRATOR_REAL_FBNEO_DAT to the FBNeo DAT")
def test_real_fbneo_dat_shape():
    dat = load_dat(Path(REAL_FBNEO_DAT).expanduser(), emulator="fbneo")
    assert len(dat.games) == 8747
    assert sum(g.is_bios for g in dat.games.values()) == 15
    # mslug should have some required roms (but not all 47)
    mslug = dat.games["mslug"]
    required = dat.required_roms(mslug)
    assert len(required) < 47
    # mslug is a game that depends on neogeo BIOS
    assert dat.bios_of(mslug) is not None
    assert dat.bios_of(mslug).name == "neogeo"

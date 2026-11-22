import json
import zlib

from conftest import label_bytes

from infiltrator.config import Settings
from infiltrator.dat import DEFAULT_EMULATOR, FBNEO
from infiltrator.dats import load_dats


def settings(tmp_path, mame, **kw) -> Settings:
    return Settings(tmp_path / "d", tmp_path / "l", tmp_path / "c.db", mame, tmp_path / "m", **kw)


def test_without_fbneo_configured_only_mame_2003_plus_is_loaded(tmp_path, synthetic_dat):
    dats = load_dats(settings(tmp_path, synthetic_dat))
    assert list(dats) == [DEFAULT_EMULATOR]
    assert dats[DEFAULT_EMULATOR].emulator == DEFAULT_EMULATOR


def test_fbneo_is_loaded_second_in_its_own_dialect(tmp_path, synthetic_dat, synthetic_fbneo_dat):
    dats = load_dats(settings(tmp_path, synthetic_dat, fbneo_dat_path=synthetic_fbneo_dat))
    assert list(dats) == [DEFAULT_EMULATOR, FBNEO]
    assert dats[FBNEO].emulator == FBNEO
    assert dats[FBNEO].games["biosx"].is_bios  # isbios="yes", which MAME's dialect ignores


def test_fbneo_is_loaded_with_its_optional_rom_list(tmp_path, synthetic_dat, synthetic_fbneo_dat):
    optional = tmp_path / "optional.json"
    optional.write_text(json.dumps({"alpha": [f"{zlib.crc32(label_bytes('a2')):08x}"]}))
    config = settings(
        tmp_path, synthetic_dat, fbneo_dat_path=synthetic_fbneo_dat, fbneo_optional_path=optional
    )
    dats = load_dats(config)
    fbneo_alpha = dats[FBNEO].games["alpha"]
    assert [r.name for r in dats[FBNEO].required_roms(fbneo_alpha)] == ["a1.bin"]
    mame_alpha = dats[DEFAULT_EMULATOR].games["alpha"]
    assert len(dats[DEFAULT_EMULATOR].required_roms(mame_alpha)) == 2

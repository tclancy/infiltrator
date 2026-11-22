from pathlib import Path

import pytest

from infiltrator.config import load_settings


def _toml(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(body)
    return path


def test_toml_supplies_paths(tmp_path):
    cfg = _toml(
        tmp_path,
        'drop_dir = "/d"\nlibrary_dir = "/l"\ndb_path = "/c.db"\n'
        'dat_path = "/x.xml"\nmetadata_dir = "/m"\n',
    )
    s = load_settings(env={}, config_file=cfg)
    assert s.drop_dir == Path("/d")
    assert s.shelf_size == 8


def test_env_overrides_toml(tmp_path):
    cfg = _toml(
        tmp_path,
        'drop_dir = "/d"\nlibrary_dir = "/l"\ndb_path = "/c.db"\n'
        'dat_path = "/x.xml"\nmetadata_dir = "/m"\nshelf_size = 6\n',
    )
    s = load_settings(
        env={"INFILTRATOR_DROP_DIR": "/elsewhere", "INFILTRATOR_SHELF_SIZE": "10"},
        config_file=cfg,
    )
    assert s.drop_dir == Path("/elsewhere")
    assert s.shelf_size == 10


@pytest.mark.parametrize("size", [5, 11])
def test_shelf_size_outside_6_to_10_raises(tmp_path, size):
    cfg = _toml(
        tmp_path,
        'drop_dir = "/d"\nlibrary_dir = "/l"\ndb_path = "/c.db"\n'
        f'dat_path = "/x.xml"\nmetadata_dir = "/m"\nshelf_size = {size}\n',
    )
    with pytest.raises(ValueError):
        load_settings(env={}, config_file=cfg)


def test_missing_required_path_raises(tmp_path):
    cfg = _toml(tmp_path, 'drop_dir = "/d"\n')
    with pytest.raises(ValueError, match="library_dir"):
        load_settings(env={}, config_file=cfg)


def test_tilde_is_expanded(tmp_path):
    cfg = _toml(
        tmp_path,
        'drop_dir = "~/drop"\nlibrary_dir = "/l"\ndb_path = "/c.db"\n'
        'dat_path = "/x.xml"\nmetadata_dir = "/m"\n',
    )
    s = load_settings(env={}, config_file=cfg)
    assert s.drop_dir == Path.home() / "drop"


def test_romm_settings_are_optional(tmp_path):
    cfg = _toml(
        tmp_path,
        'drop_dir = "/d"\nlibrary_dir = "/l"\ndb_path = "/c.db"\n'
        'dat_path = "/x.xml"\nmetadata_dir = "/m"\n',
    )
    s = load_settings(env={}, config_file=cfg)
    assert (s.shelf_dir, s.bios_dir, s.romm_url, s.romm_token) == (None, None, None, None)


def test_romm_settings_from_toml_and_token_from_env_only(tmp_path):
    cfg = _toml(
        tmp_path,
        'drop_dir = "/d"\nlibrary_dir = "/l"\ndb_path = "/c.db"\n'
        'dat_path = "/x.xml"\nmetadata_dir = "/m"\nshelf_dir = "~/shelf"\n'
        'bios_dir = "/b"\nromm_url = "http://romm:8080/"\nromm_token = "in-toml"\n',
    )
    s = load_settings(env={"INFILTRATOR_ROMM_TOKEN": "rmm_x"}, config_file=cfg)
    assert s.shelf_dir == Path.home() / "shelf"
    assert s.bios_dir == Path("/b")
    assert s.romm_url == "http://romm:8080"
    assert s.romm_token == "rmm_x"
    assert load_settings(env={}, config_file=cfg).romm_token is None


def test_romm_token_can_come_from_a_file(tmp_path):
    secret = tmp_path / "token"
    secret.write_text("rmm_from_file\n")
    cfg = _toml(
        tmp_path,
        'drop_dir = "/d"\nlibrary_dir = "/l"\ndb_path = "/c.db"\n'
        f'dat_path = "/x.xml"\nmetadata_dir = "/m"\nromm_token_file = "{secret}"\n',
    )
    assert load_settings(env={}, config_file=cfg).romm_token == "rmm_from_file"
    env = {"INFILTRATOR_ROMM_TOKEN": "rmm_env"}
    assert load_settings(env=env, config_file=cfg).romm_token == "rmm_env"


def test_missing_or_empty_token_file_means_no_token(tmp_path):
    empty = tmp_path / "empty"
    empty.write_text("")
    for path in (tmp_path / "absent", empty):
        cfg = _toml(
            tmp_path,
            'drop_dir = "/d"\nlibrary_dir = "/l"\ndb_path = "/c.db"\n'
            f'dat_path = "/x.xml"\nmetadata_dir = "/m"\nromm_token_file = "{path}"\n',
        )
        assert load_settings(env={}, config_file=cfg).romm_token is None


@pytest.mark.parametrize(
    "folders",
    [
        'shelf_dir = "/r/arcade"\nbios_dir = "/r/arcade"\n',
        'shelf_dir = "/r/arcade"\nbios_dir = "/r/arcade/bios"\n',
        'shelf_dir = "/r/arcade"\n',
    ],
)
def test_romm_folders_must_be_two_separate_folders(tmp_path, folders):
    cfg = _toml(
        tmp_path,
        'drop_dir = "/d"\nlibrary_dir = "/l"\ndb_path = "/c.db"\n'
        'dat_path = "/x.xml"\nmetadata_dir = "/m"\n' + folders,
    )
    with pytest.raises(ValueError):
        load_settings(env={}, config_file=cfg)


BASE = (
    'drop_dir = "/d"\nlibrary_dir = "/l"\ndb_path = "/c.db"\n'
    'dat_path = "/x.xml"\nmetadata_dir = "/m"\n'
)


def test_fbneo_is_off_unless_configured(tmp_path):
    s = load_settings(env={}, config_file=_toml(tmp_path, BASE))
    assert (s.fbneo_dat_path, s.fbneo_optional_path) == (None, None)


def test_fbneo_paths_come_from_toml(tmp_path):
    cfg = _toml(
        tmp_path, BASE + 'fbneo_dat_path = "~/fbneo.dat"\nfbneo_optional_path = "/o.json"\n'
    )
    s = load_settings(env={}, config_file=cfg)
    assert s.fbneo_dat_path == Path.home() / "fbneo.dat"
    assert s.fbneo_optional_path == Path("/o.json")


def test_fbneo_paths_can_be_overridden_by_the_environment(tmp_path):
    cfg = _toml(tmp_path, BASE + 'fbneo_dat_path = "/toml.dat"\n')
    env = {
        "INFILTRATOR_FBNEO_DAT_PATH": "/env.dat",
        "INFILTRATOR_FBNEO_OPTIONAL_PATH": "/env.json",
    }
    s = load_settings(env=env, config_file=cfg)
    assert (s.fbneo_dat_path, s.fbneo_optional_path) == (Path("/env.dat"), Path("/env.json"))


def test_an_fbneo_optional_list_without_the_fbneo_set_list_is_refused(tmp_path):
    cfg = _toml(tmp_path, BASE + 'fbneo_optional_path = "/o.json"\n')
    with pytest.raises(ValueError, match="fbneo_dat_path"):
        load_settings(env={}, config_file=cfg)


FBNEO = 'fbneo_dat_path = "/f.dat"\n'
FOUR_FOLDERS = (
    'shelf_dir = "/r/roms/mame"\nbios_dir = "/r/bios/mame"\n'
    'fbneo_shelf_dir = "/r/roms/fbneo"\nfbneo_bios_dir = "/r/bios/fbneo"\n'
)


def test_fbneo_folders_are_off_unless_configured(tmp_path):
    s = load_settings(env={}, config_file=_toml(tmp_path, BASE + FBNEO))
    assert (s.fbneo_shelf_dir, s.fbneo_bios_dir) == (None, None)


def test_fbneo_folders_come_from_toml_and_the_environment(tmp_path):
    s = load_settings(env={}, config_file=_toml(tmp_path, BASE + FBNEO + FOUR_FOLDERS))
    assert (s.fbneo_shelf_dir, s.fbneo_bios_dir) == (Path("/r/roms/fbneo"), Path("/r/bios/fbneo"))
    assert (s.shelf_dir, s.bios_dir) == (Path("/r/roms/mame"), Path("/r/bios/mame"))
    env = {"INFILTRATOR_FBNEO_SHELF_DIR": "/e/roms", "INFILTRATOR_FBNEO_BIOS_DIR": "~/e/bios"}
    s = load_settings(env=env, config_file=_toml(tmp_path, BASE + FBNEO + FOUR_FOLDERS))
    assert (s.fbneo_shelf_dir, s.fbneo_bios_dir) == (Path("/e/roms"), Path.home() / "e/bios")


def test_fbneo_folders_without_mames_are_fine(tmp_path):
    folders = 'fbneo_shelf_dir = "/r/roms/fbneo"\nfbneo_bios_dir = "/r/bios/fbneo"\n'
    s = load_settings(env={}, config_file=_toml(tmp_path, BASE + FBNEO + folders))
    assert s.shelf_dir is None and s.fbneo_shelf_dir == Path("/r/roms/fbneo")


@pytest.mark.parametrize(
    ("folders", "says"),
    [
        ('fbneo_shelf_dir = "/r/roms/fbneo"\n', "fbneo_bios_dir"),
        ('fbneo_bios_dir = "/r/bios/fbneo"\n', "fbneo_shelf_dir"),
        (FOUR_FOLDERS.replace("/r/bios/fbneo", "/r/roms/fbneo"), "separate"),
        (FOUR_FOLDERS.replace("/r/roms/fbneo", "/r/roms/mame/fbneo"), "separate"),
        (FOUR_FOLDERS.replace("/r/bios/fbneo", "/r/bios/mame"), "separate"),
        (FOUR_FOLDERS.replace("/r/roms/fbneo", "/r/bios"), "separate"),
    ],
)
def test_fbneo_folders_come_as_a_pair_apart_from_every_other_folder(tmp_path, folders, says):
    with pytest.raises(ValueError, match=says):
        load_settings(env={}, config_file=_toml(tmp_path, BASE + FBNEO + folders))


def test_fbneo_folders_without_the_fbneo_set_list_are_refused(tmp_path):
    folders = 'fbneo_shelf_dir = "/r/roms/fbneo"\nfbneo_bios_dir = "/r/bios/fbneo"\n'
    with pytest.raises(ValueError, match="fbneo_dat_path"):
        load_settings(env={}, config_file=_toml(tmp_path, BASE + folders))


BASE = (
    'drop_dir = "/d"\nlibrary_dir = "/l"\ndb_path = "/c.db"\n'
    'dat_path = "/x.xml"\nmetadata_dir = "/m"\n'
)
WITH_ROMM = BASE + 'romm_url = "http://romm:8080"\n'
TOKEN = {"INFILTRATOR_ROMM_TOKEN": "rmm_x"}


def test_the_shelf_collection_is_off_unless_configured(tmp_path):
    assert load_settings(env=TOKEN, config_file=_toml(tmp_path, WITH_ROMM)).romm_collection is None


def test_the_shelf_collection_comes_from_toml(tmp_path):
    cfg = _toml(tmp_path, WITH_ROMM + 'romm_collection = "On the shelf"\n')
    assert load_settings(env=TOKEN, config_file=cfg).romm_collection == "On the shelf"


def test_the_shelf_collection_can_be_overridden_by_the_environment(tmp_path):
    cfg = _toml(tmp_path, WITH_ROMM + 'romm_collection = "On the shelf"\n')
    env = {**TOKEN, "INFILTRATOR_ROMM_COLLECTION": "Tonight"}
    assert load_settings(env=env, config_file=cfg).romm_collection == "Tonight"


@pytest.mark.parametrize(
    ("body", "env"),
    [
        (BASE + 'romm_collection = "On the shelf"\n', TOKEN),  # no RomM address
        (WITH_ROMM + 'romm_collection = "On the shelf"\n', {}),  # no token
        (BASE, {"INFILTRATOR_ROMM_COLLECTION": "On the shelf", **TOKEN}),
    ],
)
def test_a_shelf_collection_without_romm_is_refused(tmp_path, body, env):
    with pytest.raises(ValueError, match="romm_collection needs romm_url and a RomM token"):
        load_settings(env=env, config_file=_toml(tmp_path, body))

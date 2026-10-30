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

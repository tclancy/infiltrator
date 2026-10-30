"""Where things live, read from a TOML file with environment overrides."""

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG = Path("~/.config/infiltrator/config.toml").expanduser()
PATH_KEYS = ("drop_dir", "library_dir", "db_path", "dat_path", "metadata_dir")
OPTIONAL_PATH_KEYS = ("shelf_dir", "bios_dir")
TOKEN_ENV = "INFILTRATOR_ROMM_TOKEN"  # a secret: read from the environment, never the TOML
SHELF_MIN, SHELF_MAX = 6, 10


@dataclass(frozen=True)
class Settings:
    drop_dir: Path
    library_dir: Path
    db_path: Path
    dat_path: Path
    metadata_dir: Path
    shelf_size: int = 8
    shelf_dir: Path | None = None  # RomM's roms/arcade: the shelf's games, nothing else
    bios_dir: Path | None = None  # RomM's bios/arcade
    romm_url: str | None = None
    romm_token: str | None = None


def _read_toml(config_file: Path | None) -> dict:
    path = config_file or DEFAULT_CONFIG
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _merge_env(raw: dict, env: Mapping[str, str]) -> dict:
    merged = dict(raw)
    for key in (*PATH_KEYS, *OPTIONAL_PATH_KEYS, "shelf_size", "romm_url"):
        value = env.get(f"INFILTRATOR_{key.upper()}")
        if value is not None:
            merged[key] = value
    return merged


def _shelf_size(value) -> int:
    size = int(value)
    if not SHELF_MIN <= size <= SHELF_MAX:
        raise ValueError(f"shelf_size must be {SHELF_MIN}-{SHELF_MAX}, got {size}")
    return size


def load_settings(env: Mapping[str, str] = os.environ, config_file: Path | None = None) -> Settings:
    merged = _merge_env(_read_toml(config_file), env)
    missing = [k for k in PATH_KEYS if k not in merged]
    if missing:
        raise ValueError(f"missing setting(s): {', '.join(missing)}")
    paths = {k: Path(str(merged[k])).expanduser() for k in PATH_KEYS}
    optional = {k: Path(str(merged[k])).expanduser() for k in OPTIONAL_PATH_KEYS if k in merged}
    url = merged.get("romm_url")
    return Settings(
        **paths,
        **optional,
        shelf_size=_shelf_size(merged.get("shelf_size", 8)),
        romm_url=str(url).rstrip("/") if url else None,
        romm_token=env.get(TOKEN_ENV) or None,
    )

"""Where things live, read from a TOML file with environment overrides."""

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG = Path("~/.config/infiltrator/config.toml").expanduser()
PATH_KEYS = ("drop_dir", "library_dir", "db_path", "dat_path", "metadata_dir")
OPTIONAL_PATH_KEYS = (
    "shelf_dir",
    "bios_dir",
    "fbneo_dat_path",
    "fbneo_optional_path",
    "fbneo_shelf_dir",
    "fbneo_bios_dir",
)
FOLDER_PAIRS = (("shelf_dir", "bios_dir"), ("fbneo_shelf_dir", "fbneo_bios_dir"))
TOKEN_ENV = "INFILTRATOR_ROMM_TOKEN"  # a secret: the environment or romm_token_file, never the TOML
SHELF_MIN, SHELF_MAX = 6, 10


@dataclass(frozen=True)
class Settings:
    drop_dir: Path
    library_dir: Path
    db_path: Path
    dat_path: Path  # MAME 2003-Plus's set list
    metadata_dir: Path
    shelf_size: int = 8
    shelf_dir: Path | None = None  # RomM's roms/mame: MAME 2003-Plus's shelf games, nothing else
    bios_dir: Path | None = None  # RomM's bios/mame
    romm_url: str | None = None
    romm_token: str | None = None
    fbneo_dat_path: Path | None = None  # FBNeo's set list; FBNeo is off without it
    fbneo_optional_path: Path | None = None  # `scripts/fbneo_optional.py`'s output
    fbneo_shelf_dir: Path | None = None  # RomM's roms/fbneo: FBNeo's shelf games, nothing else
    fbneo_bios_dir: Path | None = None  # RomM's bios/fbneo


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


def _check_pairs(optional: dict[str, Path]) -> None:
    """An emulator's games and its BIOS sets are published together or not at all."""
    for shelf, bios in FOLDER_PAIRS:
        if (shelf in optional) != (bios in optional):
            raise ValueError(f"set both {shelf} and {bios}, or neither")


def _check_separate(optional: dict[str, Path]) -> None:
    """Each folder's publish would undo another's if they were one folder or nested."""
    folders = [k for pair in FOLDER_PAIRS for k in pair if k in optional]
    for i, one in enumerate(folders):
        for other in folders[i + 1 :]:
            a, b = optional[one], optional[other]
            if a.is_relative_to(b) or b.is_relative_to(a):
                raise ValueError(f"{one} and {other} must be separate folders")


def _check_romm_folders(optional: dict[str, Path]) -> None:
    _check_pairs(optional)
    _check_separate(optional)


def _check_fbneo(optional: dict[str, Path]) -> None:
    """An optional-ROM list, or FBNeo's folders, mean nothing without FBNeo's set list."""
    for needs_it in ("fbneo_optional_path", "fbneo_shelf_dir"):
        if needs_it in optional and "fbneo_dat_path" not in optional:
            raise ValueError(f"{needs_it} needs fbneo_dat_path")


def _romm_token(merged: dict, env: Mapping[str, str]) -> str | None:
    if env.get(TOKEN_ENV):
        return env[TOKEN_ENV]
    path = merged.get("romm_token_file")
    if not path:
        return None
    try:
        return Path(str(path)).expanduser().read_text().strip() or None
    except FileNotFoundError:
        return None


def load_settings(env: Mapping[str, str] = os.environ, config_file: Path | None = None) -> Settings:
    merged = _merge_env(_read_toml(config_file), env)
    missing = [k for k in PATH_KEYS if k not in merged]
    if missing:
        raise ValueError(f"missing setting(s): {', '.join(missing)}")
    paths = {k: Path(str(merged[k])).expanduser() for k in PATH_KEYS}
    optional = {k: Path(str(merged[k])).expanduser() for k in OPTIONAL_PATH_KEYS if k in merged}
    _check_romm_folders(optional)
    _check_fbneo(optional)
    url = merged.get("romm_url")
    return Settings(
        **paths,
        **optional,
        shelf_size=_shelf_size(merged.get("shelf_size", 8)),
        romm_url=str(url).rstrip("/") if url else None,
        romm_token=_romm_token(merged, env),
    )

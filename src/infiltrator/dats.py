"""The set lists of every emulator the settings name, loaded in one place."""

from collections.abc import Collection, Mapping

from infiltrator.config import Settings
from infiltrator.dat import DEFAULT_EMULATOR, FBNEO, Dat, OptionalRoms, load_dat, load_optional_roms


def _fbneo_optional(settings: Settings) -> OptionalRoms | None:
    if settings.fbneo_optional_path is None:
        return None
    return load_optional_roms(settings.fbneo_optional_path)


def load_dats(settings: Settings) -> dict[str, Dat]:
    """MAME 2003-Plus first, always; FBNeo after it, only when its set list is configured."""
    dats = {DEFAULT_EMULATOR: load_dat(settings.dat_path)}
    if settings.fbneo_dat_path is not None:
        dats[FBNEO] = load_dat(
            settings.fbneo_dat_path, emulator=FBNEO, optional_roms=_fbneo_optional(settings)
        )
    return dats


Wanted = Mapping[str, Collection[str] | None]
"""Emulator → the set names to build for it; None means every set that can be built."""


def default_wanted(dats: Mapping[str, Dat]) -> dict[str, frozenset[str] | None]:
    """Every MAME 2003-Plus set; no set for any other emulator until something names it."""
    return {name: None if name == DEFAULT_EMULATOR else frozenset() for name in dats}

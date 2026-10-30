"""Write complete, self-contained (non-merged) sets from a pool of verified chips."""

import hashlib
import os
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from infiltrator.dat import ChipKey, Dat, Game, Rom
from infiltrator.scan import Chip, fingerprint


@dataclass
class RebuildResult:
    built: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)


class ChipPool:
    def __init__(self) -> None:
        self._by_key: dict[ChipKey, Chip] = {}

    def add(self, chip: Chip) -> None:
        self._by_key.setdefault(chip.sha1, chip)
        self._by_key.setdefault((chip.size, chip.crc), chip)

    def find(self, rom: Rom) -> Chip | None:
        return self._by_key.get(rom.key)


def library_chips(library: Path) -> list[Chip]:
    """Every member of every library zip, so earlier runs' parents and BIOSes count."""
    chips = []
    for path in sorted(library.glob("*.zip")):
        try:
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    chips.append(fingerprint(zf.read(name), _reader(path, name)))
        except zipfile.BadZipFile:
            continue
    return chips


def _reader(path: Path, member: str):
    def read() -> bytes:
        with zipfile.ZipFile(path) as zf:
            return zf.read(member)

    return read


def _matches(rom: Rom, data: bytes) -> bool:
    if rom.sha1:
        return hashlib.sha1(data).hexdigest() == rom.sha1
    return len(data) == rom.size and f"{zlib.crc32(data):08x}" == rom.crc


def set_is_valid(path: Path, roms: tuple[Rom, ...]) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            return all(r.name in names and _matches(r, zf.read(r.name)) for r in roms)
    except (zipfile.BadZipFile, OSError):
        return False


def _write_set(path: Path, roms: tuple[Rom, ...], pool: ChipPool) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for rom in sorted(roms, key=lambda r: r.name):
                zf.writestr(rom.name, pool.find(rom).read())
        if not set_is_valid(tmp, roms):
            raise RuntimeError(f"read-back verification failed for {path.name}")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _buildable(game: Game, dat: Dat, pool: ChipPool, library: Path) -> bool:
    if game.has_disk:
        return False
    bios = dat.bios_of(game)
    if bios is not None and not (library / f"{bios.name}.zip").exists():
        return False
    return all(pool.find(r) for r in dat.required_roms(game))


def rebuild(pool: ChipPool, dat: Dat, library: Path) -> RebuildResult:
    library.mkdir(parents=True, exist_ok=True)
    result = RebuildResult()
    ordered = sorted(dat.games.values(), key=lambda g: (not g.is_bios, g.name))
    for game in ordered:
        if not _buildable(game, dat, pool, library):
            continue
        roms = dat.required_roms(game)
        target = library / f"{game.name}.zip"
        if target.exists() and set_is_valid(target, roms):
            result.already_present.append(game.name)
            continue
        _write_set(target, roms, pool)
        result.built.append(game.name)
    return result

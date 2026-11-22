"""Write complete, self-contained (non-merged) sets from a pool of verified chips.

Each emulator's sets go to its own library folder. The pool is shared: a chip is one chip
whichever emulator's DAT names it, so FBNeo sets can be made from chips MAME sets hold.
"""

import hashlib
import os
import zipfile
import zlib
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from infiltrator.dat import IS_BIOS, ChipKey, Dat, Game, Rom
from infiltrator.library import emulator_dir
from infiltrator.scan import Chip, fingerprint


@dataclass
class RebuildResult:
    built: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    # A library file with this set's name exists but isn't this set (another
    # core's version, say). It is never overwritten, and the sieve leaves the
    # sources that could have built it alone.
    blocked: list[str] = field(default_factory=list)


class ChipPool:
    """Chips by SHA-1 (how MAME 2003-Plus names a ROM) and by size and CRC (how FBNeo does)."""

    def __init__(self) -> None:
        self._by_key: dict[ChipKey, Chip] = {}

    def add(self, chip: Chip) -> None:
        self._by_key.setdefault(chip.sha1, chip)
        self._by_key.setdefault((chip.size, chip.crc), chip)

    def find(self, rom: Rom) -> Chip | None:
        return self._by_key.get(rom.key)


def _library_zips(library: Path) -> Iterator[Path]:
    for emulator in IS_BIOS:
        yield from sorted(emulator_dir(library, emulator).glob("*.zip"))


def library_chips(library: Path) -> list[Chip]:
    """Every member of every zip in every emulator's folder, so earlier runs' sets count."""
    chips = []
    for path in _library_zips(library):
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
    """By SHA-1 when the DAT gives one; FBNeo's never does, so by size and CRC."""
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


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_set(path: Path, roms: tuple[Rom, ...], pool: ChipPool) -> None:
    """Write, flush, verify, then atomically move into place; durable before return."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for rom in sorted(roms, key=lambda r: r.name):
                zf.writestr(rom.name, pool.find(rom).read())
        with tmp.open("rb") as f:
            os.fsync(f.fileno())
        if not set_is_valid(tmp, roms):
            raise RuntimeError(f"read-back verification failed for {path.name}")
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        tmp.unlink(missing_ok=True)


def bios_ready(game: Game, dat: Dat, library: Path) -> bool:
    """A game that needs a BIOS only counts if that BIOS is in its emulator's folder and valid."""
    bios = dat.bios_of(game)
    if bios is None:
        return True
    return set_is_valid(library / f"{bios.name}.zip", dat.required_roms(bios))


def _buildable(game: Game, dat: Dat, pool: ChipPool, library: Path) -> bool:
    if game.has_disk or not bios_ready(game, dat, library):
        return False
    return all(pool.find(r) for r in dat.required_roms(game))


def _candidates(dat: Dat, wanted: Collection[str] | None) -> list[Game]:
    """The games to try, BIOS sets first: all of them, or the wanted ones and their BIOSes."""
    if wanted is None:
        games = list(dat.games.values())
    else:
        unknown = sorted(set(wanted) - set(dat.games))
        if unknown:
            raise ValueError(f"not in the {dat.emulator} set list: {', '.join(unknown)}")
        games = [dat.games[name] for name in wanted]
        games += [bios for bios in map(dat.bios_of, games) if bios is not None]
    return sorted(set(games), key=lambda g: (not g.is_bios, g.name))


def _optional_present(game: Game, dat: Dat, pool: ChipPool) -> tuple[Rom, ...]:
    """The ROMs this set can run without that the pool holds anyway: worth putting in."""
    return tuple(
        rom
        for rom in game.roms
        if rom.optional
        and rom.status != "nodump"
        and not dat.is_bios_held(game, rom)
        and pool.find(rom)
    )


def _contents(game: Game, dat: Dat, pool: ChipPool) -> tuple[Rom, ...]:
    """What goes in the zip: every required ROM, then any optional one the pool holds."""
    by_name = {rom.name: rom for rom in dat.required_roms(game)}
    for rom in _optional_present(game, dat, pool):
        by_name.setdefault(rom.name, rom)
    return tuple(by_name.values())


def rebuild_emulator(
    pool: ChipPool, dat: Dat, folder: Path, wanted: Collection[str] | None = None
) -> RebuildResult:
    """Build this emulator's sets into its folder: every buildable one, or only the wanted."""
    result = RebuildResult()
    candidates = _candidates(dat, wanted)
    if candidates:
        folder.mkdir(parents=True, exist_ok=True)
    for game in candidates:
        if not _buildable(game, dat, pool, folder):
            continue
        target = folder / f"{game.name}.zip"
        if target.exists() or target.is_symlink():
            if set_is_valid(target, dat.required_roms(game)):
                result.already_present.append(game.name)
            else:
                result.blocked.append(game.name)
            continue
        _write_set(target, _contents(game, dat, pool), pool)
        result.built.append(game.name)
    return result


def rebuild(
    pool: ChipPool,
    dats: Mapping[str, Dat],
    library: Path,
    wanted: Mapping[str, Collection[str] | None],
) -> dict[str, RebuildResult]:
    """Each wanted emulator's sets into `library/<emulator>/`, in the order `wanted` names them."""
    return {
        emulator: rebuild_emulator(pool, dats[emulator], emulator_dir(library, emulator), names)
        for emulator, names in wanted.items()
    }

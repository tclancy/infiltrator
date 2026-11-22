"""Walk the drop folder and find every chip some emulator's DAT knows about."""

import hashlib
import io
import os
import tempfile
import zipfile
import zlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import py7zr

from infiltrator.dat import Dat
from infiltrator.safety import has_executable_extension, has_executable_magic

ARCHIVE_SUFFIXES = {".zip", ".7z", ".rar"}
ARCHIVE_ERRORS = (
    zipfile.BadZipFile,
    py7zr.exceptions.ArchiveError,
    py7zr.exceptions.Bad7zFile,
    py7zr.exceptions.DecompressionBombError,
    OSError,
    EOFError,
    ValueError,
)
Kind = Literal["zip", "7z", "loose", "executable", "unreadable", "rar", "symlink"]


@dataclass(frozen=True)
class Chip:
    sha1: str
    size: int
    crc: str
    read: Callable[[], bytes] = field(compare=False, repr=False)


@dataclass
class Source:
    path: Path
    kind: Kind
    chips: list[Chip] = field(default_factory=list)
    nested_foreign: bool = False  # holds a nested archive with no DAT chips in it
    stamp: tuple[int, int, int] | None = None  # (size, mtime_ns, inode) when scanned


def stamp_of(path: Path) -> tuple[int, int, int]:
    st = os.lstat(path)
    return (st.st_size, st.st_mtime_ns, st.st_ino)


def fingerprint(data: bytes, read: Callable[[], bytes]) -> Chip:
    return Chip(
        sha1=hashlib.sha1(data).hexdigest(),
        size=len(data),
        crc=f"{zlib.crc32(data):08x}",
        read=read,
    )


@dataclass(frozen=True)
class Known:
    """The chips worth keeping: any that at least one emulator's DAT lists."""

    dats: tuple[Dat, ...]
    sizes: frozenset[int]  # only a file of one of these sizes is worth hashing

    @classmethod
    def of(cls, dats: Iterable[Dat]) -> "Known":
        dats = tuple(dats)
        return cls(dats, frozenset().union(*(dat.sizes for dat in dats)))

    def knows(self, chip: Chip) -> bool:
        return any(dat.lookup(chip.sha1, chip.size, chip.crc) for dat in self.dats)


def _zip_chips(known: Known, opener: Callable[[], zipfile.ZipFile]) -> tuple[list[Chip], bool]:
    chips, nested_foreign = [], False
    with opener() as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if Path(info.filename).suffix.lower() in ARCHIVE_SUFFIXES:
                inner, foreign = _nested_chips(known, opener, info.filename)
                chips.extend(inner)
                nested_foreign = nested_foreign or foreign or not inner
                continue
            if info.file_size not in known.sizes:
                continue
            chip = fingerprint(zf.read(info), _zip_reader(opener, info.filename))
            if known.knows(chip):
                chips.append(chip)
    return chips, nested_foreign


def _zip_reader(opener: Callable[[], zipfile.ZipFile], member: str) -> Callable[[], bytes]:
    def read() -> bytes:
        with opener() as zf:
            return zf.read(member)

    return read


def _nested_chips(
    known: Known, outer: Callable[[], zipfile.ZipFile], member: str
) -> tuple[list[Chip], bool]:
    """Chips inside an archive inside a zip, and whether it hides something foreign."""

    def member_bytes() -> bytes:
        with outer() as zf:
            return zf.read(member)

    suffix = Path(member).suffix.lower()
    try:
        if suffix == ".zip":
            return _zip_chips(known, lambda: zipfile.ZipFile(io.BytesIO(member_bytes())))
        if suffix == ".7z":
            return _sevenzip_chips(known, f"{id(outer)}:{member}", member_bytes), False
    except (*ARCHIVE_ERRORS,):
        return [], True
    return [], True  # .rar: can't look inside, so it's foreign


_SEVENZIP_CACHE: dict[str, dict[str, bytes]] = {}


def _sevenzip_members(key: str, read_archive: Callable[[], bytes | Path]) -> dict[str, bytes]:
    """Extract a 7z once per run; py7zr has no random-access member read."""
    if key not in _SEVENZIP_CACHE:
        if len(_SEVENZIP_CACHE) >= 8:
            _SEVENZIP_CACHE.pop(next(iter(_SEVENZIP_CACHE)))
        source = read_archive()
        archive_file = source if isinstance(source, Path) else io.BytesIO(source)
        with tempfile.TemporaryDirectory() as tmp, py7zr.SevenZipFile(archive_file) as archive:
            archive.extractall(path=tmp)
            root = Path(tmp)
            _SEVENZIP_CACHE[key] = {
                str(f.relative_to(root)): f.read_bytes()
                for f in root.rglob("*")
                if f.is_file() and not f.is_symlink()
            }
    return _SEVENZIP_CACHE[key]


def _sevenzip_chips(known: Known, key: str, read_archive: Callable[[], bytes | Path]) -> list[Chip]:
    chips = []
    for name, data in _sevenzip_members(key, read_archive).items():
        if len(data) not in known.sizes:
            continue
        chip = fingerprint(data, _sevenzip_reader(key, read_archive, name))
        if known.knows(chip):
            chips.append(chip)
    return chips


def _sevenzip_reader(
    key: str, read_archive: Callable[[], bytes | Path], member: str
) -> Callable[[], bytes]:
    def read() -> bytes:
        return _sevenzip_members(key, read_archive)[member]

    return read


def _loose_chip(known: Known, path: Path) -> list[Chip]:
    if path.stat().st_size not in known.sizes:
        return []
    chip = fingerprint(path.read_bytes(), path.read_bytes)
    return [chip] if known.knows(chip) else []


DISGUISES = {"", ".zip", ".7z"}  # where executable magic bytes mean malware, not chance


def _scan_file(known: Known, path: Path) -> Source:
    if path.is_symlink():
        return Source(path, "symlink")
    if has_executable_extension(path):
        return Source(path, "executable")
    suffix = path.suffix.lower()
    if suffix in DISGUISES and has_executable_magic(path):
        return Source(path, "executable")
    try:
        if suffix == ".zip":
            chips, foreign = _zip_chips(known, lambda: zipfile.ZipFile(path))
            return Source(path, "zip", chips, foreign)
        if suffix == ".7z":
            return Source(path, "7z", _sevenzip_chips(known, str(path), lambda: path))
    except ARCHIVE_ERRORS:
        return Source(path, "unreadable")
    if suffix == ".rar":
        return Source(path, "rar")
    return Source(path, "loose", _loose_chip(known, path))


def scan_file(known: Known, path: Path) -> Source:
    stamp = None if path.is_symlink() else stamp_of(path)
    source = _scan_file(known, path)
    source.stamp = stamp
    return source


def scan(drop: Path, dats: Mapping[str, Dat]) -> list[Source]:
    """Every file in the drop folder, with the chips in it that any of these DATs lists."""
    _SEVENZIP_CACHE.clear()
    known = Known.of(dats.values())
    sources = []
    for dirpath, _dirnames, filenames in os.walk(drop, followlinks=False):
        for name in sorted(filenames):
            sources.append(scan_file(known, Path(dirpath) / name))
    return sources


def is_judged(source: Source, dats: Mapping[str, Dat]) -> bool:
    """Arcade-looking to any emulator: the only things the sieve may rebuild from and delete.

    An unreadable archive is never judged, even when it is named like a set: a
    stalled, preallocated download looks exactly like that, and deleting it only
    makes the torrent client fetch it again.
    """
    if source.kind == "executable":
        return True
    if source.kind in ("rar", "symlink", "unreadable") or source.nested_foreign:
        return False
    named_like_set = source.path.suffix.lower() in ARCHIVE_SUFFIXES and any(
        source.path.stem in dat.games for dat in dats.values()
    )
    return named_like_set or bool(source.chips)

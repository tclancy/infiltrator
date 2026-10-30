"""Walk the drop folder and find every chip the DAT knows about."""

import functools
import hashlib
import io
import os
import tempfile
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import py7zr

from infiltrator.dat import Dat
from infiltrator.safety import is_executable

ARCHIVE_SUFFIXES = {".zip", ".7z", ".rar"}
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


def fingerprint(data: bytes, read: Callable[[], bytes]) -> Chip:
    return Chip(
        sha1=hashlib.sha1(data).hexdigest(),
        size=len(data),
        crc=f"{zlib.crc32(data):08x}",
        read=read,
    )


def _known(dat: Dat, chip: Chip) -> bool:
    return bool(dat.lookup(chip.sha1, chip.size, chip.crc))


def _zip_chips(dat: Dat, opener: Callable[[], zipfile.ZipFile]) -> tuple[list[Chip], bool]:
    chips, nested_foreign = [], False
    with opener() as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if info.filename.lower().endswith(".zip"):
                inner = _nested_zip_chips(dat, opener, info.filename)
                if inner:
                    chips.extend(inner)
                else:
                    nested_foreign = True
                continue
            if info.file_size not in dat.sizes:
                continue
            chip = fingerprint(zf.read(info), _zip_reader(opener, info.filename))
            if _known(dat, chip):
                chips.append(chip)
    return chips, nested_foreign


def _zip_reader(opener: Callable[[], zipfile.ZipFile], member: str) -> Callable[[], bytes]:
    def read() -> bytes:
        with opener() as zf:
            return zf.read(member)

    return read


def _nested_zip_chips(dat: Dat, outer: Callable[[], zipfile.ZipFile], member: str) -> list[Chip]:
    def inner_opener() -> zipfile.ZipFile:
        with outer() as zf:
            return zipfile.ZipFile(io.BytesIO(zf.read(member)))

    try:
        chips, _ = _zip_chips(dat, inner_opener)
    except zipfile.BadZipFile:
        return []
    return chips


@functools.lru_cache(maxsize=1)
def _sevenzip_members(path: Path) -> dict[str, bytes]:
    with tempfile.TemporaryDirectory() as tmp, py7zr.SevenZipFile(path) as archive:
        archive.extractall(path=tmp)
        root = Path(tmp)
        return {
            str(f.relative_to(root)): f.read_bytes()
            for f in root.rglob("*")
            if f.is_file() and not f.is_symlink()
        }


def _sevenzip_chips(dat: Dat, path: Path) -> list[Chip]:
    chips = []
    for name, data in _sevenzip_members(path).items():
        if len(data) not in dat.sizes:
            continue
        chip = fingerprint(data, _sevenzip_reader(path, name))
        if _known(dat, chip):
            chips.append(chip)
    return chips


def _sevenzip_reader(path: Path, member: str) -> Callable[[], bytes]:
    def read() -> bytes:
        return _sevenzip_members(path)[member]

    return read


def _loose_chip(dat: Dat, path: Path) -> list[Chip]:
    if path.stat().st_size not in dat.sizes:
        return []
    chip = fingerprint(path.read_bytes(), path.read_bytes)
    return [chip] if _known(dat, chip) else []


def scan_file(dat: Dat, path: Path) -> Source:
    if path.is_symlink():
        return Source(path, "symlink")
    if is_executable(path):
        return Source(path, "executable")
    suffix = path.suffix.lower()
    try:
        if suffix == ".zip":
            chips, foreign = _zip_chips(dat, lambda: zipfile.ZipFile(path))
            return Source(path, "zip", chips, foreign)
        if suffix == ".7z":
            return Source(path, "7z", _sevenzip_chips(dat, path))
    except (
        zipfile.BadZipFile,
        py7zr.exceptions.ArchiveError,
        py7zr.exceptions.Bad7zFile,
        py7zr.exceptions.DecompressionBombError,
        OSError,
        EOFError,
        ValueError,
    ):
        return Source(path, "unreadable")
    if suffix == ".rar":
        return Source(path, "rar")
    return Source(path, "loose", _loose_chip(dat, path))


def scan(drop: Path, dat: Dat) -> list[Source]:
    sources = []
    for dirpath, _dirnames, filenames in os.walk(drop, followlinks=False):
        for name in sorted(filenames):
            sources.append(scan_file(dat, Path(dirpath) / name))
    return sources


def is_judged(source: Source, dat: Dat) -> bool:
    """Arcade-looking: the only things the sieve may rebuild from and delete."""
    if source.kind == "executable":
        return True
    if source.kind in ("rar", "symlink") or source.nested_foreign:
        return False
    named_like_set = (
        source.path.suffix.lower() in ARCHIVE_SUFFIXES and source.path.stem in dat.games
    )
    if source.kind == "unreadable":
        return named_like_set
    return named_like_set or bool(source.chips)

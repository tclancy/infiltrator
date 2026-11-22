"""Where the library keeps its sets: one folder per emulator, `library/<emulator>/<set>.zip`.

Set names clash between emulators (MAME 2003-Plus `hbarrel` is the US Heavy Barrel, FBNeo's
is the World one), so nothing may live at a bare name in the library's top level.
"""

import os
from pathlib import Path

from infiltrator.dat import DEFAULT_EMULATOR


class LibraryLayoutError(Exception):
    """The library holds the same set in both the old flat layout and the new one."""


def emulator_dir(library: Path, emulator: str) -> Path:
    return library / emulator


def set_path(library: Path, emulator: str, set_name: str) -> Path:
    return emulator_dir(library, emulator) / f"{set_name}.zip"


def _flat_sets(library: Path) -> list[Path]:
    return sorted(p for p in library.glob("*.zip") if p.is_file() or p.is_symlink())


def _same_file(a: Path, b: Path) -> bool:
    mine, theirs = os.lstat(a), os.lstat(b)
    return (mine.st_dev, mine.st_ino) == (theirs.st_dev, theirs.st_ino)


def _collisions(flat: list[Path], target: Path) -> list[str]:
    """Names in both places that are not one file under two names (a move cut short)."""
    clashes = []
    for path in flat:
        moved = target / path.name
        if (moved.exists() or moved.is_symlink()) and not _same_file(path, moved):
            clashes.append(path.name)
    return clashes


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _move(path: Path, target: Path) -> None:
    """Give the file its new name, then drop the old one: the inode never changes.

    A link cannot overwrite, so a file that appears at the new name meanwhile stops the move
    instead of being lost. A crash between the two steps leaves one file under both names,
    which the next run finishes.
    """
    moved = target / path.name
    try:
        os.link(path, moved, follow_symlinks=False)
    except FileExistsError:
        if not _same_file(path, moved):
            raise LibraryLayoutError(f"{path.name} is in both {path.parent} and {target}") from None
    path.unlink()


def move_flat_library(library: Path) -> list[str]:
    """Move a pre-emulator library's `*.zip` into its MAME 2003-Plus folder; returns names moved.

    Idempotent. Refuses, moving nothing, when a name is in both places with different files.
    """
    flat = _flat_sets(library)
    if not flat:
        return []
    target = emulator_dir(library, DEFAULT_EMULATOR)
    clashes = _collisions(flat, target)
    if clashes:
        raise LibraryLayoutError(
            f"in both {library} and {target}, so neither was moved: {', '.join(clashes)}. "
            "Keep the right one and delete the other."
        )
    target.mkdir(parents=True, exist_ok=True)
    for path in flat:
        _move(path, target)
    _fsync_dir(target)
    _fsync_dir(library)
    return [p.name for p in flat]

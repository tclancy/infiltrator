"""Make RomM's folders show the shelf: hardlinks into the library, nothing else.

A file in a published folder is ours when it is the library file of the same
name (same inode). Ours and unwanted: unlinked. Anything that isn't ours stops
the publish before a single change, because nothing here deletes what it
didn't put there.
"""

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path


class PublishError(Exception):
    """A published folder holds something Infiltrator didn't put there."""


@dataclass
class PublishResult:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed)


@dataclass
class _Plan:
    folder: Path
    link: list[str]
    unlink: list[str]


@contextmanager
def locked(lock_file: Path) -> Iterator[None]:
    """One publisher at a time: the sieve service and a person at a shell share folders."""
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _is_ours(entry: Path, library: Path) -> bool:
    source = library / entry.name
    if entry.is_symlink() or not entry.is_file() or not source.is_file():
        return False
    mine, theirs = entry.stat(), source.stat()
    return (mine.st_dev, mine.st_ino) == (theirs.st_dev, theirs.st_ino)


def _ours_present(folder: Path, library: Path) -> list[str]:
    """Set names we placed in folder; raises on anything we didn't."""
    if not folder.is_dir() or folder.is_symlink():
        raise PublishError(f"not a folder: {folder}")
    present = []
    for entry in sorted(folder.iterdir()):
        if entry.name.startswith("."):
            continue
        if not _is_ours(entry, library):
            raise PublishError(f"not put there by infiltrator: {entry}")
        present.append(entry.stem)
    return present


def check_folders(library: Path, *folders: Path) -> None:
    """Raise if publishing into these folders would refuse; changes nothing."""
    for folder in folders:
        _ours_present(folder, library)


def _plan(folder: Path, library: Path, wanted: list[str]) -> _Plan:
    missing = [name for name in wanted if not (library / f"{name}.zip").is_file()]
    if missing:
        raise PublishError(f"not in the library: {', '.join(missing)}")
    present = _ours_present(folder, library)
    return _Plan(
        folder,
        link=[name for name in wanted if name not in present],
        unlink=[name for name in present if name not in wanted],
    )


def _link(plan: _Plan, library: Path, result: PublishResult) -> None:
    for name in plan.link:
        target = plan.folder / f"{name}.zip"
        try:
            os.link(library / f"{name}.zip", target)
        except FileExistsError:
            if not _is_ours(target, library):
                raise PublishError(f"not put there by infiltrator: {target}") from None
            continue
        result.added.append(name)


def _unlink(plan: _Plan, library: Path, result: PublishResult) -> None:
    for name in plan.unlink:
        target = plan.folder / f"{name}.zip"
        if not _is_ours(target, library):  # changed since the plan: not ours to delete
            continue
        target.unlink()
        result.removed.append(name)


def publish(
    library: Path, shelf_dir: Path, bios_dir: Path, sets: list[str], bios: list[str]
) -> PublishResult:
    """Check both folders first, then change them; returns set names added and removed.

    Order matters if something fails part-way: BIOS sets arrive before the games
    that need them, and new links go in before old ones come out.
    """
    shelf = _plan(shelf_dir, library, sorted(sets))
    bios_plan = _plan(bios_dir, library, sorted(bios))
    result = PublishResult()
    _link(bios_plan, library, result)
    _link(shelf, library, result)
    _unlink(shelf, library, result)
    _unlink(bios_plan, library, result)
    return result

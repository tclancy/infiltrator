"""Make RomM's folders show the shelf: hardlinks into the library, nothing else.

A file in a published folder is ours when it is the library file of the same
name (same inode). Ours and unwanted: unlinked. Anything that isn't ours stops
the publish before a single change, because nothing here deletes what it
didn't put there.
"""

import os
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


def _is_ours(entry: Path, library: Path) -> bool:
    source = library / entry.name
    if entry.is_symlink() or not entry.is_file() or not source.is_file():
        return False
    mine, theirs = entry.stat(), source.stat()
    return (mine.st_dev, mine.st_ino) == (theirs.st_dev, theirs.st_ino)


def _plan(folder: Path, library: Path, wanted: list[str]) -> _Plan:
    if not folder.is_dir() or folder.is_symlink():
        raise PublishError(f"not a folder: {folder}")
    missing = [name for name in wanted if not (library / f"{name}.zip").is_file()]
    if missing:
        raise PublishError(f"not in the library: {', '.join(missing)}")
    present = []
    for entry in sorted(folder.iterdir()):
        if entry.name.startswith("."):
            continue
        if not _is_ours(entry, library):
            raise PublishError(f"not put there by infiltrator: {entry}")
        present.append(entry.stem)
    return _Plan(
        folder,
        link=[name for name in wanted if name not in present],
        unlink=[name for name in present if name not in wanted],
    )


def _apply(plan: _Plan, library: Path, result: PublishResult) -> None:
    for name in plan.unlink:
        (plan.folder / f"{name}.zip").unlink()
        result.removed.append(name)
    for name in plan.link:
        os.link(library / f"{name}.zip", plan.folder / f"{name}.zip")
        result.added.append(name)


def publish(
    library: Path, shelf_dir: Path, bios_dir: Path, sets: list[str], bios: list[str]
) -> PublishResult:
    """Check both folders first, then change them; returns set names added and removed."""
    plans = [_plan(shelf_dir, library, sorted(sets)), _plan(bios_dir, library, sorted(bios))]
    result = PublishResult()
    for plan in plans:
        _apply(plan, library, result)
    return result

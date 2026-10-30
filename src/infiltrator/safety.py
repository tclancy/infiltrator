"""Guards that keep the sieve's deletions inside the drop folder and off live torrents."""

import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path

PARTIAL_SUFFIXES = (".!qb", ".part", ".!ut", ".crdownload", ".aria2", ".tmp")

# Same list homelab blocks at the torrent client (#565).
EXECUTABLE_EXTENSIONS = frozenset(
    [
        "exe",
        "scr",
        "lnk",
        "bat",
        "cmd",
        "pif",
        "msi",
        "msix",
        "vbs",
        "vbe",
        "jse",
        "wsf",
        "wsh",
        "hta",
        "ps1",
        "reg",
        "jar",
        "apk",
    ]
)
EXECUTABLE_MAGIC = (b"MZ", b"\x7fELF", b"#!")


class DropFolderError(Exception):
    """The drop folder is the wrong place, or it is still being written to."""


def _regular_files(root: Path) -> Iterator[Path]:
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            path = Path(dirpath) / name
            if not path.is_symlink():
                yield path


def _snapshot(root: Path) -> dict[Path, tuple[int, int]]:
    snap = {}
    for path in _regular_files(root):
        st = path.stat()
        snap[path] = (st.st_size, st.st_mtime_ns)
    return snap


def active_download_reasons(
    drop: Path,
    settle_seconds: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
) -> list[str]:
    """Why the drop folder looks like it is still downloading; empty means quiet."""
    reasons = [
        f"in-progress file: {p.name}"
        for p in _regular_files(drop)
        if p.name.lower().endswith(PARTIAL_SUFFIXES)
    ]
    before = _snapshot(drop)
    sleep(settle_seconds)
    after = _snapshot(drop)
    reasons += [f"still changing: {p.name}" for p in after if before.get(p) != after[p]]
    reasons += [f"disappeared: {p.name}" for p in before if p not in after]
    return reasons


def has_executable_extension(path: Path) -> bool:
    return path.suffix.lower().lstrip(".") in EXECUTABLE_EXTENSIONS


def has_executable_magic(path: Path) -> bool:
    with path.open("rb") as f:
        head = f.read(4)
    return head.startswith(EXECUTABLE_MAGIC)


def inside(drop: Path, path: Path) -> bool:
    """True only for a real (non-symlink) path that resolves under the drop folder."""
    if path.is_symlink():
        return False
    return path.resolve().is_relative_to(drop.resolve())


def check_drop(drop: Path, library: Path, db_path: Path | None = None) -> None:
    if drop.is_symlink():
        raise DropFolderError(f"drop folder is a symlink: {drop}")
    if not drop.is_dir():
        raise DropFolderError(f"drop folder missing: {drop}")
    resolved = drop.resolve()
    if resolved in (Path("/").resolve(), Path.home().resolve()):
        raise DropFolderError(f"refusing to treat {resolved} as a drop folder")
    lib = library.resolve()
    if resolved == lib or lib.is_relative_to(resolved) or resolved.is_relative_to(lib):
        raise DropFolderError("drop folder and library overlap")
    if db_path is not None and db_path.resolve().is_relative_to(resolved):
        raise DropFolderError("catalogue database is inside the drop folder")

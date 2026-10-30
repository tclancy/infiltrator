"""Guard, scan, rebuild, and only then delete: Old Testament rules."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from infiltrator.config import Settings
from infiltrator.dat import Dat
from infiltrator.rebuild import ChipPool, library_chips, rebuild
from infiltrator.safety import (
    DropFolderBusy,
    active_download_reasons,
    check_drop,
    inside,
)
from infiltrator.scan import Source, is_judged, scan, stamp_of


@dataclass
class SieveReport:
    new_games: list[str] = field(default_factory=list)
    new_bios: list[str] = field(default_factory=list)
    deleted: list[Path] = field(default_factory=list)
    left_alone: list[Path] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)


def _pool(judged: list[Source], library: Path) -> ChipPool:
    pool = ChipPool()
    for chip in library_chips(library) if library.exists() else []:
        pool.add(chip)
    for source in judged:
        for chip in source.chips:
            pool.add(chip)
    return pool


def _unchanged(source: Source) -> bool:
    try:
        return stamp_of(source.path) == source.stamp
    except FileNotFoundError:
        return False


def _delete(drop: Path, sources: list[Source]) -> tuple[list[Path], list[Path]]:
    """Unlink judged sources still exactly as scanned; return (deleted, skipped)."""
    deleted, skipped = [], []
    for source in sources:
        if inside(drop, source.path) and _unchanged(source):
            source.path.unlink()
            deleted.append(source.path)
        else:
            skipped.append(source.path)
    _prune_emptied_dirs(drop, deleted)
    return deleted, skipped


def _feeds_blocked(source: Source, dat: Dat, blocked: set[str]) -> bool:
    return any(
        game.name in blocked
        for chip in source.chips
        for game, _rom in dat.lookup(chip.sha1, chip.size, chip.crc)
    )


def _prune_emptied_dirs(drop: Path, deleted: list[Path]) -> None:
    """Remove folders the sieve emptied; folders that were already empty stay."""
    for parent in sorted({p.parent for p in deleted}, key=lambda p: len(p.parts), reverse=True):
        current = parent
        while current != drop and inside(drop, current) and not any(current.iterdir()):
            current.rmdir()
            current = current.parent


def run_sieve(
    settings: Settings,
    dat: Dat,
    *,
    settle_seconds: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
    on_library_changed: Callable[[], None] | None = None,
) -> SieveReport:
    drop, library = settings.drop_dir, settings.library_dir
    check_drop(drop, library, settings.db_path)
    reasons = active_download_reasons(drop, settle_seconds, sleep)
    if reasons:
        raise DropFolderBusy("; ".join(reasons))

    try:
        sources = scan(drop, dat)
        judged = [s for s in sources if is_judged(s, dat)]
        result = rebuild(_pool(judged, library), dat, library)
        blocked = set(result.blocked)
        doomed = [s for s in judged if not _feeds_blocked(s, dat, blocked)]
        doomed_ids = {id(s) for s in doomed}
        report = SieveReport(
            new_games=[n for n in result.built if not dat.games[n].is_bios],
            new_bios=[n for n in result.built if dat.games[n].is_bios],
            blocked=result.blocked,
            left_alone=[s.path for s in sources if id(s) not in doomed_ids],
        )
        report.deleted, changed = _delete(drop, doomed)
        report.left_alone += changed
        return report
    finally:
        if on_library_changed is not None:
            on_library_changed()

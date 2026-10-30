"""Guard, scan, rebuild, and only then delete: Old Testament rules."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from infiltrator.config import Settings
from infiltrator.dat import Dat
from infiltrator.rebuild import ChipPool, library_chips, rebuild
from infiltrator.safety import (
    DropFolderError,
    active_download_reasons,
    check_drop,
    inside,
)
from infiltrator.scan import Source, is_judged, scan


@dataclass
class SieveReport:
    new_games: list[str] = field(default_factory=list)
    new_bios: list[str] = field(default_factory=list)
    deleted: list[Path] = field(default_factory=list)
    left_alone: list[Path] = field(default_factory=list)


def _pool(judged: list[Source], library: Path) -> ChipPool:
    pool = ChipPool()
    for chip in library_chips(library) if library.exists() else []:
        pool.add(chip)
    for source in judged:
        for chip in source.chips:
            pool.add(chip)
    return pool


def _delete(drop: Path, sources: list[Source]) -> list[Path]:
    deleted = []
    for source in sources:
        if inside(drop, source.path):
            source.path.unlink()
            deleted.append(source.path)
    _prune_emptied_dirs(drop, deleted)
    return deleted


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
        raise DropFolderError("; ".join(reasons))

    sources = scan(drop, dat)
    judged = [s for s in sources if is_judged(s, dat)]
    judged_ids = {id(s) for s in judged}
    result = rebuild(_pool(judged, library), dat, library)

    report = SieveReport(
        new_games=[n for n in result.built if not dat.games[n].is_bios],
        new_bios=[n for n in result.built if dat.games[n].is_bios],
        left_alone=[s.path for s in sources if id(s) not in judged_ids],
    )
    report.deleted = _delete(drop, judged)
    if on_library_changed is not None:
        on_library_changed()
    return report

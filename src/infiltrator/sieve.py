"""Guard, scan, rebuild, and only then delete: Old Testament rules."""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from infiltrator.config import Settings
from infiltrator.dat import Dat
from infiltrator.dats import Wanted, default_wanted
from infiltrator.rebuild import ChipPool, RebuildResult, library_chips, rebuild
from infiltrator.safety import (
    DropFolderBusy,
    active_download_reasons,
    check_drop,
    inside,
)
from infiltrator.scan import Chip, Source, is_judged, scan, stamp_of

Blocked = Mapping[str, set[str]]  # emulator → set names a stranger's file stands in for


@dataclass
class SieveReport:
    new_games: dict[str, list[str]] = field(default_factory=dict)  # by emulator
    new_bios: dict[str, list[str]] = field(default_factory=dict)  # by emulator
    deleted: list[Path] = field(default_factory=list)
    left_alone: list[Path] = field(default_factory=list)
    blocked: dict[str, list[str]] = field(default_factory=dict)  # by emulator
    # Sources kept because they hold a chip no library zip has that only an emulator not
    # built in full knows (FBNeo, today): the library holds sets, so until a set that uses
    # the chip is wanted, the drop folder is the only place it lives. Path → those emulators.
    held: dict[Path, list[str]] = field(default_factory=dict)


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


def _feeds_blocked(source: Source, dats: Mapping[str, Dat], blocked: Blocked) -> bool:
    """True if any chip here belongs to a set, in any emulator, that a stranger's file blocks."""
    return any(
        game.name in names
        for emulator, names in blocked.items()
        for chip in source.chips
        for game, _rom in dats[emulator].lookup(chip.sha1, chip.size, chip.crc)
    )


def _knowers(chip: Chip, dats: Mapping[str, Dat]) -> list[str]:
    return [e for e, dat in dats.items() if dat.lookup(chip.sha1, chip.size, chip.crc)]


def _unbuilt_only(chip: Chip, dats: Mapping[str, Dat], wanted: Wanted) -> list[str]:
    """The emulators that know this chip, if none of them has every set built; else []."""
    knowers = _knowers(chip, dats)
    if any(wanted.get(e, frozenset()) is None for e in knowers):
        return []
    return knowers


def _stranded(
    source: Source, dats: Mapping[str, Dat], wanted: Wanted, in_library: set[str]
) -> list[str]:
    """The emulators that alone know a chip in this source that no library zip holds."""
    return sorted(
        {
            emulator
            for chip in source.chips
            if chip.sha1 not in in_library
            for emulator in _unbuilt_only(chip, dats, wanted)
        }
    )


def _held(
    judged: list[Source], dats: Mapping[str, Dat], wanted: Wanted, library: Path
) -> dict[Path, list[str]]:
    """Sources to keep for a chip only a partly-built emulator knows and no library zip holds.

    Run after the rebuild, so a chip that just went into a wanted set no longer holds anything.
    """
    suspects = [s for s in judged if any(_unbuilt_only(c, dats, wanted) for c in s.chips)]
    if not suspects:
        return {}
    in_library = {chip.sha1 for chip in library_chips(library)}
    held = {s.path: _stranded(s, dats, wanted, in_library) for s in suspects}
    return {path: emulators for path, emulators in held.items() if emulators}


def _prune_emptied_dirs(drop: Path, deleted: list[Path]) -> None:
    """Remove folders the sieve emptied; folders that were already empty stay."""
    for parent in sorted({p.parent for p in deleted}, key=lambda p: len(p.parts), reverse=True):
        current = parent
        while current != drop and inside(drop, current) and not any(current.iterdir()):
            current.rmdir()
            current = current.parent


def _report(results: Mapping[str, RebuildResult], dats: Mapping[str, Dat]) -> SieveReport:
    def built(emulator: str, bios: bool) -> list[str]:
        games = dats[emulator].games
        return [n for n in results[emulator].built if games[n].is_bios == bios]

    return SieveReport(
        new_games={e: built(e, bios=False) for e in results},
        new_bios={e: built(e, bios=True) for e in results},
        blocked={e: r.blocked for e, r in results.items()},
    )


def _check_wanted(dats: Mapping[str, Dat], wanted: Wanted) -> None:
    unknown = sorted(set(wanted) - set(dats))
    if unknown:
        raise ValueError(f"no set list loaded for: {', '.join(unknown)}")


def run_sieve(
    settings: Settings,
    dats: Mapping[str, Dat],
    *,
    wanted: Wanted | None = None,
    settle_seconds: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
    on_library_changed: Callable[[], None] | None = None,
) -> SieveReport:
    """Rebuild what the drop folder holds into the library, then delete what is safe to.

    `wanted` says which sets to build per emulator (see `dats.Wanted`); by default every
    MAME 2003-Plus set and nothing for any other emulator.
    """
    wanted = default_wanted(dats) if wanted is None else wanted
    _check_wanted(dats, wanted)
    drop, library = settings.drop_dir, settings.library_dir
    check_drop(drop, library, settings.db_path)
    reasons = active_download_reasons(drop, settle_seconds, sleep)
    if reasons:
        raise DropFolderBusy("; ".join(reasons))

    try:
        sources = scan(drop, dats)
        judged = [s for s in sources if is_judged(s, dats)]
        results = rebuild(_pool(judged, library), dats, library, wanted)
        blocked = {e: set(r.blocked) for e, r in results.items()}
        held = _held(judged, dats, wanted, library)
        doomed = [s for s in judged if not _feeds_blocked(s, dats, blocked) and s.path not in held]
        doomed_ids = {id(s) for s in doomed}
        report = _report(results, dats)
        report.held = held
        report.left_alone = [s.path for s in sources if id(s) not in doomed_ids]
        report.deleted, changed = _delete(drop, doomed)
        report.left_alone += changed
        return report
    finally:
        if on_library_changed is not None:
            on_library_changed()

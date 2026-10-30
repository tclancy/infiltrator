"""The gate: Tom's eight verified arcade games through the real sieve. Local only.

Copies the eight zips from homelab into a temp drop folder (never touching the
real RomM library), disguises 1942b as 1942.zip, adds an executable and two
files that must survive, runs the sieve against the real MAME 2003-Plus DAT,
and checks the result. Prints PASS or FAIL.

    uv run python scripts/gate.py [--dat PATH]
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from infiltrator.catalogue import connect
from infiltrator.config import Settings
from infiltrator.dat import load_dat
from infiltrator.sieve import run_sieve

EIGHT = ["hbarrelw", "congo", "zaxxon", "btimem", "popeye", "tapper", "gauntlet", "1942b"]
REMOTE = "tom@192.168.68.67"
REMOTE_DIR = "/mnt/samsungusb/games/romm/library/roms/arcade"
SSH = ["-i", str(Path("~/.ssh/id_claude").expanduser()), "-o", "IdentitiesOnly=yes"]
DEFAULT_DAT = Path("~/Documents/work/mame2003-plus-libretro/metadata/mame2003-plus.xml")
SURVIVORS = {"notes.mp3", "mario.nes"}
# hbarrelw.zip on homelab is a merged zip: it also holds every chip of its
# parent hbarrel (US), so the sieve correctly builds both. Found by the first
# gate run, 2026-10-30. The shelf shows one per family.
EXPECTED_LIBRARY = {*EIGHT, "hbarrel"}


def fetch(drop: Path) -> None:
    sources = [f"{REMOTE}:{REMOTE_DIR}/{name}.zip" for name in EIGHT]
    subprocess.run(["scp", "-q", *SSH, *sources, str(drop)], check=True)
    (drop / "1942b.zip").rename(drop / "1942.zip")
    (drop / "setup.exe").write_bytes(b"MZ\x90\x00")
    (drop / "notes.mp3").write_bytes(b"ID3 not a game")
    (drop / "mario.nes").write_bytes(b"NES\x1a not arcade")


def check(settings: Settings, report, games_in_catalogue: int | None) -> list[str]:
    problems = []
    built = {p.stem for p in settings.library_dir.glob("*.zip")}
    if built != EXPECTED_LIBRARY:
        missing, extra = EXPECTED_LIBRARY - built, built - EXPECTED_LIBRARY
        problems.append(f"library: missing {missing}, extra {extra}")
    left = {p.name for p in settings.drop_dir.rglob("*") if p.is_file()}
    if left != SURVIVORS:
        problems.append(f"drop folder holds {sorted(left)}, expected {sorted(SURVIVORS)}")
    if games_in_catalogue is not None and games_in_catalogue != len(EXPECTED_LIBRARY):
        problems.append(f"catalogue has {games_in_catalogue} games")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dat", type=Path, default=DEFAULT_DAT)
    parser.add_argument("--keep", action="store_true", help="leave the temp folder for a look")
    args = parser.parse_args()

    root = Path(tempfile.mkdtemp(prefix="infiltrator-gate-"))
    settings = Settings(
        drop_dir=root / "drop",
        library_dir=root / "library",
        db_path=root / "catalogue.db",
        dat_path=args.dat.expanduser(),
        metadata_dir=root / "metadata",
    )
    settings.drop_dir.mkdir()
    try:
        fetch(settings.drop_dir)
        dat = load_dat(settings.dat_path)
        catalogued = None
        try:
            from infiltrator.catalogue.games import sync_games  # Task 6
        except ImportError:
            sync_games = None
        conn = connect(settings.db_path)
        report = run_sieve(settings, dat, settle_seconds=1)
        if sync_games is not None:
            catalogued = sync_games(conn, settings.library_dir, dat, {})
        problems = check(settings, report, catalogued)
        print(f"built: {sorted(report.new_games)}")
        print(f"deleted: {sorted(p.name for p in report.deleted)}")
        for problem in problems:
            print(f"  - {problem}")
        print("FAIL" if problems else "PASS")
        return 1 if problems else 0
    finally:
        if args.keep:
            print(f"kept: {root}")
        else:
            shutil.rmtree(root)


if __name__ == "__main__":
    sys.exit(main())

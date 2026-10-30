"""Persona metadata from the progettoSNAPS and nplayers ini files the user supplies.

These files are keyed by modern MAME names; the DAT is MAME 0.78-era. A set is
looked up under its modern name, found by replaying renameSET's per-version
renames from 0.79 onward. Each version's renames apply simultaneously, because
MAME swaps names (tappera <-> tapperb) and reuses them; chaining renames across
all versions at once scrambles exactly those sets.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from infiltrator.dat import Dat

MATURE = "* Mature *"
TIER_SECTION = re.compile(r"^(\d+) to \d+")
UNKNOWN_PLAYERS = {"???", "Device", "Non-arcade"}


@dataclass(frozen=True)
class SetMeta:
    language: str | None = None
    mature: bool | None = None
    genre: str | None = None
    players: str | None = None
    quality_tier: int | None = None


def read_sections(path: Path) -> dict[str, list[str]]:
    """Section name -> raw lines. Hand-parsed: these files are not configparser-safe."""
    sections: dict[str, list[str]] = defaultdict(list)
    current = None
    if not path.exists():
        return sections
    for raw in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
        elif current is not None:
            sections[current].append(line)
    return sections


def _pairs(lines: list[str]) -> dict[str, str]:
    return dict(line.split("=", 1) for line in lines if "=" in line)


def _version(section: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", section))


DAT_VERSION = (0, 78)


def parse_renames(path: Path, names: set[str]) -> dict[str, str]:
    """0.78 name -> modern name, for each of `names` that was ever renamed."""
    sections = read_sections(path)
    versions = sorted((v for v in sections if _version(v) > DAT_VERSION), key=_version)
    current = {name: name for name in names}
    for version in versions:
        step = {}
        for value in _pairs(sections[version]).values():
            if ">" in value:
                old, new = (part.strip() for part in value.split(">", 1))
                step[old] = new
        current = {orig: step.get(now, now) for orig, now in current.items()}
    return {orig: now for orig, now in current.items() if orig != now}


def _catver(path: Path) -> dict[str, tuple[str, bool]]:
    out = {}
    for name, value in _pairs(read_sections(path).get("Category", [])).items():
        mature = value.endswith(MATURE)
        out[name] = (value.removesuffix(MATURE).strip(), mature)
    return out


def _languages(path: Path) -> dict[str, str]:
    out = {}
    for section, names in read_sections(path).items():
        if section in ("FOLDER_SETTINGS", "ROOT_FOLDER"):
            continue
        for name in names:
            out.setdefault(name, section)
    return out


def _bestgames(path: Path) -> dict[str, int]:
    out = {}
    for section, names in read_sections(path).items():
        match = TIER_SECTION.match(section)
        if match:
            for name in names:
                out[name] = int(match.group(1)) // 10
    return out


def _nplayers(path: Path) -> dict[str, str]:
    values = _pairs(read_sections(path).get("NPlayers", []))
    return {k: v for k, v in values.items() if v not in UNKNOWN_PLAYERS}


def load_metadata(metadata_dir: Path, dat: Dat) -> dict[str, SetMeta]:
    renames = parse_renames(metadata_dir / "renameSET.ini", set(dat.games))
    catver = _catver(metadata_dir / "catver.ini")
    languages = _languages(metadata_dir / "languages.ini")
    tiers = _bestgames(metadata_dir / "bestgames.ini")
    players = _nplayers(metadata_dir / "nplayers.ini")

    def entry(key: str) -> SetMeta:
        genre, mature = catver.get(key, (None, None))
        return SetMeta(languages.get(key), mature, genre, players.get(key), tiers.get(key))

    def entries(name: str | None) -> list[SetMeta]:
        """The modern name first, then the 0.78 one: MAME reshuffles sets (PuckMan)."""
        if name is None:
            return []
        return [entry(n) for n in dict.fromkeys([renames.get(name, name), name])]

    def first(found: list[SetMeta], field: str):
        return next((getattr(e, field) for e in found if getattr(e, field) is not None), None)

    result = {}
    for game in dat.games.values():
        own = entries(game.name)
        family = own + entries(game.cloneof)
        result[game.name] = SetMeta(
            language=first(own, "language"),  # never inherited: clones differ by region
            mature=first(family, "mature"),
            genre=first(family, "genre"),
            players=first(family, "players"),
            quality_tier=first(family, "quality_tier"),
        )
    return result

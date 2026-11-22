"""An emulator's DAT: which games exist and exactly which chips each one needs.

Two dialects are read: MAME 2003-Plus's and FBNeo's. They differ in how a set says it is a BIOS,
and FBNeo's cannot say a ROM is optional, so that list is passed in (see `load_optional_roms`).
"""

import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

ChipKey = str | tuple[int, str]


@dataclass(frozen=True)
class Rom:
    name: str
    size: int
    crc: str | None
    sha1: str | None
    merge: str | None
    bios: str | None
    status: str
    optional: bool = False

    @property
    def key(self) -> ChipKey:
        """SHA-1 when the DAT has one; otherwise (size, crc). 13 games lack SHA-1s."""
        return self.sha1 if self.sha1 else (self.size, self.crc or "")


@dataclass(frozen=True)
class Game:
    name: str
    description: str
    year: str | None
    manufacturer: str | None
    cloneof: str | None
    romof: str | None
    is_bios: bool
    roms: tuple[Rom, ...]
    has_disk: bool
    players: int | None
    control: str | None
    buttons: int
    default_bios: str | None


OptionalRoms = Mapping[str, frozenset[str]]
"""Set name → CRCs (lowercase, 8 hex digits) of the ROMs that set can load without."""


def _mame2003_plus_is_bios(el: ET.Element) -> bool:
    return el.get("runnable") == "no"


def _fbneo_is_bios(el: ET.Element) -> bool:
    return el.get("isbios") == "yes"


IS_BIOS: dict[str, Callable[[ET.Element], bool]] = {
    "mame2003-plus": _mame2003_plus_is_bios,
    "fbneo": _fbneo_is_bios,
}
"""How each emulator's DAT marks a BIOS set. Its keys are the emulators Infiltrator knows."""


def _known(emulator: str) -> str:
    if emulator not in IS_BIOS:
        raise ValueError(f"Unknown emulator: {emulator!r}. Known emulators: {', '.join(IS_BIOS)}")
    return emulator


def _rom(el: ET.Element, optional: bool = False) -> Rom:
    def low(attr: str) -> str | None:
        value = el.get(attr)
        return value.lower() if value else None

    return Rom(
        name=el.get("name"),
        size=int(el.get("size")),
        crc=low("crc"),
        sha1=low("sha1"),
        merge=el.get("merge"),
        bios=el.get("bios"),
        status=el.get("status", "good"),
        optional=optional,
    )


def _is_optional(el: ET.Element, optional: frozenset[str]) -> bool:
    return (el.get("crc") or "").lower() in optional


def _game(
    el: ET.Element,
    is_bios: Callable[[ET.Element], bool] = _mame2003_plus_is_bios,
    optional_roms: OptionalRoms | None = None,
) -> Game:
    inp = el.find("input")
    default_bios = next(
        (b.get("name") for b in el.findall("biosset") if b.get("default") == "yes"), None
    )
    players = inp.get("players") if inp is not None else None
    name = el.get("name")
    optional = (optional_roms or {}).get(name, frozenset())
    return Game(
        name=name,
        description=el.findtext("description", ""),
        year=el.findtext("year"),
        manufacturer=el.findtext("manufacturer"),
        cloneof=el.get("cloneof"),
        romof=el.get("romof"),
        is_bios=is_bios(el),
        roms=tuple(_rom(r, optional=_is_optional(r, optional)) for r in el.findall("rom")),
        has_disk=el.find("disk") is not None,
        players=int(players) if players else None,
        control=inp.get("control") if inp is not None else None,
        buttons=int(inp.get("buttons", 0)) if inp is not None else 0,
        default_bios=default_bios,
    )


class Dat:
    def __init__(self, games: dict[str, Game], emulator: str = "mame2003-plus"):
        self.emulator = _known(emulator)
        self.games = games
        self._index: dict[ChipKey, list[tuple[Game, Rom]]] = defaultdict(list)
        for game in games.values():
            for rom in game.roms:
                if rom.status != "nodump":
                    self._index[rom.key].append((game, rom))
        self.sizes = frozenset(size for size, _crc in self._crc_keys())

    def _crc_keys(self):
        for game in self.games.values():
            for rom in game.roms:
                yield rom.size, rom.crc

    def lookup(self, sha1: str, size: int, crc: str) -> list[tuple[Game, Rom]]:
        return self._index.get(sha1, []) + self._index.get((size, crc), [])

    def romof_chain(self, game: Game) -> list[Game]:
        """Ancestors by romof, nearest first."""
        chain, seen = [], {game.name}
        current = game
        while current.romof and current.romof not in seen and current.romof in self.games:
            current = self.games[current.romof]
            seen.add(current.name)
            chain.append(current)
        return chain

    def bios_of(self, game: Game) -> Game | None:
        return next((g for g in self.romof_chain(game) if g.is_bios), None)

    def is_bios_held(self, game: Game, rom: Rom) -> bool:
        """True if following rom.merge up the romof chain ends in a BIOS set."""
        holder, current = game, rom
        while current.merge and holder.romof in self.games:
            parent = self.games[holder.romof]
            match = next((r for r in parent.roms if r.name == current.merge), None)
            if match is None:
                return False
            if parent.is_bios:
                return True
            holder, current = parent, match
        return False

    def required_roms(self, game: Game) -> tuple[Rom, ...]:
        if game.is_bios:
            wanted = [r for r in game.roms if r.bios is None or r.bios == game.default_bios]
        else:
            wanted = [r for r in game.roms if not self.is_bios_held(game, r)]
        by_name: dict[str, Rom] = {}
        for rom in wanted:
            if rom.status != "nodump" and not rom.optional:
                by_name.setdefault(rom.name, rom)
        return tuple(by_name.values())

    def family(self, game: Game) -> str:
        """Root of the cloneof chain: PuckMan and Pac-Man are one game."""
        current = game
        while current.cloneof and current.cloneof in self.games:
            current = self.games[current.cloneof]
        return current.name


def _crc(value: object, set_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 8
        or set(value.lower()) - set("0123456789abcdef")
    ):
        raise ValueError(f"CRC for {set_name!r} must be 8-hex string, got {value!r}")
    return value.lower()


def load_optional_roms(path: Path) -> dict[str, frozenset[str]]:
    """The ROMs each set can load without, as `scripts/fbneo_optional.py` writes them.

    A JSON object: set name → list of CRCs, 8 hex digits each (lowercased on the way in).
    """
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError("Optional ROMs file must be a JSON object")
    for set_name, crcs in data.items():
        if not isinstance(crcs, list):
            raise ValueError(
                f"Optional ROMs values must be lists, got {type(crcs).__name__} for {set_name!r}"
            )
    return {name: frozenset(_crc(c, name) for c in crcs) for name, crcs in data.items()}


def load_dat(
    path: Path, emulator: str = "mame2003-plus", optional_roms: OptionalRoms | None = None
) -> Dat:
    is_bios = IS_BIOS[_known(emulator)]
    games = {}
    for _event, el in ET.iterparse(path, events=("end",)):
        if el.tag == "game":
            game = _game(el, is_bios=is_bios, optional_roms=optional_roms)
            games[game.name] = game
            el.clear()
    return Dat(games, emulator=emulator)

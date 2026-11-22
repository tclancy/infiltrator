"""The MAME 2003-Plus DAT: which games exist and exactly which chips each one needs."""

import json
import xml.etree.ElementTree as ET
from collections import defaultdict
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


@dataclass(frozen=True)
class _Dialect:
    """Parsing differences between emulator DATs."""

    is_bios_marker: str


def _mame2003_plus_is_bios(el: ET.Element) -> bool:
    return el.get("runnable") == "no"


def _fbneo_is_bios(el: ET.Element) -> bool:
    return el.get("isbios") == "yes"


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


def _game(
    el: ET.Element,
    is_bios_func: callable = _mame2003_plus_is_bios,
    optional_roms: dict[str, frozenset[str]] | None = None,
) -> Game:
    inp = el.find("input")
    default_bios = next(
        (b.get("name") for b in el.findall("biosset") if b.get("default") == "yes"), None
    )
    players = inp.get("players") if inp is not None else None
    game_name = el.get("name")
    optional_set = optional_roms.get(game_name, frozenset()) if optional_roms else frozenset()
    roms = []
    for r in el.findall("rom"):
        rom_crc = r.get("crc")
        is_optional = (rom_crc and rom_crc.lower() in optional_set) if rom_crc else False
        roms.append(_rom(r, optional=is_optional))
    return Game(
        name=game_name,
        description=el.findtext("description", ""),
        year=el.findtext("year"),
        manufacturer=el.findtext("manufacturer"),
        cloneof=el.get("cloneof"),
        romof=el.get("romof"),
        is_bios=is_bios_func(el),
        roms=tuple(roms),
        has_disk=el.find("disk") is not None,
        players=int(players) if players else None,
        control=inp.get("control") if inp is not None else None,
        buttons=int(inp.get("buttons", 0)) if inp is not None else 0,
        default_bios=default_bios,
    )


class Dat:
    def __init__(
        self,
        games: dict[str, Game],
        emulator: str = "mame2003-plus",
        optional_roms: dict[str, frozenset[str]] | None = None,
    ):
        if emulator not in {"mame2003-plus", "fbneo"}:
            raise ValueError(
                f'Unknown emulator: {emulator!r}. Known emulators: "mame2003-plus", "fbneo"'
            )
        self.emulator = emulator
        self.games = games
        self.optional_roms = optional_roms or {}
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


def load_optional_roms(path: Path) -> dict[str, frozenset[str]]:
    """Load optional ROMs mapping from a JSON file.

    File format: {"setname": ["crc1", "crc2", ...], ...}
    CRCs are 8-hex-digit strings (case-insensitive; normalized to lowercase).
    """
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Optional ROMs file must be a JSON object")
    result = {}
    for set_name, crc_list in data.items():
        if not isinstance(set_name, str):
            raise ValueError(f"Optional ROMs keys must be strings, got {type(set_name).__name__}")
        if not isinstance(crc_list, list):
            msg = (
                f"Optional ROMs values must be lists, got "
                f"{type(crc_list).__name__} for {set_name!r}"
            )
            raise ValueError(msg)
        normalized_crcs = []
        for crc in crc_list:
            if (
                not isinstance(crc, str)
                or len(crc) != 8
                or not all(c in "0123456789abcdefABCDEF" for c in crc)
            ):
                raise ValueError(f"CRC for {set_name!r} must be 8-hex string, got {crc!r}")
            normalized_crcs.append(crc.lower())
        result[set_name] = frozenset(normalized_crcs)
    return result


def load_dat(
    path: Path,
    emulator: str = "mame2003-plus",
    optional_roms: dict[str, frozenset[str]] | None = None,
) -> Dat:
    if emulator == "mame2003-plus":
        is_bios_func = _mame2003_plus_is_bios
    elif emulator == "fbneo":
        is_bios_func = _fbneo_is_bios
    else:
        raise ValueError(
            f"Unknown emulator: {emulator!r}. Known emulators: 'mame2003-plus', 'fbneo'"
        )
    games = {}
    for _event, el in ET.iterparse(path, events=("end",)):
        if el.tag == "game":
            game = _game(el, is_bios_func=is_bios_func, optional_roms=optional_roms)
            games[game.name] = game
            el.clear()
    return Dat(games, emulator=emulator, optional_roms=optional_roms)

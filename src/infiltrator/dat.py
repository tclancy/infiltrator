"""The MAME 2003-Plus DAT: which games exist and exactly which chips each one needs."""

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


def _rom(el: ET.Element) -> Rom:
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
    )


def _game(el: ET.Element) -> Game:
    inp = el.find("input")
    default_bios = next(
        (b.get("name") for b in el.findall("biosset") if b.get("default") == "yes"), None
    )
    players = inp.get("players") if inp is not None else None
    return Game(
        name=el.get("name"),
        description=el.findtext("description", ""),
        year=el.findtext("year"),
        manufacturer=el.findtext("manufacturer"),
        cloneof=el.get("cloneof"),
        romof=el.get("romof"),
        is_bios=el.get("runnable") == "no",
        roms=tuple(_rom(r) for r in el.findall("rom")),
        has_disk=el.find("disk") is not None,
        players=int(players) if players else None,
        control=inp.get("control") if inp is not None else None,
        buttons=int(inp.get("buttons", 0)) if inp is not None else 0,
        default_bios=default_bios,
    )


class Dat:
    def __init__(self, games: dict[str, Game]):
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
            if rom.status != "nodump":
                by_name.setdefault(rom.name, rom)
        return tuple(by_name.values())

    def family(self, game: Game) -> str:
        """Root of the cloneof chain: PuckMan and Pac-Man are one game."""
        current = game
        while current.cloneof and current.cloneof in self.games:
            current = self.games[current.cloneof]
        return current.name


def load_dat(path: Path) -> Dat:
    games = {}
    for _event, el in ET.iterparse(path, events=("end",)):
        if el.tag == "game":
            game = _game(el)
            games[game.name] = game
            el.clear()
    return Dat(games)

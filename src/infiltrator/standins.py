"""Which FBNeo sets stand in for a MAME 2003-Plus game, worked out from the two set lists.

A person thinks in games, and a game is a MAME family. The FBNeo sets that "stand in" for a
family are the ones that have at least half their own ROMs in common with the sets of it,
matched by size and CRC (the only identity FBNeo's list gives a ROM). A ROM some BIOS set
holds, in either list, does not count: every Neo Geo game shares the Neo Geo BIOS, and that
makes none of them the same game. Half, not one: boards share colour PROMs and sound ROMs, and
on the real lists "shares any ROM" gave Pac-Man 202 stand-ins.

Nothing here is stored. It is derived from the two DATs each time, through one index per call,
so the work grows with the size of the lists, never with their product.
"""

from collections import Counter, defaultdict
from collections.abc import Collection, Iterable

from infiltrator.dat import Dat, Game
from infiltrator.names import title

Key = tuple[int, str]  # (size, crc)


def rom_keys(game: Game) -> frozenset[Key]:
    """Every dumped ROM of a set, as (size, crc)."""
    return frozenset((r.size, r.crc) for r in game.roms if r.crc and r.status != "nodump")


def bios_keys(*dats: Dat) -> frozenset[Key]:
    """The ROMs some BIOS set holds, in any of these lists."""
    held: set[Key] = set()
    for dat in dats:
        for game in dat.games.values():
            if game.is_bios:
                held |= rom_keys(game)
    return frozenset(held)


def _games(dat: Dat) -> Iterable[Game]:
    return (g for g in dat.games.values() if not g.is_bios)


def family_keys(mame: Dat, ignore: frozenset[Key]) -> dict[str, frozenset[Key]]:
    """MAME family → the ROMs any of its sets has, less the ignored ones."""
    keys: dict[str, set[Key]] = defaultdict(set)
    for game in _games(mame):
        keys[mame.family(game)] |= rom_keys(game) - ignore
    return {family: frozenset(k) for family, k in keys.items()}


def sets_by_key(fbneo: Dat, ignore: frozenset[Key]) -> dict[Key, frozenset[str]]:
    """The index: an FBNeo ROM → the FBNeo sets (non-BIOS) that have it."""
    index: dict[Key, set[str]] = defaultdict(set)
    for game in _games(fbneo):
        for key in rom_keys(game) - ignore:
            index[key].add(game.name)
    return {key: frozenset(names) for key, names in index.items()}


def _counted(mame: Dat, index: dict[Key, frozenset[str]], ignore: frozenset[Key]):
    """FBNeo set → how many ROMs it has in common with each MAME family, however few."""
    shared: dict[str, Counter[str]] = defaultdict(Counter)
    for family, keys in family_keys(mame, ignore).items():
        for key in keys:
            for name in index.get(key, ()):
                shared[name][family] += 1
    return shared


def _mostly(counts: Counter[str], own: int) -> Counter[str]:
    """Only the families this set has at least half of its own ROMs in common with."""
    return Counter({family: n for family, n in counts.items() if 2 * n >= own})


def shared_roms(mame: Dat, fbneo: Dat) -> dict[str, Counter[str]]:
    """FBNeo set → the MAME families it is mostly made of, with how many ROMs they share."""
    ignore = bios_keys(mame, fbneo)
    index = sets_by_key(fbneo, ignore)
    own = Counter(name for names in index.values() for name in names)  # ROMs per FBNeo set
    mostly = {n: _mostly(counts, own[n]) for n, counts in _counted(mame, index, ignore).items()}
    return {name: counts for name, counts in mostly.items() if counts}


def standins(
    mame: Dat, fbneo: Dat, families: Collection[str] | None = None
) -> dict[str, frozenset[str]]:
    """MAME family → the FBNeo sets that stand in for it: of these families, or of all of them."""
    found: dict[str, set[str]] = defaultdict(set)
    for name, counts in shared_roms(mame, fbneo).items():
        for family in counts:
            if families is None or family in families:
                found[family].add(name)
    return {family: frozenset(names) for family, names in found.items()}


def _most_shared(counts: Counter[str]) -> str:
    """The family with the most ROMs in common; on a tie, the first by name."""
    return min(counts, key=lambda family: (-counts[family], family))


def stands_in_for(mame: Dat, fbneo: Dat) -> dict[str, str]:
    """FBNeo set → the MAME family it shares the most ROMs with; sets sharing none are left out."""
    return {name: _most_shared(counts) for name, counts in shared_roms(mame, fbneo).items()}


def with_bios(fbneo: Dat, names: Iterable[str]) -> frozenset[str]:
    """These FBNeo sets and the BIOS set each one needs."""
    wanted = set(names)
    for name in list(wanted):
        bios = fbneo.bios_of(fbneo.games[name])
        if bios is not None:
            wanted.add(bios.name)
    return frozenset(wanted)


def fbneo_wanted(mame: Dat, fbneo: Dat, families: Collection[str]) -> frozenset[str]:
    """What to build for games chosen to run on FBNeo: every stand-in, and the BIOS it needs."""
    if not families:
        return frozenset()
    found = standins(mame, fbneo, families)
    return with_bios(fbneo, (name for names in found.values() for name in names))


def families_titled(mame: Dat, wanted: str) -> frozenset[str]:
    """The MAME families a person means by this title: any with a set so titled, in any case."""
    name = wanted.casefold()
    return frozenset(
        mame.family(game) for game in _games(mame) if title(game.description).casefold() == name
    )

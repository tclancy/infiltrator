"""The shelf: a few games per persona, best first, and the sommelier that rotates them.

Choosing works on MAME 2003-Plus rows: a game is a MAME family. Only when a choice is written
to the shelf is each chosen game put on the emulator picked for it (see `stand_ins`), so the
shelf holds one entry per game whichever emulator runs it. `emulators` says which emulators the
TV can show; MAME 2003-Plus always, the others only once their folders are configured.
"""

import sqlite3
from collections import defaultdict
from collections.abc import Callable, Collection

from infiltrator.catalogue import utcnow
from infiltrator.dat import DEFAULT_EMULATOR
from infiltrator.names import set_label
from infiltrator.personas import Persona, eligible, is_must_have

Key = tuple[str, str]  # (emulator, set_name): a set, wherever it is
MAME_ONLY: Collection[str] = (DEFAULT_EMULATOR,)


def key(g: sqlite3.Row) -> Key:
    return (g["emulator"], g["set_name"])


def _labels(keys: list[Key]) -> list[str]:
    return [set_label(*k) for k in keys]


def _family_choice(group: list[sqlite3.Row], p: Persona) -> sqlite3.Row:
    """One version per game: a named one, a clone in your language, the parent, the rest."""

    def preference(g: sqlite3.Row) -> tuple:
        speaks = p.language is None or g["language"] == p.language
        return (
            not is_must_have(p, g["title"]),
            not speaks,
            g["parent"] is not None,
            g["set_name"],
        )

    return min(group, key=preference)


def pick_one_per_family(rows: list[sqlite3.Row], p: Persona) -> list[sqlite3.Row]:
    families: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        families[row["family"]].append(row)
    return [_family_choice(group, p) for group in families.values()]


def last_shelved(conn: sqlite3.Connection, persona: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT set_name, MAX(at) AS at FROM shelf_history "
        "WHERE persona = ? AND emulator = ? AND action = 'on' GROUP BY set_name",
        (persona, DEFAULT_EMULATOR),
    )
    return {r["set_name"]: r["at"] for r in rows}


def _last_shelved_elsewhere(conn: sqlite3.Connection, persona: str) -> dict[str, str]:
    """Family → when the game was last put on this shelf as another emulator's set."""
    rows = conn.execute(
        "SELECT g.family, MAX(h.at) AS at FROM shelf_history h "
        "JOIN games g ON g.emulator = h.emulator AND g.set_name = h.set_name "
        "WHERE h.persona = ? AND h.emulator != ? AND h.action = 'on' GROUP BY g.family",
        (persona, DEFAULT_EMULATOR),
    )
    return {r["family"]: r["at"] for r in rows}


def _last_seen(conn: sqlite3.Connection, persona: str) -> Callable[[sqlite3.Row], str]:
    """When this MAME row's game was last put on the shelf, as itself or as a stand-in."""
    as_itself, elsewhere = last_shelved(conn, persona), _last_shelved_elsewhere(conn, persona)
    return lambda g: max(as_itself.get(g["set_name"], ""), elsewhere.get(g["family"], ""))


def _rank(conn: sqlite3.Connection, p: Persona, rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """One per family, best first; among equals, the one off the shelf longest."""
    seen = _last_seen(conn, p.name)

    def rank(g: sqlite3.Row) -> tuple:
        tier = g["quality_tier"]
        return (tier is None, -(tier or 0), seen(g), g["set_name"])

    return sorted(pick_one_per_family(rows, p), key=rank)


def _ranked(conn: sqlite3.Connection, p: Persona) -> list[sqlite3.Row]:
    return _rank(conn, p, eligible(conn, p))


def current_shelf(conn: sqlite3.Connection, persona: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT g.*, s.placed_at FROM shelf s "
        "JOIN games g ON g.emulator = s.emulator AND g.set_name = s.set_name "
        "WHERE s.persona = ? ORDER BY g.title",
        (persona,),
    ).fetchall()


def stand_ins(conn: sqlite3.Connection, emulators: Collection[str]) -> dict[str, Key]:
    """Family → the set to shelve in place of its MAME 2003-Plus one, for each game that has one.

    A game gets one when someone chose another emulator for it, that emulator's set for it is
    in the library (built and verified), and the TV can show that emulator. Of several, the
    one its own DAT calls a parent, then the lowest name.
    """
    others = sorted(set(emulators) - {DEFAULT_EMULATOR})
    if not others:
        return {}
    rows = conn.execute(
        "SELECT g.family, g.emulator, g.set_name FROM game_emulators c "
        "JOIN games g ON g.emulator = c.emulator AND g.family = c.family "
        f"WHERE g.is_bios = 0 AND c.emulator IN ({', '.join('?' * len(others))}) "
        "ORDER BY g.parent IS NOT NULL, g.set_name",
        others,
    )
    found: dict[str, Key] = {}
    for r in rows:
        found.setdefault(r["family"], key(r))
    return found


def _placed(conn: sqlite3.Connection, chosen: list[sqlite3.Row], emulators) -> list[Key]:
    """Where each chosen MAME row goes on the shelf: its game's stand-in, or itself."""
    swaps = stand_ins(conn, emulators)
    return [swaps.get(g["family"], key(g)) for g in chosen]


def _shelf_keys(conn: sqlite3.Connection, persona: str, emulators: Collection[str]) -> set[Key]:
    rows = conn.execute("SELECT emulator, set_name FROM shelf WHERE persona = ?", (persona,))
    return {key(r) for r in rows if r["emulator"] in emulators}


def _insert(conn: sqlite3.Connection, persona: str, k: Key, placed_at: str) -> None:
    """Put a set on the shelf, remembering which game it is in case its row ever goes."""
    conn.execute(
        "INSERT INTO shelf (persona, emulator, set_name, placed_at, family) VALUES "
        "(?, ?, ?, ?, (SELECT family FROM games WHERE emulator = ? AND set_name = ?))",
        (persona, *k, placed_at, *k),
    )


def _delete(conn: sqlite3.Connection, persona: str, k: Key) -> None:
    conn.execute(
        "DELETE FROM shelf WHERE persona = ? AND emulator = ? AND set_name = ?", (persona, *k)
    )


def _replace_shelf(
    conn: sqlite3.Connection,
    persona: str,
    wanted: list[Key],
    now: str,
    emulators: Collection[str] = MAME_ONLY,
) -> None:
    """Make the persona's shelf hold exactly these sets, logging each move.

    Only the rows of `emulators` are this call's to change; settling handles the rest.
    """
    before = _shelf_keys(conn, persona, emulators)
    after = {k for k in wanted if k[0] in emulators}
    with conn:
        for k in sorted(before - after):
            _delete(conn, persona, k)
            _log_move(conn, persona, *k, "off", now)
        for k in sorted(after - before):
            _insert(conn, persona, k, now)
            _log_move(conn, persona, *k, "on", now)


def _log_move(
    conn: sqlite3.Connection, persona: str, emulator: str, set_name: str, action: str, now: str
) -> None:
    conn.execute(
        "INSERT INTO shelf_history (persona, emulator, set_name, action, at) "
        "VALUES (?, ?, ?, ?, ?)",
        (persona, emulator, set_name, action, now),
    )


def build_shelf(
    conn: sqlite3.Connection,
    p: Persona,
    size: int,
    now: Callable[[], str] = utcnow,
    emulators: Collection[str] = MAME_ONLY,
) -> list[str]:
    ranked = _ranked(conn, p)
    musts = [g for g in ranked if is_must_have(p, g["title"])]
    if len(musts) >= size:
        seen = _last_seen(conn, p.name)
        chosen = sorted(musts, key=lambda g: (seen(g), g["set_name"]))[:size]
    else:
        others = [g for g in ranked if not is_must_have(p, g["title"])]
        chosen = musts + others[: size - len(musts)]
    wanted = _placed(conn, chosen, emulators)
    _replace_shelf(conn, p.name, wanted, now(), emulators)
    return _labels(wanted)


def rotate(
    conn: sqlite3.Connection,
    p: Persona,
    size: int,
    count: int = 1,
    now: Callable[[], str] = utcnow,
    emulators: Collection[str] = MAME_ONLY,
) -> tuple[list[str], list[str]]:
    """Retire the longest-shelved games and bring in the best ones not on the shelf.

    Must-haves stay put unless there are more of them than the shelf holds, in
    which case only must-haves rotate. Returns the sets out and in, as `set_label` names them.
    """
    ranked = _ranked(conn, p)
    over_cap = sum(is_must_have(p, g["title"]) for g in ranked) >= size
    shelf = current_shelf(conn, p.name)
    out = _retirable(shelf, p, over_cap)[:count]
    taken = {g["family"] for g in shelf}
    incoming = [
        g
        for g in ranked
        if g["family"] not in taken and (not over_cap or is_must_have(p, g["title"]))
    ][: len(out)]
    out = out[: len(incoming)]
    if not out:
        return [], []
    retired = {key(g) for g in out}
    placed = _placed(conn, incoming, emulators)
    wanted = [key(g) for g in shelf if key(g) not in retired] + placed
    _replace_shelf(conn, p.name, wanted, now(), emulators)
    return _labels([key(g) for g in out]), _labels(placed)


def _fill(
    conn: sqlite3.Connection,
    p: Persona,
    size: int,
    ranked: list[sqlite3.Row],
    now: str,
    emulators: Collection[str],
) -> list[str]:
    """Put the best of ranked in the empty slots; nothing already shelved moves."""
    shelf = current_shelf(conn, p.name)
    taken = {g["family"] for g in shelf}
    chosen = [g for g in ranked if g["family"] not in taken][: max(size - len(shelf), 0)]
    incoming = _placed(conn, chosen, emulators)
    if incoming:
        _replace_shelf(conn, p.name, [key(g) for g in shelf] + incoming, now, emulators)
    return _labels(incoming)


def fill_shelf(
    conn: sqlite3.Connection,
    p: Persona,
    size: int,
    now: Callable[[], str] = utcnow,
    emulators: Collection[str] = MAME_ONLY,
) -> list[str]:
    """Put the best new games in the empty slots; nothing already shelved moves."""
    return _fill(conn, p, size, _ranked(conn, p), now(), emulators)


def _ranked_arrivals(conn: sqlite3.Connection, p: Persona, arrived: set[str]) -> list[sqlite3.Row]:
    """Arrivals only, chosen one per family among themselves: a new clone of an old game counts."""
    return _rank(conn, p, [g for g in eligible(conn, p) if g["set_name"] in arrived])


def demo_shelf(
    conn: sqlite3.Connection,
    p: Persona,
    size: int,
    arrived: set[str],
    now: Callable[[], str] = utcnow,
    emulators: Collection[str] = MAME_ONLY,
) -> list[str]:
    """Replace the shelf with the best of these arrivals; with none eligible, change nothing."""
    wanted = _placed(conn, _ranked_arrivals(conn, p, arrived)[:size], emulators)
    if wanted:
        _replace_shelf(conn, p.name, wanted, now(), emulators)
    return _labels(wanted)


def fill_demo_shelf(
    conn: sqlite3.Connection,
    p: Persona,
    size: int,
    arrived: set[str],
    now: Callable[[], str] = utcnow,
    emulators: Collection[str] = MAME_ONLY,
) -> list[str]:
    """Like fill_shelf, but only these arrivals may take an empty slot."""
    return _fill(conn, p, size, _ranked_arrivals(conn, p, arrived), now(), emulators)


def _retirable(shelf: list[sqlite3.Row], p: Persona, over_cap: bool) -> list[sqlite3.Row]:
    """What may leave, longest-shelved first. Must-haves stay unless they outnumber the shelf."""
    oldest_first = sorted(shelf, key=lambda g: (g["placed_at"], g["set_name"]))
    return [g for g in oldest_first if over_cap or not is_must_have(p, g["title"])]


def _titled(conn: sqlite3.Connection, p: Persona, title: str) -> list[sqlite3.Row]:
    """Every version of the game so titled that this persona could play, dropped or not."""
    wanted = title.casefold()
    rows = [g for g in eligible(conn, p, ignore_drops=True) if g["title"].casefold() == wanted]
    if not rows:
        raise LookupError(f"no game called {title!r} that {p.name} can play")
    return rows


def drop(
    conn: sqlite3.Connection,
    p: Persona,
    title: str,
    now: Callable[[], str] = utcnow,
    emulators: Collection[str] = MAME_ONLY,
) -> str:
    """Take a game off the shelf and keep it off: no fill, build or rotate brings it back.

    Works whether or not the game is on the shelf now, on whichever emulator. Returns its title
    as the catalogue has it.
    """
    rows = _titled(conn, p, title)
    families = {g["family"] for g in rows}
    at = now()
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO shelf_drops (persona, family, at) VALUES (?, ?, ?)",
            [(p.name, family, at) for family in sorted(families)],
        )
    shelf = current_shelf(conn, p.name)
    staying = [key(g) for g in shelf if g["family"] not in families]
    _replace_shelf(conn, p.name, staying, at, {*emulators, *(g["emulator"] for g in shelf)})
    return rows[0]["title"]


def _leaving_for(
    conn: sqlite3.Connection, p: Persona, shelf: list[sqlite3.Row], game: sqlite3.Row, size: int
) -> list[sqlite3.Row]:
    """What makes room for `game`: its other version, or the longest-shelved on a full shelf."""
    same_game = [g for g in shelf if g["family"] == game["family"]]
    if same_game or len(shelf) < size:
        return same_game
    over_cap = sum(is_must_have(p, g["title"]) for g in _ranked(conn, p)) >= size
    retirable = _retirable(shelf, p, over_cap)
    if not retirable:
        raise LookupError("the shelf is full and nothing on it may leave")
    return retirable[:1]


def add(
    conn: sqlite3.Connection,
    p: Persona,
    title: str,
    size: int,
    now: Callable[[], str] = utcnow,
    emulators: Collection[str] = MAME_ONLY,
) -> tuple[list[str], list[str]]:
    """Put a game on the shelf, forgetting it was ever dropped. Returns (sets out, sets in).

    Its other version leaves if one is shelved, on any emulator; otherwise, on a full shelf, the
    game `rotate` would retire first. The game goes on as its chosen emulator's set.
    """
    game = _family_choice(_titled(conn, p, title), p)
    (target,) = _placed(conn, [game], emulators)
    shelf = current_shelf(conn, p.name)
    leaving = {key(g) for g in _leaving_for(conn, p, shelf, game, size)} - {target}
    already = target in {key(g) for g in shelf}
    with conn:
        conn.execute(
            "DELETE FROM shelf_drops WHERE persona = ? AND family = ?", (p.name, game["family"])
        )
    wanted = [key(g) for g in shelf if key(g) not in leaving] + ([] if already else [target])
    _replace_shelf(conn, p.name, wanted, now(), {*emulators, *(k[0] for k in leaving)})
    return sorted(_labels(list(leaving))), [] if already else _labels([target])


# Settling: a game already on a shelf follows its emulator choice without a rebuild.


def _raw_shelf(conn: sqlite3.Connection, persona: str) -> list[sqlite3.Row]:
    """Every shelf row, including one whose set has left the catalogue (`present` is 0)."""
    return conn.execute(
        "SELECT s.emulator, s.set_name, s.placed_at, COALESCE(g.family, s.family) AS family, "
        "g.set_name IS NOT NULL AS present FROM shelf s "
        "LEFT JOIN games g ON g.emulator = s.emulator AND g.set_name = s.set_name "
        "WHERE s.persona = ? ORDER BY s.emulator, s.set_name",
        (persona,),
    ).fetchall()


def _mame_versions(conn: sqlite3.Connection, p: Persona) -> dict[str, Key]:
    """Family → the MAME 2003-Plus set this persona would be given for it."""
    return {g["family"]: key(g) for g in pick_one_per_family(eligible(conn, p), p)}


def _settled(row: sqlite3.Row, swaps: dict[str, Key], mame: Callable[[], dict]) -> Key | None:
    """Where a shelf row's game belongs now; None when it has nowhere to go."""
    if row["family"] in swaps:
        return swaps[row["family"]]
    if row["emulator"] == DEFAULT_EMULATOR:
        return key(row)
    return mame().get(row["family"])


def _move(
    conn: sqlite3.Connection, persona: str, old: Key, new: Key | None, placed_at: str, now: str
) -> None:
    """Swap one set for another as the same game, keeping its place in the rotation queue."""
    _delete(conn, persona, old)
    _log_move(conn, persona, *old, "off", now)
    if new is not None:
        _insert(conn, persona, new, placed_at)
        _log_move(conn, persona, *new, "on", now)


def settle_emulators(
    conn: sqlite3.Connection,
    p: Persona,
    emulators: Collection[str] = MAME_ONLY,
    now: Callable[[], str] = utcnow,
) -> list[tuple[str, str]]:
    """Put each shelved game on the emulator chosen for it now; returns (from, to) labels.

    MAME 2003-Plus becomes the chosen emulator's set once that exists and the TV can show it;
    that set goes back to MAME 2003-Plus when the choice is removed, the set leaves the library
    or the TV can no longer show it. A game keeps when it was placed, so a switch does not send
    it to the back of the rotation queue.
    """
    swaps = stand_ins(conn, emulators)
    cache: dict[str, dict[str, Key]] = {}

    def mame() -> dict[str, Key]:
        return cache.setdefault("versions", _mame_versions(conn, p))

    rows = _raw_shelf(conn, p.name)
    shelved, moves, at = {key(r) for r in rows}, [], now()
    with conn:
        for row in rows:
            new = _settled(row, swaps, mame)
            if new == key(row):
                continue
            target = None if new in shelved else new
            _move(conn, p.name, key(row), target, row["placed_at"], at)
            shelved.discard(key(row))
            shelved |= {target} if target else set()
            moves.append((set_label(*key(row)), set_label(*target) if target else ""))
    return moves

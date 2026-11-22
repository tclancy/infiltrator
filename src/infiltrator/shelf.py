"""The shelf: a few games per persona, best first, and the sommelier that rotates them."""

import sqlite3
from collections import defaultdict
from collections.abc import Callable

from infiltrator.catalogue import utcnow
from infiltrator.dat import DEFAULT_EMULATOR
from infiltrator.personas import Persona, eligible, is_must_have


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


def _rank(conn: sqlite3.Connection, p: Persona, rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """One per family, best first; among equals, the one off the shelf longest."""
    seen = last_shelved(conn, p.name)

    def rank(g: sqlite3.Row) -> tuple:
        tier = g["quality_tier"]
        return (tier is None, -(tier or 0), seen.get(g["set_name"], ""), g["set_name"])

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


def _replace_shelf(conn: sqlite3.Connection, persona: str, wanted: list[str], now: str) -> None:
    """Make the persona's shelf hold exactly these MAME 2003-Plus sets, logging each move."""
    emu = DEFAULT_EMULATOR
    rows = conn.execute(
        "SELECT set_name FROM shelf WHERE persona = ? AND emulator = ?", (persona, emu)
    )
    before = {r["set_name"] for r in rows}
    after = set(wanted)
    with conn:
        for name in sorted(before - after):
            conn.execute(
                "DELETE FROM shelf WHERE persona = ? AND emulator = ? AND set_name = ?",
                (persona, emu, name),
            )
            _log_move(conn, persona, emu, name, "off", now)
        for name in sorted(after - before):
            conn.execute(
                "INSERT INTO shelf (persona, emulator, set_name, placed_at) VALUES (?, ?, ?, ?)",
                (persona, emu, name, now),
            )
            _log_move(conn, persona, emu, name, "on", now)


def _log_move(
    conn: sqlite3.Connection, persona: str, emulator: str, set_name: str, action: str, now: str
) -> None:
    conn.execute(
        "INSERT INTO shelf_history (persona, emulator, set_name, action, at) "
        "VALUES (?, ?, ?, ?, ?)",
        (persona, emulator, set_name, action, now),
    )


def build_shelf(
    conn: sqlite3.Connection, p: Persona, size: int, now: Callable[[], str] = utcnow
) -> list[str]:
    ranked = _ranked(conn, p)
    musts = [g for g in ranked if is_must_have(p, g["title"])]
    if len(musts) >= size:
        seen = last_shelved(conn, p.name)
        chosen = sorted(musts, key=lambda g: (seen.get(g["set_name"], ""), g["set_name"]))[:size]
    else:
        others = [g for g in ranked if not is_must_have(p, g["title"])]
        chosen = musts + others[: size - len(musts)]
    wanted = [g["set_name"] for g in chosen]
    _replace_shelf(conn, p.name, wanted, now())
    return wanted


def rotate(
    conn: sqlite3.Connection,
    p: Persona,
    size: int,
    count: int = 1,
    now: Callable[[], str] = utcnow,
) -> tuple[list[str], list[str]]:
    """Retire the longest-shelved games and bring in the best ones not on the shelf.

    Must-haves stay put unless there are more of them than the shelf holds, in
    which case only must-haves rotate.
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
    retired = {g["set_name"] for g in out}
    wanted = [g["set_name"] for g in shelf if g["set_name"] not in retired]
    wanted += [g["set_name"] for g in incoming]
    _replace_shelf(conn, p.name, wanted, now())
    return [g["set_name"] for g in out], [g["set_name"] for g in incoming]


def _fill(
    conn: sqlite3.Connection, p: Persona, size: int, ranked: list[sqlite3.Row], now: str
) -> list[str]:
    """Put the best of ranked in the empty slots; nothing already shelved moves."""
    shelf = current_shelf(conn, p.name)
    taken = {g["family"] for g in shelf}
    incoming = [g["set_name"] for g in ranked if g["family"] not in taken]
    incoming = incoming[: max(size - len(shelf), 0)]
    if incoming:
        _replace_shelf(conn, p.name, [g["set_name"] for g in shelf] + incoming, now)
    return incoming


def fill_shelf(
    conn: sqlite3.Connection, p: Persona, size: int, now: Callable[[], str] = utcnow
) -> list[str]:
    """Put the best new games in the empty slots; nothing already shelved moves."""
    return _fill(conn, p, size, _ranked(conn, p), now())


def _ranked_arrivals(conn: sqlite3.Connection, p: Persona, arrived: set[str]) -> list[sqlite3.Row]:
    """Arrivals only, chosen one per family among themselves: a new clone of an old game counts."""
    return _rank(conn, p, [g for g in eligible(conn, p) if g["set_name"] in arrived])


def demo_shelf(
    conn: sqlite3.Connection,
    p: Persona,
    size: int,
    arrived: set[str],
    now: Callable[[], str] = utcnow,
) -> list[str]:
    """Replace the shelf with the best of these arrivals; with none eligible, change nothing."""
    wanted = [g["set_name"] for g in _ranked_arrivals(conn, p, arrived)[:size]]
    if wanted:
        _replace_shelf(conn, p.name, wanted, now())
    return wanted


def fill_demo_shelf(
    conn: sqlite3.Connection,
    p: Persona,
    size: int,
    arrived: set[str],
    now: Callable[[], str] = utcnow,
) -> list[str]:
    """Like fill_shelf, but only these arrivals may take an empty slot."""
    return _fill(conn, p, size, _ranked_arrivals(conn, p, arrived), now())


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


def drop(conn: sqlite3.Connection, p: Persona, title: str, now: Callable[[], str] = utcnow) -> str:
    """Take a game off the shelf and keep it off: no fill, build or rotate brings it back.

    Works whether or not the game is on the shelf now. Returns its title as the catalogue has it.
    """
    rows = _titled(conn, p, title)
    families = {g["family"] for g in rows}
    at = now()
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO shelf_drops (persona, family, at) VALUES (?, ?, ?)",
            [(p.name, family, at) for family in sorted(families)],
        )
    staying = [g["set_name"] for g in current_shelf(conn, p.name) if g["family"] not in families]
    _replace_shelf(conn, p.name, staying, at)
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
    conn: sqlite3.Connection, p: Persona, title: str, size: int, now: Callable[[], str] = utcnow
) -> tuple[list[str], list[str]]:
    """Put a game on the shelf, forgetting it was ever dropped. Returns (sets out, sets in).

    Its other version leaves if one is shelved; otherwise, on a full shelf, the game `rotate`
    would retire first.
    """
    game = _family_choice(_titled(conn, p, title), p)
    shelf = current_shelf(conn, p.name)
    leaving = {g["set_name"] for g in _leaving_for(conn, p, shelf, game, size)} - {game["set_name"]}
    already = any(g["set_name"] == game["set_name"] for g in shelf)
    with conn:
        conn.execute(
            "DELETE FROM shelf_drops WHERE persona = ? AND family = ?", (p.name, game["family"])
        )
    wanted = [g["set_name"] for g in shelf if g["set_name"] not in leaving]
    _replace_shelf(conn, p.name, wanted + ([] if already else [game["set_name"]]), now())
    return sorted(leaving), [] if already else [game["set_name"]]

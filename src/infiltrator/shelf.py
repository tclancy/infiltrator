"""The shelf: a few games per persona, best first, and the sommelier that rotates them."""

import sqlite3
from collections import defaultdict
from collections.abc import Callable

from infiltrator.catalogue import utcnow
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
        "WHERE persona = ? AND action = 'on' GROUP BY set_name",
        (persona,),
    )
    return {r["set_name"]: r["at"] for r in rows}


def _ranked(conn: sqlite3.Connection, p: Persona) -> list[sqlite3.Row]:
    """Best first; among equals, the one off the shelf longest (never shelved first)."""
    seen = last_shelved(conn, p.name)

    def rank(g: sqlite3.Row) -> tuple:
        tier = g["quality_tier"]
        return (tier is None, -(tier or 0), seen.get(g["set_name"], ""), g["set_name"])

    return sorted(pick_one_per_family(eligible(conn, p), p), key=rank)


def current_shelf(conn: sqlite3.Connection, persona: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT g.*, s.placed_at FROM shelf s JOIN games g USING (set_name) "
        "WHERE s.persona = ? ORDER BY g.title",
        (persona,),
    ).fetchall()


def _replace_shelf(conn: sqlite3.Connection, persona: str, wanted: list[str], now: str) -> None:
    before = {
        r["set_name"]
        for r in conn.execute("SELECT set_name FROM shelf WHERE persona = ?", (persona,))
    }
    after = set(wanted)
    with conn:
        for name in sorted(before - after):
            conn.execute("DELETE FROM shelf WHERE persona = ? AND set_name = ?", (persona, name))
            conn.execute(
                "INSERT INTO shelf_history (persona, set_name, action, at) VALUES (?, ?, 'off', ?)",
                (persona, name, now),
            )
        for name in sorted(after - before):
            conn.execute(
                "INSERT INTO shelf (persona, set_name, placed_at) VALUES (?, ?, ?)",
                (persona, name, now),
            )
            conn.execute(
                "INSERT INTO shelf_history (persona, set_name, action, at) VALUES (?, ?, 'on', ?)",
                (persona, name, now),
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
    shelf = sorted(current_shelf(conn, p.name), key=lambda g: (g["placed_at"], g["set_name"]))
    retirable = [g for g in shelf if over_cap or not is_must_have(p, g["title"])]
    out = retirable[:count]
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

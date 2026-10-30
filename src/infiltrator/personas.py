"""Who's playing: a few plain answers, saved, that decide which games qualify."""

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Literal

from infiltrator.catalogue.tuning import tuned_sets

GAMEPAD = frozenset({"joy4way", "joy8way", "doublejoy4way", "doublejoy8way", "stick"})
SPINNERS = frozenset({"dial", "trackball", "paddle"})
LIGHT_GUN = frozenset({"lightgun"})


@dataclass(frozen=True)
class Persona:
    name: str
    language: str | None = "English"
    mature_ok: bool = False
    players: Literal["solo", "together", "any"] = "any"
    controls: frozenset[str] = GAMEPAD
    one_handed: bool = False
    must_haves: tuple[str, ...] = field(default=())


def save_persona(conn: sqlite3.Connection, p: Persona) -> None:
    data = asdict(p)
    data["controls"] = sorted(p.controls)
    data.pop("must_haves")
    data.pop("name")
    with conn:
        conn.execute(
            "INSERT INTO personas (name, data) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET data = excluded.data",
            (p.name, json.dumps(data)),
        )
        conn.execute("DELETE FROM must_haves WHERE persona = ?", (p.name,))
        conn.executemany(
            "INSERT OR IGNORE INTO must_haves (persona, title) VALUES (?, ?)",
            [(p.name, t) for t in p.must_haves],
        )


def load_persona(conn: sqlite3.Connection, name: str) -> Persona:
    found = conn.execute("SELECT data FROM personas WHERE name = ?", (name,)).fetchone()
    if found is None:
        raise KeyError(name)
    data = json.loads(found["data"])
    data["controls"] = frozenset(data["controls"])
    titles = conn.execute(
        "SELECT title FROM must_haves WHERE persona = ? ORDER BY title", (name,)
    ).fetchall()
    return Persona(name=name, must_haves=tuple(r["title"] for r in titles), **data)


def list_personas(conn: sqlite3.Connection) -> list[str]:
    return [r["name"] for r in conn.execute("SELECT name FROM personas ORDER BY name")]


def is_must_have(p: Persona, title: str | None) -> bool:
    wanted = {t.casefold() for t in p.must_haves}
    return title is not None and title.casefold() in wanted


def _playable(p: Persona, game: sqlite3.Row, tuned: set[str]) -> bool:
    """Controls and the body: no must-have can override these.

    A game with saved control tuning counts as playable whatever its listed
    control: Heavy Barrel is a dial in MAME but plays fine with an L1/R1 remap.
    """
    if game["control"] not in p.controls and game["set_name"] not in tuned:
        return False
    return not p.one_handed or bool(game["a11y_one_button"])


def _players_ok(p: Persona, players: str | None) -> bool:
    if p.players != "together":
        return True
    text = players or ""
    return "sim" in text or "alt" in text or (text[:1].isdigit() and int(text[0]) >= 2)


def _suitable(p: Persona, game: sqlite3.Row) -> bool:
    """Language and age: a lifer naming a game overrides these."""
    if p.language is not None and game["language"] != p.language:
        return False
    return p.mature_ok or game["mature"] != 1


def eligible(conn: sqlite3.Connection, p: Persona) -> list[sqlite3.Row]:
    games = conn.execute("SELECT * FROM games WHERE is_bios = 0 ORDER BY set_name").fetchall()
    tuned = tuned_sets(conn)
    return [
        g
        for g in games
        if _playable(p, g, tuned)
        and _players_ok(p, g["players"])
        and (is_must_have(p, g["title"]) or _suitable(p, g))
    ]

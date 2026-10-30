import itertools

import pytest
from test_personas import add_game

from infiltrator.catalogue import connect
from infiltrator.personas import Persona, save_persona
from infiltrator.shelf import build_shelf, current_shelf, rotate


@pytest.fixture
def conn(tmp_path):
    return connect(tmp_path / "c.db")


def P(conn, name, **kw) -> Persona:  # noqa: N802
    persona = Persona(name, **kw)
    save_persona(conn, persona)
    return persona


def clock():
    ticks = itertools.count(1)
    return lambda: f"2026-10-30T00:00:{next(ticks):02d}+00:00"


def shelf_names(conn, persona="tom"):
    return sorted(r["set_name"] for r in current_shelf(conn, persona))


def stock(conn, n, **cols):
    for i in range(n):
        add_game(conn, f"game{i:02d}", quality_tier=9 - (i % 10), **cols)


def test_shelf_respects_size_cap(conn):
    stock(conn, 12)
    assert len(build_shelf(conn, P(conn, "tom"), 8, now=clock())) == 8


def test_best_games_first(conn):
    add_game(conn, "meh", quality_tier=3)
    add_game(conn, "great", quality_tier=9)
    add_game(conn, "unrated", quality_tier=None)
    assert build_shelf(conn, P(conn, "tom"), 6, now=clock())[:2] == ["great", "meh"]


def test_one_version_per_game_parent_preferred(conn):
    add_game(conn, "puckman", title="PuckMan", family="puckman", quality_tier=9)
    add_game(conn, "pacman", title="Pac-Man", family="puckman", parent="puckman", quality_tier=9)
    assert shelf_names_after(conn) == ["puckman"]


def shelf_names_after(conn, persona=None):
    build_shelf(conn, persona or P(conn, "tom", language=None), 6, now=clock())
    return shelf_names(conn)


def test_clone_in_your_language_beats_foreign_parent(conn):
    add_game(conn, "jpn", family="jpn", language="Japanese")
    add_game(conn, "usa", family="jpn", parent="jpn")
    assert shelf_names_after(conn, P(conn, "tom")) == ["usa"]


def test_named_clone_wins_when_must_have(conn):
    add_game(conn, "puckman", title="PuckMan", family="puckman")
    add_game(conn, "pacman", title="Pac-Man", family="puckman", parent="puckman")
    assert shelf_names_after(conn, P(conn, "tom", must_haves=("pac-man",))) == ["pacman"]


def test_must_haves_first_even_if_unrated(conn):
    stock(conn, 10)
    add_game(conn, "congo", title="Congo Bongo", quality_tier=None)
    assert "congo" in build_shelf(conn, P(conn, "tom", must_haves=("Congo Bongo",)), 6, clock())


def test_must_haves_rotate_when_over_cap(conn):
    titles = [f"Fave {i}" for i in range(8)]
    for i, t in enumerate(titles):
        add_game(conn, f"fave{i}", title=t)
    stock(conn, 5)
    p = P(conn, "tom", must_haves=tuple(titles))
    tick = clock()
    first = set(build_shelf(conn, p, 6, now=tick))
    assert all(n.startswith("fave") for n in first)
    out, incoming = rotate(conn, p, 6, count=2, now=tick)
    assert len(out) == 2 and all(n.startswith("fave") for n in incoming)
    assert set(incoming).isdisjoint(first)


def test_rotate_swaps_oldest_for_best_unshelved(conn):
    stock(conn, 9)
    tick = clock()
    p = P(conn, "tom")
    build_shelf(conn, p, 6, now=tick)
    out, incoming = rotate(conn, p, 6, count=2, now=tick)
    assert len(out) == len(incoming) == 2
    assert set(incoming) <= {"game06", "game07", "game08"}
    assert len(shelf_names(conn)) == 6


def test_rotate_keeps_must_haves_under_cap(conn):
    stock(conn, 9)
    add_game(conn, "congo", title="Congo Bongo")
    tick = clock()
    p = P(conn, "tom", must_haves=("Congo Bongo",))
    build_shelf(conn, p, 6, now=tick)
    for _ in range(4):
        rotate(conn, p, 6, count=2, now=tick)
        assert "congo" in shelf_names(conn)


def test_rotate_with_nothing_new_is_a_noop(conn):
    stock(conn, 6)
    tick = clock()
    build_shelf(conn, P(conn, "tom"), 6, now=tick)
    assert rotate(conn, P(conn, "tom"), 6, now=tick) == ([], [])
    assert len(shelf_names(conn)) == 6


def test_history_records_on_and_off_in_utc(conn):
    stock(conn, 8)
    p = P(conn, "tom")
    build_shelf(conn, p, 6)
    rotate(conn, p, 6)
    actions = conn.execute("SELECT action, at FROM shelf_history ORDER BY id").fetchall()
    assert [a["action"] for a in actions].count("on") == 7
    assert [a["action"] for a in actions].count("off") == 1
    assert all(a["at"].endswith("+00:00") for a in actions)

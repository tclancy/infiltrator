"""The shelf holds one entry per game, on the emulator chosen for it."""

import pytest
from test_personas import add_game
from test_shelf import P, clock

from infiltrator.catalogue import connect
from infiltrator.catalogue.emulators import choose_emulator
from infiltrator.dat import DEFAULT_EMULATOR, FBNEO
from infiltrator.shelf import (
    add,
    build_shelf,
    current_shelf,
    demo_shelf,
    drop,
    fill_demo_shelf,
    fill_shelf,
    rotate,
    settle_emulators,
)

MAME = DEFAULT_EMULATOR
BOTH = frozenset({MAME, FBNEO})


@pytest.fixture
def conn(tmp_path):
    return connect(tmp_path / "c.db")


def heavy_barrel(conn, fbneo=True, quality_tier=9):
    """MAME's hbarrel and its clone; FBNeo's hbarrelua standing in for them, catalogued as such."""
    add_game(conn, "hbarrel", title="Heavy Barrel", quality_tier=quality_tier)
    add_game(conn, "hbarrelw", title="Heavy Barrel", family="hbarrel", parent="hbarrel")
    if fbneo:
        fbneo_set(conn, "hbarrelua", parent="hbarrel")


def fbneo_set(conn, name, family="hbarrel", parent=None):
    add_game(conn, name, emulator=FBNEO, family=family, parent=parent, title="Heavy Barrel")


def others(conn, n):
    for i in range(n):
        add_game(conn, f"game{i:02d}", quality_tier=5)


def on_shelf(conn, persona="tom"):
    return sorted((r["emulator"], r["set_name"]) for r in current_shelf(conn, persona))


def raw_shelf(conn):
    rows = conn.execute("SELECT emulator, set_name, placed_at FROM shelf ORDER BY 1, 2")
    return [tuple(r) for r in rows]


def history(conn):
    rows = conn.execute("SELECT emulator, set_name, action, at FROM shelf_history ORDER BY id")
    return [tuple(r) for r in rows]


def families(conn):
    return [r["family"] for r in current_shelf(conn, "tom")]


# T1: no choice, MAME; a choice that can be honoured, FBNeo, for every way onto the shelf.


def test_without_a_choice_the_mame_set_is_shelved(conn):
    heavy_barrel(conn)
    build_shelf(conn, P(conn, "tom"), 6, now=clock(), emulators=BOTH)
    assert on_shelf(conn) == [(MAME, "hbarrel")]


def test_with_fbneo_chosen_build_shelves_the_fbneo_set(conn):
    heavy_barrel(conn)
    choose_emulator(conn, "hbarrel", FBNEO)
    assert build_shelf(conn, P(conn, "tom"), 6, now=clock(), emulators=BOTH) == ["fbneo/hbarrelua"]
    assert on_shelf(conn) == [(FBNEO, "hbarrelua")]


def test_with_fbneo_chosen_fill_shelves_the_fbneo_set(conn):
    heavy_barrel(conn)
    choose_emulator(conn, "hbarrel", FBNEO)
    assert fill_shelf(conn, P(conn, "tom"), 6, now=clock(), emulators=BOTH) == ["fbneo/hbarrelua"]
    assert on_shelf(conn) == [(FBNEO, "hbarrelua")]


def test_with_fbneo_chosen_rotate_brings_in_the_fbneo_set(conn):
    tom = P(conn, "tom")
    others(conn, 6)
    tick = clock()
    build_shelf(conn, tom, 6, now=tick, emulators=BOTH)
    heavy_barrel(conn)
    choose_emulator(conn, "hbarrel", FBNEO)
    out, incoming = rotate(conn, tom, 6, now=tick, emulators=BOTH)
    assert (out, incoming) == (["game00"], ["fbneo/hbarrelua"])
    assert (FBNEO, "hbarrelua") in on_shelf(conn) and len(on_shelf(conn)) == 6


def test_with_fbneo_chosen_a_demo_shows_the_fbneo_set(conn):
    heavy_barrel(conn)
    choose_emulator(conn, "hbarrel", FBNEO)
    tom = P(conn, "tom")
    assert demo_shelf(conn, tom, 6, {"hbarrel"}, now=clock(), emulators=BOTH) == ["fbneo/hbarrelua"]
    on_shelf_before = on_shelf(conn)
    add_game(conn, "fresh")
    assert fill_demo_shelf(conn, tom, 6, {"hbarrel", "fresh"}, now=clock(), emulators=BOTH) == [
        "fresh"
    ]
    assert on_shelf_before == [(FBNEO, "hbarrelua")]


def test_with_fbneo_chosen_add_puts_the_fbneo_set_on(conn):
    heavy_barrel(conn)
    choose_emulator(conn, "hbarrel", FBNEO)
    assert add(conn, P(conn, "tom"), "heavy barrel", 6, now=clock(), emulators=BOTH) == (
        [],
        ["fbneo/hbarrelua"],
    )
    assert on_shelf(conn) == [(FBNEO, "hbarrelua")]


# The three conditions of a swap, each on its own.


def test_an_fbneo_set_nobody_chose_is_not_shelved(conn):  # (a)
    heavy_barrel(conn)
    build_shelf(conn, P(conn, "tom"), 6, now=clock(), emulators=BOTH)
    assert on_shelf(conn) == [(MAME, "hbarrel")]


def test_a_choice_with_no_fbneo_set_in_the_library_keeps_the_mame_set(conn):  # (b)
    heavy_barrel(conn, fbneo=False)
    choose_emulator(conn, "hbarrel", FBNEO)
    build_shelf(conn, P(conn, "tom"), 6, now=clock(), emulators=BOTH)
    assert on_shelf(conn) == [(MAME, "hbarrel")]


def test_a_choice_the_tv_cannot_show_keeps_the_mame_set(conn):  # (c)
    heavy_barrel(conn)
    choose_emulator(conn, "hbarrel", FBNEO)
    build_shelf(conn, P(conn, "tom"), 6, now=clock())  # MAME 2003-Plus only
    assert on_shelf(conn) == [(MAME, "hbarrel")]


def test_of_several_fbneo_sets_fbneos_parent_then_the_lowest_name_is_shelved(conn):
    heavy_barrel(conn, fbneo=False)
    fbneo_set(conn, "hbarrelb", parent="hbarrelx")
    fbneo_set(conn, "hbarrelc")
    fbneo_set(conn, "hbarreld")
    choose_emulator(conn, "hbarrel", FBNEO)
    build_shelf(conn, P(conn, "tom"), 6, now=clock(), emulators=BOTH)
    assert on_shelf(conn) == [(FBNEO, "hbarrelc")]


def test_an_fbneo_bios_never_stands_in(conn):
    heavy_barrel(conn, fbneo=False)
    add_game(conn, "abios", emulator=FBNEO, family="hbarrel", is_bios=1)
    choose_emulator(conn, "hbarrel", FBNEO)
    build_shelf(conn, P(conn, "tom"), 6, now=clock(), emulators=BOTH)
    assert on_shelf(conn) == [(MAME, "hbarrel")]


# T4: one entry per game, whichever emulator.


def test_a_swap_changes_no_shelf_size_and_never_doubles_a_game(conn):
    heavy_barrel(conn)
    others(conn, 8)
    choose_emulator(conn, "hbarrel", FBNEO)
    tom = P(conn, "tom", language=None)
    tick = clock()
    build_shelf(conn, tom, 6, now=tick, emulators=BOTH)
    for change in (
        lambda: fill_shelf(conn, tom, 6, now=tick, emulators=BOTH),
        lambda: rotate(conn, tom, 6, count=2, now=tick, emulators=BOTH),
        lambda: add(conn, tom, "Heavy Barrel", 6, now=tick, emulators=BOTH),
        lambda: settle_emulators(conn, tom, BOTH, now=tick),
    ):
        change()
        assert len(on_shelf(conn)) == 6
        assert len(set(families(conn))) == 6


def test_drop_by_title_takes_off_the_fbneo_set(conn):
    heavy_barrel(conn)
    others(conn, 2)
    choose_emulator(conn, "hbarrel", FBNEO)
    tom = P(conn, "tom")
    tick = clock()
    build_shelf(conn, tom, 6, now=tick, emulators=BOTH)
    assert drop(conn, tom, "Heavy Barrel", now=tick, emulators=BOTH) == "Heavy Barrel"
    assert on_shelf(conn) == [(MAME, "game00"), (MAME, "game01")]
    assert (FBNEO, "hbarrelua", "off", "2026-10-30T00:00:02+00:00") in history(conn)


def test_drop_takes_off_an_fbneo_set_even_where_the_tv_cannot_show_it(conn):
    heavy_barrel(conn)
    choose_emulator(conn, "hbarrel", FBNEO)
    tom = P(conn, "tom")
    build_shelf(conn, tom, 6, now=clock(), emulators=BOTH)
    drop(conn, tom, "Heavy Barrel", now=clock())
    assert raw_shelf(conn) == []


def test_add_swaps_the_shelved_mame_version_for_the_chosen_fbneo_one(conn):
    heavy_barrel(conn)
    tom = P(conn, "tom")
    tick = clock()
    build_shelf(conn, tom, 6, now=tick, emulators=BOTH)
    choose_emulator(conn, "hbarrel", FBNEO)
    assert add(conn, tom, "Heavy Barrel", 6, now=tick, emulators=BOTH) == (
        ["hbarrel"],
        ["fbneo/hbarrelua"],
    )
    assert on_shelf(conn) == [(FBNEO, "hbarrelua")]


def test_adding_a_game_already_shelved_on_fbneo_changes_nothing(conn):
    heavy_barrel(conn)
    choose_emulator(conn, "hbarrel", FBNEO)
    tom = P(conn, "tom")
    tick = clock()
    build_shelf(conn, tom, 6, now=tick, emulators=BOTH)
    before = history(conn)
    assert add(conn, tom, "Heavy Barrel", 6, now=tick, emulators=BOTH) == ([], [])
    assert history(conn) == before


def test_rotate_retires_an_fbneo_set_by_its_label(conn):
    heavy_barrel(conn, quality_tier=9)
    choose_emulator(conn, "hbarrel", FBNEO)
    tom = P(conn, "tom")
    tick = clock()
    build_shelf(conn, tom, 1, now=tick, emulators=BOTH)
    others(conn, 1)
    assert rotate(conn, tom, 1, now=tick, emulators=BOTH) == (["fbneo/hbarrelua"], ["game00"])


def test_a_game_shelved_as_fbneo_counts_as_recently_shelved(conn):
    heavy_barrel(conn, quality_tier=5)
    add_game(conn, "rival", quality_tier=5, title="Rival")
    choose_emulator(conn, "hbarrel", FBNEO)
    tom = P(conn, "tom")
    tick = clock()
    build_shelf(conn, tom, 1, now=tick, emulators=BOTH)
    assert on_shelf(conn) == [(FBNEO, "hbarrelua")]  # hbarrel before rival, by name
    build_shelf(conn, tom, 1, now=tick, emulators=BOTH)
    assert on_shelf(conn) == [(MAME, "rival")]  # Heavy Barrel was on more recently


# T5: settling a game already on the shelf.


def placed(conn):
    return {(r["emulator"], r["set_name"]): r["placed_at"] for r in current_shelf(conn, "tom")}


def test_settle_moves_a_shelved_game_to_fbneo_once_its_set_exists_keeping_its_place(conn):
    heavy_barrel(conn, fbneo=False)
    tom = P(conn, "tom")
    build_shelf(conn, tom, 6, now=lambda: "2026-01-01T00:00:00+00:00", emulators=BOTH)
    choose_emulator(conn, "hbarrel", FBNEO)
    assert settle_emulators(conn, tom, BOTH, now=clock()) == []  # no FBNeo set yet
    fbneo_set(conn, "hbarrelua")
    moves = settle_emulators(conn, tom, BOTH, now=lambda: "2026-02-02T00:00:00+00:00")
    assert moves == [("hbarrel", "fbneo/hbarrelua")]
    assert placed(conn) == {(FBNEO, "hbarrelua"): "2026-01-01T00:00:00+00:00"}
    assert history(conn)[-2:] == [
        (MAME, "hbarrel", "off", "2026-02-02T00:00:00+00:00"),
        (FBNEO, "hbarrelua", "on", "2026-02-02T00:00:00+00:00"),
    ]


def test_settle_moves_a_game_back_to_mame_when_the_choice_is_removed(conn):
    heavy_barrel(conn)
    choose_emulator(conn, "hbarrel", FBNEO)
    tom = P(conn, "tom")
    build_shelf(conn, tom, 6, now=lambda: "2026-01-01T00:00:00+00:00", emulators=BOTH)
    choose_emulator(conn, "hbarrel", MAME)
    assert settle_emulators(conn, tom, BOTH, now=clock()) == [("fbneo/hbarrelua", "hbarrel")]
    assert placed(conn) == {(MAME, "hbarrel"): "2026-01-01T00:00:00+00:00"}


def test_settle_moves_a_game_back_to_mame_when_the_tv_can_no_longer_show_fbneo(conn):
    heavy_barrel(conn)
    choose_emulator(conn, "hbarrel", FBNEO)
    tom = P(conn, "tom")
    build_shelf(conn, tom, 6, now=clock(), emulators=BOTH)
    settle_emulators(conn, tom, now=clock())
    assert on_shelf(conn) == [(MAME, "hbarrel")]


def test_settle_replaces_an_fbneo_row_whose_set_left_the_library(conn):
    heavy_barrel(conn)
    choose_emulator(conn, "hbarrel", FBNEO)
    tom = P(conn, "tom")
    build_shelf(conn, tom, 6, now=lambda: "2026-01-01T00:00:00+00:00", emulators=BOTH)
    with conn:
        conn.execute("DELETE FROM games WHERE emulator = ?", (FBNEO,))
    assert on_shelf(conn) == []  # hidden from every reader, but still there
    assert raw_shelf(conn) == [(FBNEO, "hbarrelua", "2026-01-01T00:00:00+00:00")]
    settle_emulators(conn, tom, BOTH, now=clock())
    assert raw_shelf(conn) == [(MAME, "hbarrel", "2026-01-01T00:00:00+00:00")]


def test_settle_gives_back_the_version_the_persona_would_be_given(conn):
    add_game(conn, "hbarrel", title="Heavy Barrel", language="Japanese")
    add_game(conn, "hbarrelw", title="Heavy Barrel", family="hbarrel", parent="hbarrel")
    fbneo_set(conn, "hbarrelua")
    choose_emulator(conn, "hbarrel", FBNEO)
    tom = P(conn, "tom")
    build_shelf(conn, tom, 6, now=clock(), emulators=BOTH)
    choose_emulator(conn, "hbarrel", MAME)
    settle_emulators(conn, tom, BOTH, now=clock())
    assert on_shelf(conn) == [(MAME, "hbarrelw")]  # the English one


def test_a_stale_row_for_a_game_nobody_can_play_now_just_goes(conn):
    heavy_barrel(conn)
    choose_emulator(conn, "hbarrel", FBNEO)
    tom = P(conn, "tom")
    build_shelf(conn, tom, 6, now=clock(), emulators=BOTH)
    with conn:
        conn.execute("DELETE FROM games")
    settle_emulators(conn, tom, BOTH, now=clock())
    assert raw_shelf(conn) == []
    assert history(conn)[-1][:3] == (FBNEO, "hbarrelua", "off")


def test_settling_a_settled_shelf_writes_nothing(conn):
    heavy_barrel(conn)
    others(conn, 3)
    choose_emulator(conn, "hbarrel", FBNEO)
    tom = P(conn, "tom")
    build_shelf(conn, tom, 6, now=clock(), emulators=BOTH)
    before = history(conn)
    assert settle_emulators(conn, tom, BOTH, now=clock()) == []
    assert history(conn) == before


def test_settle_changes_only_its_personas_shelf(conn):
    heavy_barrel(conn)
    tom, kids = P(conn, "tom"), P(conn, "kids")
    build_shelf(conn, tom, 6, now=clock(), emulators=BOTH)
    build_shelf(conn, kids, 6, now=clock(), emulators=BOTH)
    choose_emulator(conn, "hbarrel", FBNEO)
    settle_emulators(conn, tom, BOTH, now=clock())
    assert on_shelf(conn, "tom") == [(FBNEO, "hbarrelua")]
    assert on_shelf(conn, "kids") == [(MAME, "hbarrel")]

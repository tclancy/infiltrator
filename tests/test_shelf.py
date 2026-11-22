import itertools

import pytest
from test_personas import add_game

from infiltrator.catalogue import connect
from infiltrator.personas import Persona, save_persona
from infiltrator.shelf import (
    add,
    build_shelf,
    current_shelf,
    demo_shelf,
    drop,
    fill_demo_shelf,
    fill_shelf,
    rotate,
)


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


def test_fill_on_an_empty_shelf_matches_build(conn):
    stock(conn, 12)
    filled = fill_shelf(conn, P(conn, "tom"), 8, now=clock())
    assert sorted(filled) == shelf_names(conn)
    assert len(filled) == 8


def test_fill_never_displaces_a_shelved_game(conn):
    add_game(conn, "meh", quality_tier=1)
    tom = P(conn, "tom")
    build_shelf(conn, tom, 6, now=clock())
    stock(conn, 12)
    fill_shelf(conn, tom, 6, now=clock())
    shelf = shelf_names(conn)
    assert "meh" in shelf and len(shelf) == 6


def test_fill_takes_the_best_new_game_for_a_free_slot(conn):
    stock(conn, 5)
    tom = P(conn, "tom")
    build_shelf(conn, tom, 6, now=clock())
    add_game(conn, "worse", quality_tier=1)
    add_game(conn, "better", quality_tier=9)
    assert fill_shelf(conn, tom, 6, now=clock()) == ["better"]


def test_fill_skips_a_family_already_on_the_shelf(conn):
    add_game(conn, "puckman", title="PuckMan", family="puckman", quality_tier=9)
    tom = P(conn, "tom", language=None)
    build_shelf(conn, tom, 6, now=clock())
    add_game(conn, "pacman", title="Pac-Man", family="puckman", parent="puckman", quality_tier=9)
    assert fill_shelf(conn, tom, 6, now=clock()) == []


def test_fill_on_a_full_shelf_changes_nothing(conn):
    stock(conn, 6)
    tom = P(conn, "tom")
    build_shelf(conn, tom, 6, now=clock())
    add_game(conn, "newcomer", quality_tier=9)
    before = shelf_names(conn)
    assert fill_shelf(conn, tom, 6, now=clock()) == []
    assert shelf_names(conn) == before


def test_demo_shelf_is_only_the_arrivals(conn):
    stock(conn, 8)
    tom = P(conn, "tom")
    build_shelf(conn, tom, 6, now=clock())
    add_game(conn, "fresh", quality_tier=1)
    assert demo_shelf(conn, tom, 6, {"fresh"}, now=clock()) == ["fresh"]
    assert shelf_names(conn) == ["fresh"]


def test_demo_shelf_keeps_the_persona_filters(conn):
    add_game(conn, "fresh")
    add_game(conn, "foreign", language="Japanese")
    assert demo_shelf(conn, P(conn, "tom", language="English"), 6, {"fresh", "foreign"}) == [
        "fresh"
    ]


def test_demo_shelf_is_one_per_family(conn):
    add_game(conn, "puckman", title="PuckMan", family="puckman", quality_tier=9)
    add_game(conn, "pacman", title="Pac-Man", family="puckman", parent="puckman", quality_tier=9)
    tom = P(conn, "tom", language=None)
    assert demo_shelf(conn, tom, 6, {"puckman", "pacman"}) == ["puckman"]


def test_demo_shelf_caps_at_shelf_size_best_first(conn):
    add_game(conn, "meh", quality_tier=3)
    add_game(conn, "good", quality_tier=6)
    add_game(conn, "great", quality_tier=9)
    assert demo_shelf(conn, P(conn, "tom"), 2, {"meh", "good", "great"}) == ["great", "good"]


def test_demo_shelf_goes_in_the_history(conn):
    add_game(conn, "fresh")
    demo_shelf(conn, P(conn, "tom"), 6, {"fresh"})
    rows = conn.execute("SELECT set_name, action FROM shelf_history").fetchall()
    assert [(r["set_name"], r["action"]) for r in rows] == [("fresh", "on")]


def test_demo_shelf_with_no_eligible_arrivals_changes_nothing(conn):
    stock(conn, 3)
    tom = P(conn, "tom")
    build_shelf(conn, tom, 6, now=clock())
    add_game(conn, "foreign", language="Japanese")
    before = shelf_names(conn)
    assert demo_shelf(conn, tom, 6, {"foreign"}) == []
    assert shelf_names(conn) == before


def test_fill_demo_shelf_only_tops_up_with_arrivals(conn):
    add_game(conn, "fresh")
    tom = P(conn, "tom")
    demo_shelf(conn, tom, 6, {"fresh"}, now=clock())
    add_game(conn, "old_but_great", quality_tier=9)
    add_game(conn, "fresher", quality_tier=1)
    assert fill_demo_shelf(conn, tom, 6, {"fresh", "fresher"}, now=clock()) == ["fresher"]
    assert shelf_names(conn) == ["fresh", "fresher"]


def test_demo_shelf_shows_a_new_clone_of_an_old_game(conn):
    add_game(conn, "puckman", title="PuckMan", family="puckman", quality_tier=9)
    add_game(conn, "pacman", title="Pac-Man", family="puckman", parent="puckman", quality_tier=9)
    tom = P(conn, "tom", language=None)
    assert demo_shelf(conn, tom, 6, {"pacman"}) == ["pacman"]


# Requirement 1: drop takes a game off the shelf and records a drop row
def test_a_dropped_game_comes_off_the_shelf(conn):
    stock(conn, 8)
    tom = P(conn, "tom")
    tick = clock()
    build_shelf(conn, tom, 6, now=tick)
    before = shelf_names(conn)
    assert "game00" in before

    drop(conn, tom, "Game00", now=tick)
    after = shelf_names(conn)
    assert "game00" not in after
    assert len(after) == 5


# Requirement 1: drops are recorded in shelf_history as off
def test_drop_records_off_in_shelf_history(conn):
    stock(conn, 8)
    tom = P(conn, "tom")
    tick = clock()
    build_shelf(conn, tom, 6, now=tick)

    drop(conn, tom, "Game00", now=tick)
    rows = conn.execute(
        "SELECT action, set_name FROM shelf_history WHERE set_name = 'game00' ORDER BY at"
    ).fetchall()
    assert [r["action"] for r in rows] == ["on", "off"]


# Requirement 1: drops create a row in shelf_drops
def test_drop_records_to_shelf_drops(conn):
    stock(conn, 8)
    tom = P(conn, "tom")
    tick = clock()
    build_shelf(conn, tom, 6, now=tick)

    drop(conn, tom, "Game00", now=tick)
    rows = conn.execute(
        "SELECT family FROM shelf_drops WHERE persona = ? AND family = ?",
        ("tom", "game00"),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["family"] == "game00"


# Requirement 2: a dropped game stays off through fill, build, and rotate
def test_a_dropped_game_stays_off_through_fill_build_and_rotate(conn):
    stock(conn, 10)
    tom = P(conn, "tom")
    tick = clock()
    build_shelf(conn, tom, 6, now=tick)

    # game00 is highest quality and will return; drop it
    drop(conn, tom, "Game00", now=tick)
    assert "game00" not in shelf_names(conn)
    # Try to bring it back via fill
    fill_shelf(conn, tom, 6, now=tick)
    assert "game00" not in shelf_names(conn)
    # Try to bring it back via build
    build_shelf(conn, tom, 6, now=tick)
    assert "game00" not in shelf_names(conn)
    # Try to bring it back via rotate
    rotate(conn, tom, 6, count=6, now=tick)
    assert "game00" not in shelf_names(conn)


# Requirement 3: add puts a game on the shelf and forgets the drop
def test_add_puts_a_game_on_the_shelf(conn):
    stock(conn, 8)
    tom = P(conn, "tom")
    tick = clock()
    build_shelf(conn, tom, 6, now=tick)

    # Drop a game
    drop(conn, tom, "Game00", now=tick)
    assert "game00" not in shelf_names(conn)
    # Add it back
    add(conn, tom, "Game00", 6, now=tick)
    assert "game00" in shelf_names(conn)


# Requirement 3: add forgets that a game was dropped
def test_add_removes_the_drop_record(conn):
    stock(conn, 8)
    tom = P(conn, "tom")
    tick = clock()
    build_shelf(conn, tom, 6, now=tick)

    drop(conn, tom, "Game00", now=tick)
    rows = conn.execute(
        "SELECT family FROM shelf_drops WHERE persona = ? AND family = ?",
        ("tom", "game00"),
    ).fetchall()
    assert len(rows) == 1
    add(conn, tom, "Game00", 6, now=tick)
    rows = conn.execute(
        "SELECT family FROM shelf_drops WHERE persona = ? AND family = ?",
        ("tom", "game00"),
    ).fetchall()
    assert len(rows) == 0


# Requirement 3: a dropped then added game stays on through fill
def test_a_dropped_then_added_game_stays_on_through_fill(conn):
    stock(conn, 10)
    tom = P(conn, "tom")
    tick = clock()
    build_shelf(conn, tom, 6, now=tick)

    # Drop and add back
    drop(conn, tom, "Game00", now=tick)
    add(conn, tom, "Game00", 6, now=tick)
    before = shelf_names(conn)
    assert "game00" in before
    # fill_shelf shouldn't change anything
    fill_shelf(conn, tom, 6, now=tick)
    assert shelf_names(conn) == before


# Requirement 4: adding to full shelf removes the longest-shelved non-must-have
def test_add_to_full_shelf_removes_longest_shelved(conn):
    stock(conn, 10)
    tom = P(conn, "tom")
    tick = clock()
    build_shelf(conn, tom, 6, now=tick)
    shelf_before = current_shelf(conn, "tom")
    # Find the oldest shelved game that's not a must-have
    oldest = min(shelf_before, key=lambda g: g["placed_at"])

    # Add a new game that's not on the shelf
    add(conn, tom, "Game06", 6, now=tick)
    # oldest should be gone, game06 should be on
    assert "game06" in shelf_names(conn)
    assert oldest["set_name"] not in shelf_names(conn)
    assert len(current_shelf(conn, "tom")) == 6


# Requirement 4: add with must-haves removes oldest non-must-have
def test_add_to_shelf_with_must_haves_respects_them(conn):
    # Create a must-have that's the oldest shelved
    add_game(conn, "fave", title="Fave Game", quality_tier=1)
    stock(conn, 10)
    tom = P(conn, "tom", must_haves=("Fave Game",))
    tick = clock()
    build_shelf(conn, tom, 6, now=tick)
    before = shelf_names(conn)
    assert "fave" in before
    # Find the oldest non-must-have
    shelf_before = current_shelf(conn, "tom")
    non_must_haves = [g for g in shelf_before if g["set_name"] != "fave"]
    oldest_other = min(non_must_haves, key=lambda g: g["placed_at"])

    add(conn, tom, "Game06", 6, now=tick)
    after = shelf_names(conn)
    assert "fave" in after
    assert "game06" in after
    assert oldest_other["set_name"] not in after


# Requirement 5: title is matched case-insensitive
def test_add_matches_title_case_insensitive(conn):
    add_game(conn, "puckman", title="PuckMan", family="puckman", quality_tier=9)
    tom = P(conn, "tom")
    tick = clock()
    build_shelf(conn, tom, 6, now=tick)

    # Even though we ask for lowercase, it should work
    add(conn, tom, "puckman", 6, now=tick)
    assert "puckman" in shelf_names(conn)


# Requirement 5: adding a game with same family swaps versions
def test_add_swaps_versions_of_same_family(conn):
    add_game(conn, "puckman", title="PuckMan", family="puckman", quality_tier=9)
    add_game(conn, "pacman", title="Pac-Man", family="puckman", parent="puckman", quality_tier=9)
    tom = P(conn, "tom", language=None)
    tick = clock()
    build_shelf(conn, tom, 6, now=tick)
    shelf = shelf_names(conn)
    assert "puckman" in shelf
    assert "pacman" not in shelf

    add(conn, tom, "Pac-Man", 6, now=tick)
    shelf_after = shelf_names(conn)
    assert "pacman" in shelf_after
    assert "puckman" not in shelf_after


def test_dropping_a_game_that_is_not_on_the_shelf_still_keeps_it_off(conn):
    stock(conn, 8)
    tom = P(conn, "tom")
    tick = clock()
    build_shelf(conn, tom, 3, now=tick)
    waiting = next(f"game{i:02d}" for i in range(8) if f"game{i:02d}" not in shelf_names(conn))
    before = shelf_names(conn)

    drop(conn, tom, waiting.title(), now=tick)

    assert shelf_names(conn) == before
    rotate(conn, tom, 3, count=3, now=tick)
    build_shelf(conn, tom, 8, now=tick)
    assert waiting not in shelf_names(conn)


def test_drop_takes_off_whichever_version_of_the_game_is_shelved(conn):
    # Two playable versions share a title; the shelved one (the parent) is not first by set name.
    add_game(conn, "zbarrel", title="Barrel")
    add_game(conn, "abarrel", family="zbarrel", parent="zbarrel", title="Barrel")
    tom = P(conn, "tom")
    tick = clock()
    build_shelf(conn, tom, 6, now=tick)
    assert shelf_names(conn) == ["zbarrel"]

    assert drop(conn, tom, "barrel", now=tick) == "Barrel"

    assert shelf_names(conn) == []
    build_shelf(conn, tom, 6, now=tick)
    assert shelf_names(conn) == []


def test_add_picks_the_version_the_persona_would_be_given(conn):
    add_game(conn, "zbarrel", title="Barrel")
    add_game(conn, "abarrel", family="zbarrel", parent="zbarrel", title="Barrel")
    tom = P(conn, "tom")

    assert add(conn, tom, "BARREL", 6, now=clock()) == ([], ["zbarrel"])
    assert shelf_names(conn) == ["zbarrel"]


def test_adding_a_game_that_is_already_shelved_changes_nothing(conn):
    stock(conn, 4)
    tom = P(conn, "tom")
    tick = clock()
    build_shelf(conn, tom, 4, now=tick)
    history = conn.execute("SELECT COUNT(*) FROM shelf_history").fetchone()[0]

    assert add(conn, tom, "Game01", 4, now=tick) == ([], [])

    assert conn.execute("SELECT COUNT(*) FROM shelf_history").fetchone()[0] == history


def test_on_a_shelf_of_nothing_but_must_haves_add_bumps_the_longest_shelved_one(conn):
    # As rotate does: must-haves only stay put while there is something else to retire.
    add_game(conn, "fave", title="Fave")
    add_game(conn, "other", title="Other")
    tom = P(conn, "tom", must_haves=("Fave",))
    tick = clock()
    build_shelf(conn, tom, 1, now=tick)

    assert add(conn, tom, "Other", 1, now=tick) == (["fave"], ["other"])


def test_a_title_nobody_has_is_refused_by_both(conn):
    stock(conn, 2)
    tom = P(conn, "tom")
    for change in (lambda: drop(conn, tom, "Nope"), lambda: add(conn, tom, "Nope", 6)):
        with pytest.raises(LookupError):
            change()
    assert conn.execute("SELECT COUNT(*) FROM shelf_drops").fetchone()[0] == 0


def test_an_fbneo_set_with_a_shelved_sets_name_is_not_mistaken_for_it(conn):
    add_game(conn, "alpha", title="Alpha Blaster")
    add_game(conn, "alpha", emulator="fbneo", title="Alpha Blaster (FBNeo)", quality_tier=9)
    build_shelf(conn, P(conn, "tom"), 6, now=clock())
    shelf = current_shelf(conn, "tom")
    assert [(g["emulator"], g["title"]) for g in shelf] == [("mame2003-plus", "Alpha Blaster")]


def test_shelf_moves_are_recorded_as_mame_2003_plus(conn):
    stock(conn, 2)
    tom = P(conn, "tom")
    tick = clock()
    build_shelf(conn, tom, 6, now=tick)
    drop(conn, tom, "Game00", now=tick)
    found = conn.execute("SELECT emulator, action FROM shelf_history ORDER BY id").fetchall()
    assert [tuple(r) for r in found] == [("mame2003-plus", "on")] * 2 + [("mame2003-plus", "off")]
    shelved = {r["emulator"] for r in conn.execute("SELECT emulator FROM shelf")}
    assert shelved == {"mame2003-plus"}


def test_a_shelf_row_for_another_emulator_is_left_alone_by_a_rebuild(conn):
    stock(conn, 2)
    tom = P(conn, "tom")
    with conn:
        conn.execute(
            "INSERT INTO shelf (persona, emulator, set_name, placed_at) "
            "VALUES ('tom', 'fbneo', 'game00', 'then')"
        )
    build_shelf(conn, tom, 6, now=clock())
    found = conn.execute("SELECT emulator, set_name FROM shelf ORDER BY 1, 2").fetchall()
    assert [tuple(r) for r in found] == [
        ("fbneo", "game00"),
        ("mame2003-plus", "game00"),
        ("mame2003-plus", "game01"),
    ]

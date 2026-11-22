import pytest

from infiltrator.catalogue import connect
from infiltrator.dat import DEFAULT_EMULATOR
from infiltrator.personas import SPINNERS, Persona, eligible, load_persona, save_persona


def add_game(conn, set_name, **cols):
    row = {
        "set_name": set_name,
        "family": cols.pop("family", set_name),
        "title": set_name.title(),
        "is_bios": 0,
        "path": f"{set_name}.zip",
        "language": "English",
        "mature": 0,
        "control": "joy8way",
        "buttons": 1,
        "a11y_one_button": 1,
        "players": "2P alt",
        "synced_at": "now",
        **cols,
    }
    keys = ", ".join(row)
    with conn:
        conn.execute(
            f"INSERT INTO games ({keys}) VALUES ({', '.join('?' * len(row))})", tuple(row.values())
        )


@pytest.fixture
def conn(tmp_path):
    return connect(tmp_path / "c.db")


def names(rows):
    return sorted(r["set_name"] for r in rows)


def test_language_filter_excludes_unknown(conn):
    add_game(conn, "eng")
    add_game(conn, "jpn", language="Japanese")
    add_game(conn, "unknown", language=None)
    assert names(eligible(conn, Persona("tom"))) == ["eng"]


def test_mature_hidden_for_kids(conn):
    add_game(conn, "clean")
    add_game(conn, "racy", mature=1)
    assert names(eligible(conn, Persona("niece"))) == ["clean"]
    assert names(eligible(conn, Persona("tom", mature_ok=True))) == ["clean", "racy"]


def test_must_have_bypasses_mature_and_language(conn):
    add_game(conn, "racy", mature=1, language="Japanese", title="Racy Thing")
    assert names(eligible(conn, Persona("tom", must_haves=("racy thing",)))) == ["racy"]


def test_must_have_never_bypasses_controls(conn):
    add_game(conn, "spinner", control="dial", title="Tempest")
    assert eligible(conn, Persona("tom", must_haves=("Tempest",))) == []
    assert names(eligible(conn, Persona("tom", controls=SPINNERS))) == ["spinner"]


def test_no_control_is_never_eligible(conn):
    add_game(conn, "mahjong", control=None)
    assert eligible(conn, Persona("tom")) == []


def test_one_handed_uses_a11y_flag(conn):
    add_game(conn, "simple")
    add_game(conn, "busy", buttons=3, a11y_one_button=0)
    assert names(eligible(conn, Persona("tom", one_handed=True))) == ["simple"]


def test_together_needs_two_players(conn):
    add_game(conn, "duo")
    add_game(conn, "solo", players="1P")
    assert names(eligible(conn, Persona("party", players="together"))) == ["duo"]


def test_bios_never_eligible(conn):
    add_game(conn, "neogeo", is_bios=1)
    assert eligible(conn, Persona("tom")) == []


def test_round_trip_persona(conn):
    p = Persona(
        "tom",
        language=None,
        mature_ok=True,
        players="solo",
        controls=SPINNERS,
        one_handed=True,
        must_haves=("Congo Bongo", "Zaxxon"),
    )
    save_persona(conn, p)
    assert load_persona(conn, "tom") == p
    save_persona(conn, Persona("tom"))
    assert load_persona(conn, "tom") == Persona("tom")


def test_tuned_game_is_playable_despite_listed_control(conn):
    from infiltrator.catalogue.tuning import set_tuning

    add_game(conn, "hbarrelw", control="dial", title="Heavy Barrel")
    assert eligible(conn, Persona("tom")) == []
    set_tuning(conn, DEFAULT_EMULATOR, "hbarrelw", "sabrina", 'input_libretro_device_p1 = "3"')
    assert names(eligible(conn, Persona("tom"))) == ["hbarrelw"]


def test_tuning_does_not_override_one_handed(conn):
    from infiltrator.catalogue.tuning import set_tuning

    add_game(conn, "hbarrelw", control="dial", buttons=2, a11y_one_button=0)
    set_tuning(conn, DEFAULT_EMULATOR, "hbarrelw", "sabrina", "remap")
    assert eligible(conn, Persona("tom", one_handed=True)) == []


def test_tuning_an_fbneo_set_does_not_make_the_mame_set_of_that_name_playable(conn):
    from infiltrator.catalogue.tuning import set_tuning

    add_game(conn, "hbarrelw", control="dial", title="Heavy Barrel")
    set_tuning(conn, "fbneo", "hbarrelw", "sabrina", "remap")
    assert eligible(conn, Persona("tom")) == []


def test_only_mame_2003_plus_sets_are_eligible_for_now(conn):
    # FBNeo rows carry no language, players or controls yet; the next step decides when
    # an FBNeo set may stand in for its game.
    add_game(conn, "hbarrel", emulator="fbneo", family="hbarrel", title="Heavy Barrel")
    add_game(conn, "hbarrelw", title="Heavy Barrel")
    persona = Persona("tom", language=None, must_haves=("Heavy Barrel",))
    found = eligible(conn, persona)
    assert [(g["emulator"], g["set_name"]) for g in found] == [(DEFAULT_EMULATOR, "hbarrelw")]
    assert eligible(conn, persona, ignore_drops=True) == found

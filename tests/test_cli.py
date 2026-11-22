import os
import time

import pytest
from conftest import chips_for, fbneo_chips_for, make_zip
from typer.testing import CliRunner

from infiltrator import cli
from infiltrator.dat import DEFAULT_EMULATOR

runner = CliRunner()


@pytest.fixture
def home(tmp_path, synthetic_dat, monkeypatch):
    drop, library = tmp_path / "drop", tmp_path / "library"
    drop.mkdir()
    env = {
        "INFILTRATOR_DROP_DIR": str(drop),
        "INFILTRATOR_LIBRARY_DIR": str(library),
        "INFILTRATOR_DB_PATH": str(tmp_path / "c.db"),
        "INFILTRATOR_DAT_PATH": str(synthetic_dat),
        "INFILTRATOR_METADATA_DIR": str(tmp_path / "meta"),
        "INFILTRATOR_SHELF_SIZE": "6",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("infiltrator.config.DEFAULT_CONFIG", tmp_path / "none.toml")
    monkeypatch.setattr(cli, "SETTLE_SECONDS", 0)
    meta = tmp_path / "meta"
    meta.mkdir()
    (meta / "languages.ini").write_text("[English]\nalpha\nalphab\ndelta\nbeta\n")
    return drop


def run(*args, input=None):
    return runner.invoke(cli.app, list(args), input=input)


def test_sieve_prints_titles_not_set_names(home):
    make_zip(home / "foo.zip", chips_for("alphab"))
    result = run("sieve")
    assert result.exit_code == 0, result.output
    assert "New: Alpha Blaster" in result.output
    assert "alphab" not in result.output


def test_sieve_verbose_shows_set_names(home):
    make_zip(home / "foo.zip", chips_for("alpha"))
    assert "[alpha]" in run("sieve", "-v").output


def test_sieve_on_a_busy_drop_folder_is_a_temporary_failure(home):
    (home / "alpha.zip.!qB").write_bytes(b"x")
    result = run("sieve")
    assert result.exit_code == 75
    assert result.output.strip() == "Try again later!"


def test_sieve_on_a_missing_drop_folder_is_a_real_failure(home):
    home.rmdir()
    result = run("sieve")
    assert result.exit_code == 1
    assert result.output.strip() == "Try again later!"


def test_sieve_reports_rar(home):
    (home / "pack.rar").write_bytes(b"Rar!")
    assert "1 .rar file(s)" in run("sieve").output


def test_persona_add_defaults(home):
    result = run("persona", "add", "tom", input="\n\n\n\n\n\n")
    assert result.exit_code == 0, result.output
    from infiltrator.catalogue import connect
    from infiltrator.config import load_settings
    from infiltrator.personas import Persona, load_persona

    assert load_persona(connect(load_settings().db_path), "tom") == Persona("tom", mature_ok=True)


def test_shelf_show_titles_only(home):
    make_zip(home / "alpha.zip", chips_for("alpha"))
    make_zip(home / "delta.zip", chips_for("delta"))
    run("sieve")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    result = run("shelf", "build", "tom")
    assert result.exit_code == 0, result.output
    assert set(result.output.split("\n")) >= {"Alpha Blaster", "Delta"}
    assert "alpha\n" not in result.output


def test_unknown_persona_is_friendly(home):
    result = run("shelf", "show", "nobody")
    assert result.exit_code == 1
    assert "persona add nobody" in result.output


def test_issue_log_by_title(home):
    make_zip(home / "alpha.zip", chips_for("alpha"))
    run("sieve")
    result = run("issue", "log", "alpha blaster", "--device", "sabrina", "--note", "froze")
    assert result.exit_code == 0, result.output
    assert "Alpha Blaster on sabrina: froze" in run("issue", "list").output


def test_two_versions_of_one_game_print_once(home):
    merged = {**chips_for("alpha"), "ab3.bin": chips_for("alphab")["ab3.bin"]}
    make_zip(home / "alpha.zip", merged)
    assert run("sieve").output.count("New: Alpha Blaster") == 1


def test_unexpected_error_is_still_try_again_later(home, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli, "run_sieve", boom)
    result = run("sieve")
    assert result.exit_code == 1
    assert result.output.strip() == "Try again later!"


def test_tune_set_by_title(home):
    make_zip(home / "alpha.zip", chips_for("alpha"))
    run("sieve")
    result = run("tune", "set", "Alpha Blaster", "--device", "sabrina", "--settings", "remap")
    assert result.exit_code == 0, result.output
    from infiltrator.catalogue import connect
    from infiltrator.catalogue.tuning import tuned_sets
    from infiltrator.config import load_settings

    assert tuned_sets(connect(load_settings().db_path), DEFAULT_EMULATOR) == {"alpha"}


@pytest.fixture
def tv(home, tmp_path, monkeypatch):
    """RomM's folders, plus a stand-in for RomM that records refreshes."""
    shelf, bios = tmp_path / "romm-arcade", tmp_path / "romm-bios"
    shelf.mkdir()
    bios.mkdir()
    monkeypatch.setenv("INFILTRATOR_SHELF_DIR", str(shelf))
    monkeypatch.setenv("INFILTRATOR_BIOS_DIR", str(bios))
    refreshed = []

    class FakeClient:
        def refresh_platform(self, slug):
            refreshed.append(slug)

    monkeypatch.setattr("infiltrator.tv.romm_client", lambda settings: FakeClient())
    return shelf, refreshed


def on_tv(shelf):
    return sorted(p.stem for p in shelf.iterdir())


def stock_drop(home, *names):
    for name in names:
        make_zip(home / f"{name}.zip", chips_for(name))
    assert run("sieve").exit_code == 0


def test_play_fills_and_publishes_the_shelf(home, tv):
    shelf, refreshed = tv
    stock_drop(home, "alpha", "delta")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    result = run("play", "tom")
    assert result.exit_code == 0, result.output
    assert on_tv(shelf) == ["alpha", "delta"]
    assert refreshed == ["arcade"]
    assert "Alpha Blaster" in result.output


def test_play_an_unknown_persona_changes_nothing(home, tv):
    shelf, _ = tv
    assert run("play", "nobody").exit_code == 1
    assert on_tv(shelf) == []


def test_sieve_puts_new_games_on_the_tv_shelf(home, tv):
    shelf, _ = tv
    stock_drop(home, "alpha")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    run("play", "tom")
    stock_drop(home, "delta")
    assert on_tv(shelf) == ["alpha", "delta"]


def test_sieve_without_a_tv_persona_publishes_nothing(home, tv):
    shelf, refreshed = tv
    stock_drop(home, "alpha")
    assert on_tv(shelf) == [] and refreshed == []


def test_rotate_of_the_tv_persona_changes_the_tv(home, tv):
    shelf, _ = tv
    stock_drop(home, "alpha", "delta")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    run("play", "tom")
    from infiltrator.catalogue import connect
    from infiltrator.config import load_settings

    conn = connect(load_settings().db_path)
    with conn:
        conn.execute("DELETE FROM shelf WHERE set_name = 'delta'")
    run("shelf", "rotate", "tom")  # alpha has been on longest; delta is the best unshelved
    assert on_tv(shelf) == ["delta"]


def test_shelf_build_for_another_persona_leaves_the_tv_alone(home, tv):
    shelf, _ = tv
    stock_drop(home, "alpha", "delta")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    run("persona", "add", "kids", input="\n\n\n\n\n\n")
    run("play", "tom")
    before = on_tv(shelf)
    for path in shelf.iterdir():
        path.unlink()
    run("shelf", "build", "kids")
    assert on_tv(shelf) == [] and before == ["alpha", "delta"]


def test_a_stranger_in_romms_folder_is_try_again_later(home, tv):
    shelf, _ = tv
    stock_drop(home, "alpha")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    (shelf / "hbarrelw.zip").write_bytes(b"hand placed")
    result = run("play", "tom")
    assert result.exit_code == 1
    assert result.output.strip().endswith("Try again later!")
    assert on_tv(shelf) == ["hbarrelw"]


def test_a_failed_rotate_changes_nothing_so_a_retry_rotates_once(home, tv):
    shelf, _ = tv
    stock_drop(home, "alpha", "delta")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    run("play", "tom")
    from infiltrator.catalogue import connect
    from infiltrator.config import load_settings

    conn = connect(load_settings().db_path)
    before = conn.execute("SELECT COUNT(*) FROM shelf_history").fetchone()[0]
    (shelf / "hbarrelw.zip").write_bytes(b"hand placed")
    result = run("shelf", "rotate", "tom")
    assert result.exit_code == 1 and result.output.strip() == "Try again later!"
    assert conn.execute("SELECT COUNT(*) FROM shelf_history").fetchone()[0] == before


def test_play_with_a_broken_setup_is_try_again_later_and_keeps_the_old_tv(home, tv, tmp_path):
    shelf, _ = tv
    stock_drop(home, "alpha")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    run("persona", "add", "kids", input="\n\n\n\n\n\n")
    run("play", "tom")
    (tmp_path / "dat.xml").unlink()
    result = run("play", "kids")
    assert result.exit_code == 1 and result.output.strip() == "Try again later!"
    from infiltrator.catalogue import connect
    from infiltrator.catalogue.tv import tv_persona
    from infiltrator.config import load_settings

    assert tv_persona(connect(load_settings().db_path)) == "tom"


def test_the_next_sieve_finishes_a_publish_that_failed(home, tv):
    shelf, _ = tv
    stock_drop(home, "alpha")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    run("play", "tom")
    (shelf / "stranger.zip").write_bytes(b"x")
    make_zip(home / "delta.zip", chips_for("delta"))
    assert run("sieve").exit_code == 1
    (shelf / "stranger.zip").unlink()
    assert run("sieve").exit_code == 0
    assert on_tv(shelf) == ["alpha", "delta"]


def test_romm_down_at_a_shell_is_not_an_error(home, tv, monkeypatch):
    shelf, _ = tv
    stock_drop(home, "alpha")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")

    class Down:
        def refresh_platform(self, slug):
            raise OSError("RomM is down")

    monkeypatch.setattr("infiltrator.tv.romm_client", lambda settings: Down())
    result = run("play", "tom")
    assert result.exit_code == 0
    assert "The TV will catch up shortly." in result.output
    assert on_tv(shelf) == ["alpha"]


A_MONTH_AGO = 1_760_270_400  # 2025-10-12, long before any test runs


def stock_library_long_ago(home, *names):
    """Sets that were already in the library before today, as at an upgrade."""
    library = home.parent / "library" / DEFAULT_EMULATOR
    for name in names:
        path = make_zip(library / f"{name}.zip", chips_for(name))
        os.utime(path, (A_MONTH_AGO, A_MONTH_AGO))


def demo_since():
    from infiltrator.catalogue import connect
    from infiltrator.catalogue.tv import demo_since as current
    from infiltrator.config import load_settings

    return current(connect(load_settings().db_path))


def test_play_new_shows_only_recent_arrivals(home, tv):
    shelf, refreshed = tv
    stock_library_long_ago(home, "alpha")
    stock_drop(home, "delta")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    result = run("play", "tom", "--new")
    assert result.exit_code == 0, result.output
    assert on_tv(shelf) == ["delta"]
    assert refreshed == ["arcade"]
    assert "Delta" in result.output and "Alpha" not in result.output
    assert demo_since() is not None


def test_play_new_with_nothing_new_changes_nothing(home, tv):
    shelf, _ = tv
    stock_library_long_ago(home, "alpha")
    run("rescan")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    run("persona", "add", "kids", input="\n\n\n\n\n\n")
    run("play", "kids")
    result = run("play", "tom", "--new")
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "Nothing new for tom in the last 24 hours."
    assert on_tv(shelf) == ["alpha"]
    from infiltrator.catalogue import connect
    from infiltrator.catalogue.tv import tv_persona
    from infiltrator.config import load_settings

    assert tv_persona(connect(load_settings().db_path)) == "kids"


def test_a_sieve_during_a_demo_adds_only_new_arrivals(home, tv):
    shelf, _ = tv
    stock_drop(home, "delta")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    run("play", "tom", "--new")
    stock_library_long_ago(home, "alpha")  # an old set turning up in the library
    assert run("sieve").exit_code == 0
    assert on_tv(shelf) == ["delta"]
    stock_drop(home, "alphab")  # a real new arrival joins the demo
    assert on_tv(shelf) == ["alphab", "delta"]


def test_shelf_build_ends_the_demo(home, tv):
    shelf, _ = tv
    stock_library_long_ago(home, "alpha")
    stock_drop(home, "delta")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    run("play", "tom", "--new")
    run("shelf", "build", "tom")
    assert demo_since() is None
    assert on_tv(shelf) == ["alpha", "delta"]


def test_a_plain_play_ends_the_demo(home, tv):
    stock_drop(home, "delta")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    run("play", "tom", "--new")
    run("play", "tom")
    assert demo_since() is None


def stock_library_hours_ago(home, hours, *names):
    library = home.parent / "library" / DEFAULT_EMULATOR
    when = time.time() - hours * 3600
    for name in names:
        path = make_zip(library / f"{name}.zip", chips_for(name))
        os.utime(path, (when, when))


def test_play_new_days_reaches_further_back(home, tv):
    shelf, _ = tv
    stock_library_hours_ago(home, 70, "alpha")
    run("rescan")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    assert run("play", "tom", "--new").output.strip() == "Nothing new for tom in the last 24 hours."
    result = run("play", "tom", "--new", "--days", "3")
    assert result.exit_code == 0, result.output
    assert on_tv(shelf) == ["alpha"]


def test_play_new_days_refuses_zero(home):
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    assert run("play", "tom", "--new", "--days", "0").exit_code != 0


def test_days_without_new_is_refused(home, tv):
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    result = run("play", "tom", "--days", "2")
    assert result.exit_code != 0
    assert "--new" in result.output


# Requirement 6: drop returns Try again later! for non-existent game
def test_shelf_drop_nonexistent_game_is_try_again_later(home):
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    result = run("shelf", "drop", "tom", "Nonexistent Game")
    assert result.exit_code == 1
    assert result.output.strip() == "Try again later!"


# Requirement 6: drop returns Try again later! for ineligible game
def test_shelf_drop_ineligible_game_is_try_again_later(home):
    make_zip(home / "alpha.zip", chips_for("alpha"))
    run("sieve")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    # Create an ineligible game
    from test_personas import add_game

    from infiltrator.catalogue import connect
    from infiltrator.config import load_settings

    conn = connect(load_settings().db_path)
    add_game(conn, "dial_game", control="dial", title="Dial Game")
    conn.close()
    result = run("shelf", "drop", "tom", "Dial Game")
    assert result.exit_code == 1
    assert result.output.strip() == "Try again later!"


# Requirement 1&6: drop prints the title on success
def test_shelf_drop_prints_title_on_success(home):
    make_zip(home / "alpha.zip", chips_for("alpha"))
    run("sieve")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    run("shelf", "build", "tom")
    result = run("shelf", "drop", "tom", "Alpha Blaster")
    assert result.exit_code == 0, result.output
    assert "Alpha Blaster" in result.output


# Requirement 7: drop for one persona changes no other persona's shelf
def test_shelf_drop_for_one_persona_leaves_others_alone(home):
    make_zip(home / "alpha.zip", chips_for("alpha"))
    run("sieve")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    run("persona", "add", "kids", input="\n\n\n\n\n\n")
    run("shelf", "build", "tom")
    run("shelf", "build", "kids")
    from infiltrator.catalogue import connect
    from infiltrator.config import load_settings

    conn = connect(load_settings().db_path)
    before_kids = sorted(
        r["set_name"] for r in conn.execute("SELECT set_name FROM shelf WHERE persona = 'kids'")
    )
    conn.close()
    run("shelf", "drop", "tom", "Alpha Blaster")
    conn = connect(load_settings().db_path)
    after_kids = sorted(
        r["set_name"] for r in conn.execute("SELECT set_name FROM shelf WHERE persona = 'kids'")
    )
    conn.close()
    assert before_kids == after_kids


# Requirement 8: drop of TV persona changes the TV
def test_shelf_drop_of_tv_persona_changes_the_tv(home, tv):
    shelf, refreshed = tv
    stock_drop(home, "alpha", "delta")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    run("play", "tom")
    assert on_tv(shelf) == ["alpha", "delta"]
    result = run("shelf", "drop", "tom", "Alpha Blaster")
    assert result.exit_code == 0, result.output
    # alpha should be gone from TV
    assert on_tv(shelf) == ["delta"]
    assert "arcade" in refreshed


# Requirement 6: add returns Try again later! for non-existent game
def test_shelf_add_nonexistent_game_is_try_again_later(home):
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    result = run("shelf", "add", "tom", "Nonexistent Game")
    assert result.exit_code == 1
    assert result.output.strip() == "Try again later!"


# Requirement 6: add returns Try again later! for ineligible game
def test_shelf_add_ineligible_game_is_try_again_later(home):
    make_zip(home / "alpha.zip", chips_for("alpha"))
    run("sieve")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    from test_personas import add_game

    from infiltrator.catalogue import connect
    from infiltrator.config import load_settings

    conn = connect(load_settings().db_path)
    add_game(conn, "dial_game", control="dial", title="Dial Game")
    conn.close()
    result = run("shelf", "add", "tom", "Dial Game")
    assert result.exit_code == 1
    assert result.output.strip() == "Try again later!"


# Requirement 3&6: add prints the title on success
def test_shelf_add_prints_title_on_success(home):
    make_zip(home / "alpha.zip", chips_for("alpha"))
    make_zip(home / "delta.zip", chips_for("delta"))
    run("sieve")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    run("shelf", "build", "tom")
    # Drop a game first
    run("shelf", "drop", "tom", "Alpha Blaster")
    result = run("shelf", "add", "tom", "Alpha Blaster")
    assert result.exit_code == 0, result.output
    assert "Alpha Blaster" in result.output


# Requirement 7: add for one persona changes no other persona's shelf
def test_shelf_add_for_one_persona_leaves_others_alone(home):
    make_zip(home / "alpha.zip", chips_for("alpha"))
    make_zip(home / "delta.zip", chips_for("delta"))
    run("sieve")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    run("persona", "add", "kids", input="\n\n\n\n\n\n")
    run("shelf", "build", "tom")
    run("shelf", "build", "kids")
    from infiltrator.catalogue import connect
    from infiltrator.config import load_settings

    conn = connect(load_settings().db_path)
    before_kids = sorted(
        r["set_name"] for r in conn.execute("SELECT set_name FROM shelf WHERE persona = 'kids'")
    )
    conn.close()
    run("shelf", "drop", "tom", "Alpha Blaster")
    run("shelf", "add", "tom", "Alpha Blaster")
    conn = connect(load_settings().db_path)
    after_kids = sorted(
        r["set_name"] for r in conn.execute("SELECT set_name FROM shelf WHERE persona = 'kids'")
    )
    conn.close()
    assert before_kids == after_kids


# Requirement 8: add of TV persona changes the TV
def test_shelf_add_of_tv_persona_changes_the_tv(home, tv):
    shelf, refreshed = tv
    stock_drop(home, "alpha", "delta")
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    run("play", "tom")
    assert on_tv(shelf) == ["alpha", "delta"]
    run("shelf", "drop", "tom", "Alpha Blaster")
    assert on_tv(shelf) == ["delta"]
    result = run("shelf", "add", "tom", "Alpha Blaster")
    assert result.exit_code == 0, result.output
    # alpha should be back on TV
    assert on_tv(shelf) == ["alpha", "delta"]
    assert refreshed.count("arcade") >= 2


def test_a_configured_fbneo_set_list_is_read_by_every_sieve(home, tmp_path, monkeypatch):
    monkeypatch.setenv("INFILTRATOR_FBNEO_DAT_PATH", str(tmp_path / "missing-fbneo.dat"))
    make_zip(home / "alpha.zip", chips_for("alpha"))
    result = run("sieve")
    assert result.exit_code == 1
    assert "missing-fbneo.dat" in str(result.exception)
    assert (home / "alpha.zip").exists()


def flat_library(home, *names):
    """A library as it was before emulators: sets at the top level."""
    library = home.parent / "library"
    return {
        name: make_zip(library / f"{name}.zip", chips_for(name)).stat().st_ino for name in names
    }


@pytest.mark.parametrize(
    "command",
    [("sieve",), ("rescan",), ("play", "tom"), ("play", "tom", "--new"), ("shelf", "build", "tom")],
)
def test_every_library_command_first_moves_an_old_flat_library(home, command):
    inode = flat_library(home, "alpha")["alpha"]
    run("persona", "add", "tom", input="\n\n\n\n\n\n")
    result = run(*command)
    assert result.exit_code == 0, result.output
    library = home.parent / "library"
    assert list(library.glob("*.zip")) == []
    assert (library / DEFAULT_EMULATOR / "alpha.zip").stat().st_ino == inode


def test_a_moved_library_is_not_rebuilt_by_the_sieve(home):
    inode = flat_library(home, "alpha")["alpha"]
    make_zip(home / "alpha.zip", chips_for("alpha"))
    result = run("sieve", "-v")
    assert result.exit_code == 0, result.output
    assert "Nothing new." in result.output
    assert (home.parent / "library" / DEFAULT_EMULATOR / "alpha.zip").stat().st_ino == inode
    assert not (home / "alpha.zip").exists()


def test_a_set_in_both_layouts_stops_the_sieve_before_it_touches_anything(home):
    flat_library(home, "alpha")
    make_zip(home.parent / "library" / DEFAULT_EMULATOR / "alpha.zip", {"a1.bin": b"other"})
    make_zip(home / "delta.zip", chips_for("delta"))
    result = run("sieve", "-v")
    assert result.exit_code == 1
    assert result.output.startswith("Try again later!")
    assert "alpha.zip" in result.output  # --verbose says which
    assert (home / "delta.zip").exists()
    assert not (home.parent / "library" / DEFAULT_EMULATOR / "delta.zip").exists()


def test_a_game_named_by_title_is_its_mame_2003_plus_set(home):
    make_zip(home / "alpha.zip", chips_for("alpha"))
    run("sieve")
    from test_personas import add_game

    from infiltrator.catalogue import connect
    from infiltrator.catalogue.issues import list_issues
    from infiltrator.catalogue.tuning import tuned_sets
    from infiltrator.config import load_settings

    conn = connect(load_settings().db_path)
    add_game(conn, "fbonly", emulator="fbneo", title="Only On FBNeo")
    assert run("issue", "log", "Only On FBNeo", "--device", "s", "--note", "n").exit_code == 1
    assert run("tune", "set", "Only On FBNeo", "--device", "s", "--settings", "x").exit_code == 1
    assert run("issue", "log", "Alpha Blaster", "--device", "s", "--note", "n").exit_code == 0
    assert [(r["emulator"], r["set_name"]) for r in list_issues(conn)] == [
        (DEFAULT_EMULATOR, "alpha")
    ]
    assert tuned_sets(conn, "fbneo") == set()


@pytest.fixture
def with_fbneo(home, disagreeing_fbneo_dat, monkeypatch):
    monkeypatch.setenv("INFILTRATOR_FBNEO_DAT_PATH", str(disagreeing_fbneo_dat))
    return home


def test_with_fbneo_configured_a_mame_zip_is_sieved_as_before(with_fbneo):
    make_zip(with_fbneo / "alpha.zip", chips_for("alpha"))
    result = run("sieve")
    assert result.exit_code == 0, result.output
    assert result.output == "New: Alpha Blaster\n"
    library = with_fbneo.parent / "library"
    assert sorted(p.name for p in library.iterdir()) == [DEFAULT_EMULATOR]
    assert not (with_fbneo / "alpha.zip").exists()


def test_a_zip_only_fbneo_can_use_is_held_and_says_so_only_when_asked(with_fbneo):
    make_zip(with_fbneo / "world.zip", fbneo_chips_for("alpha"))
    assert run("sieve").output == "Nothing new.\n"
    verbose = run("sieve", "-v").output
    assert f"held for fbneo: {with_fbneo / 'world.zip'}" in verbose
    assert (with_fbneo / "world.zip").exists()


def test_fbneo_sets_in_the_library_are_catalogued_but_never_shelved_yet(with_fbneo, tv):
    shelf, _ = tv
    make_zip(with_fbneo.parent / "library" / "fbneo" / "fbonly.zip", fbneo_chips_for("fbonly"))
    stock_drop(with_fbneo, "alpha")
    assert run("rescan").output == "2 games in the library.\n"
    run("persona", "add", "tom", input="any\n\n\n\n\nOnly In FBNeo\n")
    result = run("play", "tom")
    assert result.exit_code == 0, result.output
    assert on_tv(shelf) == ["alpha"]
    assert result.output.strip().splitlines()[-1] == "Alpha Blaster"


# Choosing an emulator per game.


def catalogue():
    from infiltrator.catalogue import connect
    from infiltrator.config import load_settings

    return connect(load_settings().db_path)


def choices():
    rows = catalogue().execute("SELECT family, emulator FROM game_emulators ORDER BY family")
    return [tuple(r) for r in rows]


def tunings():
    rows = catalogue().execute("SELECT emulator, set_name, device, settings FROM control_tuning")
    return sorted(tuple(r) for r in rows)


def tune(title, *extra, settings="remap"):
    return run("tune", "set", title, "--device", "sabrina", "--settings", settings, *extra)


def test_tune_set_with_an_emulator_records_the_choice_for_the_game(with_fbneo):
    stock_drop(with_fbneo, "alpha")
    result = tune("alpha blaster", "--emulator", "fbneo")
    assert result.exit_code == 0, result.output
    assert choices() == [("alpha", "fbneo")]
    assert tunings() == [(DEFAULT_EMULATOR, "alpha", "sabrina", "remap")]


def test_a_clones_choice_is_recorded_for_its_whole_game(with_fbneo):
    stock_drop(with_fbneo, "alphab")
    assert tune("Alpha Blaster", "--emulator", "fbneo").exit_code == 0
    assert choices() == [("alpha", "fbneo")]


def test_tune_set_with_mame_2003_plus_forgets_the_choice(with_fbneo):
    stock_drop(with_fbneo, "alpha")
    tune("Alpha Blaster", "--emulator", "fbneo")
    result = tune("Alpha Blaster", "--emulator", DEFAULT_EMULATOR, settings="plain")
    assert result.exit_code == 0, result.output
    assert choices() == []
    assert tunings() == [(DEFAULT_EMULATOR, "alpha", "sabrina", "plain")]


def test_tune_set_without_an_emulator_leaves_the_choice_alone(with_fbneo):
    stock_drop(with_fbneo, "alpha")
    tune("Alpha Blaster", "--emulator", "fbneo")
    assert tune("Alpha Blaster", settings="again").exit_code == 0
    assert choices() == [("alpha", "fbneo")]


@pytest.mark.parametrize(
    ("emulator", "says"), [("snes9x", "No emulator called snes9x"), ("fbneo", "FBNeo")]
)
def test_an_emulator_that_cannot_run_games_here_changes_nothing(home, emulator, says):
    stock_drop(home, "alpha")  # no FBNeo set list configured
    result = tune("Alpha Blaster", "--emulator", emulator)
    assert result.exit_code == 1
    assert says in result.output and "Saved." not in result.output
    assert choices() == [] and tunings() == []


def test_an_unknown_emulator_is_refused_with_fbneo_configured_too(with_fbneo):
    stock_drop(with_fbneo, "alpha")
    assert tune("Alpha Blaster", "--emulator", "FBNeo").exit_code == 1
    assert choices() == [] and tunings() == []


def test_the_choice_survives_a_rescan(with_fbneo):
    stock_drop(with_fbneo, "alpha")
    tune("Alpha Blaster", "--emulator", "fbneo")
    assert run("rescan").exit_code == 0
    assert choices() == [("alpha", "fbneo")]


@pytest.fixture
def fbneo_home(with_fbneo, fbneo_optional_json, monkeypatch):
    """FBNeo's set list and its optional-ROM list, so alphaua can be built without its PROM."""
    monkeypatch.setenv("INFILTRATOR_FBNEO_OPTIONAL_PATH", str(fbneo_optional_json))
    return with_fbneo


def fbneo_library(home):
    folder = home.parent / "library" / "fbneo"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def choose_directly(family, emulator="fbneo"):
    """The choice alone, as `tune set` records it, without the build that follows it there."""
    from infiltrator.catalogue.emulators import choose_emulator

    choose_emulator(catalogue(), family, emulator)


def test_a_sieve_with_an_empty_drop_folder_builds_a_chosen_games_fbneo_set(fbneo_home):
    stock_drop(fbneo_home, "alpha")
    choose_directly("alpha")
    assert list(fbneo_home.iterdir()) == []
    assert run("sieve").exit_code == 0
    assert fbneo_library(fbneo_home) == ["alphaua.zip"]  # FBNeo's alpha needs a chip nobody has
    found = catalogue().execute("SELECT set_name FROM games WHERE emulator = 'fbneo'").fetchall()
    assert [r["set_name"] for r in found] == ["alphaua"]


def test_a_chosen_games_fbneo_set_comes_with_the_fbneo_bios_it_needs(fbneo_home):
    stock_drop(fbneo_home, "alpha", "biosx", "beta")
    choose_directly("beta")
    assert run("sieve").exit_code == 0
    assert fbneo_library(fbneo_home) == ["betafb.zip", "biosx.zip"]


def test_games_nobody_chose_for_fbneo_get_no_fbneo_set(fbneo_home):
    stock_drop(fbneo_home, "alpha", "biosx", "beta")
    assert run("sieve").exit_code == 0
    assert fbneo_library(fbneo_home) == []


def test_tune_set_to_fbneo_builds_the_set_without_waiting_for_a_sieve(fbneo_home):
    stock_drop(fbneo_home, "alpha")
    left_there = make_zip(fbneo_home / "delta.zip", chips_for("delta"))
    result = tune("Alpha Blaster", "--emulator", "fbneo")
    assert result.exit_code == 0, result.output
    assert result.output == "Saved.\n"
    assert fbneo_library(fbneo_home) == ["alphaua.zip"]
    assert left_there.exists()  # the drop folder is the sieve's alone


def test_tune_set_to_fbneo_says_so_when_no_fbneo_set_can_be_built(fbneo_home):
    stock_drop(fbneo_home, "delta")
    result = tune("Delta", "--emulator", "fbneo")
    assert result.exit_code == 0, result.output
    assert "No fbneo set for it yet" in result.output
    assert choices() == [("delta", "fbneo")]

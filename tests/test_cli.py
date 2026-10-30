import pytest
from conftest import chips_for, make_zip
from typer.testing import CliRunner

from infiltrator import cli

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

    assert tuned_sets(connect(load_settings().db_path)) == {"alpha"}


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

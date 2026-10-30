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


def test_sieve_refusal_prints_try_again_later(home):
    (home / "alpha.zip.!qB").write_bytes(b"x")
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

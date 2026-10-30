import os
from pathlib import Path

import pytest

from infiltrator.publish import PublishError, publish


@pytest.fixture
def tree(tmp_path):
    library, shelf, bios = tmp_path / "library", tmp_path / "shelf", tmp_path / "bios"
    for folder in (library, shelf, bios):
        folder.mkdir()
    for name in ("alpha", "beta", "gamma", "biosx"):
        (library / f"{name}.zip").write_bytes(name.encode())
    return library, shelf, bios


def names(folder):
    return sorted(p.name for p in folder.iterdir())


def same_file(a, b):
    return os.stat(a).st_ino == os.stat(b).st_ino


def test_links_the_shelf_and_its_bios(tree):
    library, shelf, bios = tree
    result = publish(library, shelf, bios, ["alpha", "beta"], ["biosx"])
    assert names(shelf) == ["alpha.zip", "beta.zip"]
    assert names(bios) == ["biosx.zip"]
    assert same_file(shelf / "alpha.zip", library / "alpha.zip")
    assert same_file(bios / "biosx.zip", library / "biosx.zip")
    assert sorted(result.added) == ["alpha", "beta", "biosx"] and result.removed == []


def test_unlinks_games_that_left_the_shelf_but_keeps_the_library(tree):
    library, shelf, bios = tree
    publish(library, shelf, bios, ["alpha", "beta"], ["biosx"])
    result = publish(library, shelf, bios, ["alpha", "gamma"], [])
    assert names(shelf) == ["alpha.zip", "gamma.zip"]
    assert names(bios) == []
    assert result.added == ["gamma"] and result.removed == ["beta", "biosx"]
    assert (library / "beta.zip").exists() and (library / "biosx.zip").exists()


def test_second_run_changes_nothing(tree):
    library, shelf, bios = tree
    publish(library, shelf, bios, ["alpha"], [])
    result = publish(library, shelf, bios, ["alpha"], [])
    assert not result.changed


def test_a_stranger_stops_everything(tree):
    library, shelf, bios = tree
    publish(library, shelf, bios, ["alpha"], [])
    (shelf / "hbarrelw.zip").write_bytes(b"hand placed")
    with pytest.raises(PublishError, match="hbarrelw.zip"):
        publish(library, shelf, bios, ["beta"], [])
    assert names(shelf) == ["alpha.zip", "hbarrelw.zip"]


def test_a_copy_of_a_library_file_is_still_a_stranger(tree):
    library, shelf, bios = tree
    (shelf / "alpha.zip").write_bytes(b"alpha")
    with pytest.raises(PublishError):
        publish(library, shelf, bios, ["alpha"], [])
    assert (shelf / "alpha.zip").read_bytes() == b"alpha"


def test_a_stranger_in_the_bios_folder_stops_the_shelf_too(tree):
    library, shelf, bios = tree
    (bios / "neogeo.zip").write_bytes(b"x")
    with pytest.raises(PublishError):
        publish(library, shelf, bios, ["alpha"], [])
    assert names(shelf) == []


def test_symlinks_and_folders_are_strangers(tree):
    library, shelf, bios = tree
    (shelf / "alpha.zip").symlink_to(library / "alpha.zip")
    with pytest.raises(PublishError):
        publish(library, shelf, bios, ["alpha"], [])
    (shelf / "alpha.zip").unlink()
    (shelf / "sub").mkdir()
    with pytest.raises(PublishError):
        publish(library, shelf, bios, ["alpha"], [])


def test_dotfiles_are_ignored(tree):
    library, shelf, bios = tree
    (shelf / ".DS_Store").write_bytes(b"x")
    publish(library, shelf, bios, ["alpha"], [])
    assert names(shelf) == [".DS_Store", "alpha.zip"]


def test_a_shelf_game_missing_from_the_library_stops_everything(tree):
    library, shelf, bios = tree
    with pytest.raises(PublishError, match="nope"):
        publish(library, shelf, bios, ["alpha", "nope"], [])
    assert names(shelf) == []


def test_missing_folder_is_an_error(tree, tmp_path):
    library, _shelf, bios = tree
    with pytest.raises(PublishError):
        publish(library, tmp_path / "absent", bios, ["alpha"], [])


def test_bios_and_new_games_go_in_before_old_games_come_out(tree, monkeypatch):
    library, shelf, bios = tree
    publish(library, shelf, bios, ["alpha"], [])
    real_link = os.link

    def flaky(src, dst):
        if Path(dst).name == "gamma.zip":
            raise OSError("disk hiccup")
        real_link(src, dst)

    monkeypatch.setattr("infiltrator.publish.os.link", flaky)
    with pytest.raises(OSError):
        publish(library, shelf, bios, ["beta", "gamma"], ["biosx"])
    assert names(bios) == ["biosx.zip"]
    assert names(shelf) == ["alpha.zip", "beta.zip"]


def test_a_link_someone_else_already_made_is_fine(tree, monkeypatch):
    library, shelf, bios = tree
    real_link = os.link

    def racing(src, dst):  # another publisher got there between plan and link
        real_link(src, dst)
        raise FileExistsError(dst)

    monkeypatch.setattr("infiltrator.publish.os.link", racing)
    result = publish(library, shelf, bios, ["alpha"], [])
    assert names(shelf) == ["alpha.zip"] and result.added == []


def test_a_stranger_that_appears_after_the_plan_is_not_deleted(tree, monkeypatch):
    library, shelf, bios = tree
    publish(library, shelf, bios, ["alpha"], [])
    real_link = os.link

    def swap_in_a_stranger(src, dst):
        real_link(src, dst)
        (shelf / "alpha.zip").unlink()
        (shelf / "alpha.zip").write_bytes(b"someone else's")

    monkeypatch.setattr("infiltrator.publish.os.link", swap_in_a_stranger)
    publish(library, shelf, bios, ["beta"], [])
    assert (shelf / "alpha.zip").read_bytes() == b"someone else's"

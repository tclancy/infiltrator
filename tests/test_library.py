import os

import pytest
from conftest import chips_for, make_zip

from infiltrator.dat import DEFAULT_EMULATOR
from infiltrator.library import LibraryLayoutError, move_flat_library, set_path


@pytest.fixture
def flat(tmp_path):
    """A library from before emulators: every set at the top level."""
    library = tmp_path / "library"
    for name in ("alpha", "delta"):
        make_zip(library / f"{name}.zip", chips_for(name))
    return library


def inodes(paths):
    return {p.name: os.stat(p).st_ino for p in paths}


def test_a_flat_library_moves_into_the_mame_folder_keeping_every_inode(flat):
    before = inodes(flat.glob("*.zip"))
    assert move_flat_library(flat) == ["alpha.zip", "delta.zip"]
    assert list(flat.glob("*.zip")) == []
    assert inodes((flat / DEFAULT_EMULATOR).glob("*.zip")) == before


def test_a_hardlink_elsewhere_still_points_at_the_moved_file(flat, tmp_path):
    published = tmp_path / "romm" / "alpha.zip"
    published.parent.mkdir()
    os.link(flat / "alpha.zip", published)
    move_flat_library(flat)
    assert os.path.samefile(published, set_path(flat, DEFAULT_EMULATOR, "alpha"))


def test_moving_twice_changes_nothing_the_second_time(flat):
    move_flat_library(flat)
    after = inodes((flat / DEFAULT_EMULATOR).glob("*.zip"))
    assert move_flat_library(flat) == []
    assert inodes((flat / DEFAULT_EMULATOR).glob("*.zip")) == after


def test_a_set_already_in_its_new_place_is_left_alone(flat):
    target = flat / DEFAULT_EMULATOR
    kept = make_zip(target / "beta.zip", {"b1.bin": b"already moved"})
    before, content = os.stat(kept), kept.read_bytes()
    move_flat_library(flat)
    assert os.stat(kept).st_ino == before.st_ino and kept.read_bytes() == content
    assert sorted(p.name for p in target.iterdir()) == ["alpha.zip", "beta.zip", "delta.zip"]


def test_a_name_in_both_places_stops_the_move_and_overwrites_nothing(flat):
    target = flat / DEFAULT_EMULATOR
    other = make_zip(target / "delta.zip", {"d1.bin": b"a different delta"})
    other_bytes, flat_bytes = other.read_bytes(), (flat / "delta.zip").read_bytes()
    with pytest.raises(LibraryLayoutError, match="delta.zip"):
        move_flat_library(flat)
    assert other.read_bytes() == other_bytes
    assert (flat / "delta.zip").read_bytes() == flat_bytes
    assert (flat / "alpha.zip").exists() and not (target / "alpha.zip").exists()


def test_a_move_cut_short_between_link_and_unlink_is_finished(flat):
    target = flat / DEFAULT_EMULATOR
    target.mkdir()
    os.link(flat / "alpha.zip", target / "alpha.zip")  # the crash came before the unlink
    move_flat_library(flat)
    assert list(flat.glob("*.zip")) == []
    assert sorted(p.name for p in target.iterdir()) == ["alpha.zip", "delta.zip"]


def test_a_missing_or_empty_library_is_fine(tmp_path):
    assert move_flat_library(tmp_path / "absent") == []
    (tmp_path / "empty").mkdir()
    assert move_flat_library(tmp_path / "empty") == []
    assert not (tmp_path / "empty" / DEFAULT_EMULATOR).exists()


def test_leftover_temp_files_are_not_sets_and_stay_put(flat):
    (flat / "alpha.zip.tmp").write_bytes(b"half written")
    move_flat_library(flat)
    assert (flat / "alpha.zip.tmp").exists()

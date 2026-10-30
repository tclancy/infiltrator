from pathlib import Path

import pytest

from infiltrator.safety import (
    DropFolderError,
    active_download_reasons,
    check_drop,
    has_executable_extension,
    has_executable_magic,
    inside,
)


def _no_sleep(_seconds):
    pass


def test_partial_suffix_blocks(tmp_path):
    (tmp_path / "pacman.zip.!qB").write_bytes(b"x")
    assert active_download_reasons(tmp_path, sleep=_no_sleep)


def test_growing_file_blocks(tmp_path):
    growing = tmp_path / "pacman.zip"
    growing.write_bytes(b"x")

    def grow(_seconds):
        with growing.open("ab") as f:
            f.write(b"more")

    assert active_download_reasons(tmp_path, sleep=grow)


def test_quiet_folder_passes(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "pacman.zip").write_bytes(b"x")
    assert active_download_reasons(tmp_path, sleep=_no_sleep) == []


def test_exe_magic_detected(tmp_path):
    sneaky = tmp_path / "pacman.zip"
    sneaky.write_bytes(b"MZ\x90\x00rest")
    assert has_executable_magic(sneaky)


@pytest.mark.parametrize("name", ["setup.exe", "run.BAT", "x.ps1", "game.apk"])
def test_exe_by_extension(tmp_path, name):
    f = tmp_path / name
    f.write_bytes(b"harmless bytes")
    assert has_executable_extension(f)


def test_plain_file_is_not_executable(tmp_path):
    f = tmp_path / "song.mp3"
    f.write_bytes(b"ID3")
    assert not has_executable_extension(f)
    assert not has_executable_magic(f)


def test_symlink_to_outside_is_not_inside(tmp_path):
    drop = tmp_path / "drop"
    drop.mkdir()
    outside = tmp_path / "taxes.pdf"
    outside.write_bytes(b"precious")
    link = drop / "taxes.pdf"
    link.symlink_to(outside)
    assert not inside(drop, link)
    real = drop / "real.zip"
    real.write_bytes(b"x")
    assert inside(drop, real)


def test_symlink_does_not_count_as_activity(tmp_path):
    target = tmp_path / "elsewhere"
    target.write_bytes(b"x")
    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "link.!qB").symlink_to(target)
    assert active_download_reasons(drop, sleep=_no_sleep) == []


def test_check_drop_refuses_home_root_and_library(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    for bad in (Path("/"), Path.home(), library, tmp_path / "missing"):
        with pytest.raises(DropFolderError):
            check_drop(bad, library)


def test_check_drop_refuses_symlinked_folder(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "drop"
    link.symlink_to(real)
    with pytest.raises(DropFolderError):
        check_drop(link, tmp_path / "library")


def test_check_drop_refuses_drop_containing_library(tmp_path):
    drop = tmp_path / "drop"
    (drop / "library").mkdir(parents=True)
    with pytest.raises(DropFolderError):
        check_drop(drop, drop / "library")


def test_check_drop_accepts_plain_folder(tmp_path):
    drop = tmp_path / "drop"
    drop.mkdir()
    check_drop(drop, tmp_path / "library")


def test_check_drop_refuses_db_inside_drop(tmp_path):
    drop = tmp_path / "drop"
    drop.mkdir()
    with pytest.raises(DropFolderError, match="database"):
        check_drop(drop, tmp_path / "library", drop / "c.db")


def test_check_drop_refuses_library_inside_drop_or_drop_inside_library(tmp_path):
    lib = tmp_path / "lib"
    (lib / "drop").mkdir(parents=True)
    with pytest.raises(DropFolderError):
        check_drop(lib / "drop", lib)

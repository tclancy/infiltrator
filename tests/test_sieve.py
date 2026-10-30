import os
import zipfile
from pathlib import Path

import py7zr
import pytest
from conftest import chips_for, make_zip

from infiltrator.config import Settings
from infiltrator.dat import load_dat
from infiltrator.safety import DropFolderError
from infiltrator.sieve import run_sieve


@pytest.fixture
def env(tmp_path, synthetic_dat):
    drop, library = tmp_path / "drop", tmp_path / "library"
    drop.mkdir()
    settings = Settings(
        drop_dir=drop,
        library_dir=library,
        db_path=tmp_path / "c.db",
        dat_path=synthetic_dat,
        metadata_dir=tmp_path / "meta",
    )
    return settings, load_dat(synthetic_dat)


def sieve(env, **kw):
    settings, dat = env
    return run_sieve(settings, dat, settle_seconds=0, sleep=lambda _s: None, **kw)


def members(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as zf:
        return set(zf.namelist())


def drop_files(settings) -> set[str]:
    return {
        str(p.relative_to(settings.drop_dir)) for p in settings.drop_dir.rglob("*") if p.is_file()
    }


def library_sets(settings) -> set[str]:
    return {p.stem for p in settings.library_dir.glob("*.zip")}


def test_clean_parent_is_built_and_source_deleted(env):
    settings, _ = env
    make_zip(settings.drop_dir / "alpha.zip", chips_for("alpha"))
    report = sieve(env)
    assert report.new_games == ["alpha"]
    assert members(settings.library_dir / "alpha.zip") == {"a1.bin", "a2.bin"}
    assert drop_files(settings) == set()


def test_misnamed_zip_is_rebuilt_under_dat_name(env):
    settings, _ = env
    clone = chips_for("alphab")
    make_zip(settings.drop_dir / "foo.zip", clone)
    sieve(env)
    assert "alphab" in library_sets(settings)
    assert members(settings.library_dir / "alphab.zip") == {"a1.bin", "ab2.bin", "ab3.bin"}


def test_merged_zip_yields_parent_and_clone(env):
    settings, _ = env
    merged = {**chips_for("alpha"), "ab3.bin": chips_for("alphab")["ab3.bin"]}
    make_zip(settings.drop_dir / "alpha.zip", merged)
    sieve(env)
    assert library_sets(settings) == {"alpha", "alphab"}


def test_clone_with_chips_in_parent_zip_is_built_nonmerged(env):
    settings, _ = env
    make_zip(settings.drop_dir / "alpha.zip", chips_for("alpha"))
    make_zip(settings.drop_dir / "alphab.zip", {"ab3.bin": chips_for("alphab")["ab3.bin"]})
    sieve(env)
    assert members(settings.library_dir / "alphab.zip") == {"a1.bin", "ab2.bin", "ab3.bin"}


def test_parent_in_library_from_earlier_run_completes_split_clone(env):
    settings, _ = env
    make_zip(settings.drop_dir / "alpha.zip", chips_for("alpha"))
    sieve(env)
    make_zip(settings.drop_dir / "alphab.zip", {"ab3.bin": chips_for("alphab")["ab3.bin"]})
    report = sieve(env)
    assert report.new_games == ["alphab"]


def test_bios_game_needs_bios(env):
    settings, _ = env
    make_zip(settings.drop_dir / "beta.zip", {"b1.bin": chips_for("beta")["b1.bin"]})
    assert sieve(env).new_games == []
    make_zip(settings.drop_dir / "beta.zip", {"b1.bin": chips_for("beta")["b1.bin"]})
    make_zip(settings.drop_dir / "biosx.zip", chips_for("biosx"))
    report = sieve(env)
    assert report.new_games == ["beta"]
    assert report.new_bios == ["biosx"]
    assert members(settings.library_dir / "beta.zip") == {"b1.bin"}
    assert members(settings.library_dir / "biosx.zip") == {"bx-std.bin", "bx-fix.bin"}


def test_clone_reaches_bios_through_parent(env):
    settings, _ = env
    make_zip(settings.drop_dir / "biosx.zip", chips_for("biosx"))
    make_zip(
        settings.drop_dir / "betab.zip",
        {"b1.bin": chips_for("beta")["b1.bin"], "bb2.bin": chips_for("betab")["bb2.bin"]},
    )
    sieve(env)
    assert members(settings.library_dir / "betab.zip") == {"b1.bin", "bb2.bin"}


def test_disk_game_never_built(env):
    settings, _ = env
    make_zip(settings.drop_dir / "gamma.zip", chips_for("gamma"))
    assert sieve(env).new_games == []
    assert drop_files(settings) == set()


def test_crc_only_rom_is_matched(env):
    settings, _ = env
    make_zip(settings.drop_dir / "delta.zip", chips_for("delta"))
    assert sieve(env).new_games == ["delta"]


def test_extra_junk_member_dropped_and_source_deleted(env):
    settings, _ = env
    make_zip(settings.drop_dir / "alpha.zip", {**chips_for("alpha"), "readme.txt": b"hi"})
    sieve(env)
    assert members(settings.library_dir / "alpha.zip") == {"a1.bin", "a2.bin"}
    assert drop_files(settings) == set()


def test_executable_deleted_even_if_unrelated_name(env):
    settings, _ = env
    (settings.drop_dir / "free_games.exe").write_bytes(b"MZ\x90")
    (settings.drop_dir / "song.mp3").write_bytes(b"MZ\x90")  # magic bytes say exe
    sieve(env)
    assert drop_files(settings) == set()


def test_unrelated_file_left_alone(env):
    settings, _ = env
    (settings.drop_dir / "song.mp3").write_bytes(b"ID3 music")
    (settings.drop_dir / "nes").mkdir()
    (settings.drop_dir / "nes" / "alpha.nes").write_bytes(b"NES\x1a")  # set-named, not an archive
    report = sieve(env)
    assert drop_files(settings) == {"song.mp3", "nes/alpha.nes"}
    assert len(report.left_alone) == 2


def test_mp3_named_like_set_is_deleted(env):
    settings, _ = env
    (settings.drop_dir / "alpha.zip").write_bytes(b"ID3 this is really an mp3")
    sieve(env)
    assert drop_files(settings) == set()


def test_truncated_zip_is_deleted_without_crash(env):
    settings, _ = env
    good = make_zip(settings.drop_dir / "alpha.zip", chips_for("alpha"))
    good.write_bytes(good.read_bytes()[:60])
    assert sieve(env).new_games == []
    assert drop_files(settings) == set()


def test_unreadable_zip_not_named_like_set_left_alone(env):
    settings, _ = env
    (settings.drop_dir / "holiday.zip").write_bytes(b"not a zip")
    sieve(env)
    assert drop_files(settings) == {"holiday.zip"}


def test_duplicate_sources_build_once_delete_both(env):
    settings, _ = env
    make_zip(settings.drop_dir / "alpha.zip", chips_for("alpha"))
    make_zip(settings.drop_dir / "copy" / "alpha.zip", chips_for("alpha"))
    assert sieve(env).new_games == ["alpha"]
    assert drop_files(settings) == set()
    assert not (settings.drop_dir / "copy").exists()


def test_write_failure_deletes_nothing(env, monkeypatch):
    settings, _ = env
    make_zip(settings.drop_dir / "alpha.zip", chips_for("alpha"))
    make_zip(settings.drop_dir / "delta.zip", chips_for("delta"))
    real_replace, calls = os.replace, []

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) == 2:
            raise OSError("disk full")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    with pytest.raises(OSError):
        sieve(env)
    assert drop_files(settings) == {"alpha.zip", "delta.zip"}
    assert not list(settings.library_dir.glob("*.tmp"))
    monkeypatch.setattr(os, "replace", real_replace)
    sieve(env)
    assert library_sets(settings) == {"alpha", "delta"}


def test_rerun_is_noop_and_existing_set_not_rewritten(env):
    settings, _ = env
    make_zip(settings.drop_dir / "alpha.zip", chips_for("alpha"))
    sieve(env)
    built = settings.library_dir / "alpha.zip"
    before = built.stat().st_mtime_ns
    make_zip(settings.drop_dir / "alpha.zip", chips_for("alpha"))
    report = sieve(env)
    assert report.new_games == []
    assert built.stat().st_mtime_ns == before
    assert drop_files(settings) == set()


def test_active_download_refuses(env):
    settings, _ = env
    make_zip(settings.drop_dir / "alpha.zip", chips_for("alpha"))
    (settings.drop_dir / "delta.zip.part").write_bytes(b"x")
    with pytest.raises(DropFolderError):
        sieve(env)
    assert "alpha.zip" in drop_files(settings)


def test_7z_and_nested_zip_are_read(env, tmp_path):
    settings, _ = env
    staging = tmp_path / "staging"
    staging.mkdir()
    for name, data in chips_for("alpha").items():
        (staging / name).write_bytes(data)
    with py7zr.SevenZipFile(settings.drop_dir / "pack.7z", "w") as archive:
        for name in chips_for("alpha"):
            archive.write(staging / name, name)
    inner = make_zip(tmp_path / "delta.zip", chips_for("delta"))
    make_zip(settings.drop_dir / "bundle.zip", {"delta.zip": inner.read_bytes()})
    assert sorted(sieve(env).new_games) == ["alpha", "delta"]
    assert drop_files(settings) == set()


def test_archive_with_foreign_nested_archive_left_alone(env, tmp_path):
    settings, _ = env
    nes = make_zip(tmp_path / "nes.zip", {"mario.nes": b"NES\x1a"})
    make_zip(
        settings.drop_dir / "everything.zip",
        {**chips_for("alpha"), "nes.zip": nes.read_bytes()},
    )
    sieve(env)
    assert drop_files(settings) == {"everything.zip"}


def test_rar_left_alone(env):
    settings, _ = env
    (settings.drop_dir / "alpha.rar").write_bytes(b"Rar!\x1a\x07")
    report = sieve(env)
    assert drop_files(settings) == {"alpha.rar"}
    assert report.left_alone == [settings.drop_dir / "alpha.rar"]


def test_symlink_never_followed_or_deleted(env, tmp_path):
    settings, _ = env
    precious = make_zip(tmp_path / "outside" / "alpha.zip", chips_for("alpha"))
    (settings.drop_dir / "alpha.zip").symlink_to(precious)
    sieve(env)
    assert precious.exists()
    assert (settings.drop_dir / "alpha.zip").is_symlink()

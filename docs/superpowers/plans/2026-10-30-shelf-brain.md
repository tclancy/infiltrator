# Shelf Brain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A terminal tool that turns a dropped pile of arcade files into a verified MAME 2003-Plus
library, records it in a SQLite catalogue, and serves each persona a rotating shelf of 6-10 games.

**Architecture:**

- **One pure-Python package, `infiltrator`.**
- **The sieve** pulls every candidate chip out of the drop folder and verifies it by SHA-1
  against the DAT. It rebuilds self-contained ("non-merged") zips into the library, then
  deletes the judged sources.
- **The catalogue** (SQLite, migrated) is rebuilt from the library plus metadata `.ini` files.
  The personas, shelf and sommelier read it.

**Tech Stack:** Python 3.12, uv, Typer (CLI), stdlib `sqlite3` / `zipfile` / `xml.etree`,
py7zr (7z reading), pytest, ruff, pre-commit.

**Spec:** `docs/superpowers/specs/2026-10-30-shelf-brain-design.md`

## Global Constraints

- **Licence:** GPL-3.0-or-later (`LICENSE` already in repo). `pyproject.toml` declares
  `license = "GPL-3.0-or-later"`.
- **No ROM ever committed.** `.gitignore` already blocks `*.rom *.zip *.7z *.chd`. All test
  archives are generated at test time under `tmp_path`.
- **Never bundle AntoPISA's files** (`bestgames.ini`, `catver.ini`, `languages.ini`,
  `renameSET.ini`). The user points `metadata_dir` at their own copy. Tests use tiny
  hand-written ini fixtures in the same format.
- **Deletion happens only inside the configured drop folder,** and never by following a
  symlink.
- **Normal output has no nerd stuff:** no set names, CRCs, merge modes or versions, unless
  `--verbose` is passed. A rejection prints exactly `Try again later!`.
- **UTC** for every timestamp stored or logged. Store ISO-8601 with `+00:00`.
- **Target DAT:** MAME 2003-Plus `metadata/mame2003-plus.xml` (5,715 `<game>` entries, 20 of
  them `runnable="no"` BIOS sets).
- **Shelf size:** a configurable cap of 6 to 10, default 8.

## Decisions this plan makes (builder's calls, beyond the spec)

- **The sieve is pure Python, not Igir.** No Node dependency, it drops straight into RomM's
  Python backend, and all the DAT logic needed fits in a few hundred lines.
- **Match on SHA-1 + size, Old Testament.** CRC32 only narrows candidates. This kills the
  spec's forged-CRC fixture idea, which only worked without SHA-1. **Tests instead use a
  synthetic DAT generated from junk bytes**, so every hash is real and nothing is forged. The
  gate test (Task 10) exercises the real DAT locally.
- **The output is non-merged sets.** Each game zip holds every chip it needs, including chips
  shared with its parent, **except BIOS chips** (`<rom bios=...>`). Those live in the BIOS
  set's own zip. This matches what already works on Tom's TV (`hbarrelw` and `1942b` are
  clones that play standalone).
- **BIOS sets** (`runnable="no"`) are rebuilt like games, flagged `is_bios` and never shown.
  A game with `romof` pointing at a BIOS is complete only if that BIOS zip is in the library.
- **Games with a `<disk>` (CHD) are never built in part 1,** so they are always incomplete.
  CHD files are left alone. Samples are ignored.
- **`nodump` ROMs are not required. `baddump` ROMs must match the hash the DAT lists.**
- **RAR is left alone** (it would need a non-Python `unrar`) and reported in `--verbose`.
- **"Arcade-looking"** (the only things that get judged and deleted):
  - an executable or script, wherever it is, judged by extension or magic bytes;
  - a file or archive whose stem is a DAT set name;
  - an archive containing at least one chip whose SHA-1 is in the DAT;
  - a loose file whose SHA-1 is in the DAT.

  Everything else is untouched.

## File Structure

```
pyproject.toml, .pre-commit-config.yaml, README.md
src/infiltrator/
  __init__.py
  config.py          Settings (paths, shelf size) from env / TOML
  dat.py             parse the DAT -> Dat, Game, Rom; SHA-1 index
  safety.py          drop-folder guard: active-torrent detection, executables, symlinks
  scan.py            walk the drop folder -> Source, each with its Chips
  rebuild.py         chip pool + Dat -> write complete non-merged zips
  sieve.py           orchestrate guard -> scan -> rebuild -> delete -> catalogue sync
  names.py           friendly display names ("Pac-Man", not "Pac-Man (Midway)")
  metadata.py        ini parsers + rename map -> per-set metadata
  catalogue/
    __init__.py      connect(path) -> sqlite3.Connection (migrated)
    migrations/0001_initial.sql
    games.py         sync_games(conn, library, dat, meta)
    issues.py        log_issue / list_issues
  personas.py        Persona dataclass, save/load, eligible()
  shelf.py           build_shelf, rotate, history
  cli.py             Typer app
tests/
  conftest.py        synthetic DAT + archive factories
  test_*.py          one per module
scripts/gate.py      local-only gate run against Tom's eight real games (never in CI)
```

## Review Focus

1. **Two sources carry the same chip** (a duplicate zip, or a merged zip plus a split one):
   it's used once, the set is built once, and both sources are deleted. Test in Task 4.
2. **A file named like a set that isn't an archive at all** (an mp3 called `pacman.zip`,
   or a truncated zip): it's judged, deleted, and nothing crashes. Test in Task 4.
3. **An interrupted run:** sources are deleted only after every rebuilt zip has been
   atomically renamed into place, so a crash mid-run loses nothing and a rerun finishes the
   job. Test in Task 4 (simulated failure in the write step).
4. **The library already holds the set:** nothing is rewritten, the duplicate source is still
   deleted, and a rerun is a no-op. Test in Task 4.
5. **A symlink in the drop folder pointing outside it:** never followed and never deleted
   through. Only the link itself may be removed, and only if it is a link to an executable.
   Test in Task 3.

---

### Task 1: Project skeleton, config, DAT parser

**Files:**
- Create: `pyproject.toml`, `.pre-commit-config.yaml`, `README.md`,
  `src/infiltrator/__init__.py`, `src/infiltrator/config.py`, `src/infiltrator/dat.py`
- Create: `tests/conftest.py`, `tests/test_dat.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `Rom(name: str, size: int, crc: str, sha1: str | None, merge: str | None, bios: str | None, status: str)`, a frozen dataclass.
  - `Game(name, description, year, manufacturer, cloneof, romof, is_bios: bool, roms: tuple[Rom, ...], has_disk: bool, players: int | None, control: str | None, buttons: int | None)`.
  - `Dat(games: dict[str, Game])` with:
    - `by_sha1(sha1) -> list[tuple[Game, Rom]]`;
    - `required_roms(game) -> tuple[Rom, ...]`, which excludes `nodump` and BIOS roms.
  - `load_dat(path: Path) -> Dat`.
  - `Settings(drop_dir, library_dir, db_path, dat_path, metadata_dir, shelf_size=8)` and
    `load_settings(env=os.environ, config_file: Path | None = None) -> Settings`.
    - Env vars are `INFILTRATOR_DROP_DIR` etc.
    - The TOML default is `~/.config/infiltrator/config.toml`.
    - `shelf_size` outside 6-10 raises `ValueError`.
  - **conftest fixtures:**
    - `synthetic_dat(tmp_path) -> Path`: an XML in the real DAT's shape, containing:
      - `alpha`, a parent with 3 roms, one of them `nodump`;
      - `alphab`, a clone of alpha that shares 2 roms via `merge` and adds 1 of its own;
      - `biosx`, `runnable="no"`, with 1 rom;
      - `beta`, `romof="biosx"`, with 1 own rom and 1 rom with a `bios` attribute;
      - `gamma`, with a `<disk>`.

      Each rom's bytes are `hashlib.sha256(name).digest()` repeated to its size, so the hashes
      are real.
    - `chip_bytes(set_name, rom_name) -> bytes`.
    - `make_zip(path, {member: bytes})`.

- [ ] **Step 1:** Write `pyproject.toml`:
  - uv, src layout, script `infiltrator = "infiltrator.cli:app"`;
  - dependencies `typer`, `py7zr`; dev dependencies `pytest`, `ruff`;
  - plus `.pre-commit-config.yaml` (ruff, ruff-format, trailing-whitespace,
    end-of-file-fixer).

  Run `uv sync`. Expected: it resolves.
- [ ] **Step 2: Failing tests in `tests/test_dat.py`:**
  - `test_parses_games_and_flags`: `alphab.cloneof == "alpha"`, `biosx.is_bios`,
    `gamma.has_disk`, and `alpha.control`/`players`/`buttons` read from `<input>`.
  - `test_required_roms_skip_nodump_and_bios`: `required_roms(alpha)` has 2 roms and
    `required_roms(beta)` has 1.
  - `test_by_sha1_finds_shared_chip_in_parent_and_clone`: it returns 2 hits.
  - `test_loads_real_dat_if_present`: skipped unless `INFILTRATOR_REAL_DAT` is set; asserts
    5,715 games and 20 `is_bios`.
- [ ] **Step 3:** Failing tests in `tests/test_config.py`: env overrides TOML, and
  `shelf_size=11` raises.
- [ ] **Step 4:** Implement `dat.py`, using `xml.etree.ElementTree.iterparse`. The DOCTYPE is
  internal and harmless; don't resolve external entities. Implement `config.py` with
  `tomllib`.
- [ ] **Step 5:** `uv run pytest -q` passes, and `INFILTRATOR_REAL_DAT=~/Documents/work/mame2003-plus-libretro/metadata/mame2003-plus.xml uv run pytest -q tests/test_dat.py` passes. Then `uv run pre-commit run -a`.
- [ ] **Step 6:** Commit with `feat: project skeleton, settings and DAT parser`.

### Task 2: Catalogue database with migrations

**Files:**
- Create: `src/infiltrator/catalogue/__init__.py`, `catalogue/migrations/0001_initial.sql`,
  `catalogue/issues.py`, `tests/test_catalogue.py`

**Interfaces:**
- Produces:
  - `connect(db_path: Path) -> sqlite3.Connection`. It applies the numbered
    `migrations/*.sql` files above `PRAGMA user_version`, each in its own transaction, then
    sets `user_version`. `foreign_keys=ON`, and `row_factory=sqlite3.Row`.
  - `log_issue(conn, set_name, device: str, note: str) -> int`.
  - `list_issues(conn, set_name=None) -> list[sqlite3.Row]`.
- **Schema in `0001_initial.sql`:**
  - `games(set_name TEXT PRIMARY KEY, platform TEXT NOT NULL DEFAULT 'arcade', parent TEXT, description TEXT, title TEXT, year TEXT, manufacturer TEXT, is_bios INTEGER NOT NULL, path TEXT NOT NULL, language TEXT, mature INTEGER, genre TEXT, players TEXT, control TEXT, buttons INTEGER, quality_tier INTEGER, a11y_one_button INTEGER, a11y_stick_only INTEGER, synced_at TEXT NOT NULL)`.
  - `personas(name TEXT PRIMARY KEY, data TEXT NOT NULL)`, where `data` is JSON.
  - `must_haves(persona TEXT REFERENCES personas ON DELETE CASCADE, title TEXT, PRIMARY KEY(persona,title))`.
  - `shelf(persona TEXT REFERENCES personas ON DELETE CASCADE, set_name TEXT, placed_at TEXT, PRIMARY KEY(persona,set_name))`.
  - `shelf_history(id INTEGER PRIMARY KEY, persona TEXT, set_name TEXT, action TEXT CHECK(action IN ('on','off')), at TEXT)`.
  - `issues(id INTEGER PRIMARY KEY, set_name TEXT, device TEXT, note TEXT, at TEXT)`.
  - `control_tuning(set_name TEXT, device TEXT, settings TEXT NOT NULL, updated_at TEXT, PRIMARY KEY(set_name, device))`.
  - No foreign key from `issues`, `shelf_history` or `control_tuning` to `games`: human data
    survives a game disappearing on re-scan (spec: never regenerated).

- [ ] **Step 1: Failing tests:**
  - `test_fresh_db_migrates_to_latest`: `user_version == 1`, and all 7 tables exist.
  - `test_connect_twice_is_idempotent`.
  - `test_issue_survives_game_row_deletion`.
  - `test_timestamps_are_utc`: `at` ends with `+00:00`.
- [ ] **Step 2:** Implement, with migrations found via `importlib.resources`.
- [ ] **Step 3:** `uv run pytest -q` passes, and so does pre-commit.
- [ ] **Step 4:** Commit with `feat: SQLite catalogue with migrations and issue log`.

### Task 3: Drop-folder safety

**Files:** Create `src/infiltrator/safety.py`, `tests/test_safety.py`

**Interfaces:**
- Produces:
  - `active_download_reasons(drop: Path, settle_seconds: float = 5.0, sleep=time.sleep) -> list[str]`.
    - It returns non-empty if any file has an in-progress suffix (`.!qB`, `.part`, `.!ut`,
      `.crdownload`, `.aria2`, `.tmp`), or if any file's size or mtime changes across two
      snapshots `settle_seconds` apart.
    - `sleep` is injected for tests.
  - `is_executable(path: Path) -> bool`. True for the 18 extensions `exe scr lnk bat cmd pif msi msix vbs vbe jse wsf wsh hta ps1 reg jar apk`, or for content starting with `MZ`, `\x7fELF` or `#!`.
  - `inside(drop: Path, path: Path) -> bool`. True only if `path` is not a symlink and its
    resolved path is under `drop.resolve()`.
  - `DropFolderError(Exception)`, raised by `check_drop(drop)` if `drop` is missing, is a
    symlink, or is `/`, `~`, or the library dir.

- [ ] **Step 1: Failing tests:**
  - `test_partial_suffix_blocks`.
  - `test_growing_file_blocks`: the injected sleep appends bytes.
  - `test_quiet_folder_passes`.
  - `test_exe_by_magic_even_when_named_zip`.
  - `test_symlink_to_outside_is_not_inside` (Review Focus 5).
  - `test_check_drop_refuses_home_root_and_library`.
- [ ] **Step 2:** Implement.
- [ ] **Step 3:** Tests and pre-commit pass. Commit with `feat: drop-folder guard`.

### Task 4: Scan, rebuild, sieve

**Files:**
- Create: `src/infiltrator/scan.py`, `rebuild.py`, `sieve.py`,
  `tests/test_scan.py`, `tests/test_sieve.py`

**Interfaces:**
- Consumes: `Dat`, `load_dat` (Task 1); `safety.*` (Task 3).
- Produces:
  - `Chip(sha1: str, size: int, read: Callable[[], bytes])`.
  - `Source(path: Path, kind: Literal["zip","7z","loose","executable","unreadable","rar","other"], chips: list[Chip])`.
  - `scan(drop: Path, dat: Dat) -> list[Source]`.
    - It walks without following symlinks.
    - It opens zip and 7z archives, plus zips nested one level inside them, and hashes every
      member.
    - A `.zip`/`.7z` that fails to open is `unreadable`.
  - `is_judged(source, dat) -> bool`, which implements the plan's "arcade-looking" rule.
  - `RebuildResult(built: list[str], already_present: list[str])`.
  - `rebuild(pool: dict[str, Chip], dat: Dat, library: Path) -> RebuildResult`.
    - For every runnable or BIOS game whose `required_roms` are all in the pool (and, for
      `romof`-BIOS games, whose BIOS zip is in the library or built this run; BIOS first):
      write `library/<set>.zip` via `<set>.zip.tmp` then `os.replace`.
    - Each member is named by its DAT rom name.
    - Skip games with `has_disk`.
    - Skip if `library/<set>.zip` exists and every required rom in it verifies by SHA-1.
  - `SieveReport(new_games: list[str], deleted: list[Path], left_alone: list[Path])`.
  - `run_sieve(settings, dat, conn, *, verbose=False) -> SieveReport`.
    - `check_drop`, then `active_download_reasons` (raises `DropFolderError` if active).
    - Then `scan`; build the pool from judged sources; `rebuild`.
    - **Only then** delete every judged source (unlink files, never through a symlink;
      `rmtree` only for directories that end up empty).
    - Then `sync_games` (Task 6; until then, a no-op hook). The **first** version of
      `run_sieve` takes an optional `on_library_changed: Callable[[], None] | None`, and
      Task 6 wires `sync_games` into it.

- [ ] **Step 1: Failing tests in `tests/test_sieve.py`.** Use `synthetic_dat` plus
  `make_zip`; `drop`/`library` are `tmp_path` subdirs.
  - `test_clean_parent_is_built_and_source_deleted`.
  - `test_misnamed_zip_is_rebuilt_under_dat_name`: `1942.zip`-style, i.e. `foo.zip` holding
    `alphab`'s chips plus alpha's shared chips becomes `alphab.zip`.
  - `test_merged_zip_yields_parent_and_clone`.
  - `test_clone_with_chips_in_parent_zip_is_built_nonmerged`: `alphab.zip` contains all 3 of
    its chips.
  - `test_bios_game_needs_bios`: `beta` without `biosx` is not built; with both, both are
    built, and `beta.zip` contains no BIOS chip.
  - `test_disk_game_never_built`.
  - `test_extra_junk_member_dropped_and_source_deleted`.
  - `test_executable_deleted_even_if_unrelated_name`.
  - `test_unrelated_file_left_alone`: `song.mp3` and `mario.nes` remain.
  - `test_mp3_named_like_set_is_deleted` (Review Focus 2).
  - `test_truncated_zip_is_deleted_without_crash` (Review Focus 2).
  - `test_duplicate_sources_build_once_delete_both` (Review Focus 1).
  - `test_write_failure_deletes_nothing` (Review Focus 3): monkeypatch `os.replace` to raise
    on the 2nd call. Assert every source still exists and no `.tmp` is left behind.
  - `test_rerun_is_noop_and_existing_set_not_rewritten` (Review Focus 4): the mtime is
    unchanged.
  - `test_active_download_refuses`.
  - `test_7z_and_nested_zip_are_read` (create the 7z with `py7zr`).
  - `test_rar_left_alone`.
- [ ] **Step 2:** Run them and watch them fail.
- [ ] **Step 3:** Implement `scan.py`, then `rebuild.py`, then `sieve.py`.
  - Zips are written with `zipfile.ZIP_DEFLATED` and members sorted by name.
  - **Every member is re-verified by SHA-1 after writing** (read back) **before** the
    `os.replace`.
- [ ] **Step 4:** Tests and pre-commit pass. Commit with
  `feat: sieve rebuilds verified non-merged sets and deletes judged sources`.

### Task 5: Metadata from the progettoSNAPS/nplayers ini files

**Files:** Create `src/infiltrator/metadata.py`, `src/infiltrator/names.py`,
`tests/test_metadata.py`, `tests/test_names.py`, `tests/fixtures/metadata/*.ini`
(hand-written, a few lines each, in the real formats below).

**Real formats** (verified 2026-10-29 against the 0.288 pack and nplayers 0.278):

- **`catver.ini`:** under `[Category]`, lines of the form `name=Genre / Sub` with an optional
  ` * Mature *` suffix.
- **`languages.ini`:** `[Language]` sections with bare set names as lines.
- **`bestgames.ini`:** sections like `[90 to 100 (Best Games)]`, ten of them; the tier is the
  lower bound divided by 10, so 0-9. Bare names.
- **`nplayers.ini`:** under `[NPlayers]`, values like `1P`, `2P alt`, `2P sim`,
  `4P alt / 2P sim`, `Device`, `Non-arcade` or `???`.
- **`renameSET.ini`:** `[0.NNN]` version sections, with lines of the form
  `Ren_NNN=old   > new` (whitespace varies).
- All of them have `[FOLDER_SETTINGS]` and `[ROOT_FOLDER]` sections and `;;` comments, which
  are ignored.
- They are **not** stdlib-`configparser` safe (bare keys, duplicate sections), so hand-parse
  them.

**Interfaces:**
- Produces:
  - `SetMeta(language: str | None, mature: bool | None, genre: str | None, players: str | None, quality_tier: int | None)`.
  - `load_metadata(metadata_dir: Path, dat: Dat) -> dict[str, SetMeta]`.
    - Files are optional; a missing file means those fields are `None`.
    - Lookup order for a 2003-Plus set name:
      1. the exact name;
      2. the rename-mapped name;
      3. the parent's resolved entry, for `genre`, `mature`, `players` and `quality_tier`.
         bestgames lists parents only, by design. **Never** for `language`, because clones
         differ by region.
  - The rename map comes from chaining every `old > new` in ascending version order.
    **Guard:** discard a mapping whose final target is itself a set name in the 2003-Plus DAT
    (name reuse, e.g. `yard`), so a reused name is never trusted.
  - `title(description: str) -> str` in `names.py`. It strips every trailing parenthetical
    group and whitespace: `"Pac-Man (Midway)" -> "Pac-Man"`,
    `"1942 (set 2)" -> "1942"`, `"Burger Time (Midway)" -> "Burger Time"`.

- [ ] **Step 1: Failing tests:**
  - `test_mature_flag_and_genre`.
  - `test_language_section`.
  - `test_bestgames_tier`: a name under `[90 to 100 ...]` gets tier 9.
  - `test_clone_inherits_tier_and_genre_not_language`.
  - `test_rename_chain_resolves`: `a > b` in 0.100 and `b > c` in 0.200 means `a` maps to `c`.
  - `test_rename_to_existing_dat_name_is_discarded`.
  - `test_missing_files_give_none`.
  - `test_title_strips_parentheticals`.
- [ ] **Step 2:** Implement.
- [ ] **Step 3:** Tests and pre-commit pass. Commit with `feat: persona metadata from ini files`.

### Task 6: Game catalogue sync

**Files:** Create `src/infiltrator/catalogue/games.py`, `tests/test_catalogue_games.py`;
modify `sieve.py` to call it.

**Interfaces:**
- Consumes: `connect` (Task 2), `Dat` (Task 1), `load_metadata`/`title` (Task 5).
- Produces: `sync_games(conn, library: Path, dat: Dat, meta: dict[str, SetMeta]) -> int`.
  - It re-verifies each `library/*.zip` against the DAT (by SHA-1). Any that fails is
    **not** catalogued, and the CLI reports it in `--verbose` (the sieve never wrote it, so a
    human put it there).
  - It upserts `games`, deletes `games` rows whose file is gone, and returns the number of
    rows.
  - `a11y_one_button = control.startswith("joy") and buttons <= 1`.
  - `a11y_stick_only = control.startswith("joy") and buttons == 0`.
  - `players` stores the nplayers string when known, otherwise `f"{players}P"` from the DAT.

- [ ] **Step 1: Failing tests:**
  - `test_sync_inserts_rows_with_title_and_meta`.
  - `test_removed_file_removes_game_row_but_keeps_issue`.
  - `test_a11y_flags_from_dat_input`.
  - `test_unverified_zip_not_catalogued`.
  - `test_sieve_end_to_end_populates_games`.
- [ ] **Step 2:** Implement, and wire it into `run_sieve`.
- [ ] **Step 3:** Tests and pre-commit pass. Commit with `feat: catalogue syncs from the verified library`.

### Task 7: Personas

**Files:** Create `src/infiltrator/personas.py`, `tests/test_personas.py`

**Interfaces:**
- Produces:
  - `Persona(name: str, language: str | None = "English", max_age_mature_ok: bool = False, players: Literal["solo","together","any"] = "any", controls: frozenset[str] = frozenset({"joy4way","joy8way","joy2way"}), max_buttons: int | None = None, one_handed: bool = False, must_haves: tuple[str, ...] = ())`.
    - `must_haves` holds game **titles** as typed, matched case-insensitively against
      `games.title`.
    - The age question maps to `max_age_mature_ok`, true only for adults.
  - `save_persona(conn, p)`, `load_persona(conn, name) -> Persona`, `list_personas(conn) -> list[str]`.
  - `eligible(conn, p) -> list[sqlite3.Row]`. Non-BIOS games where all of these hold:
    - `control` is in `controls`;
    - `buttons <= max_buttons` when one is set;
    - if `one_handed`, `a11y_one_button` is true;
    - if `players == "together"`, `players` contains `sim` or `alt`, or starts with a digit
      `>= 2`;
    - unless the title is a must-have: `language` matches (an unknown language is excluded)
      **and** (`mature` is not 1 or `max_age_mature_ok`).

    Must-haves bypass language and mature but **never** controls or one-handed (spec).

- [ ] **Step 1: Failing tests:**
  - `test_language_filter_excludes_unknown`.
  - `test_mature_hidden_for_kids`.
  - `test_must_have_bypasses_mature_and_language`.
  - `test_must_have_never_bypasses_controls`.
  - `test_one_handed_uses_a11y_flag`.
  - `test_round_trip_persona`.
- [ ] **Step 2:** Implement.
- [ ] **Step 3:** Tests and pre-commit pass. Commit with `feat: personas and eligibility`.

### Task 8: Shelf and sommelier

**Files:** Create `src/infiltrator/shelf.py`, `tests/test_shelf.py`

**Interfaces:**
- Consumes: `eligible`, `Persona` (Task 7).
- Produces:
  - `pick_one_per_title(rows, p) -> list[Row]`. Group by `title`. Within a group, prefer:
    1. a set whose title is a must-have;
    2. otherwise the parent (`parent IS NULL`);
    3. otherwise the clone whose `language` matches.

    Ties go to the lower `set_name`.
  - `build_shelf(conn, p, size: int, now=utcnow) -> list[str]`.
    - Fill it with must-haves first. If there are more must-haves than `size`, take the ones
      shelved least recently.
    - Then rank the rest by `quality_tier DESC NULLS LAST`, then by least-recently-shelved
      (from `shelf_history`), then by `set_name`.
    - Replace the `shelf` rows and write the `on`/`off` history.
  - `rotate(conn, p, size, count: int = 1, now=utcnow) -> tuple[list[str], list[str]]`
    returns (removed, added).
    - It removes the `count` longest-shelved games. Must-haves are removed only when there
      are more of them than `size`.
    - It adds the same number of best-ranked eligible games that aren't currently shelved,
      using `build_shelf`'s ranking.
  - `current_shelf(conn, persona) -> list[Row]`.

- [ ] **Step 1: Failing tests:**
  - `test_shelf_respects_size_cap`.
  - `test_one_version_per_game_parent_preferred`.
  - `test_named_clone_wins_when_must_have`.
  - `test_must_haves_first_and_rotate_when_over_cap`.
  - `test_rotate_swaps_oldest_for_best_unshelved`.
  - `test_history_records_on_and_off_in_utc`.
- [ ] **Step 2:** Implement.
- [ ] **Step 3:** Tests and pre-commit pass. Commit with `feat: shelf builder and sommelier rotation`.

### Task 9: CLI

**Files:** Create `src/infiltrator/cli.py`, `tests/test_cli.py`; extend `README.md`.

**Interfaces:**
- Consumes everything above. Commands, via Typer's `CliRunner` in tests:
  - **`infiltrator sieve [--verbose]`.** On success it prints one line per new game title
    (`New: Pac-Man`), or `Nothing new.`. On `DropFolderError` it prints exactly
    `Try again later!` and exits 1. `--verbose` adds set names, deletions and the
    left-alone list.
  - **`infiltrator rescan`**: re-syncs the catalogue from the library.
  - **`infiltrator persona add NAME`**: interactive questions (language, "Is anyone playing
    under 18?", solo/together/any, one-handed?, must-haves as comma-separated titles).
    Defaults: English, no, any, no, none. Also `persona list`.
  - **`infiltrator shelf show PERSONA`**: titles only. `shelf build PERSONA`, and
    `shelf rotate PERSONA [--count N]` which prints `Out: X` / `In: Y`.
  - **`infiltrator issue log TITLE --device D --note N`** (resolves the title to a set; if it
    matches more than one, the shelf's set wins), and `issue list`.
- `--verbose` is the only way to see set names.

- [ ] **Step 1: Failing tests:**
  - `test_sieve_prints_titles_not_set_names`.
  - `test_sieve_refusal_prints_try_again_later`.
  - `test_persona_add_defaults`.
  - `test_shelf_show_titles_only`.
  - `test_issue_log_by_title`.
- [ ] **Step 2:** Implement. The README gets setup (config TOML example, `metadata_dir`
  sourcing note: "download the progettoSNAPS and nplayers packs yourself") and the commands.
- [ ] **Step 3:** Tests and pre-commit pass. Commit with `feat: infiltrator CLI`.

### Task 10: The gate (local only)

**Files:** Create `scripts/gate.py`. It is not collected by pytest.

**Behaviour:**

- Make a temp drop and library under `$TMPDIR`. **Never** point at the real RomM library.
- Fetch Tom's eight real zips **by copying**: `scp homelab:/mnt/samsungusb/games/romm/library/roms/arcade/{hbarrelw,congo,zaxxon,btimem,popeye,tapper,gauntlet,1942b}.zip`, using `ssh -i ~/.ssh/id_claude -o IdentitiesOnly=yes tom@192.168.68.67`.
- Rename `1942b.zip` to `1942.zip` in the drop folder.
- Add a fake `setup.exe`, plus a `notes.mp3` and a `mario.nes` that must survive.
- Run `run_sieve` with the real DAT.
- **Assert:**
  - the library contains exactly those 8 sets as `<set>.zip`;
  - the drop folder contains only `notes.mp3` and `mario.nes`;
  - the catalogue has 8 rows with non-empty titles.
- Print PASS/FAIL. Afterwards, delete the temp dirs.

- [ ] **Step 1:** Write the script.
- [ ] **Step 2:** Run `uv run python scripts/gate.py`. Expected: `PASS`. If a set fails,
  investigate with `--verbose` rather than loosening anything.
  - These sets are known to verify against the 2003-Plus DAT (checked by hand 2026-10-28).
  - Note the non-merged expectation: if a real zip lacks parent-shared chips (it shouldn't,
    since they play standalone), that's a finding to report, not a fix to make.
- [ ] **Step 3:** Commit with `test: local gate against the eight real games`.
- [ ] **Step 4:** Tom's manual half, not automated: confirm each game still plays on the TV.
  That only matters once part 2 points RomM at Infiltrator's library; until then it is listed
  in the PR as pending.

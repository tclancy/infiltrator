# Infiltrator: named shelf changes, an emulator per game, and a library RomM keeps

Approved requirements and decisions: Tom, 2026-11-22, in chat.
Covers issues #7, #8, #9 and #10. Builds on `2026-10-30-shelf-brain-design.md` and
`2026-10-30-romm-end-design.md`, and reverses two of the latter's "Not doing" lines (RomM
collections; any other platform folder).

## Intent

Three things went wrong on 2026-11-22, all with the same root: Infiltrator knows more than it tells.

- Getting one unwanted game (Tekken Tag Tournament) off the shelf meant rotating, which removed
  Heavy Barrel instead. There is no way to name a game.
- Heavy Barrel plays far better in FBNeo (the right stick aims the gun) than in MAME 2003-Plus (L1/R1
  turn it). Infiltrator only keeps MAME 2003-Plus sets, and the emulator a game runs on is a setting
  typed into the TV by hand. That setting was wiped by a library reset and every game stopped launching.
- Rotated-out games lost their cover art, because each rotation deletes their RomM records.

The work is three parts, each shippable alone, in this order.

## Part 1: drop and add a named game (#7)

| # | Requirement | Check |
|---|-------------|-------|
| 1 | `infiltrator shelf drop <persona> "<title>"` takes that game off the persona's shelf. | Test: shelf of 3, drop one → `current_shelf` has the other 2, an `off` row in `shelf_history`. |
| 2 | A dropped game stays off that persona's shelf through every fill, build and rotate. | Test: drop, then `fill_shelf`, `build_shelf`, `rotate` → never returns, though it is the best-ranked candidate. |
| 3 | `infiltrator shelf add <persona> "<title>"` puts that game on the persona's shelf and forgets that it was dropped. | Test: drop then add → on the shelf; a later fill keeps it. |
| 4 | Adding to a full shelf takes off the longest-shelved game that is not a must-have. | Test: full shelf, add → size unchanged, the oldest `placed_at` non-must-have is gone. |
| 5 | A title is matched without regard to case, and one game is one family. | Test: `"heavy barrel"` finds it; adding a game whose other version is shelved swaps the version, not the count. |
| 6 | A title that is not in the library, or that the persona cannot play, changes nothing and says "Try again later!". | Test: unknown title, and a dial game with no tuning → shelf unchanged, exit 1. |
| 7 | Dropping or adding for one persona changes no other persona's shelf. | Test: two personas share a game; drop for one → the other keeps it. |
| 8 | When the persona is the one on the TV, a drop or add reaches the TV like a rotate does. | Test: `shelf_dir` and the fake RomM client reflect it; preflight runs first. |

Design: a `shelf_drops` table (persona, family, at), human data like `must_haves`. `eligible` leaves
out a persona's dropped families; `shelf add` deletes the row. Both commands go through
`_replace_shelf` inside `_changing_shelf`, as `rotate` does. Title lookup is a new function scoped to
the persona's eligible rows; today's `_set_for_title` ignores the persona.

## Part 2: an emulator per game, FBNeo first (#8, #10)

| # | Requirement | Check |
|---|-------------|-------|
| 9 | A set is identified by emulator and name together. | Test: `mame2003-plus/hbarrel` and `fbneo/hbarrel` are both in `games` and in the library on disk, with different contents. |
| 10 | Everything recorded before this change carries over as MAME 2003-Plus. | Migration test: old `shelf`, `shelf_history`, `arrivals`, `control_tuning`, `issues` rows all survive with `emulator = 'mame2003-plus'`. |
| 11 | Infiltrator reads FBNeo's set list. | Test: a synthetic DAT in FBNeo's dialect (`isbios="yes"`, no sha1, no `biosset`) → BIOS sets recognised, BIOS-held ROMs left out of a game's set. |
| 12 | A ROM that FBNeo itself treats as optional does not have to be present. | Test: a set missing only optional ROMs is valid; missing a required one is not. Gate: the real merged Heavy Barrel zip yields `fbneo/hbarrelua`. |
| 13 | The list of optional ROMs is generated from FBNeo's source at the pinned commit, never kept by hand. | `scripts/fbneo_optional.py` run on the pinned checkout reproduces the committed-to hash byte for byte. |
| 14 | A game runs on MAME 2003-Plus unless its tuning says otherwise. | Test: no tuning → the MAME set is the one shelved. `tune set "Heavy Barrel" --device sabrina --emulator fbneo …` → the FBNeo set is. |
| 15 | An FBNeo set is built only for a game tuned to FBNeo, from ROMs Infiltrator already holds. | Test: tune, then sieve with an empty drop folder → `library/fbneo/hbarrelua.zip` appears, valid; untuned games get no FBNeo set. |
| 16 | The shelf still holds one entry per game, whichever emulator it runs on. | Test: Heavy Barrel on FBNeo counts once and its MAME sets are not shelved beside it. |
| 17 | MAME 2003-Plus sets are published to a RomM folder named `mame`, FBNeo sets to one named `fbneo`, each with its own BIOS folder. | Test: `publish` links each set under its emulator's folder and refuses a stranger in either. |
| 18 | The TV launches each game in the right RetroArch core with no emulator setting on the TV. | Live, after a Reset Library in Argosy: Tapper logs `RetroArch core: …mame2003_plus…`, Heavy Barrel logs `…fbneo…`, and the right stick aims. |
| 19 | The old `arcade` folder ends up empty and unused. | Live: `roms/arcade` and `bios/arcade` hold nothing; RomM's Arcade platform shows no games. |
| 20 | FBNeo's set list and optional-ROM list are pinned by commit and sha256 where the MAME 2003-Plus one is. | Homelab: `get_url` with `checksum:` for both; a changed file fails the deploy. |

Design:

- **Why folders.** Argosy picks its default core from the platform folder name: `mame` → MAME
  2003-Plus, `fbneo` → FBNeo, `arcade` → FBNeo (`EmulatorRegistry.platformCores`; when RomM's slug is
  `arcade`, Argosy uses the folder name, `PlatformDefinitions.resolveImportSlug`). RomM 5.4.1 treats
  folders named `mame` and `fbneo` as the Arcade platform with no config. RomM has no per-game
  emulator field and Argosy reads none, so the folder is the only channel there is.
- **Identity.** `emulator` joins `set_name` in every key: `games`, `shelf`, `shelf_history`,
  `arrivals`, `control_tuning`, `issues`. The library becomes `library/<emulator>/<set>.zip`; the
  migration moves today's flat files into `library/mame2003-plus/`. `family` stays the unit a person
  sees and is shared across emulators.
- **Two set lists, one parser.** `Dat` gains an emulator name and a dialect: where the BIOS flag is,
  and an optional-ROM set. Settings take a table of DATs in place of one `dat_path`.
- **Which FBNeo set.** For a tuned family: the FBNeo sets whose required ROMs are all among the ROMs
  held for that family, then the usual choice (persona's language, parent first, name). For Heavy
  Barrel today that is `hbarrelua`; `hbarrel` (World) needs an MCU dump the library does not have.
- **Metadata.** FBNeo's list has no players/controls/buttons. An FBNeo set takes language, genre,
  players and controls from the family's MAME sets. A game only FBNeo knows is out of scope.
- **Names really do clash.** Of 3,679 set names in both lists, 1,400 have different contents and 425
  mean a different version (MAME 2003-Plus `hbarrel` is US; FBNeo `hbarrel` is World). Nothing may
  key on a bare name again.

## Part 3: the shelf as a RomM collection (#9)

| # | Requirement | Check |
|---|-------------|-------|
| 21 | Every verified set is in RomM, not only the shelved ones. | Test: `publish` links the whole library per emulator folder. |
| 22 | The shelf on the TV is a RomM collection holding exactly the shelved games. | Test against a fake RomM: after `play`, the collection's `rom_ids` are the shelf's, in no particular order. |
| 23 | Rotating, dropping or adding changes the collection and removes no file from RomM. | Test: rotate → folder contents unchanged, collection membership changed. |
| 24 | Infiltrator never asks RomM to delete missing games. | Test: the fake RomM records no `cleanup_missing_roms` call anywhere. |
| 25 | A game keeps its RomM record and its cover when it leaves the shelf and comes back. | Live: set a cover by hand, rotate the game off and on → same cover, same RomM id. |
| 26 | A RomM token without the new permissions changes nothing and says the TV will catch up. | Test: the fake RomM answers 403 → shelf rows untouched, `romm_pending` stays set. |

Design: the token gains "View ROMs" and "View / Modify collections". Infiltrator maps set to RomM id
from `GET /api/roms` per platform, creates the collection once, and replaces its members with
`PUT /api/collections/{id}`. RomM only flags a vanished file as missing and re-attaches it when it
returns; it is the cleanup task Infiltrator runs today that deletes the record and its cover.

## Decisions (Tom, 2026-11-22: yes to all)

1. **Folder names `mame` and `fbneo`, retiring `arcade`.** One-time cost: every game gets a new RomM
   id, covers are fetched again (Zaxxon's hand-set cover is lost once), and Argosy shows two platforms
   in place of one. The alternative, keeping MAME sets in `arcade`, leaves them one reset away from
   launching in FBNeo.
2. **MAME 2003-Plus stays the default; FBNeo is opt-in per game through tuning.** The alternative,
   FBNeo wherever it has the game, changes how every game on the shelf plays.
3. **Adding to a full shelf bumps the longest-shelved game** (requirement 4). The alternative is to refuse.
4. **The whole library becomes visible in RomM and Argosy** (12 games today), with the shelf as a
   collection pinned to Argosy's home screen. This reverses "RomM shows the shelf and nothing else".
   If the short shelf must stay the only thing on show, Part 3 is dropped and covers keep vanishing.
5. **One collection that mirrors whoever `play` put on the TV**, not one per persona. Smallest change
   and the same behaviour as now. Per-persona collections can follow.
6. **Order: Part 1, then 2, then 3**, one branch and PR each. Part 3 can be left out.

## Not doing

- Any emulator beyond MAME 2003-Plus and FBNeo. Games only FBNeo has.
- Backing up or restoring Argosy's own settings. Requirement 18 makes them unnecessary.
- Upgrading Argosy to 3.x. It prefers its built-in player over RetroArch by default, which needs its
  own look before the pin moves.
- Smart or virtual collections; a collection as Argosy's default view (it cannot be).

## Unknowns, tested before building on them

1. **RomM with `roms/mame` and `roms/fbneo`.** Read from RomM 5.4.1 source, not run. Spike: one zip in
   each folder by hand, scan, read `GET /api/platforms`.
2. **Argosy 2.25.2 on the TV picks RetroArch and the right core for each folder with no settings.**
   Read from source. Only RetroArch and Argosy are installed on the TV, so RetroArch is the only
   candidate. Spike: after 1, Reset Library in Argosy, launch one game from each, read logcat.
3. **The FBNeo core's "Second Stick" option** defaults to "Moves & Shoots". From source; confirmed by
   hand on the TV only as "the stick aims".
4. **The FBNeo core on the TV versus the pinned set list.** The list changes almost daily and the core
   reports no commit. Pin a commit near the core's download date; re-pin when the core is updated.

## What the research found (2026-11-22)

- A dropped game would return at the next fill (every sieve run), because it ranks first among
  candidates. Hence requirement 2.
- The current parser loads FBNeo's list without error and gets it wrong: no BIOS sets recognised, so
  `mslug` appears to need 47 ROMs where 9 are its own.
- FBNeo's list cannot say a ROM is optional. 2,409 of its sets have at least one, and the real Heavy
  Barrel zip is rejected without that knowledge. Hence requirements 12 and 13.
- The sieve today would take an FBNeo-named zip apart into MAME sets and delete the original.
- Argosy's "Reset Library" and "Hard Reset" delete every emulator setting; plain cache clears do not.
- Infiltrator's pre-push hook installs and runs nothing, and there is no CI. Out of scope here; noted.

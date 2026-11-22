# Plan: named shelf changes, an emulator per game, the shelf as a collection

Spec: `../specs/2026-11-22-emulator-per-game-design.md`.

Done as of 2026-11-22: Part 1 (PR #13, deployed; Tekken Tag Tournament dropped and Heavy Barrel
added for tom), step 7 (PR #12) and step 8 (PR #14).
One branch and PR per part. Test first for each step; `uv run pytest` and
`uv run pre-commit run -a` green at the end of each part.

## Part 1: `shelf drop` / `shelf add`. Branch `claude/shelf-drop-add`

1. Migration `0005_shelf_drops.sql`: `shelf_drops (persona, family, at)`.
2. `personas.eligible` leaves out a persona's dropped families. (Req 2, 7)
3. `shelf.py`: `drop(conn, persona, family, now)` and `add(conn, persona, set, size, now)`, both through `_replace_shelf`; `add` bumps as `rotate` picks its leaver. (Req 1, 3, 4)
4. `cli.py`: a persona-scoped title lookup; `shelf drop`, `shelf add` inside `_changing_shelf`. (Req 5, 6, 8)
5. README: both commands.
6. Deploy; Tom drops Tekken Tag Tournament and adds Heavy Barrel.

## Part 2: an emulator per game. Branch `claude/emulator-per-game`

Spikes first (spec, Unknowns 1 and 2). If either fails, stop and revise the spec.

7. `dat.py`: `Dat` carries an emulator name and a dialect; FBNeo dialect reads `isbios`, keys on size and crc, takes an optional-ROM set. (Req 11, 12)
8. `scripts/fbneo_optional.py`: derive the optional-ROM list from FBNeo's driver sources. (Req 13)
9. `config.py`: a table of DATs replaces `dat_path`; per-emulator publish folders replace `shelf_dir` / `bios_dir`. The old keys keep working as the MAME 2003-Plus entry.
10. Migration `0006_emulator.sql` and the library move to `library/<emulator>/`. (Req 9, 10)
11. `scan.py`, `rebuild.py`, `sieve.py`, `catalogue/games.py`: thread the emulator through; a chip either list knows is kept. (Req 9, 15)
12. `catalogue/tuning.py`, `cli.py`: `tune set --emulator`; `personas` / `shelf` choose the tuned emulator's set for a family. (Req 14, 15, 16)
13. `publish.py`, `tv.py`, `romm.py`: one folder pair and one RomM platform per emulator. (Req 17)
14. `scripts/gate.py`: expect both emulators' sets from the real zips. (Req 12)
15. README and `docs/romm.md` in tclancy/homelab.
16. tclancy/homelab: pin FBNeo's list and the optional list; new folders and config; retire `arcade`. (Req 19, 20)
17. tclancy/living-room-tv: README (no Argosy emulator setting needed; FBNeo core is a one-time download), controls page row for Heavy Barrel, remove the per-game override on the TV.
18. Live acceptance on the TV. (Req 18, 19)

## Part 3: the shelf as a collection. Branch `claude/shelf-collection`

19. `romm.py`: list ROMs for a platform; find-or-create a collection; replace its members. (Req 22, 26)
20. `publish.py`, `tv.py`: publish the whole library; the shelf goes to the collection; no cleanup task. (Req 21, 23, 24)
21. README; homelab token scopes; Tom pins the collection in Argosy.
22. Live acceptance. (Req 25)

## What can run in parallel

- Part 1 touches `shelf.py`, `personas.py`, `cli.py`; steps 7 and 8 touch only `dat.py` and a new
  script. Those three can be built at once by separate agents on separate branches.
- Step 10 onward changes the key of every table and must be one author, in order.
- Part 3 starts after Part 2 merges: it builds on per-emulator folders.

# Infiltrator part 2: the RomM end

Approved requirements: Tom, 2026-10-30, in chat. Part 1 (the shelf brain) is
`2026-10-30-shelf-brain-design.md`; this document only adds to it.

## Intent

Drop files into a folder from the Mac. Without any further step, the real
games are kept, the junk is deleted, and the TV's arcade list shows the
current shelf: 6 to 10 games, never the whole pile.

## Requirements and their checks

| # | Requirement | Check |
|---|-------------|-------|
| 1 | Infiltrator runs on homelab, installed by Ansible. | `scripts/deploy.sh --limit homelab --tags infiltrator` is green; `ssh homelab ~/.local/bin/infiltrator --help` works. |
| 2 | There is a drop folder reachable from the Mac over Samba. | A file copied in Finder to `smb://homelab.local/Infiltrator` appears in the drop folder on homelab. |
| 3 | The sieve runs automatically when files land. | Drop the gate's files; within a few minutes the good sets are in the library, the junk is gone, `mario.nes` is left alone. |
| 4 | Infiltrator owns RomM's `roms/arcade/`; nothing else writes there. | The homelab test fails if another task targets that path; the 8 hand-placed zips are moved into the drop folder and rebuilt from it. |
| 5 | RomM shows only the current shelf, not the whole library. | After a publish the arcade folder holds exactly the shelf's sets, and RomM's arcade ROM count matches it. |
| 6 | `shelf rotate` changes what RomM shows without a manual scan. | After rotate, RomM's arcade list (API) changes with no click in the UI. |
| 7 | BIOS sets go in RomM's `bios/arcade/`. | A Neo Geo game on the shelf puts `neogeo.zip` there. |
| 8 | Tom confirms each shelf game plays on the TV. | Tom, on the couch. Not automatable. |

## Design

### Where things live (homelab)

- `/mnt/samsungusb/games/infiltrator/drop`: the Samba share, the only place anything is deleted.
- `/mnt/samsungusb/games/infiltrator/library`: every verified set. RomM never sees this folder.
- `/mnt/samsungusb/games/infiltrator/catalogue.db`, `dat/`, `metadata/`: catalogue and inputs on the data drive, so a system-disk death (2026-05) costs nothing.
- `/mnt/samsungusb/games/romm/library/roms/arcade`: the **shelf folder**, hardlinks to the shelf's library files.
- `/mnt/samsungusb/games/romm/library/bios/arcade`: the **BIOS folder**, hardlinks to the BIOS sets the shelf needs.

The two trees share a filesystem, so a hardlink costs no space and a publish is instant.

### Publish (Infiltrator)

`publish` makes the shelf folder and the BIOS folder match the TV persona's shelf exactly:

- A file in either folder is **ours** when it is a hardlink to the library file of the same name (same inode). Ours and wanted: kept. Ours and unwanted: unlinked.
- A file that is **not ours** stops the publish before anything changes ("Try again later!"). Publish never deletes something it didn't put there. Dotfiles (`.DS_Store`) are ignored.
- Missing wanted files are hardlinked in.

### The TV persona

One persona at a time is on the TV. `infiltrator play <persona>` makes it the TV persona, fills its shelf if empty, and publishes. `shelf build` and `shelf rotate` publish when they act on the TV persona. Swapping solo to party is `play party`.

### Magic on arrival

After a sieve that added games, the TV persona's shelf is **topped up** (empty slots only; nothing already on the shelf is displaced) and published. A full shelf stays as it is until a rotate.

### Telling RomM

The RomM watcher (#647) notices new files and quick-scans after 5 minutes, but a removed file only becomes "missing" and stays listed. So after a publish that changed anything, Infiltrator calls RomM's API:

1. `GET /api/platforms`: find the platform whose `fs_slug` is `arcade`.
2. `POST /api/tasks/scan` with `{"type": "quick", "platforms": [id]}`, then poll `GET /api/tasks/{task_id}` until it is `finished` (or `failed`, which is an error).
3. `POST /api/tasks/run/cleanup_missing_roms` with `{"platform_ids": [id]}`: purges rotated-out games, arcade only.

A change sets a "RomM pending" flag that clears only when step 3 succeeds. Every sieve (the 10-minute timer included) tops up, publishes and retries a pending RomM call, so an outage heals itself. At a shell, a RomM failure prints "The TV will catch up shortly." and exits 0: the shelf change is made, and repeating the command would rotate twice. `play`, `shelf build` and `shelf rotate` check RomM's folders for strangers *before* changing the shelf, so "Try again later!" from them means nothing changed. A file lock keeps the sieve service and a shell from publishing at once.

Auth is a RomM client token (`rmm_…`, scopes `platforms.read` and `tasks.run`) in `INFILTRATOR_ROMM_TOKEN`; the URL is `romm_url` in config. With no token, publish still happens and RomM catches up on adds by itself; removals linger as "missing" until a token is set. Verified against RomM 5.4.1 source (`backend/endpoints/tasks.py`, `backend/tasks/manual/cleanup_missing_roms.py`).

### Running on its own (homelab)

- Installed with `uv tool install` from GitHub at a pinned ref, as a user tool for `tom` (native-apps pattern).
- `infiltrator-sieve.service` (user, oneshot) runs `infiltrator sieve`, fired by `infiltrator-sieve.path` (the drop folder changed) and `infiltrator-sieve.timer` (every 10 minutes, catching subfolder drops and copies that were still in progress).
- A drop folder that is still being written to exits **75** (EX_TEMPFAIL), declared `SuccessExitStatus=75`, so a slow copy is not a failed unit and does not page anyone.
- The DAT is fetched by Ansible from libretro's GitHub at a pinned commit with a checksum. The progettoSNAPS/nplayers files are copied from the controller (`~/.config/infiltrator/metadata/` on the Mac) when present; they are never committed to either repo.

## Decisions that were mine (check these)

- Hardlinks, not copies or symlinks (symlinks would point outside RomM's container mount).
- Top-up on arrival, not a rebuild: new games never knock a game off the shelf mid-week.
- Publish refuses on a stranger in the shelf folder rather than deleting it.
- The sieve timer cadence (10 minutes).
- Catalogue and inputs on the USB drive.

## Not doing

- Starting the sommelier on a schedule (rotate stays a command).
- Any other platform folder.
- RomM collections.

## Blocked on Tom

- **A RomM client token**: RomM → Settings → Client API Tokens, scopes "View platforms" and "Run tasks"; then `vault_infiltrator_romm_token` in the vault (Tom edits the vault).
- **Merging and deploying** homelab #647 and this work.
- **Requirement 8**, the couch check.

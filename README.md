# Infiltrator

Point it at a pile of arcade files. It keeps the real games, throws away everything else,
and gives each person in the house a small shelf of games that rotates.

Named for the C64 game and its hero, Johnny "Jimbo Baby" McGibbits: slip into the stack,
make it work, sneak back out.

Status: part 1 (the shelf brain) in progress. See `docs/superpowers/`.

Infiltrator never downloads, links to or ships ROMs. It only handles files you already have.

Licence: GPL-3.0-or-later.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

Create `~/.config/infiltrator/config.toml`. Every key can also be set as an
`INFILTRATOR_<KEY>` environment variable.

```toml
drop_dir = "~/infiltrator/drop"         # put downloads here; the only place anything is deleted
library_dir = "~/infiltrator/library"   # verified games end up here, one zip per game per emulator
db_path = "~/infiltrator/catalogue.db"
dat_path = "~/mame2003-plus-libretro/metadata/mame2003-plus.xml"
metadata_dir = "~/infiltrator/metadata"
shelf_size = 8                          # 6 to 12

# Optional: put a shelf on a RomM server's TV list. These are MAME 2003-Plus's folders.
shelf_dir = "/mnt/samsungusb/games/romm/library/roms/mame"  # the shelf, or the library
bios_dir = "/mnt/samsungusb/games/romm/library/bios/mame"
romm_url = "http://localhost:7767"
romm_token_file = "~/.config/infiltrator/romm-token"   # chmod 600
# Optional: the whole library in RomM, with the shelf as this collection (see "The TV").
romm_collection = "On the shelf"                       # needs romm_url and the token

# Optional: FBNeo's set list, so a game can be switched to FBNeo.
fbneo_dat_path = "~/infiltrator/fbneo-arcade.dat"
fbneo_optional_path = "~/infiltrator/fbneo-optional.json"   # needs fbneo_dat_path
# ...and FBNeo's own RomM folders, without which no game is shown on FBNeo.
fbneo_shelf_dir = "/mnt/samsungusb/games/romm/library/roms/fbneo"   # needs fbneo_dat_path
fbneo_bios_dir = "/mnt/samsungusb/games/romm/library/bios/fbneo"
```

The RomM token is a secret, so it never goes in this file: it is read from
`romm_token_file`, or from `INFILTRATOR_ROMM_TOKEN`, which wins. Make one in RomM under Settings → Client API Tokens with "View platforms" and
"Run tasks". With `romm_collection` set it also needs "View ROMs", "View collections" and
"Modify collections"; until it has them, RomM's folders are kept up to date but the
collection isn't, and you'll see `The TV will catch up shortly.`

- **`dat_path`** is the MAME 2003-Plus game list from the
  [core's repo](https://github.com/libretro/mame2003-plus-libretro).
- **`fbneo_dat_path`** (optional) is FBNeo's arcade game list, `dats/FinalBurn Neo (ClrMame
  Pro XML, Arcade only).dat` in [FBNeo's repo](https://github.com/libretro/FBNeo).
  **`fbneo_optional_path`** is the list of ROMs FBNeo can run without, which its game list
  cannot say; generate it from the same commit with `scripts/fbneo_optional.py`. Without it,
  an FBNeo set missing only an optional ROM counts as incomplete.

  With FBNeo configured, the sieve also keeps any chip only FBNeo knows: a drop file holding
  one that no library zip has stays in the drop folder (`--verbose` says `held for fbneo`),
  because the library holds only sets. FBNeo sets are built only for games switched to FBNeo
  (see below).
- **`fbneo_shelf_dir`** and **`fbneo_bios_dir`** (optional, set both or neither) are FBNeo's
  RomM folders, as `shelf_dir` and `bios_dir` are MAME 2003-Plus's. No two of the four may be
  the same folder or inside one another. Each can be overridden like any other key
  (`INFILTRATOR_FBNEO_SHELF_DIR`, `INFILTRATOR_FBNEO_BIOS_DIR`).

**The library** keeps one folder per emulator: `library/mame2003-plus/<set>.zip` and
`library/fbneo/<set>.zip`. Both emulators use some of the same set names for different
games (MAME 2003-Plus `hbarrel` is the US Heavy Barrel, FBNeo's is the World one), so a set
is always an emulator and a name. A library from before this, with the zips at the top, is
moved into `library/mame2003-plus/` by the first command that uses it. Each file keeps its
inode, so hardlinks into RomM's folders stay good. If a name is in both places the command
stops and changes nothing (`--verbose` names it): keep the right file, delete the other.
- **`metadata_dir`** holds the files you download yourself. Infiltrator doesn't ship them:
  - from [progettoSNAPS](https://www.progettosnaps.net/support/): `catver.ini`,
    `languages.ini`, `bestgames.ini` and `renameSET.ini`;
  - `nplayers.ini` from [nplayers](https://nplayers.arcadebelgium.be).

  Each file is optional. Without them, games just have less to be filtered and ranked by,
  except `languages.ini`: without it no game has a language, so a persona that speaks one
  sees nothing. Answer `any` to the language question until it's there.

## Use

```sh
infiltrator sieve                 # keep the real games from the drop folder, delete the rest
infiltrator persona add tom       # a few questions about who's playing
infiltrator shelf build tom       # pick the shelf
infiltrator shelf show tom
infiltrator shelf rotate tom      # the sommelier: swap the longest-shelved game for a fresh one
infiltrator shelf drop tom "Title"  # take a game off the shelf and keep it off until you add it back
infiltrator shelf add tom "Title"   # put a game on the shelf; on a full shelf the longest-shelved makes room
infiltrator play tom              # put tom's shelf on the TV (swap to `play party` for a party)
infiltrator play tom --new        # demo the last 24 hours' arrivals on the TV; `play tom` puts the usual shelf back
infiltrator play tom --new --days 3   # ...or the last 3 days'
infiltrator issue log "Heavy Barrel" --device sabrina --note "froze on stage 2"
infiltrator tune set "Heavy Barrel" --device sabrina --settings 'L1/R1 rotate (keyboard device)'
                                  # a tuned game counts as gamepad-playable
infiltrator tune set "Heavy Barrel" --device sabrina --settings 'right stick aims' --emulator fbneo
                                  # ...and from now on it runs on FBNeo; `--emulator mame2003-plus` undoes it
infiltrator rescan                # rebuild the game list from the library
```

Add `--verbose` to `sieve`, `play` or `issue list` to see the nerd stuff.

**The TV.** With `shelf_dir` and `bios_dir` set, the persona you `play` is on the TV:
its shelf is hardlinked into `shelf_dir` (and the BIOS sets it needs into `bios_dir`), and
nothing else is left there (unless `romm_collection` is set: see below). `shelf build` and
`shelf rotate` for that persona change the TV
too, and a sieve that finds new games drops them into any empty shelf slots. Nothing already
on the shelf is ever bumped by a new arrival. With `romm_url` and the token set, RomM is told
to rescan and to forget games that left; if RomM doesn't answer, you'll see
`The TV will catch up shortly.` and the next sieve tries again. If `shelf_dir` holds a file Infiltrator didn't put
there, it changes nothing and says `Try again later!`; move that file into the drop folder.
Each emulator with folders is its own RomM platform, named after its games folder (`mame`,
`fbneo`; `arcade` on a setup from before emulators). RomM only meets a folder by scanning it,
so the first time a platform is missing Infiltrator asks RomM to scan every folder once.

**The shelf as a RomM collection.** With `romm_collection` set, RomM's folders hold the whole
library instead: every verified set of each emulator that has folders goes to its games
folder, and every BIOS set it has to its BIOS folder. A game chosen for another emulator
(`tune set --emulator`) is listed as that emulator's set only: its MAME 2003-Plus sets stay in
the library and out of RomM, and RomM marks the records it had for them missing (delete those
in RomM by hand). The TV sees every game, and the shelf
of the persona you `play` is the RomM collection of that name: Infiltrator makes it (public)
the first time, and from then on `play`, `shelf build`, `rotate`, `drop`, `add` and the sieve
change only what is in it. Pin the collection to Argosy's home screen to see the shelf first.
RomM is never asked to forget missing games, so a game that leaves the shelf keeps its RomM
record, its id and its cover (a hand-set one too), and has them all again when it comes
back. A set that leaves the library is only marked missing in RomM. One collection follows
whoever is on the TV, not one per persona. If RomM hasn't listed a shelved set yet,
Infiltrator leaves the collection alone and the next sieve tries again (`--verbose` names
the sets).

**Switching a game to FBNeo.** Every game runs on MAME 2003-Plus unless you say otherwise
with `tune set ... --emulator fbneo`. That needs `fbneo_dat_path`, and the TV shows FBNeo
games only once `fbneo_shelf_dir` and `fbneo_bios_dir` are set too; until then the game stays
on the TV as its MAME 2003-Plus set. Infiltrator works out which FBNeo sets are the same game
from the chips they share with its MAME 2003-Plus sets, and builds the ones it can from chips
it already has: at once from the library, or at the next sieve when a chip is still held in
the drop folder (it says `Not on fbneo yet` then). The game
is still one game: it keeps its MAME title, filters and place on every shelf that has it, and
on the TV its MAME 2003-Plus zip leaves `shelf_dir` as its FBNeo zip arrives in
`fbneo_shelf_dir` (with any FBNeo BIOS it needs in `fbneo_bios_dir`). The TV picks the
emulator from the folder, so nothing is set on the TV. `shelf drop` and `shelf add` by title
work whichever emulator it is on. Switching back, or the FBNeo zip going away, puts the MAME
2003-Plus set back the same way.

**Demo new arrivals.** `play tom --new` swaps tom's shelf for the games that arrived in
the library in the last 24 hours (a rolling window, so midnight doesn't reset it; `--days 3`
looks back 3 days), still filtered for tom and capped at `shelf_size`.
While the demo is on, each sieve adds only games new since the demo's window began, so drops
join it as you go. `play tom`, `shelf build tom` or `shelf rotate tom` ends it. A game's
arrival is when its set first reached the library; sets there before this existed count from
their library file's date.

**What the sieve does to the drop folder.** It deletes:

- anything that's a real arcade set, after rebuilding it into the library;
- broken or fake arcade files;
- executables.

Everything else is left alone: other systems' games, music, and `.rar` files (not supported
yet). If the folder looks like it's still downloading, it does nothing, says
`Try again later!` and exits 75, so a scheduler can tell "not yet" from "broken".

## Development

```sh
uv run pytest
uv run pre-commit run -a
uv run python scripts/gate.py   # local only: Tom's eight real games against the real DAT
```

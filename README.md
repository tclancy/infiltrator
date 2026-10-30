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
library_dir = "~/infiltrator/library"   # verified games end up here, one zip per game
db_path = "~/infiltrator/catalogue.db"
dat_path = "~/mame2003-plus-libretro/metadata/mame2003-plus.xml"
metadata_dir = "~/infiltrator/metadata"
shelf_size = 8                          # 6 to 10

# Optional: put a shelf on a RomM server's TV list.
shelf_dir = "/mnt/samsungusb/games/romm/library/roms/arcade"  # holds only the shelf
bios_dir = "/mnt/samsungusb/games/romm/library/bios/arcade"
romm_url = "http://localhost:7767"
romm_token_file = "~/.config/infiltrator/romm-token"   # chmod 600
```

The RomM token is a secret, so it never goes in this file: it is read from
`romm_token_file`, or from `INFILTRATOR_ROMM_TOKEN`, which wins. Make one in RomM under Settings → Client API Tokens with "View platforms" and
"Run tasks".

- **`dat_path`** is the MAME 2003-Plus game list from the
  [core's repo](https://github.com/libretro/mame2003-plus-libretro).
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
infiltrator play tom              # put tom's shelf on the TV (swap to `play party` for a party)
infiltrator issue log "Heavy Barrel" --device sabrina --note "froze on stage 2"
infiltrator tune set "Heavy Barrel" --device sabrina --settings 'L1/R1 rotate (keyboard device)'
                                  # a tuned game counts as gamepad-playable
infiltrator rescan                # rebuild the game list from the library
```

Add `--verbose` to `sieve`, `play` or `issue list` to see the nerd stuff.

**The TV.** With `shelf_dir` and `bios_dir` set, the persona you `play` is on the TV:
its shelf is hardlinked into `shelf_dir` (and the BIOS sets it needs into `bios_dir`), and
nothing else is left there. `shelf build` and `shelf rotate` for that persona change the TV
too, and a sieve that finds new games drops them into any empty shelf slots. Nothing already
on the shelf is ever bumped by a new arrival. With `romm_url` and the token set, RomM is told
to rescan and to forget games that left. If `shelf_dir` holds a file Infiltrator didn't put
there, it changes nothing and says `Try again later!`; move that file into the drop folder.

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

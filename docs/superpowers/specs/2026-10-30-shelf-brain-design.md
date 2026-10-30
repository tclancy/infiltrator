# Infiltrator, part 1: the shelf brain

Status: draft for Tom's review, 2026-10-30. Builder check done; Tom answered its two open questions.
This is the scope document for part 1. The plan comes after it is approved.

## Why

Tom grew up in arcades, is technical, and still always gave up on MAME. He bought two
overseas kits that "worked" and were The Illusion of Choice: every game, every version,
some of them in Malaysian. Getting the eight games on his living-room TV right took a night
of hand-checking checksums. Along the way that night:

- `1942.zip` was really `1942b`.
- A Zaxxon set existed only in newer MAME.
- Rolling Thunder carried a re-dumped chip that the emulator rejects.
- 4,772 macOS `._` junk files were sitting in the folder.

Those checks are the product. Nobody wants a drill, they want holes. Nobody wants a MAME set,
they want to play Pac-Man.

**Infiltrator** (named for the C64 game and its hero, Johnny "Jimbo Baby" McGibbits) slips
into an existing emulation stack, makes it work, and sneaks back out without anyone noticing.

## The whole project, and where this part fits

Infiltrator is several projects, done in this order (approved by Tom):

1. **The shelf brain** (this document). A torrent goes in and a small, clean shelf comes out.
2. **The RomM end.** Plug the brain into RomM, so Tom's homelab works this way first.
3. **Accessibility tags.** Which games someone can play one-handed, button-only, and so on.
4. **The other end.** A normal person installs one thing on a TV.
5. **Stretch goals.** Controller feel, and haptics driven from game memory.

## Goals

- **Torrent in, shelf out.** Assume the input is "a torrent of every ROM ever", including
  junk like mislabeled LimeWire mp3s.
- **The sieve, Old Testament rules.** A file is either a real, complete, clean game for the
  target emulator, or it is **deleted from disk**. There is no quarantine and no "mostly
  fine". Tom: the downside of deleting is tiny, because a game file can be regrabbed in
  seconds (and deleted again if it is still bad).
- **Game, not set.** The user never sees set names, versions, chips, patches or merge
  modes. If a game needs its parent's files (Midway Pac-Man holds 4 of PuckMan's 10 chips)
  and both are present, they are combined quietly. "The game I pumped six zillion quarters
  into, even if it was that slight variation": real revisions and regional variants are
  fine.
- **Personas.** Setup asks a few plain questions and saves the answers as personas the user
  picks between from day to day (for example, "Tom solo" or "the niece"). Switching from solo
  to a party is possible. The questions:
  - **Language.** One language.
  - **Audience age.**
  - **Must-haves, or just have fun.** Lifers (the Velvet Underground buyers) name their games.
    Passers-through don't, and that's fine.
  - **Players.** Solo, or two or more.
  - **Inputs.** The hardware actually present, and what the person can physically do.
    Accessibility is a first-class goal: someone who lived in arcades and later got hurt
    should get their games back.
- **A shelf of 6 to 10 games at a time.** The persona narrows the sieved library, and the
  survivors are ranked by quality. A lifer's named games always make it.
- **The sommelier.** An easy way to rotate games on and off the shelf.
- **Headfirst.** No readiness checklist. If it's on the shelf, it plays.
- **On rejection, one line:** "Try again later!" (from Mall Madness). No reasons, no details.
- **CLI/TUI only for now.** The interface comes later.

## Non-goals

- Sourcing, downloading, linking to or distributing ROMs, ever. Infiltrator only handles
  files the user already has.
- Any UI beyond a terminal.
- The game-party exception to the shelf size. Parked.
- RomM integration, the TV install, accessibility curation beyond what falls out of the DAT,
  controller feel, haptics. These are later parts.
- Platforms other than arcade, for now. Tom wants this "to work for every system, but let's
  start small". Non-arcade files (NES, SNES, C64...) are **left alone**: never judged, never
  deleted, so a later part can pick them up.

## Anti-goals (a failure even if it technically works)

- **The Illusion of Choice:** a warehouse of hundreds of games, or several versions of one
  game.
- **Nerd stuff leaking out:** set names, merge modes or version numbers in normal output.
- **A bad file reaching the shelf.**
- **Deleting anything outside the drop folder.** Infiltrator only ever deletes inside its own
  known drop location (see "Where files come in"). A mis-aimed run can't touch someone's
  Documents folder, because it can't be aimed.
- **Committing a ROM to the repo,** which is public.

## Constraints

- **Target emulator:** MAME 2003-Plus (libretro, based on MAME 0.78). Its DAT is
  `metadata/mame2003-plus.xml` in the core's repo, with 5,695 runnable games (3,003 parents
  and 2,692 clones). Verification is against this DAT, not modern MAME.
- **Language:** Python, managed with uv. RomM's backend is Python, so part 2 can import it.
- **Licence:** GPL-3.0-or-later. It can move into RomM (AGPL-3) later and can't be taken
  closed. External data files keep their own licences in their own folder:
  - `nplayers.ini` is CC BY-SA 3.0 and can be bundled with credit.
  - AntoPISA's progettoSNAPS files (`bestgames.ini`, `catver.ini`, `languages.ini`) state
    **no licence**. Don't bundle them until he agrees. Fetching them at run time is fine.
- **No ROMs in git, real or partial.** `.gitignore` blocks `*.rom`, `*.zip`, `*.7z`, `*.chd`.
- **Timestamps are UTC** in code and logs.

## Decided parts of the how

**Persona data sources.** Coverage was measured against the MAME 2003-Plus DAT on
2026-10-29, after mapping old names through `renameSET`:

| Persona question | Source | Coverage |
|---|---|---|
| Language | `languages.ini` (progettoSNAPS) | ~99.5% of parents |
| Age | `catver.ini`, `* Mature *` tag (the core bundles a 0.239-era copy) | ~99.5% |
| Players | `nplayers.ini` (alternating vs simultaneous) | ~99.5% |
| Quality ranking | `bestgames.ini` (10 tiers, parents only) | ~86% of parents |
| Inputs | the DAT's own `<input buttons control>` | 100% |

- **Name drift.** About 1,600 names have changed since 0.78. `renameSET` maps most of them but
  reuses names, so a mapped match must be confirmed (by description or CRCs) before it is
  trusted.
- **First-cut accessibility signal.** Derive it from the DAT: 357 parents are joystick plus one
  button, and 42 are joystick only, `puckman` among them. The proper curation is part 3.
- **Tests:**
  1. **The gate.** Tom's tidy folder of eight verified arcade games (`hbarrelw`, `congo`,
     `zaxxon`, `btimem`, `popeye`, `tapper`, `gauntlet`, `1942b`), run locally, never
     committed. All eight must come out right before anything else is tried.
  2. **The stress test.** A real messy dump that Tom supplies, run locally. The bar is that
     zero bad files survive.
  3. **CI fixtures.** Synthetic files whose size and CRC32 are forged to match DAT entries,
     with junk content inside, generated at test time. CRC32 is trivially forgeable. This only
     works if matching does not also require SHA-1 (unverified; see below).

## Where files come in (Tom, 2026-10-30)

- **A known drop folder.** Files are dropped into a single location that Infiltrator owns.
  It reads, rebuilds and deletes only there.
- **It refuses to work while a torrent is still active.** If the drop folder shows signs of
  an active download, Infiltrator does nothing and says "Try again later!". Signs include
  in-progress files (`.!qB`, `.part`, `.!ut`, `.crdownload`) and files still changing size or
  modification time. Deleting from a live torrent would only make the client re-download the
  pieces, in a loop with the sieve. Exactly how to detect activity is left to the builder; the
  rule is to refuse when in doubt.
- **Inside the drop folder, only arcade-looking files are judged.** Everything else is left
  exactly where it is.

## Settled after the builder check

Each item is either Claude's call or follows from what Tom already said, and is marked as such.

- **The sieve rebuilds; it doesn't just accept or delete.** This follows from "combine
  quietly" and from Tom's "fix quietly, never explain".
  - Every chip is verified on its own, and clean sets are rebuilt from verified chips.
    That handles merged archives, extra files, clones whose chips live in the parent, and
    misnamed zips (`1942.zip` holding `1942b`).
  - After a rebuild, the source files are deleted. Anything left over that verified as
    nothing is deleted too.
  - The output is therefore always new files, which settles move-or-copy.
- **Dependencies (Claude's call).**
  - **BIOS and device sets** (e.g. `neogeo`) survive the sieve and are kept hidden. A game
    that needs one is complete only if the BIOS is present.
  - **Samples are optional.** A game is complete without them. Tom: "will worry about the
    sounds if the games play well". Congo Bongo and Zaxxon use samples and play without them.
  - **CHDs:** MAME 2003-Plus needs CHDs for only a handful of games. Treat a game whose CHD
    is missing as incomplete.
- **The library keeps every valid set; the shelf shows one per game (Claude's call).**
  Variants stay hidden in the library. Shelf-building picks one per game: the parent, unless
  the persona's language or a lifer's named variant points at a clone. That way, personas with
  different languages share one library, and clone choice can be undone.
- **Input forms (Claude's call):** zip, 7z, rar, folders of loose chips, and archives nested
  one level deep. CHDs as they come.
- **Must-haves (Claude's call).**
  - A lifer's named games skip the age and language filters, because a person naming a game
    wants it. They do not skip inputs, because a game that can't be played can't be on the
    shelf.
  - If someone names more than 10 games, the shelf is drawn from their must-haves and the
    sommelier rotates through the rest.
  - Parties stay parked.
- **The gate means (Claude's call):**
  - all eight games end up in the library under their DAT names, with `1942.zip` caught as
    `1942b`, and nothing else is created or lost;
  - Tom confirms by hand that each one still plays on the TV.

## Left to the builder

- **How the sieve verifies.** Shell out to Igir (GPL-3, CRC verification against a DAT plus
  MAME merge modes), or write it in Python. **Check first** whether Igir can match on
  size+CRC32 alone, because the CI fixture idea depends on it. If it can't, the fixtures need
  another route.
- **The output layout of the sieved library and the shelf.** It should be RomM-friendly
  (`roms/arcade/<set>.zip`) so part 2 is cheap.
- Where personas are stored, the CLI/TUI library, how setup questions are worded and what
  they default to, how the drop folder is configured, and how active torrents are detected.
- How a passer-through's shelf is chosen from the ranked survivors.

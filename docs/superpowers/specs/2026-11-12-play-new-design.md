# Infiltrator: `play --new`, demo today's arrivals

Approved requirements: Tom, 2026-11-12, in chat. **"Today" (requirement 6) is
superseded by a rolling window: `2026-11-13-new-rolling-window-design.md`.** Builds on
`2026-10-30-shelf-brain-design.md` and `2026-10-30-romm-end-design.md`.

## Intent

Drop games on the Samba share, then `infiltrator play tom --new` to try the
ones that came in today on the TV, as you go.

## Requirements and their checks

| # | Requirement | Check |
|---|-------------|-------|
| 1 | The catalogue records when each set first arrived in the library; a rescan never changes it. | Test: sync, touch the zip, sync again → `arrivals.arrived_at` unchanged. |
| 2 | Sets already in the library get their arrival from the library zip's mtime. | Test: a zip with a month-old mtime, first sync → arrival is that old time, not "today". |
| 3 | `infiltrator play <persona> --new` replaces that persona's shelf with today's arrivals and puts it on the TV. | Test: 1 game arrived today, 1 older → shelf and `shelf_dir` hold only the new one; RomM refreshed. |
| 4 | The persona's filters still apply (language, mature, controls, one per family). | Test: a new arrival not in the persona's language stays off. |
| 5 | The shelf holds at most `shelf_size`; normal ranking picks which. | Test: 3 arrivals, size 2 → the 2 best-ranked. |
| 6 | "Today" is the homelab's local day; stored timestamps stay UTC. | Test, `TZ=America/New_York`: 02:00Z on Nov 13 is Nov 12 local, so the day starts `2026-11-12T05:00:00+00:00`. |
| 7 | Demo games go in shelf history like any shelving. | Test: an `on` row in `shelf_history` for each. |
| 8 | When nothing passes the filters, nothing changes and it says so. | Test: shelf and TV persona unchanged, exit 0, `Nothing new today for tom.` |
| 9 | `play <persona>` without `--new` behaves as before. | Existing `play` tests pass unchanged. |
| 10 | While a demo is on the TV, a sieve tops up the shelf only with games arrived since the demo's day began. A normal `play`, `shelf build` or `shelf rotate` of that persona ends the demo. | Tests: demo on, sieve an old-mtime set and a new one → only the new one joins. `shelf build` → `demo_since` is NULL. |

## Design

- **`arrivals` table** (migration 0004): `set_name` primary key, `arrived_at` UTC.
  Human data: never cleared, so a game that leaves the library and comes back
  keeps its first arrival. `sync_games` does `INSERT OR IGNORE` for every
  verified set, using the library zip's mtime. A sieve writes the zip fresh, so
  mtime is when it arrived; for sets already there at upgrade, it's the best
  record we have.
- **`tv.demo_since`** (same migration): NULL, or the UTC instant the demo's local
  day began. `set_tv_persona` clears it (a new persona, or a normal `play`, is
  not a demo); `play --new` sets it afterwards.
- **Start of today**: local midnight via the system zone (homelab is
  America/New_York), converted to UTC. Handles DST because a naive
  `datetime.astimezone()` uses the zone's rules for that date.
- **Picking**: the normal ranking (`_ranked`, which applies every persona filter
  and one-per-family) restricted to sets arrived since the start, first
  `shelf_size`.
- **Sieve top-up**: `_sync_tv` uses the arrivals-only fill while `demo_since`
  is set, the normal fill otherwise. Either way it fills empty slots only.
- **Ending a demo**: `shelf build` and `shelf rotate` clear `demo_since` when they
  act on the TV persona.

## Known edge

`shelf build` after a demo gives the normal ranked shelf. It matches the
pre-demo shelf only if that shelf was itself a fresh build: the demo games now
have a recent "last shelved" time, which breaks ties among equally rated games.

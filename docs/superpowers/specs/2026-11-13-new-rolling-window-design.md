# Infiltrator: `play --new` looks back 24 hours, not since midnight

Approved requirements: Tom, 2026-11-13, in chat. Amends
`2026-11-12-play-new-design.md`, whose "today" meant since local midnight: a demo
just after 12 found nothing.

## Requirements and their checks

| # | Requirement | Check |
|---|-------------|-------|
| 1 | `play <persona> --new` uses games that arrived in the last 24 hours. | Test: 23h ago in, 25h ago out. |
| 2 | Midnight doesn't matter. | Test: arrival 23:50 local, run 00:10 → in. |
| 3 | `--days N` widens the window to N×24 hours, N ≥ 1. | Tests: `--days 3` takes a 70h-old arrival; `--days 0` refused. |
| 4 | During a demo, a sieve adds only arrivals inside that demo's window. | Existing test: an old-mtime set stays off, a new drop joins. |
| 5 | When nothing qualifies, the message names the window. | Test: `Nothing new for tom in the last 24 hours.` |
| 6 | `--days` without `--new` is refused. | Test: non-zero exit naming `--new`. |

## Design

- `window_start(days, now)` replaces `start_of_local_day`: now minus `days`
  days, in UTC. No time zone involved, so no DST either.
- `tv.demo_since` keeps its meaning, the start of the demo's window, so the
  sieve top-up and the schema are unchanged.

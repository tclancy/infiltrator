-- When each set first arrived in the library. Human data: never cleared, so a
-- game that leaves the library and comes back keeps its first arrival.
CREATE TABLE arrivals (
    set_name   TEXT PRIMARY KEY,
    arrived_at TEXT NOT NULL
);

-- NULL, or the UTC instant the demo's local day began: while it is set, a sieve
-- tops up the TV shelf only with games that arrived since then.
ALTER TABLE tv ADD COLUMN demo_since TEXT;

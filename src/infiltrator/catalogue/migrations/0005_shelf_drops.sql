-- Games a persona said no to: `shelf drop` adds a row, `shelf add` removes it.
-- A dropped family is left out of that persona's fills, builds and rotations,
-- otherwise the next sieve would put it straight back (it ranks first among
-- the games not on the shelf). Human data like must_haves: no key into games,
-- so it survives a rescan.
CREATE TABLE shelf_drops (
    persona TEXT NOT NULL,
    family  TEXT NOT NULL,
    at      TEXT NOT NULL,
    PRIMARY KEY (persona, family)
);

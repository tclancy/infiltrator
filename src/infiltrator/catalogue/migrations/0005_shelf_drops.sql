-- Games that a persona has dropped. If a family appears here, it won't be
-- offered in shelf operations, even if it's the best-ranked candidate.
-- Human data: never cleared (a drop is permanent until add() undoes it).
CREATE TABLE shelf_drops (
    persona TEXT NOT NULL,
    family  TEXT NOT NULL,
    at      TEXT NOT NULL,
    PRIMARY KEY (persona, family)
);

-- Which persona's shelf is on the TV. One row at most.
CREATE TABLE tv (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    persona TEXT NOT NULL,
    at      TEXT NOT NULL
);

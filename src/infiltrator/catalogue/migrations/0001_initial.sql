-- The catalogue. games is regenerated from the library on every sync; every
-- other table is human data and is never regenerated, so none of them carry
-- a foreign key to games (a game can vanish on re-scan and come back later).

CREATE TABLE games (
    set_name        TEXT PRIMARY KEY,
    platform        TEXT NOT NULL DEFAULT 'arcade',
    parent          TEXT,
    description     TEXT,
    title           TEXT,
    year            TEXT,
    manufacturer    TEXT,
    is_bios         INTEGER NOT NULL,
    path            TEXT NOT NULL,
    language        TEXT,
    mature          INTEGER,
    genre           TEXT,
    players         TEXT,
    control         TEXT,
    buttons         INTEGER,
    quality_tier    INTEGER,
    a11y_one_button INTEGER,
    a11y_stick_only INTEGER,
    synced_at       TEXT NOT NULL
);

CREATE TABLE personas (
    name TEXT PRIMARY KEY,
    data TEXT NOT NULL
);

CREATE TABLE must_haves (
    persona TEXT NOT NULL REFERENCES personas ON DELETE CASCADE,
    title   TEXT NOT NULL,
    PRIMARY KEY (persona, title)
);

CREATE TABLE shelf (
    persona   TEXT NOT NULL REFERENCES personas ON DELETE CASCADE,
    set_name  TEXT NOT NULL,
    placed_at TEXT NOT NULL,
    PRIMARY KEY (persona, set_name)
);

CREATE TABLE shelf_history (
    id       INTEGER PRIMARY KEY,
    persona  TEXT NOT NULL,
    set_name TEXT NOT NULL,
    action   TEXT NOT NULL CHECK (action IN ('on', 'off')),
    at       TEXT NOT NULL
);

CREATE TABLE issues (
    id       INTEGER PRIMARY KEY,
    set_name TEXT NOT NULL,
    device   TEXT NOT NULL,
    note     TEXT NOT NULL,
    at       TEXT NOT NULL
);

CREATE TABLE control_tuning (
    set_name   TEXT NOT NULL,
    device     TEXT NOT NULL,
    settings   TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (set_name, device)
);

-- A set is an emulator and a name together: MAME 2003-Plus `hbarrel` is the US
-- Heavy Barrel, FBNeo `hbarrel` the World one. Every table that names a set
-- gains `emulator`, and it joins the primary key wherever the name was in it.
-- Everything recorded before this was MAME 2003-Plus, hence the default.
-- SQLite cannot change a primary key, so those tables are rebuilt: create the
-- new shape, copy every row, drop the old, rename. Still no foreign keys into
-- games, which is regenerated on every sync.

CREATE TABLE games_new (
    emulator        TEXT NOT NULL DEFAULT 'mame2003-plus',
    set_name        TEXT NOT NULL,
    platform        TEXT NOT NULL DEFAULT 'arcade',
    parent          TEXT,
    family          TEXT NOT NULL,
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
    synced_at       TEXT NOT NULL,
    PRIMARY KEY (emulator, set_name)
);
INSERT INTO games_new (
    set_name, platform, parent, family, description, title, year, manufacturer, is_bios, path,
    language, mature, genre, players, control, buttons, quality_tier, a11y_one_button,
    a11y_stick_only, synced_at
)
SELECT
    set_name, platform, parent, family, description, title, year, manufacturer, is_bios, path,
    language, mature, genre, players, control, buttons, quality_tier, a11y_one_button,
    a11y_stick_only, synced_at
FROM games;
DROP TABLE games;
ALTER TABLE games_new RENAME TO games;

CREATE TABLE shelf_new (
    persona   TEXT NOT NULL REFERENCES personas ON DELETE CASCADE,
    emulator  TEXT NOT NULL DEFAULT 'mame2003-plus',
    set_name  TEXT NOT NULL,
    placed_at TEXT NOT NULL,
    PRIMARY KEY (persona, emulator, set_name)
);
INSERT INTO shelf_new (persona, set_name, placed_at)
SELECT persona, set_name, placed_at FROM shelf;
DROP TABLE shelf;
ALTER TABLE shelf_new RENAME TO shelf;

CREATE TABLE arrivals_new (
    emulator   TEXT NOT NULL DEFAULT 'mame2003-plus',
    set_name   TEXT NOT NULL,
    arrived_at TEXT NOT NULL,
    PRIMARY KEY (emulator, set_name)
);
INSERT INTO arrivals_new (set_name, arrived_at) SELECT set_name, arrived_at FROM arrivals;
DROP TABLE arrivals;
ALTER TABLE arrivals_new RENAME TO arrivals;

CREATE TABLE control_tuning_new (
    emulator   TEXT NOT NULL DEFAULT 'mame2003-plus',
    set_name   TEXT NOT NULL,
    device     TEXT NOT NULL,
    settings   TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (emulator, set_name, device)
);
INSERT INTO control_tuning_new (set_name, device, settings, updated_at)
SELECT set_name, device, settings, updated_at FROM control_tuning;
DROP TABLE control_tuning;
ALTER TABLE control_tuning_new RENAME TO control_tuning;

-- These two are keyed by id, so the column is enough.
ALTER TABLE shelf_history ADD COLUMN emulator TEXT NOT NULL DEFAULT 'mame2003-plus';
ALTER TABLE issues ADD COLUMN emulator TEXT NOT NULL DEFAULT 'mame2003-plus';

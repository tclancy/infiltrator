-- Which emulator a game runs on, when it is not MAME 2003-Plus: `tune set
-- --emulator` writes a row, `--emulator mame2003-plus` deletes it. No row
-- means MAME 2003-Plus. A game is a MAME family, so `family` is the MAME
-- family (FBNeo sets are catalogued under the family they stand in for).
-- Human data like must_haves: no key into games, so it survives a rescan.
CREATE TABLE game_emulators (
    family   TEXT PRIMARY KEY,
    emulator TEXT NOT NULL,
    at       TEXT NOT NULL
);

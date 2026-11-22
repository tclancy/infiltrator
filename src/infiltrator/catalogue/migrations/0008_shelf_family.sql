-- The game each shelf row is, remembered when it is placed. A shelf row whose
-- set has left the games table (its zip went, or FBNeo was switched off) is
-- otherwise a set name and nothing more, and could not be swapped back for
-- that game's MAME 2003-Plus set. Nullable: a row placed before this, whose
-- set is already gone, has no way to say. Still no key into games.
ALTER TABLE shelf ADD COLUMN family TEXT;
UPDATE shelf SET family = (
    SELECT g.family FROM games g
    WHERE g.emulator = shelf.emulator AND g.set_name = shelf.set_name
);

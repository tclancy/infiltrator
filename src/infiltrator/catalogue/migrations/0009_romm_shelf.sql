-- With the shelf as a RomM collection: the shelf that collection was last made
-- to hold (JSON, platform -> set names). Changing the shelf then moves no file,
-- so a shelf that differs from this is what tells the next run RomM must hear.
ALTER TABLE tv ADD COLUMN romm_shelf TEXT;

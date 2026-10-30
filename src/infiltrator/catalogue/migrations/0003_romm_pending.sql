-- 1 while RomM has not yet been told about the last change to its folders.
-- Every later sieve retries, so a RomM outage heals itself.
ALTER TABLE tv ADD COLUMN romm_pending INTEGER NOT NULL DEFAULT 0;

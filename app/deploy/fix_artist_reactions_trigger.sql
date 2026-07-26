-- ============================================================================
-- Diagnose + fix: "record 'new' has no field 'reaction'" on artist_reactions
-- ============================================================================
-- Root cause: a Postgres trigger function attached to the artist_reactions
-- table references NEW.reaction, but that table's actual column is named
-- "sentiment" (same as track_reactions -- see db/SUTMusic_db/artist_reaction_db.py
-- scalar_fields). track_reactions inserts work fine, which is why only the
-- artist-side write was failing.
--
-- Run the SELECT first to see exactly what's attached and what it does,
-- THEN pick ONE of the two fix options below based on what you find --
-- don't run the DROP blindly if the trigger turns out to do something the
-- app doesn't already handle in Python.

-- 1) List every trigger on artist_reactions and the function each one calls
SELECT
    t.tgname            AS trigger_name,
    p.proname            AS function_name,
    pg_get_triggerdef(t.oid) AS trigger_definition
FROM pg_trigger t
JOIN pg_proc p ON p.oid = t.tgfunction
WHERE t.tgrelid = 'artist_reactions'::regclass
  AND NOT t.tgisinternal;

-- 2) Show the full source of each function found above (replace the name)
SELECT prosrc
FROM pg_proc
WHERE proname = '<function_name_from_step_1>';

-- ----------------------------------------------------------------------------
-- Option A -- the trigger only auto-updates artists.likes_count /
-- dislikes_count / reactions_count (i.e. it duplicates what
-- webapp/repository.py:set_reaction already does explicitly from Python
-- after this migration). In that case, just fix the column reference from
-- "reaction" to "sentiment" inside the function body (edit and re-run
-- CREATE OR REPLACE FUNCTION ... with the corrected NEW.sentiment
-- reference), OR drop the trigger entirely since the app already covers it:
--
--   DROP TRIGGER <trigger_name> ON artist_reactions;
--
-- (Do NOT drop the function itself if the same function is also used by a
-- trigger on track_reactions or elsewhere -- check pg_trigger for other
-- uses of the same function name first:)
SELECT tgname, tgrelid::regclass AS table_name
FROM pg_trigger
WHERE tgfunction = (SELECT oid FROM pg_proc WHERE proname = '<function_name_from_step_1>')
  AND NOT tgisinternal;

-- ----------------------------------------------------------------------------
-- Option B -- the trigger does something else entirely (logging, a
-- notification, a materialized view refresh, etc.) that you still want.
-- In that case just fix the typo'd column name inside the function body:
--
--   CREATE OR REPLACE FUNCTION <function_name>() RETURNS trigger AS $$
--   BEGIN
--       -- wherever the body currently says NEW.reaction, change it to
--       -- NEW.sentiment
--       ...
--   END;
--   $$ LANGUAGE plpgsql;

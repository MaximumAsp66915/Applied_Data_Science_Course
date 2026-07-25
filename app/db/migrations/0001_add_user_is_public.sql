-- Adds the profile-visibility toggle used by webapp/routers/users.py and
-- model/objects/user.py (SCALAR_FIELDS now includes "is_public").
--
-- Run this against BOTH databases -- the internal_db and the external_db
-- (see db/internal_db/internal_db_session.session and
-- db/external_db/external_db_session.session) -- since model/objects/user.py
-- writes every scalar field to both on create()/update_parameter().
--
-- Existing rows default to TRUE (public), so nobody's profile that was
-- previously viewable suddenly becomes private after this migration.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_public BOOLEAN NOT NULL DEFAULT true;

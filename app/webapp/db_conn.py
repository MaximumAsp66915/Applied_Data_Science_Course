"""
Gives the webapp a raw handle on the *same* internal Postgres connection the
bot's model layer (model/SUTMusic/*.py) already uses, so we can:

  1. Use the cached Model classes (Track, Artist, TrackReaction, User, Chat,
     UserMusicBotState, Cover) for single-entity reads/writes -- this is where
     the caching in model/ actually pays off (hot get_parameter/update_parameter
     paths), and
  2. Drop down to `conn.fetch_all(query, *params)` / `conn.search_rows(...)`
     for list/search/join-style queries the model layer doesn't expose a
     one-shot method for (e.g. "latest 15 tracks", "tracks by an artist").

All Internal_DB_* classes (Track, Artist, TrackReaction, User, Chat,
UserMusicBotState, Cover, ...) load the identical encrypted session file
(db/internal_db/internal_db_session.session), so they all point at the same
physical database -- reusing one of their `.db` handles here is safe and
avoids opening a redundant connection pool.
"""

from db.internal_db.SUTMusic.track_internal_db import Internal_DB_Track

# Triggers (lazy) creation of the shared asyncpg pool on first real query.
_owner = Internal_DB_Track()

# Raw PostgreSQL helper: has get_row / search_rows / fetch_all / update_row /
# insert_and_return_id / execute_raw_query, see db/postgreSQL_helper.py
conn = _owner.db

"""Column definitions mirrored from db/SUTMusic_db/*.py and db/user_db.py so
the webapp can call `conn.search_rows(...)` (see db/postgreSQL_helper.py) for
list/search endpoints without re-deriving these sets by hand everywhere."""

TRACKS = dict(
    table_name="tracks",
    scalar_fields={
        "id", "file_id", "unique_file_id", "file_type", "mime_type", "extension",
        "title", "duration", "performer", "cover_id", "album_id", "chat_id",
        "message_id", "score", "rank", "likes_count", "dislikes_count",
        "reactions_count", "created_at", "updated_at",
    },
    array_fields={"artists_id", "uploaded_by"},
    jsonb_fields={"metadata"},
)
TRACKS["columns"] = list(TRACKS["scalar_fields"] | TRACKS["array_fields"] | TRACKS["jsonb_fields"])

ARTISTS = dict(
    table_name="artists",
    scalar_fields={
        "id", "name", "cover_id", "description", "score", "rank",
        "likes_count", "dislikes_count", "reactions_count", "created_at", "updated_at",
    },
    array_fields=set(),
    jsonb_fields={"metadata"},
)
ARTISTS["columns"] = list(ARTISTS["scalar_fields"] | ARTISTS["array_fields"] | ARTISTS["jsonb_fields"])

USERS = dict(
    table_name="users",
    scalar_fields={
        "id", "user_id", "language_code", "is_bot", "is_premium", "is_verified",
        "flag", "is_public", "created_at", "updated_at", "last_activity_at",
    },
    array_fields=set(),
    jsonb_fields={"username", "first_name", "last_name", "profile_photo", "bio", "birthday", "activity"},
)
USERS["columns"] = list(USERS["scalar_fields"] | USERS["array_fields"] | USERS["jsonb_fields"])

USER_STATE = dict(
    table_name="user_musicbot_state",
    scalar_fields={
        "user_id", "cover_id", "description", "total_likes", "total_dislikes",
        "total_reactions", "total_received_likes", "total_received_dislikes",
        "total_received_reactions", "total_uploaded_tracks", "score", "rank",
        "created_at", "updated_at",
    },
    array_fields=set(),
    jsonb_fields={"recent_actions", "metadata"},
)
USER_STATE["columns"] = list(USER_STATE["scalar_fields"] | USER_STATE["array_fields"] | USER_STATE["jsonb_fields"])

TRACK_REACTIONS = dict(
    table_name="track_reactions",
    scalar_fields={
        "id", "track_id", "user_id", "reaction_id", "sentiment", "on_user_id",
        "message_id", "genre_id", "reacted_at",
    },
    array_fields=set(),
    jsonb_fields=set(),
)
TRACK_REACTIONS["columns"] = list(TRACK_REACTIONS["scalar_fields"])

COVERS = dict(
    table_name="covers",
    scalar_fields={
        "id", "file_id", "unique_file_id", "file_format", "mime_type", "file_size",
        "file_url", "width", "height", "uploaded_by", "source", "created_at", "updated_at",
    },
    array_fields=set(),
    jsonb_fields={"metadata"},
)
COVERS["columns"] = list(COVERS["scalar_fields"] | COVERS["array_fields"] | COVERS["jsonb_fields"])

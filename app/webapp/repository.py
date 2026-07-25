"""
Data access layer for the webapp. Every function here maps 1:1 to something
a router needs -- same contract as the original placeholder repository.py,
just backed by the real SUTMusic bot database instead of guessed SQL.

Two access patterns are used on purpose:

  * Single-entity reads/writes go through the cached Model classes in
    `model/` (Track, Artist, TrackReaction, User, Chat, UserMusicBotState,
    ReactionType, Playlist, PlaylistTracks) -- this is where the
    AutoExpiringDict caching in that layer actually helps (hot
    get_parameter/update_parameter paths), and it's how reactions/counters
    stay perfectly consistent with what the Telegram bot itself does.
  * List/search/analytics queries (latest tracks, search, leaderboard,
    "who reacts to me the most") go through `webapp.db_conn.conn`, the same
    physical connection the model layer uses, via `search_rows` / `fetch_all`
    -- these need joins or bulk ordering the per-object model layer doesn't
    expose as a single call, so one raw query is far cheaper than N look-ups.

NOTE: every low-level call going through `conn` (search_rows, fetch_all,
execute_raw_query, get_row, ...) is wrapped by PostgreSQL_wrapper
(db/postgreSQL_helper.py) and ALWAYS returns a `Result` object, never the
raw rows directly -- `result.data` is the actual payload. `_fetch_all()`
below is the one place that unwrapping happens for raw `conn.fetch_all`
calls; every call site in this file goes through it rather than awaiting
`conn.fetch_all` directly (a previous direct call in get_track_queue was
exactly this bug: `nxt = await conn.fetch_all(...)` followed by `nxt[0]`
crashed with "'Result' object is not subscriptable" since `nxt` was the
Result, not a list).
"""

from __future__ import annotations
import asyncio
import random
import httpx
from . import schema
from . import lastfm as lastfm_client
from . import enrichment_queue
from .cache import top_lists_cache
from .db_conn import conn
from .media import cover_url_for
import asyncio
import random
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from model.objects.chat import Chat
from model.objects.user import User
from model.SUTMusic.track import Track
from model.SUTMusic.artist import Artist
from model.SUTMusic.track_reaction import TrackReaction
from model.SUTMusic.reaction_type import ReactionType
from model.SUTMusic.user_musicbot_state import UserMusicBotState
from model.SUTMusic.cover import Cover
from model.SUTMusic.playlist import Playlist
from model.SUTMusic.playlist_tracks import PlaylistTracks

from . import schema
from . import lastfm as lastfm_client
from .cache import top_lists_cache
from .db_conn import conn
from .config import settings

Row = dict[str, Any]

_DEFAULT_EMOJI = {"like": "\U0001F44D", "dislike": "\U0001F44E"}  # 👍 / 👎
_reaction_id_cache: dict[str, int] = {}

DEFAULT_PLAYLIST_NAME = "__default__"
DEFAULT_PLAYLIST_MAX_SIZE = 100
default_playlist_cursor_cache: dict[int, int] = {}


async def _reaction_id_for_sentiment(sentiment: str) -> Optional[int]:
    if sentiment in _reaction_id_cache:
        return _reaction_id_cache[sentiment]
    rt = await ReactionType.get_by_emoji(_DEFAULT_EMOJI[sentiment])
    if rt is None:
        matches = await ReactionType.search_reactions(conditions={"sentiment": ("=", sentiment)}, limit=1)
        rt = matches[0] if matches else None
    if rt is None:
        return None
    rid = await rt.get_parameter("id")
    if rid is None:
        return None
    _reaction_id_cache[sentiment] = rid
    return rid


def _rows(records) -> list[Row]:
    return [dict(r) for r in records]


async def _search(spec: dict, conditions: dict, **kwargs) -> list[Row]:
    result = await conn.search_rows(
        conditions=conditions,
        returning_columns=spec["columns"],
        table_name=spec["table_name"],
        scalar_fields=spec["scalar_fields"],
        array_fields=spec["array_fields"],
        jsonb_fields=spec["jsonb_fields"],
        **kwargs,
    )
    return result.data if result.success and result.data else []


async def _get_row(table_name: str, conditions: dict) -> Optional[Row]:
    result = await conn.get_row(table_name, conditions)
    if result.success and result.data:
        return dict(result.data)
    return None


async def _fetch_all(query: str, *params) -> list[Row]:
    """conn.fetch_all() is wrapped by PostgreSQL_wrapper and always returns a
    Result, never a bare list -- unwrap it here so call sites can treat the
    return value as a plain list of rows."""
    result = await conn.fetch_all(query, *params)
    if isinstance(result, list):  # defensive: tolerate an unwrapped return too
        return result
    return _rows(result.data) if result.success and result.data else []


# ---------------------------------------------------------------------------
# Users / auth
# ---------------------------------------------------------------------------

async def upsert_user_from_telegram(tg_user: dict) -> Row:
    """Called on every login (see routers/auth.py). Mirrors exactly what the
    Telegram bot's own `chat_checker` / `user_checker` do (see
    controller/bot/bots/SUT_Music_bot.py) so a person who has interacted with
    the bot in the group and one who only opens the Mini App end up as the
    *same* row -- linked through the Chat.user_id foreign key."""
    chat_id = int(tg_user["id"])
    first_name = tg_user.get("first_name")
    last_name = tg_user.get("last_name")
    username = tg_user.get("username")
    photo_url = tg_user.get("photo_url")
    language_code = tg_user.get("language_code")
    is_premium = bool(tg_user.get("is_premium", False))

    chat = await Chat.get_by_id(chat_id)
    if chat is None:
        result = await Chat.create(chat_id=chat_id, chat_type="private")
        chat = result.data if result.success else await Chat.get_by_id(chat_id)
        if chat is not None:
            await chat.assign_chat_fields(first_name=first_name, last_name=last_name, username=username)

    user = await Chat.get_user_by_chat_id(chat_id)
    if user is None:
        result = await User.create()
        if not result.success:
            raise RuntimeError(f"Failed creating user for chat {chat_id}: {result.error_message}")
        user = result.data
        await user.assign_user_fields(first_name=first_name, last_name=last_name, username=username)
        if chat is None:
            chat = await Chat.get_by_id(chat_id)
        await chat.assign_user_id(user.user_id)
    else:
        if username:
            await user.update_parameter("username", username)
        if first_name:
            await user.update_parameter("first_name", first_name)
        if last_name:
            await user.update_parameter("last_name", last_name)

    if photo_url:
        await user.update_parameter("profile_photo", photo_url)
    if language_code:
        await user.update_parameter("language_code", language_code)
    await user.update_parameter("is_premium", is_premium)
    await user.update_parameter("last_activity_at", datetime.now(timezone.utc))

    if await UserMusicBotState.get_by_user_id(user.user_id) is None:
        await UserMusicBotState.create(user.user_id)

    return await get_user(user.user_id)


async def get_user_by_chat_id(chat_id: int) -> Optional[Row]:
    """Resolve a *Telegram* id (what the Mini App/initData gives us) to our
    internal user row, without creating anything."""
    user = await Chat.get_user_by_chat_id(chat_id)
    if user is None:
        return None
    return await get_user(user.user_id)


async def get_user(user_id: int) -> Optional[Row]:
    return await _get_row("users", {"user_id": user_id})


def is_profile_visible(user_row: Row, viewer_id: Optional[int]) -> bool:
    """A profile is visible to its own owner regardless of the setting, and
    to everyone else only when `is_public` is true. Defaults to True (public)
    for any row written before the is_public column existed, so nothing that
    used to be visible suddenly disappears."""
    if viewer_id is not None and int(viewer_id) == int(user_row.get("user_id")):
        return True
    return bool(user_row.get("is_public", True))


async def set_user_visibility(user_id: int, is_public: bool) -> bool:
    user = await User.get_by_id(user_id)
    if user is None:
        return False
    result = await user.update_parameter("is_public", is_public)
    return bool(result and result.success)


async def get_user_stats(user_id: int) -> Optional[Row]:
    return await _get_row("user_musicbot_state", {"user_id": user_id})


async def get_user_tracks(user_id: int, limit: int, offset: int) -> list[Row]:
    """`search_rows` (used everywhere else in this file) doesn't support the
    array "contains" operator, so this one goes through Track.search_tracks
    (model/SUTMusic/track.py), which does -- then resolves full rows."""
    tracks = await Track.search_tracks(
        {"uploaded_by": ("contains", user_id)},
        order_by="likes_count", descending=True, limit=limit + offset,
    ) or []
    rows = [await t.get_track_row() for t in tracks[offset: offset + limit]]
    return [r for r in rows if r]



async def search_users(q: str, limit: int, offset: int) -> list[Row]:
    query = """
        SELECT * FROM users
        WHERE (username::text ILIKE $1 OR first_name::text ILIKE $1 OR last_name::text ILIKE $1)
        ORDER BY last_activity_at DESC NULLS LAST
        LIMIT $2 OFFSET $3;
    """
    result = await conn.execute_raw_query(query, [f"%{q}%", limit, offset])
    return _rows(result.data) if result.success and result.data else []


async def get_top_users(limit: int = 10) -> list[Row]:
    cache_key = ("top_users", limit)
    cached = await top_lists_cache.get(cache_key)
    if cached is not None:
        return cached

    query = """
        SELECT u.*, s.total_received_likes, s.total_received_dislikes,
               s.total_received_reactions, s.total_uploaded_tracks, s.score, s.rank
        FROM user_musicbot_state s
        JOIN users u ON u.user_id = s.user_id
        ORDER BY s.total_received_likes DESC
        LIMIT $1;
    """
    result = await conn.execute_raw_query(query, [limit])
    rows = _rows(result.data) if result.success and result.data else []
    await top_lists_cache.set(cache_key, rows)
    return rows


async def get_user_relations(user_id: int, limit: int = 10) -> dict:
    """Powers the "Community pulse" section of the profile page: who reacts
    to this user's tracks the most (in each direction), who this user
    reacts to the most (in each direction), and their favorite artists."""
    top_likers = await _fetch_all(
        """
        SELECT u.user_id, u.first_name, u.last_name, u.username, u.profile_photo,
               COUNT(*) AS metric
        FROM track_reactions r
        JOIN tracks t ON t.id = r.track_id
        JOIN users u ON u.user_id = r.user_id
        WHERE $1 = ANY(t.uploaded_by) AND r.sentiment = 'like' AND r.user_id != $1
        GROUP BY u.user_id ORDER BY metric DESC LIMIT $2;
        """,
        user_id, limit,
    )
    top_dislikers = await _fetch_all(
        """
        SELECT u.user_id, u.first_name, u.last_name, u.username, u.profile_photo,
               COUNT(*) AS metric
        FROM track_reactions r
        JOIN tracks t ON t.id = r.track_id
        JOIN users u ON u.user_id = r.user_id
        WHERE $1 = ANY(t.uploaded_by) AND r.sentiment = 'dislike' AND r.user_id != $1
        GROUP BY u.user_id ORDER BY metric DESC LIMIT $2;
        """,
        user_id, limit,
    )
    gave_most_likes_to = await _fetch_all(
        """
        SELECT u.user_id, u.first_name, u.last_name, u.username, u.profile_photo,
               COUNT(*) AS metric
        FROM track_reactions r
        JOIN tracks t ON t.id = r.track_id
        JOIN users u ON u.user_id = ANY(t.uploaded_by)
        WHERE r.user_id = $1 AND r.sentiment = 'like' AND u.user_id != $1
        GROUP BY u.user_id ORDER BY metric DESC LIMIT $2;
        """,
        user_id, limit,
    )
    gave_most_dislikes_to = await _fetch_all(
        """
        SELECT u.user_id, u.first_name, u.last_name, u.username, u.profile_photo,
               COUNT(*) AS metric
        FROM track_reactions r
        JOIN tracks t ON t.id = r.track_id
        JOIN users u ON u.user_id = ANY(t.uploaded_by)
        WHERE r.user_id = $1 AND r.sentiment = 'dislike' AND u.user_id != $1
        GROUP BY u.user_id ORDER BY metric DESC LIMIT $2;
        """,
        user_id, limit,
    )
    top_liked_artists = await _fetch_all(
        """
        SELECT a.*, COUNT(*) AS metric
        FROM track_reactions r
        JOIN tracks t ON t.id = r.track_id
        JOIN artists a ON a.id = ANY(t.artists_id)
        WHERE r.user_id = $1 AND r.sentiment = 'like'
        GROUP BY a.id ORDER BY metric DESC LIMIT $2;
        """,
        user_id, limit,
    )

    return {
        "top_likers": top_likers or [],
        "top_dislikers": top_dislikers or [],
        "gave_most_likes_to": gave_most_likes_to or [],
        "gave_most_dislikes_to": gave_most_dislikes_to or [],
        "top_liked_artists": top_liked_artists or [],
    }


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------

async def get_track(track_id: int) -> Optional[Row]:
    return await _get_row("tracks", {"id": track_id})


async def set_track_file_id(track_id: int, file_id: str) -> bool:
    """Overwrites tracks.file_id with a freshly-resolved, Bot-API-valid
    file_id (see media.resolve_message_file_id). Goes through the Track
    model rather than a raw UPDATE so the model layer's param cache
    (track_param_cache) doesn't keep serving the stale value on the next
    get_parameter('file_id') call from anywhere else in the app."""
    track = await Track.get_by_id(track_id)
    if track is None:
        return False
    result = await track.update_parameter("file_id", file_id)
    return bool(result and result.success)


async def get_track_artists(artist_ids: list[int]) -> list[Row]:
    if not artist_ids:
        return []
    return await _search(schema.ARTISTS, {"id": ("in", list(artist_ids))}, limit=len(artist_ids))


async def get_users_by_ids(user_ids: list[int]) -> list[Row]:
    if not user_ids:
        return []
    return await _search(schema.USERS, {"user_id": ("in", list(user_ids))}, limit=len(user_ids))


async def get_user_reaction(track_id: int, user_id: int) -> Optional[str]:
    rows = await _search(
        schema.TRACK_REACTIONS,
        {"track_id": ("=", track_id), "user_id": ("=", user_id)},
        limit=1,
    )
    return rows[0]["sentiment"] if rows else None


async def set_reaction(track_id: int, user_id: int, reaction: Optional[str]) -> None:
    """reaction is 'like' | 'dislike' | None (None clears it). Keeps
    tracks.likes_count/dislikes_count/reactions_count and both the reactor's
    and the uploader's user_musicbot_state totals in sync -- same bookkeeping
    the Telegram bot itself performs on a group reaction.

    Credit for a like/dislike goes to EVERY user in tracks.uploaded_by, since
    that's exactly the set of people the frontend displays under "Shared by"
    (see serializers.serialize_track -> `uploaders`, built from the same
    uploaded_by array via get_users_by_ids). A track re-uploaded by multiple
    people has all of them in uploaded_by, so all of them are shown, and all
    of them should receive credit -- someone whose name isn't shown was never
    added to uploaded_by in the first place and correctly gets nothing."""
    track = await Track.get_by_id(track_id)
    if track is None:
        return

    existing_list = await TrackReaction.search_reactions(
        conditions={"track_id": ("=", track_id), "user_id": ("=", user_id)}, limit=1
    )
    existing = existing_list[0] if existing_list else None
    previous = await existing.get_parameter("sentiment") if existing else None

    if reaction == previous:
        reaction = None  # re-sending the same reaction clears it (toggle off)

    uploaded_by = await track.get_parameter("uploaded_by") or []
    owner_ids = [int(uid) for uid in uploaded_by]

    if reaction is None:
        if existing:
            await existing.delete()
    else:
        reaction_id = await _reaction_id_for_sentiment(reaction)
        if existing:
            await existing.update_parameter("sentiment", reaction)
            if reaction_id:
                await existing.update_parameter("reaction_id", reaction_id)
        else:
            await TrackReaction.create(
                track_id=track_id, user_id=user_id, reaction_id=reaction_id,
                sentiment=reaction, on_user_id=owner_ids[0] if owner_ids else None,
            )

    like_delta = (1 if reaction == "like" else 0) - (1 if previous == "like" else 0)
    dislike_delta = (1 if reaction == "dislike" else 0) - (1 if previous == "dislike" else 0)
    reaction_delta = (1 if reaction else 0) - (1 if previous else 0)

    if like_delta:
        await track.update_count_by("likes_count", like_delta)
    if dislike_delta:
        await track.update_count_by("dislikes_count", dislike_delta)
    if reaction_delta:
        await track.update_count_by("reactions_count", reaction_delta)

    async def _adjust_state(uid: int, likes_key: str, dislikes_key: str, reactions_key: str):
        state = await UserMusicBotState.get_by_user_id(uid)
        if state is None:
            result = await UserMusicBotState.create(uid)
            state = result.data if result.success else None
        if state is None:
            return
        if like_delta:
            await state.update_count_by(likes_key, like_delta)
        if dislike_delta:
            await state.update_count_by(dislikes_key, dislike_delta)
        if reaction_delta:
            await state.update_count_by(reactions_key, reaction_delta)

    await _adjust_state(user_id, "total_likes", "total_dislikes", "total_reactions")
    for owner_id in owner_ids:
        if owner_id != user_id:
            await _adjust_state(
                owner_id, "total_received_likes", "total_received_dislikes", "total_received_reactions"
            )


async def get_latest_tracks(limit: int = 15) -> list[Row]:
    cache_key = ("latest_tracks", limit)
    cached = await top_lists_cache.get(cache_key)
    if cached is not None:
        return cached
    rows = await _search(schema.TRACKS, {}, order_by="created_at", descending=True, limit=limit)
    await top_lists_cache.set(cache_key, rows)
    return rows


async def get_top_tracks(limit: int = 10) -> list[Row]:
    cache_key = ("top_tracks", limit)
    cached = await top_lists_cache.get(cache_key)
    if cached is not None:
        return cached
    rows = await _search(schema.TRACKS, {}, order_by="likes_count", descending=True, limit=limit)
    await top_lists_cache.set(cache_key, rows)
    return rows


async def get_global_track_queue(track_id: int) -> dict:
    """Fallback prev/next for guests (no Telegram session, so no per-user
    playlist to walk): newest/oldest neighbor by created_at, same ordering
    as the home feed. See record_play_and_get_queue for the per-user
    playlist-backed version used for signed-in users."""
    nxt = await _fetch_all(
        "SELECT * FROM tracks WHERE created_at < (SELECT created_at FROM tracks WHERE id = $1) "
        "ORDER BY created_at DESC LIMIT 1;",
        track_id,
    )
    prv = await _fetch_all(
        "SELECT * FROM tracks WHERE created_at > (SELECT created_at FROM tracks WHERE id = $1) "
        "ORDER BY created_at ASC LIMIT 1;",
        track_id,
    )
    return {"next": nxt[0] if nxt else None, "prev": prv[0] if prv else None}


async def get_or_create_default_playlist(user_id: int) -> Optional[int]:
    """Every user gets one auto-managed playlist (name=__default__, never
    shown as a "real" playlist in any UI) that record_play_and_get_queue uses
    as a running log of what they've listened to, in order -- this is what
    makes the Previous button walk back through actual listening history."""
    existing = await Playlist.search_playlists(
        conditions={"owner_id": ("=", user_id), "name": ("=", DEFAULT_PLAYLIST_NAME)},
        limit=1,
    )
    if existing:
        return existing[0].playlist_id

    result = await Playlist.create(
        owner_id=user_id,
        name=DEFAULT_PLAYLIST_NAME,
        description="Auto-generated listening history",
        is_public=False,
    )
    if result.success:
        return result.data.playlist_id
    return None


async def _next_playlist_position(playlist_id: int) -> int:
    rows = await PlaylistTracks.search_playlist_tracks(
        conditions={"playlist_id": ("=", playlist_id)},
        limit=1, order_by="position", descending=True,
    )
    if not rows:
        return 1
    last_pos = await rows[0].get_parameter("position")
    return (last_pos or 0) + 1


async def _trim_default_playlist(playlist_id: int, max_size: int = DEFAULT_PLAYLIST_MAX_SIZE) -> None:
    overflow_rows = await _fetch_all(
        "SELECT id FROM playlist_tracks WHERE playlist_id = $1 "
        "ORDER BY position DESC, added_at DESC, id DESC OFFSET $2;",
        playlist_id,
        max_size,
    )
    for row in overflow_rows:
        entry_id = row.get("id")
        if entry_id is None:
            continue
        await PlaylistTracks(entry_id).delete()


async def _get_default_playlist_track_entry(playlist_id: int, track_id: int) -> Optional[PlaylistTracks]:
    entries = await PlaylistTracks.search_playlist_tracks(
        conditions={"playlist_id": ("=", playlist_id), "track_id": ("=", track_id)},
        limit=1,
        order_by="position",
        descending=True,
    )
    return entries[0] if entries else None


async def _get_default_playlist_track_at_position(playlist_id: int, position: int) -> Optional[PlaylistTracks]:
    entries = await PlaylistTracks.search_playlist_tracks(
        conditions={"playlist_id": ("=", playlist_id), "position": ("=", position)},
        limit=1,
        order_by="position",
        descending=False,
    )
    return entries[0] if entries else None


async def _first_unheard_from_artist_ids(
    artist_ids: list[int], current_track_id: int, listened_ids: set[int]
) -> Optional[Row]:
    ids = list(artist_ids)
    random.shuffle(ids)
    for artist_id in ids:
        candidates = await Track.search_tracks(
            conditions={"artists_id": ("contains", artist_id)}, limit=50
        ) or []
        random.shuffle(candidates)
        for candidate in candidates:
            if candidate.track_id == current_track_id or candidate.track_id in listened_ids:
                continue
            row = await candidate.get_track_row()
            if row:
                return row
    return None


# Only used once the user has genuinely caught up to the live edge of their
# own history (record_play_and_get_queue has no cached "next" playlist entry
# left to replay) -- when the engine is unavailable, this is the chance we
# stay on the current track's own artist(s) before branching out to someone
# else. Product ask: "90 percent chance to suggest a song that has not been
# listened to [...] from that artist, and if not found move up to another
# artist in a random way".
SAME_ARTIST_SUGGESTION_CHANCE = 0.9


async def _suggest_from_engine(user_id: Optional[int]) -> Optional[Row]:
    """Ask the external recommendation engine for a pick, same contract as
    GET /api/suggestions/next (routers/suggestions.py): configured via
    SUGGESTION_ENGINE_URL, returns None (never raises) if it's not
    configured or the call fails for any reason, so the caller can fall
    through to the in-house heuristic below."""
    if not settings.suggestion_engine_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{settings.suggestion_engine_url.rstrip('/')}/suggest",
                params={"user_id": user_id} if user_id else {},
            )
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError, KeyError):
        return None
    track_id = data.get("track_id") or data.get("id")
    return await get_track(track_id) if track_id else None


async def _suggest_unheard_track(
    current_track_id: int, listened_ids: set[int], user_id: Optional[int] = None
) -> Optional[Row]:
    """Next-track suggestion for when the user is at the live edge of their
    history (no cached "next" entry to replay -- see record_play_and_get_queue,
    which only calls this once the user has walked all the way forward
    through anything they've already seen). Priority order:

      1. The external recommendation engine, if SUGGESTION_ENGINE_URL is
         configured and answers successfully.
      2. If the engine is unavailable/errors/has nothing unheard to offer:
         a 90% roll for an unheard track (not in `listened_ids`, i.e. not
         already in the user's default listening-history playlist) by one
         of the current track's own artists.
      3. The other 10% of the time, or whenever that artist has nothing
         unheard left, move on to an artist Last.fm reports as related to
         the current one and that we already have indexed locally, then
         finally to a fully random other artist.
    """
    engine_row = await _suggest_from_engine(user_id)
    if engine_row and engine_row.get("id") not in listened_ids:
        return engine_row

    current = await get_track(current_track_id)
    artist_ids = list((current or {}).get("artists_id") or [])

    if artist_ids and random.random() < SAME_ARTIST_SUGGESTION_CHANCE:
        row = await _first_unheard_from_artist_ids(artist_ids, current_track_id, listened_ids)
        if row:
            return row

    current_artists = await get_track_artists(artist_ids)
    related_names: set[str] = set()
    for artist_row in current_artists:
        name = artist_row.get("name")
        if not name:
            continue
        for related in await lastfm_client.get_related_artist_names(name):
            related_names.add(related.strip().lower())

    if related_names:
        all_artists = await _search(schema.ARTISTS, {}, order_by="id", limit=1000)
        related_artist_ids = [
            a["id"] for a in all_artists
            if a["id"] not in artist_ids and (a.get("name") or "").strip().lower() in related_names
        ]
        if related_artist_ids:
            row = await _first_unheard_from_artist_ids(related_artist_ids, current_track_id, listened_ids)
            if row:
                return row

    # The 10% roll skips straight here -- give the current artist a shot too
    # in case it was skipped above, before finally going fully random.
    if artist_ids:
        row = await _first_unheard_from_artist_ids(artist_ids, current_track_id, listened_ids)
        if row:
            return row

    other_artists = await _search(schema.ARTISTS, {}, order_by="id", limit=200)
    random.shuffle(other_artists)
    remaining_ids = [a["id"] for a in other_artists if a["id"] not in artist_ids]
    return await _first_unheard_from_artist_ids(remaining_ids, current_track_id, listened_ids)


async def record_play_and_get_queue(track_id: int, user_id: int) -> dict:
    """Adds `track_id` to the user's default listening-history playlist as
    an append-only trace, then returns:
      * prev: whatever they listened to immediately before this, per that
        playlist's position ordering
      * next: an unheard suggestion (see _suggest_unheard_track)

    The trace is capped at the most recent DEFAULT_PLAYLIST_MAX_SIZE plays,
    so the oldest entry falls off once the history grows past the limit.
    """
    playlist_id = await get_or_create_default_playlist(user_id)
    if not playlist_id:
        return {"prev": None, "next": None}

    async with PlaylistTracks._lock:
        cached_position = default_playlist_cursor_cache.get(user_id)
        entry = await _get_default_playlist_track_entry(playlist_id, track_id)
        is_new_track = entry is None

        if entry is None:
            position = await _next_playlist_position(playlist_id)
            create_res = await PlaylistTracks.create(
                playlist_id=playlist_id, track_id=track_id, position=position
            )
            if create_res.success:
                entry = create_res.data
            else:
                entry = await _get_default_playlist_track_entry(playlist_id, track_id)

        current_position = await entry.get_parameter("position") if entry else None
        if current_position is not None:
            default_playlist_cursor_cache[user_id] = current_position
        elif cached_position is not None:
            current_position = cached_position

        prev_row = None
        if current_position is not None:
            prev_entry = await _get_default_playlist_track_at_position(playlist_id, current_position - 1)
            if prev_entry is not None:
                prev_track_id = await prev_entry.get_parameter("track_id")
                if prev_track_id is not None:
                    prev_row = await get_track(prev_track_id)

        await _trim_default_playlist(playlist_id)

        listened_entries = await PlaylistTracks.search_playlist_tracks(
            conditions={"playlist_id": ("=", playlist_id)},
            limit=DEFAULT_PLAYLIST_MAX_SIZE,
            order_by="position",
        ) or []
        listened_ids: set[int] = set()
        for e in listened_entries:
            tid = await e.get_parameter("track_id")
            if tid is not None:
                listened_ids.add(tid)

        next_row = None
        if current_position is not None:
            next_entry = await _get_default_playlist_track_at_position(playlist_id, current_position + 1)
            if next_entry is not None:
                next_track_id = await next_entry.get_parameter("track_id")
                if next_track_id is not None:
                    next_row = await get_track(next_track_id)

    next_is_suggestion = False
    if next_row is None:
        # No cached "next" entry -- the user has walked all the way forward
        # through their own history and is at the live edge, so this is the
        # only case where a brand new suggestion (engine or heuristic) gets
        # offered. Going back through prev/next within existing history
        # never hits this branch.
        next_row = await _suggest_unheard_track(track_id, listened_ids, user_id=user_id)
        next_is_suggestion = next_row is not None

    return {"prev": prev_row, "next": next_row, "next_is_suggestion": next_is_suggestion}


async def search_tracks(q: str, limit: int, offset: int) -> list[Row]:
    query = """
        SELECT * FROM tracks WHERE title ILIKE $1 OR performer ILIKE $1
        ORDER BY likes_count DESC LIMIT $2 OFFSET $3;
    """
    result = await conn.execute_raw_query(query, [f"%{q}%", limit, offset])
    return _rows(result.data) if result.success and result.data else []


async def get_cover_file_id(cover_id: int) -> Optional[str]:
    row = await _get_row("covers", {"id": cover_id})
    return row.get("file_id") if row else None


async def get_cover(cover_id: int) -> Optional[Row]:
    return await _get_row("covers", {"id": cover_id})


async def get_or_refresh_lastfm_cover_url(cover_id: int) -> Optional[str]:
    """Serves a Last.fm-backed cover's image URL, re-fetching from Last.fm
    if the stored URL has gone stale/dead (Last.fm's CDN links can expire).
    `cover.metadata` carries what's needed to look the image back up:
    {"lastfm_kind": "artist"} + lastfm_artist, or {"lastfm_kind": "track"} +
    lastfm_artist/lastfm_title. Returns None if the cover isn't Last.fm-backed
    or can't be refreshed."""
    row = await get_cover(cover_id)
    if not row or row.get("source") != "lastfm":
        return None

    file_url = row.get("file_url")
    updated_at = row.get("updated_at")
    if updated_at and getattr(updated_at, "tzinfo", None) is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    is_stale = bool(updated_at and datetime.now(timezone.utc) - updated_at > timedelta(hours=1))

    if file_url and await _url_is_alive(file_url) and not is_stale:
        return file_url

    metadata = row.get("metadata") or {}
    kind = metadata.get("lastfm_kind")
    fresh_url = None
    if kind == "artist" and metadata.get("lastfm_artist"):
        info = await lastfm_client.get_artist_info(metadata["lastfm_artist"])
        images = (info or {}).get("images") or []
        fresh_url = next((img.get("#text") for img in reversed(images) if img.get("#text")), None)
    elif kind == "track" and metadata.get("lastfm_artist") and metadata.get("lastfm_title"):
        info = await lastfm_client.get_track_info(metadata["lastfm_artist"], metadata["lastfm_title"])
        images = ((info or {}).get("album") or {}).get("images") or []
        fresh_url = next((img.get("#text") for img in reversed(images) if img.get("#text")), None)

    if not fresh_url:
        return file_url  # nothing better available -- try the old one anyway

    cover = await Cover.get_by_id(cover_id)
    if cover:
        await cover.update_parameter("file_url", fresh_url)
    return fresh_url


async def _url_is_alive(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.head(url)
            return resp.status_code < 400
    except httpx.HTTPError:
        return False


async def _link_lastfm_cover(existing_cover_id: Optional[int], image_url: Optional[str], metadata: dict) -> Optional[int]:
    """Points a real `cover_id` column at a Last.fm image, stored as a proper
    Cover row (source="lastfm") the same way a Telegram-uploaded cover would
    be -- rather than a loose URL sitting in the artist/track's own metadata.
    Reuses the existing cover row (refreshing its file_url) if one was
    already created this way; never touches a cover_id that points at a
    real Telegram-hosted cover someone actually uploaded."""
    if not image_url:
        return existing_cover_id

    if existing_cover_id:
        existing = await get_cover(existing_cover_id)
        if existing and existing.get("source") == "lastfm":
            cover = await Cover.get_by_id(existing_cover_id)
            if cover:
                await cover.update_parameter("file_url", image_url)
            return existing_cover_id
        # existing_cover_id belongs to a real, uploaded cover -- leave it alone.
        return existing_cover_id

    result = await Cover.create(uploaded_by=None, source="lastfm", metadata=metadata)
    if not result.success:
        return None
    cover = result.data
    await cover.update_parameter("file_url", image_url)
    return cover.cover_id


async def get_track_reaction_details(track_id: int, limit: int = 500) -> list[Row]:
    """Who reacted to this track and with which emoji -- powers the swipe-up
    description sheet's reaction list on the track page."""
    return await _fetch_all(
        """
        SELECT u.user_id, u.first_name, u.last_name, u.username, u.profile_photo,
               r.sentiment, rt.emoji, r.reacted_at
        FROM track_reactions r
        JOIN users u ON u.user_id = r.user_id
        LEFT JOIN reaction_types rt ON rt.id = r.reaction_id
        WHERE r.track_id = $1
        ORDER BY r.reacted_at DESC
        LIMIT $2;
        """,
        track_id, limit,
    )


async def _fetch_and_cache_track_lastfm(row: Row) -> dict:
    metadata = row.get("metadata") or {}
    if metadata.get("lastfm_synced"):
        return metadata

    performer = row.get("performer")
    title = row.get("title")
    if not performer or not title:
        return metadata

    info = await lastfm_client.get_track_info(performer, title)
    if not info:
        return metadata

    new_metadata = dict(metadata)
    new_metadata["lastfm_synced"] = True

    summary = info.get("wiki", {}).get("summary")
    if summary:
        new_metadata["lastfm_summary"] = summary

    track = await Track.get_by_id(row["id"])

    if not row.get("cover_id"):
        album_images = (info.get("album") or {}).get("images") or []
        image_url = next((img.get("#text") for img in reversed(album_images) if img.get("#text")), None)
        cover_id = await _link_lastfm_cover(
            row.get("cover_id"),
            image_url,
            metadata={"lastfm_kind": "track", "lastfm_artist": performer, "lastfm_title": title},
        )
        if cover_id and track:
            await track.update_parameter("cover_id", cover_id)
            row["cover_id"] = cover_id

    if track:
        await track.update_parameter("metadata", new_metadata)
    row["metadata"] = new_metadata
    return new_metadata


async def get_track_description(row: Row) -> Optional[str]:
    """Track "swipe up for details" description text -- DB read ONLY. Never
    calls Last.fm itself; if nothing's cached yet on `metadata.lastfm_summary`
    this simply returns None and the caller is expected to have already
    checked `track_enrichment_pending()` / called `enqueue_track_enrichment()`
    so a background worker fills it in for the *next* request."""
    metadata = row.get("metadata") or {}
    return metadata.get("lastfm_summary")


async def get_track_cover_fallback(row: Row) -> Optional[str]:
    """DB read ONLY -- see get_track_description's docstring. Never blocks
    on Last.fm; a missing cover_id here just means the enrichment job (see
    enqueue_track_enrichment) hasn't landed yet."""
    return cover_url_for(row["cover_id"]) if row.get("cover_id") else None


async def get_artist_cover_fallback(artist_id: int, row: Row) -> Optional[str]:
    """DB read ONLY -- see get_track_description's docstring."""
    cover_id = row.get("cover_id")
    return cover_url_for(cover_id) if cover_id else None


def track_enrichment_pending(row: Row) -> bool:
    """True if this track has never been synced against Last.fm at all --
    i.e. there's still something (a cover, a description, or both) that a
    background job could still fill in. Once `lastfm_synced` is set the
    answer is final either way (found something, or confirmed there's
    nothing to find), so this correctly goes back to False and polling can
    stop even if Last.fm genuinely had no cover/wiki for this track."""
    metadata = row.get("metadata") or {}
    return not metadata.get("lastfm_synced")


def artist_enrichment_pending(row: Row, *, want_description: bool = True, want_cover: bool = True) -> tuple[bool, bool]:
    """Returns (description_pending, cover_pending) for an artist row. Once
    `lastfm_synced` is set both are False regardless of whether Last.fm
    actually had a bio/image -- same reasoning as track_enrichment_pending."""
    metadata = row.get("metadata") or {}
    synced = bool(metadata.get("lastfm_synced"))
    description_pending = want_description and not row.get("description") and not synced
    cover_pending = want_cover and not row.get("cover_id") and not synced
    return description_pending, cover_pending


def enqueue_track_enrichment(row: Row) -> None:
    """Drops a (deduped) Last.fm lookup job for this track onto the shared
    background queue (see webapp/enrichment_queue.py) -- never awaited
    inline, never blocks the caller. No-op if this track was already fully
    synced, or if an identical job is already queued/in-flight."""
    track_id = row.get("id")
    if track_id is None or not track_enrichment_pending(row):
        return
    enrichment_queue.enqueue(f"track:{track_id}", lambda: _fetch_and_cache_track_lastfm(row))


def enqueue_artist_enrichment(artist_id: int, row: Row) -> None:
    """Drops a (deduped) Last.fm lookup job for this artist onto the shared
    background queue. No-op if already fully synced or already queued."""
    description_pending, cover_pending = artist_enrichment_pending(row)
    if not (description_pending or cover_pending):
        return
    enrichment_queue.enqueue(f"artist:{artist_id}", lambda: enrich_artist_with_lastfm(artist_id, row))

# ---------------------------------------------------------------------------
# Artists
# ---------------------------------------------------------------------------

async def get_artist(artist_id: int) -> Optional[Row]:
    return await _get_row("artists", {"id": artist_id})


async def enrich_artist_with_lastfm(artist_id: int, row: Row) -> Row:
    metadata = row.get("metadata") or {}
    if row.get("description") and row.get("cover_id") and metadata.get("lastfm_synced"):
        return row

    name = row.get("name")
    if not name:
        return row

    info = await lastfm_client.get_artist_info(name)
    if not info:
        return row

    artist = await Artist.get_by_id(artist_id)
    if artist is None:
        return row

    if not row.get("description") and info.get("bio", {}).get("summary"):
        await artist.update_parameter("description", info["bio"]["summary"])
        row["description"] = info["bio"]["summary"]

    if not row.get("cover_id"):
        image_url = next(
            (img.get("#text") for img in reversed(info.get("images") or []) if img.get("#text")), None
        )
        cover_id = await _link_lastfm_cover(
            row.get("cover_id"), image_url, metadata={"lastfm_kind": "artist", "lastfm_artist": name}
        )
        if cover_id:
            await artist.update_parameter("cover_id", cover_id)
            row["cover_id"] = cover_id

    new_metadata = dict(metadata)
    new_metadata["lastfm_synced"] = True
    new_metadata["genres"] = info.get("tags") or []
    new_metadata["related_artists"] = [a.get("name") for a in info.get("similar_artists") or [] if a.get("name")]
    await artist.update_parameter("metadata", new_metadata)
    row["metadata"] = new_metadata

    return row

async def get_artist_tracks(artist_id: int, limit: int, offset: int) -> list[Row]:
    tracks = await Track.search_tracks(
        {"artists_id": ("contains", artist_id)},
        order_by="likes_count", descending=True, limit=limit + offset,
    ) or []
    rows = [await t.get_track_row() for t in tracks[offset: offset + limit]]
    return [r for r in rows if r]


async def get_latest_artists(limit: int = 15) -> list[Row]:
    cache_key = ("latest_artists", limit)
    cached = await top_lists_cache.get(cache_key)
    if cached is not None:
        return cached
    rows = await _search(schema.ARTISTS, {}, order_by="created_at", descending=True, limit=limit)
    await top_lists_cache.set(cache_key, rows)
    return rows


async def get_top_artists(limit: int = 10) -> list[Row]:
    cache_key = ("top_artists", limit)
    cached = await top_lists_cache.get(cache_key)
    if cached is not None:
        return cached
    rows = await _search(schema.ARTISTS, {}, order_by="likes_count", descending=True, limit=limit)
    await top_lists_cache.set(cache_key, rows)
    return rows


async def search_artists(q: str, limit: int, offset: int) -> list[Row]:
    query = "SELECT * FROM artists WHERE name ILIKE $1 ORDER BY likes_count DESC LIMIT $2 OFFSET $3;"
    result = await conn.execute_raw_query(query, [f"%{q}%", limit, offset])
    return _rows(result.data) if result.success and result.data else []


# ---------------------------------------------------------------------------
# Suggestions (simple fallback used when no external recommendation engine
# is configured -- see routers/suggestions.py)
# ---------------------------------------------------------------------------

async def suggest_track_for_user(user_id: Optional[int]) -> Optional[Row]:
    if user_id:
        query = """
            SELECT t.* FROM tracks t
            WHERE t.id NOT IN (SELECT track_id FROM track_reactions WHERE user_id = $1)
            ORDER BY t.likes_count DESC, RANDOM() LIMIT 25;
        """
        result = await conn.execute_raw_query(query, [user_id])
        rows = _rows(result.data) if result.success and result.data else []
        if rows:
            return random.choice(rows[:10])
    top = await get_top_tracks(limit=25)
    if not top:
        return None
    return random.choice(top)

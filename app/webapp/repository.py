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
import time
import httpx
from . import schema
from . import lastfm as lastfm_client
from . import fanart as fanart_client
from . import enrichment_queue
from . import engine_client
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
from model.SUTMusic.artist_reaction import ArtistReaction
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
from .cache import recently_liked_artists_cache
from .cache import recently_suggested_cache
from .cache import playback_mode_cache

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
        # Neither the default emoji nor any row with this sentiment exists in
        # reaction_types yet -- create it explicitly rather than giving up.
        result = await ReactionType.create(_DEFAULT_EMOJI[sentiment], sentiment)
        rt = result.data if result.success else None
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


async def get_user_liked_tracks(user_id: int, limit: int, offset: int) -> list[Row]:
    """Tracks this user has liked, most popular (likes) first -- powers the
    profile page's "Liked tracks" rail (see get_user_relations's
    top_liked_artists, the artist-level version of the same idea) and is
    also what the player walks through track-by-track when someone starts
    listening from that rail (see repository._next_profile_liked_track).

    Dedupes by track: the bot's group-chat reaction collection (see
    SUT_Music_bot._collect_reactions) records one track_reactions row per
    Telegram message it saw a reaction on, keyed by message_id -- so if the
    same track (one track_id, merged uploaded_by) was reposted by more than
    one person and this user liked more than one of those postings, there'd
    be several reaction rows for the same (user_id, track_id) pair. Without
    a DISTINCT track_id here, joining straight to tracks would surface that
    same liked song more than once."""
    rows = await _fetch_all(
        """
        SELECT t.* FROM tracks t
        WHERE t.id IN (
            SELECT DISTINCT track_id FROM track_reactions
            WHERE user_id = $1 AND sentiment = 'like'
        )
        ORDER BY t.likes_count DESC, t.id ASC
        LIMIT $2 OFFSET $3;
        """,
        user_id, limit, offset,
    )
    return rows or []



async def search_users(q: str, limit: int, offset: int) -> list[Row]:
    query = """
        SELECT * FROM users
        WHERE (username::text ILIKE $1 OR first_name::text ILIKE $1 OR last_name::text ILIKE $1)
        ORDER BY last_activity_at DESC NULLS LAST
        LIMIT $2 OFFSET $3;
    """
    result = await conn.execute_raw_query(query, [f"%{q}%", limit, offset])
    return _rows(result.data) if result.success and result.data else []


async def get_top_users(limit: int = 10, offset: int = 0) -> list[Row]:
    cache_key = ("top_users", limit, offset)
    cached = await top_lists_cache.get(cache_key)
    if cached is not None:
        return cached

    query = """
        SELECT u.*, s.total_received_likes, s.total_received_dislikes,
               s.total_received_reactions, s.total_uploaded_tracks, s.score, s.rank
        FROM user_musicbot_state s
        JOIN users u ON u.user_id = s.user_id
        ORDER BY s.total_received_likes DESC
        LIMIT $1 OFFSET $2;
    """
    result = await conn.execute_raw_query(query, [limit, offset])
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


async def _apply_received_reaction_change(obj, previous: Optional[str], new: Optional[str]) -> None:
    """Shared 'someone reacted to me' bookkeeping for Track and Artist --
    both expose received_like()/received_dislike()/received_reaction(),
    the same methods the Telegram bot's reaction collector calls on
    track_obj/artist objects (see _collect_reactions). That method is only
    ever additive there, since it's importing each reaction exactly once
    from Telegram's history. Here a user can switch or clear a reaction, so
    the previous sentiment's counts are removed first, then the new one is
    added -- e.g. like -> dislike removes the like credit before adding the
    dislike credit, rather than just adding on top of the old count."""
    if previous == "like":
        await obj.update_count_by(param="likes_count", value=-1)
    elif previous == "dislike":
        await obj.update_count_by(param="dislikes_count", value=-1)
    if previous:
        await obj.update_count_by(param="reactions_count", value=-1)

    if new == "like":
        await obj.received_like()
    elif new == "dislike":
        await obj.received_dislike()
    if new:
        await obj.received_reaction()


async def _apply_user_state_reaction_change(
    state, previous: Optional[str], new: Optional[str], likes_key: str, dislikes_key: str, reactions_key: str
) -> None:
    """Same remove-old-then-add-new pattern as _apply_received_reaction_change,
    for UserMusicBotState -- covers both the reactor's own sent_* totals and
    the uploader's received_* totals (see the two call sites below), mirroring
    the bot's user_state.sent_like()/received_like() etc. calls."""
    if previous == "like":
        await state.update_count_by(likes_key, -1)
    elif previous == "dislike":
        await state.update_count_by(dislikes_key, -1)
    if previous:
        await state.update_count_by(reactions_key, -1)

    if new == "like":
        await state.update_count_by(likes_key, 1)
    elif new == "dislike":
        await state.update_count_by(dislikes_key, 1)
    if new:
        await state.update_count_by(reactions_key, 1)


async def set_reaction(track_id: int, user_id: int, reaction: Optional[str]) -> None:
    """reaction is 'like' | 'dislike' | None (None clears it). Keeps
    tracks/artists likes_count/dislikes_count/reactions_count and both the
    reactor's and the uploader's user_musicbot_state totals in sync -- same
    bookkeeping the Telegram bot itself performs on a group reaction (see
    SUT_Music_bot._collect_reactions), extended to handle a user changing
    their mind: switching like<->dislike removes the old credit before
    adding the new one, and clearing a reaction just removes it.

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
        if reaction_id is None:
            raise RuntimeError(f"Could not resolve a reaction_type id for sentiment={reaction!r}")
        if existing:
            await existing.update_parameter("sentiment", reaction)
            await existing.update_parameter("reaction_id", reaction_id)
        else:
            result = await TrackReaction.create(
                track_id=track_id, user_id=user_id, reaction_id=reaction_id,
                sentiment=reaction, on_user_id=owner_ids[0] if owner_ids else None,
            )
            if not result.success:
                raise RuntimeError(f"Failed to save track reaction: {result.error_message}")

    await _apply_received_reaction_change(track, previous, reaction)

    artist_ids = [int(aid) for aid in (await track.get_parameter("artists_id") or [])]
    try:
        existing_artist_reactions: dict[int, Any] = {}
        if artist_ids:
            for artist_id in artist_ids:
                found = await ArtistReaction.search_reactions(
                    conditions={"artist_id": ("=", artist_id), "user_id": ("=", user_id)}, limit=1
                )
                if found:
                    existing_artist_reactions[artist_id] = found[0]

        if reaction is None:
            for artist_reaction in existing_artist_reactions.values():
                await artist_reaction.delete()
        else:
            for artist_id in artist_ids:
                existing_ar = existing_artist_reactions.get(artist_id)
                if existing_ar:
                    await existing_ar.update_parameter("sentiment", reaction)
                    await existing_ar.update_parameter("reaction_id", reaction_id)
                else:
                    result = await ArtistReaction.create(
                        artist_id=artist_id, user_id=user_id, reaction_id=reaction_id,
                        sentiment=reaction, on_user_id=owner_ids[0] if owner_ids else None,
                    )
                    if not result.success:
                        raise RuntimeError(f"Failed to save artist reaction: {result.error_message}")

        for artist_id in artist_ids:
            await _apply_received_reaction_change(Artist(artist_id), previous, reaction)

        # Session-scoped "just liked this artist" signal -- see
        # cache.recently_liked_artists_cache for why this exists and why
        # it's deliberately separate from the all-time get_liked_artist_ids.
        liked_now = set(await recently_liked_artists_cache.get(user_id) or [])
        if reaction == "like":
            liked_now |= set(artist_ids)
        else:
            liked_now -= set(artist_ids)
        await recently_liked_artists_cache.set(user_id, list(liked_now))
    except Exception:
        # Artist-side bookkeeping is secondary to the track reaction itself
        # (already saved above). A problem here -- e.g. a bad DB trigger on
        # artist_reactions -- shouldn't take down the user's like/dislike or
        # the user/uploader count updates below. Still logged loudly so it
        # doesn't go unnoticed.
        import traceback
        print(f"[set_reaction] artist-side bookkeeping FAILED for track_id={track_id} artist_ids={artist_ids} (track reaction itself was NOT affected):")
        traceback.print_exc()

    async def _adjust_state(uid: int, likes_key: str, dislikes_key: str, reactions_key: str):
        state = await UserMusicBotState.get_by_user_id(uid)
        if state is None:
            result = await UserMusicBotState.create(uid)
            state = result.data if result.success else None
        if state is None:
            return
        await _apply_user_state_reaction_change(state, previous, reaction, likes_key, dislikes_key, reactions_key)

    await _adjust_state(user_id, "total_likes", "total_dislikes", "total_reactions")
    for owner_id in owner_ids:
        if owner_id != user_id:
            await _adjust_state(
                owner_id, "total_received_likes", "total_received_dislikes", "total_received_reactions"
            )


async def get_latest_tracks(limit: int = 15, offset: int = 0) -> list[Row]:
    total = offset + limit
    cache_key = ("latest_tracks", total)
    cached = await top_lists_cache.get(cache_key)
    if cached is None:
        cached = await _search(schema.TRACKS, {}, order_by="created_at", descending=True, limit=total)
        await top_lists_cache.set(cache_key, cached)
    return cached[offset:offset + limit]


async def get_top_tracks(limit: int = 10, offset: int = 0) -> list[Row]:
    total = offset + limit
    cache_key = ("top_tracks", total)
    cached = await top_lists_cache.get(cache_key)
    if cached is None:
        cached = await _search(schema.TRACKS, {}, order_by="likes_count", descending=True, limit=total)
        await top_lists_cache.set(cache_key, cached)
    return cached[offset:offset + limit]


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


async def _remove_entry_and_compact(playlist_id: int, entry: PlaylistTracks, removed_position: int) -> None:
    """Deletes `entry` and shifts every later entry's position down by one,
    so the playlist stays a contiguous 1..N sequence with no gap where the
    removed entry used to sit. Used by record_play_and_get_queue when a
    track that's already in the listening-history playlist gets replayed:
    the old occurrence is removed outright (not left in place, not swapped
    for anything) and the list is compacted before the fresh play is
    appended at the end -- see record_play_and_get_queue for why."""
    await entry.delete()
    later_entries = await PlaylistTracks.search_playlist_tracks(
        conditions={"playlist_id": ("=", playlist_id), "position": (">", removed_position)},
        limit=DEFAULT_PLAYLIST_MAX_SIZE + 1,
        order_by="position",
        descending=False,
    )
    for later_entry in later_entries:
        pos = await later_entry.get_parameter("position")
        if pos is not None:
            await later_entry.update_parameter("position", pos - 1)


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


async def get_reacted_track_ids(user_id: int) -> list[int]:
    """All track ids this user has reacted to at all (like or dislike) --
    used as the exclude set on recommendation-engine calls so it doesn't
    suggest something already reacted to (see routers/suggestions.py)."""
    rows = await _fetch_all("SELECT track_id FROM track_reactions WHERE user_id = $1;", user_id)
    return [r["track_id"] for r in rows]


async def get_liked_artist_ids(user_id: int) -> list[int]:
    """Artist ids this user has positively reacted to, directly or via one
    of their tracks -- every track reaction already mirrors to
    artist_reactions for each of the track's artists (see set_reaction
    above). Used to give the recommendation engine a fresh signal for users
    it wasn't necessarily trained on yet (see engine_client.py)."""
    rows = await _fetch_all(
        "SELECT DISTINCT artist_id FROM artist_reactions WHERE user_id = $1 AND sentiment = 'like';",
        user_id,
    )
    return [r["artist_id"] for r in rows]


async def get_recent_history_exclude_ids(
    user_id: int, liked_artist_ids: Optional[list[int]] = None
) -> list[int]:
    """Track ids from the user's default listening-history playlist (their
    last DEFAULT_PLAYLIST_MAX_SIZE plays -- see get_or_create_default_playlist)
    that should be kept OUT of engine suggestions, since re-suggesting
    something just listened to feels stale.

    One deliberate exception: a track is left OUT of this exclude list (i.e.
    still eligible to be suggested) if any of its artists is in
    `liked_artist_ids` -- an artist the user has *currently* liked. The
    product intent: liking an artist is a strong, fresh signal that should
    open the door back up to that artist's catalog immediately, even for a
    track that's sitting in recent history from days ago. Once that like
    itself ages out of "current" (the caller decides what counts as current
    -- see routers/suggestions.py, which passes the session's liked-artist
    set), the track goes back to being excluded like anything else in
    history.

    Pass liked_artist_ids explicitly rather than refetching it here, since
    callers already have it (or a session-scoped variant of it) on hand and
    the exact scope of "currently liked" is a caller decision, not this
    function's."""
    playlist_id = await get_or_create_default_playlist(user_id)
    if not playlist_id:
        return []
    liked_set = set(liked_artist_ids or [])
    rows = await _fetch_all(
        """
        SELECT t.id AS track_id, t.artists_id AS artists_id
        FROM playlist_tracks pt
        JOIN tracks t ON t.id = pt.track_id
        WHERE pt.playlist_id = $1
        ORDER BY pt.position DESC
        LIMIT $2;
        """,
        playlist_id,
        DEFAULT_PLAYLIST_MAX_SIZE,
    )
    exclude_ids: list[int] = []
    for row in rows:
        track_artist_ids = set(row.get("artists_id") or [])
        if track_artist_ids & liked_set:
            continue  # currently-liked artist -- leave eligible, don't exclude
        exclude_ids.append(row["track_id"])
    return exclude_ids


async def _suggest_from_engine(
    user_id: Optional[int],
    exclude_track_ids: Optional[set[int]] = None,
    implicit_liked_track_id: Optional[int] = None,
    implicit_disliked_track_id: Optional[int] = None,
) -> Optional[Row]:
    """Ask the external recommendation engine for a pick, same contract as
    GET /api/suggestions/next (routers/suggestions.py): configured via
    SUGGESTION_ENGINE_URL, returns None (never raises) if it's not
    configured or the call fails for any reason, so the caller can fall
    through to the in-house heuristic below. Passes along whatever
    already-seen tracks the caller has on hand, and (if the user isn't one
    the engine was trained on) their liked artists as a fallback signal --
    see engine_client.suggest_one.

    `implicit_liked_track_id` / `implicit_disliked_track_id` are a
    one-call-only nudge derived from *behavior* rather than an explicit
    reaction (see record_play_and_get_queue's docstring): a track that
    played to its natural end vs. one the user skipped past. Forwarded
    straight through to the engine for this single request and nowhere
    else -- never persisted to our database or to the engine's own state,
    and never used when the track already has a real like/dislike, since
    that's a strictly stronger signal the engine gets some other way."""
    reacted_artist_ids = await get_liked_artist_ids(user_id) if user_id else None
    data = await engine_client.suggest_one(
        user_id=user_id,
        reacted_artist_ids=reacted_artist_ids,
        exclude_track_ids=list(exclude_track_ids) if exclude_track_ids else None,
        implicit_liked_track_id=implicit_liked_track_id,
        implicit_disliked_track_id=implicit_disliked_track_id,
    )
    if not data:
        return None
    return await get_track(data["track_id"])


async def _suggest_unheard_track(
    current_track_id: int,
    listened_ids: set[int],
    user_id: Optional[int] = None,
    implicit_liked_track_id: Optional[int] = None,
    implicit_disliked_track_id: Optional[int] = None,
) -> Optional[Row]:
    """SUPERSEDED / no longer called from record_play_and_get_queue -- kept
    only for reference. The artist-cascade + related-artist-metadata logic
    this used to provide (engine -> same-artist roll -> Last.fm-related ->
    random) now lives in _next_artist_chain_track, driven through
    _get_next_for_active_program, which additionally distinguishes *why*
    the user is listening (an artist page vs. a profile's track list vs.
    the feed, etc.) rather than always running this one heuristic. Safe to
    delete once nothing else needs the old behavior as a reference.

    Original docstring, left intact below for that reference value:

    Next-track suggestion for when the user is at the live edge of their
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

    On top of `listened_ids`, every pick this function makes for `user_id`
    within the current session is remembered in recently_suggested_cache
    (the same cache routers/suggestions.py's "try another" uses) and
    excluded from every subsequent call -- so a track the *suggestion
    engine* already handed the user once this session never comes back
    around a second time, even after it ages out of the last-100-play
    history that `listened_ids` covers. This says nothing about the
    user's own default playlist: they can still walk back into their
    actual listening history via Prev/Next (see record_play_and_get_queue)
    and replay anything they've genuinely already played.
    """
    already_suggested_ids = (
        set(await recently_suggested_cache.get(user_id) or []) if user_id else set()
    )
    exclude_ids = listened_ids | already_suggested_ids

    async def _remember(row: Optional[Row]) -> Optional[Row]:
        if row and user_id:
            await recently_suggested_cache.set_add_to_list(user_id, row["id"])
        return row

    engine_row = await _suggest_from_engine(
        user_id,
        exclude_track_ids=exclude_ids,
        implicit_liked_track_id=implicit_liked_track_id,
        implicit_disliked_track_id=implicit_disliked_track_id,
    )
    if engine_row and engine_row.get("id") not in exclude_ids:
        return await _remember(engine_row)

    current = await get_track(current_track_id)
    artist_ids = list((current or {}).get("artists_id") or [])

    if artist_ids and random.random() < SAME_ARTIST_SUGGESTION_CHANCE:
        row = await _first_unheard_from_artist_ids(artist_ids, current_track_id, exclude_ids)
        if row:
            return await _remember(row)

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
            row = await _first_unheard_from_artist_ids(related_artist_ids, current_track_id, exclude_ids)
            if row:
                return await _remember(row)

    # The 10% roll skips straight here -- give the current artist a shot too
    # in case it was skipped above, before finally going fully random.
    if artist_ids:
        row = await _first_unheard_from_artist_ids(artist_ids, current_track_id, exclude_ids)
        if row:
            return await _remember(row)

    other_artists = await _search(schema.ARTISTS, {}, order_by="id", limit=200)
    random.shuffle(other_artists)
    remaining_ids = [a["id"] for a in other_artists if a["id"] not in artist_ids]
    row = await _first_unheard_from_artist_ids(remaining_ids, current_track_id, exclude_ids)
    return await _remember(row)


# ---------------------------------------------------------------------------
# Origin-aware "what plays next" programs.
#
# Where the user started listening from changes what "next" even means:
# an artist page keeps cascading through that artist (then a random related
# one, per artists.metadata.related_artists) until the whole reachable web
# runs dry; a profile's shared/liked tracks play through in a fixed order
# and then pause rather than handing off to anything else; the feed and
# top-tracks lists just keep walking their own ordering; and "suggest me a
# song" stays exactly what it always was, a fresh engine pick every time.
#
# `context` (see routers/tracks.py / PlayerContext.jsx) tells this which
# program to run: a specific origin string the first time the user starts
# listening from somewhere ("artist", "top", "feed", "suggestion",
# "profile_sent:<owner_id>", "profile_liked:<owner_id>"), or literally
# "queue" for every subsequent Prev/Next within that same sitting -- at
# which point the active program is read back from playback_mode_cache
# instead of being re-derived, so the frontend never has to keep re-stating
# where a long-running session originally started.
# ---------------------------------------------------------------------------

ARTIST_CHAIN_MAX_HOPS = 25  # guards against a pathological related-artist cycle in one request


def _parse_playback_origin(context: str) -> tuple[str, Optional[int]]:
    """"profile_sent:42" -> ("profile_sent", 42). Anything without a colon
    is its own mode name; anything unrecognized (including plain "home",
    the old default) falls back to "artist" -- the same "keep cascading
    through this artist and its neighbors" behavior that used to be the
    unconditional default for every "what's unheard next" pick."""
    if not context:
        return "artist", None
    if ":" in context:
        mode, _, rest = context.partition(":")
        try:
            return mode, int(rest)
        except ValueError:
            return mode, None
    if context in ("suggestion", "top", "feed"):
        return context, None
    return "artist", None


async def _unheard_artist_tracks(artist_id: int, exclude_ids: set[int]) -> list[Row]:
    tracks = await Track.search_tracks({"artists_id": ("contains", artist_id)}, limit=500) or []
    rows: list[Row] = []
    for t in tracks:
        if t.track_id in exclude_ids:
            continue
        row = await t.get_track_row()
        if row:
            rows.append(row)
    return rows


async def _related_artist_ids_for_chain(artist_id: int, visited: set[int]) -> list[int]:
    """Resolves artists.metadata.related_artists (a list of names, e.g.
    {"related_artists": ["D12", "Bad Meets Evil", ...]}) to local artist
    ids, skipping anything already visited earlier in this same chain
    traversal (cycle guard) -- not a session-wide exclude, since a related
    artist skipped over earlier for being mid-chain can still validly come
    up again as its own fresh seed later."""
    artist_row = await _get_row("artists", {"id": artist_id})
    names = ((artist_row or {}).get("metadata") or {}).get("related_artists") or []
    names = [n.strip() for n in names if isinstance(n, str) and n.strip()]
    if not names:
        return []
    wanted = {n.lower() for n in names}
    all_artists = await _search(schema.ARTISTS, {}, order_by="id", limit=5000)
    return [
        a["id"] for a in all_artists
        if a["id"] not in visited and (a.get("name") or "").strip().lower() in wanted
    ]


async def _next_artist_chain_track(
    user_id: int,
    seed_artist_id: Optional[int],
    exclude_ids: set[int],
    implicit_liked_track_id: Optional[int] = None,
    implicit_disliked_track_id: Optional[int] = None,
) -> tuple[Optional[Row], Optional[int]]:
    """All of `seed_artist_id`'s unheard-this-session tracks; once those run
    out, a random one of its related artists (per its metadata); once
    that artist's own tracks AND its related artists are equally dry,
    THEIR related artists, and so on. Only once that whole reachable web
    comes up empty (or the hop guard trips) does this ask the engine, once,
    for a fresh track to reseed the exact same cascade from -- the recap:
    artist -> random related -> random related-of-related -> ... -> dry?
    -> ask the engine -> resume the cascade from whatever it picked.

    Returns (row_or_None, artist_id_to_remember) -- the second value is
    what the caller should persist as the new "current artist" in
    playback_mode_cache, whether that's just wherever the cascade ended up
    or a freshly engine-reseeded artist.
    """
    visited: set[int] = set()
    artist_id = seed_artist_id

    for _ in range(ARTIST_CHAIN_MAX_HOPS):
        if artist_id is None:
            break
        visited.add(artist_id)
        candidates = await _unheard_artist_tracks(artist_id, exclude_ids)
        if candidates:
            random.shuffle(candidates)
            row = candidates[0]
            await recently_suggested_cache.set_add_to_list(user_id, row["id"])
            return row, artist_id

        related_ids = await _related_artist_ids_for_chain(artist_id, visited)
        if not related_ids:
            artist_id = None
            break
        artist_id = random.choice(related_ids)

    # Barrier: nothing unheard left anywhere in the reachable web (or the
    # chain ran unreasonably long). Ask the engine once to reseed a brand
    # new artist -- the next call resumes the exact same cascade from there.
    engine_row = await _suggest_from_engine(
        user_id,
        exclude_track_ids=exclude_ids,
        implicit_liked_track_id=implicit_liked_track_id,
        implicit_disliked_track_id=implicit_disliked_track_id,
    )
    if not engine_row or engine_row.get("id") in exclude_ids:
        engine_row = await suggest_track_for_user(user_id, exclude_ids=exclude_ids)

    if not engine_row:
        return None, None

    await recently_suggested_cache.set_add_to_list(user_id, engine_row["id"])
    reseed_artist_id = next(iter(engine_row.get("artists_id") or []), None)
    return engine_row, reseed_artist_id


async def _arm_artist_fallback(user_id: int, seed_track_id: int) -> None:
    """Switches the active program over to the artist cascade, seeded from
    `seed_track_id`'s own artist -- used when a fixed-order list program
    (profile sent/liked tracks) runs out. We still return no `next` for
    THIS call (the caller pauses and waits for the user, per the module
    docstring above), but this makes sure the NEXT call -- whenever the
    user presses play again -- picks up the artist logic for the last
    song they played, instead of re-querying the same exhausted list."""
    row = await get_track(seed_track_id)
    artist_id = next(iter((row or {}).get("artists_id") or []), None)
    state = {"mode": "artist"}
    if artist_id is not None:
        state["artist_id"] = artist_id
    await playback_mode_cache.set(user_id, state)


async def _next_in_ordered_tracks(
    ordered_rows: list[Row], current_track_id: int, exclude_ids: set[int]
) -> Optional[Row]:
    """Shared "these tracks in this fixed order, whatever comes right after
    the current one" walk, used by every list-shaped program below
    (a profile's shared/liked tracks, the feed, top tracks). Returns None
    once the list is exhausted -- the caller decides what that means
    (pause for profile lists, "can't run out" in practice for feed/top)."""
    ids_in_order = [r["id"] for r in ordered_rows]
    if current_track_id not in ids_in_order:
        return None
    for row in ordered_rows[ids_in_order.index(current_track_id) + 1:]:
        if row["id"] not in exclude_ids:
            return row
    return None


async def _next_profile_sent_track(owner_id: int, current_track_id: int, exclude_ids: set[int]) -> Optional[Row]:
    """That person's shared tracks, most popular first -- same ordering as
    GET /api/users/{id}/tracks."""
    tracks = await Track.search_tracks({"uploaded_by": ("contains", owner_id)}, limit=2000) or []
    rows: list[Row] = []
    for t in tracks:
        row = await t.get_track_row()
        if row:
            rows.append(row)
    rows.sort(key=lambda r: (-(r.get("likes_count") or 0), r["id"]))
    return await _next_in_ordered_tracks(rows, current_track_id, exclude_ids)


async def _next_profile_liked_track(owner_id: int, current_track_id: int, exclude_ids: set[int]) -> Optional[Row]:
    """That person's liked tracks, most popular first -- powers the
    profile page's "Liked tracks" rail alongside its existing "Artists
    liked most" one. Deduped by track for the same reason as
    get_user_liked_tracks above -- otherwise a track liked via more than
    one reposted message would come up twice while walking this list."""
    rows = await _fetch_all(
        """
        SELECT t.* FROM tracks t
        WHERE t.id IN (
            SELECT DISTINCT track_id FROM track_reactions
            WHERE user_id = $1 AND sentiment = 'like'
        )
        ORDER BY t.likes_count DESC, t.id ASC;
        """,
        owner_id,
    )
    return await _next_in_ordered_tracks(rows, current_track_id, exclude_ids)


async def _next_feed_track(current_track_id: int, exclude_ids: set[int]) -> Optional[Row]:
    """Home's "Latest songs" rail, newest to oldest -- every track in the
    channel, so running out in practice isn't a real concern."""
    current = await get_track(current_track_id)
    if not current or current.get("created_at") is None:
        return None
    rows = await _fetch_all(
        """
        SELECT * FROM tracks WHERE (created_at, id) < ($1, $2)
        ORDER BY created_at DESC, id DESC LIMIT 50;
        """,
        current["created_at"], current_track_id,
    )
    for row in rows:
        if row["id"] not in exclude_ids:
            return row
    return None


async def _next_top_track(current_track_id: int, exclude_ids: set[int]) -> Optional[Row]:
    """Ranks -> Tracks: most liked to least liked."""
    current = await get_track(current_track_id)
    if not current:
        return None
    rows = await _fetch_all(
        """
        SELECT * FROM tracks WHERE (likes_count, id) < ($1, $2)
        ORDER BY likes_count DESC, id DESC LIMIT 50;
        """,
        current.get("likes_count") or 0, current_track_id,
    )
    for row in rows:
        if row["id"] not in exclude_ids:
            return row
    return None


def _latest_history_value(jsonb_value):
    """Same unwrap as serializers._latest -- duplicated locally (rather than
    imported) since serializers.py imports this module, not the other way
    around. first_name/last_name/username/profile_photo are stored as JSONB
    history arrays (either plain scalars or already-unwrapped strings
    depending on the path the row came from); callers here just want the
    current value either way, not the raw history list."""
    if jsonb_value is None:
        return None
    if isinstance(jsonb_value, list):
        if not jsonb_value:
            return None
        last = jsonb_value[-1]
        if isinstance(last, dict):
            return last.get("value")
        return last
    return jsonb_value


async def _playback_source_label(mode: str, owner_id: Optional[int]) -> Optional[str]:
    if mode == "artist":
        return "By artists"
    if mode == "top":
        return "By most liked"
    if mode == "suggestion":
        return "Playing suggestions"
    if mode in ("profile_sent", "profile_liked") and owner_id is not None:
        owner = await get_user(owner_id)
        name = (
            _latest_history_value((owner or {}).get("first_name"))
            or _latest_history_value((owner or {}).get("username"))
            or "them"
        )
        return f"{'Sent' if mode == 'profile_sent' else 'Liked'} by {name}"
    return None


async def _get_next_for_active_program(
    user_id: int,
    context: str,
    current_track_id: int,
    listened_ids: set[int],
    implicit_liked_track_id: Optional[int] = None,
    implicit_disliked_track_id: Optional[int] = None,
) -> tuple[Optional[Row], Optional[str]]:
    """The live-edge dispatcher record_play_and_get_queue calls once the
    user has walked all the way forward through their own history (see its
    docstring) -- picks up whichever program is currently active (module
    docstring above has the full rundown) and returns (next_row, label) --
    `label` is what the frontend shows in place of "Now playing" (see
    SongPage.jsx), None meaning no special label applies."""
    already_suggested_ids = set(await recently_suggested_cache.get(user_id) or [])
    reacted_ids = set(await get_reacted_track_ids(user_id) or [])
    exclude_ids = listened_ids | already_suggested_ids | reacted_ids | {current_track_id}

    if context == "queue":
        state = await playback_mode_cache.get(user_id) or {}
        mode = state.get("mode") or "artist"
        owner_id = state.get("owner_id")
        artist_id = state.get("artist_id")
    else:
        mode, owner_id = _parse_playback_origin(context)
        artist_id = None
        if mode == "artist":
            current_row = await get_track(current_track_id)
            artist_id = next(iter((current_row or {}).get("artists_id") or []), None)
        state = {"mode": mode}
        if owner_id is not None:
            state["owner_id"] = owner_id
        if artist_id is not None:
            state["artist_id"] = artist_id
        await playback_mode_cache.set(user_id, state)

    if mode == "suggestion":
        row = await _suggest_from_engine(
            user_id, exclude_track_ids=exclude_ids,
            implicit_liked_track_id=implicit_liked_track_id,
            implicit_disliked_track_id=implicit_disliked_track_id,
        )
        if row:
            await recently_suggested_cache.set_add_to_list(user_id, row["id"])
        return row, await _playback_source_label(mode, owner_id)

    if mode == "top":
        return await _next_top_track(current_track_id, exclude_ids), await _playback_source_label(mode, owner_id)

    if mode == "feed":
        return await _next_feed_track(current_track_id, exclude_ids), await _playback_source_label(mode, owner_id)

    if mode == "profile_sent" and owner_id is not None:
        row = await _next_profile_sent_track(owner_id, current_track_id, exclude_ids)
        if row:
            return row, await _playback_source_label(mode, owner_id)
        # Exhausted -> pause and wait for the user, per this function's
        # module docstring. But arm the artist cascade off of the
        # last-played track for whenever they DO resume, rather than
        # leaving mode="profile_sent" in the cache to just re-query this
        # same exhausted list forever on every subsequent call.
        await _arm_artist_fallback(user_id, current_track_id)
        return None, None

    if mode == "profile_liked" and owner_id is not None:
        row = await _next_profile_liked_track(owner_id, current_track_id, exclude_ids)
        if row:
            return row, await _playback_source_label(mode, owner_id)
        await _arm_artist_fallback(user_id, current_track_id)
        return None, None

    # Default / "artist": cascade through this artist, then related
    # artists, reseeding via the engine if the whole web runs dry.
    row, new_artist_id = await _next_artist_chain_track(
        user_id, artist_id, exclude_ids,
        implicit_liked_track_id=implicit_liked_track_id,
        implicit_disliked_track_id=implicit_disliked_track_id,
    )
    await playback_mode_cache.set(user_id, {"mode": "artist", "artist_id": new_artist_id})
    return row, (await _playback_source_label("artist", None) if row else None)


async def record_play_and_get_queue(
    track_id: int,
    user_id: int,
    context: str = "home",
    last_track_id: Optional[int] = None,
    last_outcome: Optional[str] = None,
) -> dict:
    """Called every time a track starts playing -- a fresh pick, "next", or
    "prev" alike -- and returns:
      * prev: whatever sits immediately before the (possibly just-moved)
        cursor in the user's default listening-history playlist
      * next: whatever sits immediately after it, or -- only once the user
        has walked all the way forward with nothing cached ahead -- a
        brand new suggestion (see _get_next_for_active_program)
      * next_is_suggestion: whether `next` is one of those brand new picks

    What happens to the playlist itself depends on WHY track_id is now
    playing, and that matters a lot:

      * Pure navigation -- the user pressing Prev/Next over history that's
        already sitting in the playlist (e.g. having listened A, B, C, D,
        they walk back to B, then forward again). Nothing gets deleted,
        moved, or re-appended here; this is just the cursor sliding to a
        different existing row. Getting this wrong is exactly the bug this
        replaces: treating every play as "just listened to this now" and
        bumping it to the end meant walking back to B silently moved B to
        the tail of the list, so pressing Next from B handed back a brand
        new suggestion instead of C -- the rest of the history the user
        hadn't "used up" yet.
      * A genuinely new play -- a fresh pick from Home/Search, a brand new
        suggestion, or (rarer) the engine handing back a same-artist
        repeat that's already buried somewhere in history. This is
        recorded as an append-only trace at the end of the playlist, same
        as before: if `track_id` already had an older occurrence it's
        removed outright first (see _remove_entry_and_compact) so it
        reads as "just listened to this now" and moves to the front of
        the history, rather than silently staying parked at its original
        spot.

    The two are told apart using `default_playlist_cursor_cache[user_id]`,
    which remembers the position of whatever this function last recorded
    as "current" for this user: `track_id` counts as navigation if it
    already sits at that cached position (replaying the current track in
    place) or immediately next to it (one Prev/Next step away); anything
    else -- including a same-artist repeat from days-old history -- is a
    fresh play.

    The trace is capped at the most recent DEFAULT_PLAYLIST_MAX_SIZE plays,
    so the oldest entry falls off once the history grows past the limit --
    only checked on a fresh play, since navigation never grows the list.

    `last_track_id` / `last_outcome` are an ephemeral, request-scoped hint
    from the frontend about the track that was just playing before this
    one started -- "completed" if it played to its natural end, "skipped"
    if the user pressed Next/Prev or "try another" before it finished (see
    PlayerContext.jsx). They're only ever used to lightly nudge the
    external engine's *next* suggestion call (see _get_next_for_active_program),
    only when this play actually reaches that branch (the user is at the
    live edge with nothing cached ahead), and are never written to the
    database or treated as a real reaction -- that's still exclusively
    what the explicit like/dislike buttons do.
    """
    playlist_id = await get_or_create_default_playlist(user_id)
    if not playlist_id:
        return {"prev": None, "next": None, "next_is_suggestion": False}

    async with PlaylistTracks._lock:
        cached_position = default_playlist_cursor_cache.get(user_id)
        existing_entry = await _get_default_playlist_track_entry(playlist_id, track_id)
        existing_position = (
            await existing_entry.get_parameter("position") if existing_entry is not None else None
        )

        is_cursor_move = (
            existing_entry is not None
            and cached_position is not None
            and existing_position in (cached_position - 1, cached_position, cached_position + 1)
        )

        if is_cursor_move:
            entry = existing_entry
            current_position = existing_position
        else:
            if existing_entry is not None:
                # Already in the playlist, but not adjacent to where the
                # user currently is -- not navigation. Remove the old
                # occurrence (compacting the gap) and fall through to
                # appending a fresh entry at the end below, same as any
                # other new play.
                if existing_position is not None:
                    await _remove_entry_and_compact(playlist_id, existing_entry, existing_position)
                else:
                    await existing_entry.delete()

            position = await _next_playlist_position(playlist_id)
            create_res = await PlaylistTracks.create(
                playlist_id=playlist_id, track_id=track_id, position=position
            )
            entry = create_res.data if create_res.success else await _get_default_playlist_track_entry(
                playlist_id, track_id
            )
            current_position = await entry.get_parameter("position") if entry else position

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

        if not is_cursor_move:
            await _trim_default_playlist(playlist_id)

        next_row = None
        if current_position is not None:
            next_entry = await _get_default_playlist_track_at_position(playlist_id, current_position + 1)
            if next_entry is not None:
                next_track_id = await next_entry.get_parameter("track_id")
                if next_track_id is not None:
                    next_row = await get_track(next_track_id)

        listened_ids: set[int] = set()
        if next_row is None:
            listened_entries = await PlaylistTracks.search_playlist_tracks(
                conditions={"playlist_id": ("=", playlist_id)},
                limit=DEFAULT_PLAYLIST_MAX_SIZE,
                order_by="position",
            ) or []
            for e in listened_entries:
                tid = await e.get_parameter("track_id")
                if tid is not None:
                    listened_ids.add(tid)

    next_is_suggestion = False
    next_source_label = None
    if next_row is None:
        # No cached "next" entry -- the user has walked all the way forward
        # through their own history and is at the live edge, so this is the
        # only case where a brand new pick (from whichever program is
        # active -- see _get_next_for_active_program) gets offered, and the
        # only case where the implicit like/dislike hint above is actually
        # relevant. Going back and forth through existing history never
        # hits this branch.
        implicit_liked_track_id = last_track_id if last_outcome == "completed" else None
        implicit_disliked_track_id = last_track_id if last_outcome == "skipped" else None
        next_row, next_source_label = await _get_next_for_active_program(
            user_id,
            context,
            track_id,
            listened_ids,
            implicit_liked_track_id=implicit_liked_track_id,
            implicit_disliked_track_id=implicit_disliked_track_id,
        )
        next_is_suggestion = next_row is not None

    if next_source_label is None:
        # Either this was pure history navigation (no fresh pick made this
        # call) or the active program's own label helper returned nothing
        # -- either way, fall back to whatever program is on record for
        # this user so the label stays put for the whole session, not just
        # the exact call that made a fresh pick.
        active_state = await playback_mode_cache.get(user_id) or {}
        next_source_label = await _playback_source_label(
            active_state.get("mode"), active_state.get("owner_id")
        )

    return {
        "prev": prev_row,
        "next": next_row,
        "next_is_suggestion": next_is_suggestion,
        "next_source_label": next_source_label,
    }


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


# Cover.source values that mean "we linked this to an external image
# ourselves" (as opposed to "telegram", a real user upload) -- used to
# decide which covers are eligible for the stale-URL refresh path below,
# and which existing rows _link_lastfm_cover is allowed to overwrite.
EXTERNAL_COVER_SOURCES = {"lastfm", "fanart"}


async def get_or_refresh_lastfm_cover_url(cover_id: int) -> Optional[str]:
    """Serves an externally-linked cover's image URL, re-fetching it if the
    stored URL has gone stale/dead (both Last.fm's and fanart.tv's CDN links
    can expire). `cover.metadata` carries what's needed to look the image
    back up: {"lastfm_kind": "artist"} + lastfm_artist (+ "cover_source":
    "fanart" | "lastfm", defaulting to "lastfm" for covers created before
    fanart.tv was wired in), or {"lastfm_kind": "track"} +
    lastfm_artist/lastfm_title (tracks are always Last.fm-sourced -- fanart.tv
    is only used for artist covers). Returns None if the cover isn't
    externally-linked or can't be refreshed."""
    row = await get_cover(cover_id)
    if not row or row.get("source") not in EXTERNAL_COVER_SOURCES:
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
    # Older covers (created before fanart.tv was wired in) won't have a
    # cover_source recorded -- they were always Last.fm-sourced.
    cover_source = metadata.get("cover_source", "lastfm")
    fresh_url = None
    if kind == "artist" and metadata.get("lastfm_artist"):
        if cover_source == "fanart":
            fresh_url = await fanart_client.get_artist_cover_url(metadata["lastfm_artist"])
        if not fresh_url:
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


async def _link_lastfm_cover(
    existing_cover_id: Optional[int], image_url: Optional[str], metadata: dict
) -> Optional[int]:
    """Points a real `cover_id` column at an externally-sourced image (Last.fm
    or fanart.tv), stored as a proper Cover row the same way a
    Telegram-uploaded cover would be -- rather than a loose URL sitting in
    the artist/track's own metadata. The Cover row's `source` column is set
    to whichever service actually provided the image (`metadata["cover_source"]`,
    defaulting to "lastfm" for track covers which are always Last.fm-sourced)
    so routers/media.py and get_or_refresh_lastfm_cover_url know which
    service to go back to on a refresh.
    Reuses the existing cover row (refreshing its file_url/source) if one was
    already created this way; never touches a cover_id that points at a
    real Telegram-hosted cover someone actually uploaded."""
    if not image_url:
        return existing_cover_id

    source = metadata.get("cover_source", "lastfm")

    if existing_cover_id:
        existing = await get_cover(existing_cover_id)
        if existing and existing.get("source") in EXTERNAL_COVER_SOURCES:
            cover = await Cover.get_by_id(existing_cover_id)
            if cover:
                await cover.update_parameter("file_url", image_url)
                await cover.update_parameter("source", source)
                await cover.update_parameter("metadata", metadata)
            return existing_cover_id
        # existing_cover_id belongs to a real, uploaded cover -- leave it alone.
        return existing_cover_id

    result = await Cover.create(uploaded_by=None, source=source, metadata=metadata)
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
    """Drops a (deduped) Last.fm lookup job for this track onto the track
    enrichment queue (see webapp/enrichment_queue.py) -- never awaited
    inline, never blocks the caller. No-op if this track was already fully
    synced, or if an identical job is already queued/in-flight.

    Uses its own queue/worker pool, separate from artist enrichment's --
    tracks only ever make one fast Last.fm call, while artist jobs can sit
    on a slow MusicBrainz/fanart.tv round trip, so sharing a pool would let
    a burst of slow artist lookups delay fast track covers behind them."""
    track_id = row.get("id")
    if track_id is None or not track_enrichment_pending(row):
        return
    enrichment_queue.track_queue.enqueue(f"track:{track_id}", lambda: _fetch_and_cache_track_lastfm(row))


def enqueue_artist_enrichment(artist_id: int, row: Row) -> None:
    """Drops a (deduped) Last.fm + MusicBrainz/fanart.tv lookup job for this
    artist onto the artist enrichment queue -- its own queue/worker pool,
    separate from track enrichment's (see enqueue_track_enrichment's
    docstring). No-op if already fully synced or already queued."""
    description_pending, cover_pending = artist_enrichment_pending(row)
    if not (description_pending or cover_pending):
        return
    enrichment_queue.artist_queue.enqueue(f"artist:{artist_id}", lambda: enrich_artist_with_lastfm(artist_id, row))


# ---------------------------------------------------------------------------
# Lazy-fetch backfill
#
# Neither enrichment queue should ever just sit empty while there's still a
# track/artist out there with no cover -- these two functions are the
# refill callbacks (see enrichment_queue.EnrichmentQueue.set_refill_callback,
# wired up at the bottom of this section) that each queue calls the moment
# it runs dry.
#
# Two things keep this from getting stuck or stepping on client requests:
#
#   * Priority -- every job scheduled here uses PRIORITY_LAZY, so a real
#     request's PRIORITY_CLIENT job (enqueue_track_enrichment /
#     enqueue_artist_enrichment above) always cuts in front, queued before
#     or after doesn't matter. Lazy jobs only ever spend capacity a client
#     isn't currently asking for.
#   * The checklist -- a track/artist that fanart.tv/Last.fm genuinely has
#     nothing for still isn't re-tried forever: once a job actually runs,
#     `lastfm_synced` gets set (see _fetch_and_cache_track_lastfm /
#     enrich_artist_with_lastfm) and the SQL below excludes it from then on
#     -- that's the permanent "confirmed, nothing there" record. For the
#     in-between case (Last.fm/fanart.tv call itself failed or got rate
#     limited, so `lastfm_synced` is deliberately left unset for a retry),
#     `_lazy_*_last_attempt` below is a short in-memory cooldown so that one
#     stuck row doesn't get re-selected on every single pass and starve
#     everything else -- combined with the round-robin `_lazy_*_cursor`,
#     each pass looks at a fresh slice of the table so the sweep provably
#     works its way through every candidate rather than circling the front.
# ---------------------------------------------------------------------------

# Candidates enqueued per refill pass -- kept modest so a scan is cheap and
# workers get back to blocking on real (possibly client) jobs quickly.
_LAZY_FETCH_BATCH_SIZE = 25

# How long a track/artist that just failed to sync sits out before it's
# eligible to be re-selected by the sweep again.
_LAZY_FETCH_COOLDOWN_SECONDS = 15 * 60

_lazy_track_last_attempt: dict[int, float] = {}
_lazy_artist_last_attempt: dict[int, float] = {}
_lazy_track_cursor = 0
_lazy_artist_cursor = 0


async def _lazy_fetch_tracks() -> None:
    """Refill callback for enrichment_queue.track_queue. See this section's
    docstring above for the checklist/priority/round-robin policy."""
    global _lazy_track_cursor
    if not settings.lastfm_api_key:
        return  # nothing this sweep could accomplish without a Last.fm key

    now = time.monotonic()
    query = """
        SELECT id, title, performer, cover_id, metadata
        FROM tracks
        WHERE performer IS NOT NULL AND title IS NOT NULL
          AND cover_id IS NULL
          AND COALESCE((metadata->>'lastfm_synced')::boolean, false) = false
          AND id > $1
        ORDER BY id ASC
        LIMIT $2;
    """
    rows = await _fetch_all(query, _lazy_track_cursor, _LAZY_FETCH_BATCH_SIZE)

    wrapped = False
    if not rows and _lazy_track_cursor != 0:
        # Reached the end of the table with nothing left -- wrap back to the
        # start so this is a genuine round-robin over every track, not a
        # one-shot pass that goes idle forever once it hits the last id.
        wrapped = True
        _lazy_track_cursor = 0
        rows = await _fetch_all(query, 0, _LAZY_FETCH_BATCH_SIZE)

    print(f"[🔎 track lazy-fetch] scan id>{_lazy_track_cursor}{' (wrapped)' if wrapped else ''}: "
          f"{len(rows)} candidate(s) with no cover yet")
    if not rows:
        return  # nothing left in the whole table that isn't already covered/synced

    scheduled, skipped_cooldown, skipped_pending = 0, 0, 0
    for row in rows:
        track_id = row["id"]
        _lazy_track_cursor = max(_lazy_track_cursor, track_id)
        key = f"track:{track_id}"

        last_attempt = _lazy_track_last_attempt.get(track_id)
        if last_attempt is not None and now - last_attempt < _LAZY_FETCH_COOLDOWN_SECONDS:
            skipped_cooldown += 1
            continue
        if enrichment_queue.track_queue.is_pending(key):
            skipped_pending += 1
            continue

        _lazy_track_last_attempt[track_id] = now
        if enrichment_queue.track_queue.enqueue(
            key, lambda r=row: _fetch_and_cache_track_lastfm(r), priority=enrichment_queue.PRIORITY_LAZY,
        ):
            scheduled += 1

    print(f"[🔎 track lazy-fetch] scheduled {scheduled}, skipped {skipped_cooldown} (cooldown) / "
          f"{skipped_pending} (already pending) -- cursor now id>{_lazy_track_cursor}")


async def _lazy_fetch_artists() -> None:
    """Refill callback for enrichment_queue.artist_queue. See this section's
    docstring above for the checklist/priority/round-robin policy."""
    global _lazy_artist_cursor
    if not settings.lastfm_api_key and not settings.fanart_api_key:
        return  # neither service configured -- nothing this sweep could fetch

    now = time.monotonic()
    query = """
        SELECT id, name, cover_id, description, metadata
        FROM artists
        WHERE name IS NOT NULL
          AND (cover_id IS NULL OR description IS NULL)
          AND COALESCE((metadata->>'lastfm_synced')::boolean, false) = false
          AND id > $1
        ORDER BY id ASC
        LIMIT $2;
    """
    rows = await _fetch_all(query, _lazy_artist_cursor, _LAZY_FETCH_BATCH_SIZE)

    wrapped = False
    if not rows and _lazy_artist_cursor != 0:
        wrapped = True
        _lazy_artist_cursor = 0
        rows = await _fetch_all(query, 0, _LAZY_FETCH_BATCH_SIZE)

    print(f"[🔎 artist lazy-fetch] scan id>{_lazy_artist_cursor}{' (wrapped)' if wrapped else ''}: "
          f"{len(rows)} candidate(s) -> {[r['id'] for r in rows]}")
    if not rows:
        return

    scheduled, skipped_cooldown, skipped_pending = 0, 0, 0
    for row in rows:
        artist_id = row["id"]
        _lazy_artist_cursor = max(_lazy_artist_cursor, artist_id)
        key = f"artist:{artist_id}"

        last_attempt = _lazy_artist_last_attempt.get(artist_id)
        if last_attempt is not None and now - last_attempt < _LAZY_FETCH_COOLDOWN_SECONDS:
            skipped_cooldown += 1
            continue
        if enrichment_queue.artist_queue.is_pending(key):
            skipped_pending += 1
            continue

        _lazy_artist_last_attempt[artist_id] = now
        if enrichment_queue.artist_queue.enqueue(
            key, lambda aid=artist_id, r=row: enrich_artist_with_lastfm(aid, r), priority=enrichment_queue.PRIORITY_LAZY,
        ):
            scheduled += 1

    print(f"[🔎 artist lazy-fetch] scheduled {scheduled} -> "
          f"{[r['id'] for r in rows if _lazy_artist_last_attempt.get(r['id']) == now]}, "
          f"skipped {skipped_cooldown} (cooldown) / {skipped_pending} (already pending) -- "
          f"cursor now id>{_lazy_artist_cursor}")


enrichment_queue.track_queue.set_refill_callback(_lazy_fetch_tracks)
enrichment_queue.artist_queue.set_refill_callback(_lazy_fetch_artists)


# ---------------------------------------------------------------------------
# Artists
# ---------------------------------------------------------------------------

async def get_artist(artist_id: int) -> Optional[Row]:
    return await _get_row("artists", {"id": artist_id})


async def enrich_artist_with_lastfm(artist_id: int, row: Row) -> Row:
    """Fills in whatever's still missing on an artist row: bio, genre tags,
    related artists, and cover art. Cover art is sourced from fanart.tv
    first (via a MusicBrainz name->MBID lookup, see webapp/fanart.py) since
    Last.fm's own artist images are frequently missing or just its
    placeholder -- Last.fm's image list is only used as a fallback if
    fanart.tv has nothing. Everything else (bio, tags, related artists)
    still comes exclusively from Last.fm.
    """
    metadata = row.get("metadata") or {}
    if row.get("description") and row.get("cover_id") and metadata.get("lastfm_synced"):
        print(f"[🎵 artist enrichment] artist_id={artist_id} '{row.get('name')}' already fully synced, skipping")
        return row

    name = row.get("name")
    if not name:
        print(f"[🎵 artist enrichment] artist_id={artist_id} has no name, can't look anything up")
        return row

    print(f"[🎵 artist enrichment] artist_id={artist_id} name='{name}' "
          f"(cover_id={row.get('cover_id')}, has_description={bool(row.get('description'))}) -- starting lookup")

    artist = await Artist.get_by_id(artist_id)
    if artist is None:
        print(f"[🎵 artist enrichment] artist_id={artist_id} '{name}' -> no longer exists in DB, aborting")
        return row

    # Fetched regardless of whether fanart.tv finds a cover -- still needed
    # for bio/genres/related-artists below, and used as the cover fallback.
    info = await lastfm_client.get_artist_info(name)

    if not row.get("description") and info and info.get("bio", {}).get("summary"):
        await artist.update_parameter("description", info["bio"]["summary"])
        row["description"] = info["bio"]["summary"]

    if not row.get("cover_id"):
        image_url = await fanart_client.get_artist_cover_url(name)
        cover_source = "fanart"
        if not image_url and info:
            image_url = next(
                (img.get("#text") for img in reversed(info.get("images") or []) if img.get("#text")), None
            )
            cover_source = "lastfm"

        if image_url:
            print(f"[🎵 artist enrichment] artist_id={artist_id} '{name}' -> cover found via {cover_source}")
        else:
            print(f"[🎵 artist enrichment] artist_id={artist_id} '{name}' -> no cover from fanart.tv or Last.fm")

        cover_id = await _link_lastfm_cover(
            row.get("cover_id"),
            image_url,
            metadata={"lastfm_kind": "artist", "lastfm_artist": name, "cover_source": cover_source},
        )
        if cover_id:
            await artist.update_parameter("cover_id", cover_id)
            row["cover_id"] = cover_id

    if not info:
        # Last.fm itself failed -- leave lastfm_synced unset so bio/genres
        # (and, harmlessly, another fanart.tv attempt) get retried next
        # time; any cover fix already landed above regardless.
        print(f"[🎵 artist enrichment] artist_id={artist_id} '{name}' -> Last.fm lookup failed/rate-limited, "
              f"will retry on a future pass (not marked synced)")
        return row

    new_metadata = dict(metadata)
    new_metadata["lastfm_synced"] = True
    new_metadata["genres"] = info.get("tags") or []
    new_metadata["related_artists"] = [a.get("name") for a in info.get("similar_artists") or [] if a.get("name")]
    await artist.update_parameter("metadata", new_metadata)
    row["metadata"] = new_metadata

    print(f"[🎵 artist enrichment] artist_id={artist_id} '{name}' -> done, marked lastfm_synced "
          f"(cover_id={row.get('cover_id')})")
    return row

async def get_artist_tracks(artist_id: int, limit: int, offset: int) -> list[Row]:
    tracks = await Track.search_tracks(
        {"artists_id": ("contains", artist_id)},
        order_by="likes_count", descending=True, limit=limit + offset,
    ) or []
    rows = [await t.get_track_row() for t in tracks[offset: offset + limit]]
    return [r for r in rows if r]


async def get_latest_artists(limit: int = 15, offset: int = 0) -> list[Row]:
    total = offset + limit
    cache_key = ("latest_artists", total)
    cached = await top_lists_cache.get(cache_key)
    if cached is None:
        cached = await _search(schema.ARTISTS, {}, order_by="created_at", descending=True, limit=total)
        await top_lists_cache.set(cache_key, cached)
    return cached[offset:offset + limit]


async def get_top_artists(limit: int = 10, offset: int = 0) -> list[Row]:
    total = offset + limit
    cache_key = ("top_artists", total)
    cached = await top_lists_cache.get(cache_key)
    if cached is None:
        cached = await _search(schema.ARTISTS, {}, order_by="likes_count", descending=True, limit=total)
        await top_lists_cache.set(cache_key, cached)
    return cached[offset:offset + limit]


async def search_artists(q: str, limit: int, offset: int) -> list[Row]:
    query = "SELECT * FROM artists WHERE name ILIKE $1 ORDER BY likes_count DESC LIMIT $2 OFFSET $3;"
    result = await conn.execute_raw_query(query, [f"%{q}%", limit, offset])
    return _rows(result.data) if result.success and result.data else []


# ---------------------------------------------------------------------------
# Suggestions (simple fallback used when no external recommendation engine
# is configured -- see routers/suggestions.py)
# ---------------------------------------------------------------------------

async def suggest_track_for_user(user_id: Optional[int], exclude_ids: Optional[set[int]] = None) -> Optional[Row]:
    exclude_ids = exclude_ids or set()
    if user_id:
        query = """
            SELECT t.* FROM tracks t
            WHERE t.id NOT IN (SELECT track_id FROM track_reactions WHERE user_id = $1)
            ORDER BY t.likes_count DESC, RANDOM() LIMIT 25;
        """
        result = await conn.execute_raw_query(query, [user_id])
        rows = _rows(result.data) if result.success and result.data else []
        rows = [r for r in rows if r.get("id") not in exclude_ids] or rows
        if rows:
            return random.choice(rows[:10])
    top = await get_top_tracks(limit=25)
    top = [r for r in top if r.get("id") not in exclude_ids] or top
    if not top:
        return None
    return random.choice(top)

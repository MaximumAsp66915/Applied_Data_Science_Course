import httpx
from fastapi import APIRouter, Depends, HTTPException, Body, Request
from fastapi.responses import StreamingResponse

from ..telegram_auth import require_telegram_user, optional_telegram_user, TelegramUser
from .. import repository as repo
from ..serializers import (
    serialize_track,
    serialize_track_reaction,
    serialize_artist_brief,
    serialize_user_brief,
)
from ..media import open_telegram_stream, resolve_telegram_file_url, resolve_message_file_id

router = APIRouter(prefix="/api/tracks", tags=["tracks"])


async def _viewer_id(tg_user: TelegramUser | None) -> int | None:
    if not tg_user:
        return None
    viewer = await repo.get_user_by_chat_id(tg_user["id"])
    return viewer["user_id"] if viewer else None


@router.get("/{track_id}")
async def get_track(track_id: int, tg_user: TelegramUser | None = Depends(optional_telegram_user)):
    row = await repo.get_track(track_id)
    if not row:
        raise HTTPException(404, "Track not found")
    return await serialize_track(row, viewer_id=await _viewer_id(tg_user))


@router.get("/{track_id}/details")
async def get_track_details(track_id: int):
    """GET /api/tracks/{track_id}/details -- everything the swipe-up
    description sheet on the track page needs: a description, who reacted
    and with which emoji, who shared it, and the artist(s), each ready to
    link straight to their own page from the sheet.

    No-prefetch contract: description/cover are read straight from the DB
    and returned immediately -- this endpoint never waits on Last.fm. If
    either hasn't been synced yet, it comes back null with the matching
    `description_pending` / `cover_pending` flag set to true and a
    background enrichment job is queued (see repository.enqueue_track_enrichment).
    The frontend polls this same endpoint again a little later while either
    flag is true, and the sheet fills in once the worker lands the data."""
    row = await repo.get_track(track_id)
    if not row:
        raise HTTPException(404, "Track not found")

    pending = repo.track_enrichment_pending(row)
    if pending:
        repo.enqueue_track_enrichment(row)

    description = await repo.get_track_description(row)
    cover_url = await repo.get_track_cover_fallback(row)
    reactions = await repo.get_track_reaction_details(track_id)
    artists = await repo.get_track_artists(row.get("artists_id") or [])
    uploaders = await repo.get_users_by_ids(row.get("uploaded_by") or [])

    return {
        "description": description,
        "description_pending": pending,
        "cover_url": cover_url,
        "cover_pending": pending,
        "reactions": [serialize_track_reaction(r) for r in reactions],
        "artists": [await serialize_artist_brief(a) for a in artists],
        "uploaders": [serialize_user_brief(u) for u in uploaders],
    }


@router.get("/{track_id}/queue")
async def get_track_queue(
    track_id: int,
    context: str = "home",
    tg_user: TelegramUser | None = Depends(optional_telegram_user),
):
    """-> { prev, next }, used by the player's skip buttons.

    For a signed-in user this both READS and WRITES: it records the current
    track into that user's default "listening history" playlist (creating
    the playlist on first use), which is what lets `prev` walk back through
    what they've actually played, and picks `next` as an unheard track by
    one of the current track's artists (falling back to a random other
    artist once those run out) -- see repo.record_play_and_get_queue.

    Guests (no valid Telegram session) fall back to the old global
    newest/oldest ordering, since there's no per-user history to build.
    """
    viewer_id = await _viewer_id(tg_user)
    if viewer_id:
        data = await repo.record_play_and_get_queue(track_id, viewer_id)
    else:
        data = await repo.get_global_track_queue(track_id)
    return {
        "prev": await serialize_track(data["prev"]) if data.get("prev") else None,
        "next": await serialize_track(data["next"]) if data.get("next") else None,
        "next_is_suggestion": bool(data.get("next_is_suggestion")),
    }


async def _resolve_stream_url(row: dict, track_id: int, range_header: str | None):
    """Returns an already-connected TelegramStream for this track, resolving
    (and persisting) a fresh file_id first if needed. Raises HTTPException on
    failure. All Telegram connection attempts happen here, before the route
    handler returns a StreamingResponse -- see media.py's module docstring
    for why that matters."""
    file_id = row.get("file_id")

    if file_id:
        try:
            url = await resolve_telegram_file_url(file_id)
            return await open_telegram_stream(url, range_header)
        except (httpx.HTTPStatusError, httpx.TransportError):
            pass  # stored file_id is stale/invalid, or Telegram hiccuped -- fall through to re-resolve

    if not row.get("chat_id") or not row.get("message_id"):
        raise HTTPException(404, "Track file unavailable")

    fresh_file_id = await resolve_message_file_id(row["chat_id"], row["message_id"])
    if not fresh_file_id:
        raise HTTPException(404, "Track file unavailable")

    try:
        url = await resolve_telegram_file_url(fresh_file_id)
        stream = await open_telegram_stream(url, range_header)
    except (httpx.HTTPStatusError, httpx.TransportError):
        raise HTTPException(502, "Failed to fetch track from Telegram")

    await repo.set_track_file_id(track_id, fresh_file_id)
    return stream


@router.get("/{track_id}/stream")
async def stream_track(track_id: int, request: Request):
    row = await repo.get_track(track_id)
    if not row:
        raise HTTPException(404, "Track not found")

    media_type = row.get("mime_type") or "audio/mpeg"
    range_header = request.headers.get("range")

    stream = await _resolve_stream_url(row, track_id, range_header)

    headers = {"Accept-Ranges": "bytes"}
    if "content-range" in stream.headers:
        headers["Content-Range"] = stream.headers["content-range"]
    if "content-length" in stream.headers:
        headers["Content-Length"] = stream.headers["content-length"]

    status_code = 206 if stream.status_code == 206 else 200
    return StreamingResponse(
        stream.iter_and_close(),
        status_code=status_code,
        media_type=media_type,
        headers=headers,
    )


@router.post("/{track_id}/reactions")
async def react_to_track(
    track_id: int,
    payload: dict = Body(...),
    tg_user: TelegramUser = Depends(require_telegram_user),
):
    """Body: { "reaction": "like" | "dislike" | null }"""
    reaction = payload.get("reaction")
    if reaction not in ("like", "dislike", None):
        raise HTTPException(400, "reaction must be 'like', 'dislike', or null")

    viewer = await repo.get_user_by_chat_id(tg_user["id"])
    if not viewer:
        # First-time Mini App visitor who skipped /api/auth/telegram somehow.
        viewer = await repo.upsert_user_from_telegram(tg_user)
    user_id = viewer["user_id"]

    await repo.set_reaction(track_id, user_id, reaction)
    row = await repo.get_track(track_id)
    if not row:
        raise HTTPException(404, "Track not found")
    return await serialize_track(row, viewer_id=user_id)

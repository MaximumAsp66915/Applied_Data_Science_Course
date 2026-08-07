import html

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
from ..media import (
    open_telegram_stream,
    resolve_telegram_file_url,
    resolve_telegram_file_url_local,
    resolve_message_file_id,
    resolve_bot_username,
    copy_track_to_user,
    TelegramSendError,
    TelegramFileTooBigError,
)

router = APIRouter(prefix="/api/tracks", tags=["tracks"])


async def _viewer_id(tg_user: TelegramUser | None) -> int | None:
    if not tg_user:
        return None
    viewer = await repo.get_user_by_chat_id(tg_user["id"])
    return viewer["user_id"] if viewer else None


async def _build_share_caption(track_id: int, row: dict) -> str:
    """Caption attached to a track sent through the download button.

    Deliberately does NOT use `get_public_domain()` here: that URL is a
    trycloudflare.com tunnel that's re-issued on every restart (so old
    captions would dead-link) and, since it's a plain website, opening it
    launches a standalone in-app browser instead of Telegram itself.

    Instead both lines are Telegram deep links, so the whole thing always
    opens back inside Telegram:
      - the track title/performer links straight to this track's song page
        via https://t.me/{bot}?startapp=track_{id} -- App.jsx's start_param
        router (see the START_PARAM_TRACK regex there) reads "track_{id}"
        off of that and navigates to /song/{id} on launch.
      - a second "via ..." line links to the bot itself, for anyone who
        just wants to open the app rather than jump to this one track.

    Uses resolve_bot_username() rather than reading settings.bot_username
    directly: pydantic-settings reads .env once at process start, so if
    BOT_USERNAME was added/edited without a restart, settings.bot_username
    would still read as empty here. resolve_bot_username() covers that --
    it falls back to a live Bot API getMe() call (cached after) whenever
    the settings value is blank -- so this self-heals without needing a
    restart. Both link lines are simply omitted if the username still
    can't be resolved either way (e.g. BOT_TOKEN itself is missing).
    """
    title = row.get("title") or "Untitled track"
    performer = row.get("performer") or "Unknown artist"
    label = html.escape(f"{title} - {performer}")

    bot_username = await resolve_bot_username()
    if not bot_username:
        return label

    deep_link = f"https://t.me/{bot_username}?startapp=track_{track_id}"
    bot_link = f"https://t.me/{bot_username}?startapp"
    return f'<a href="{deep_link}">{label}</a>/<a href="{bot_link}">Via SUT Music</a>'


@router.post("/{track_id}/download")
async def download_track(track_id: int, tg_user: TelegramUser = Depends(require_telegram_user)):
    """Sends this track to whoever pressed the download button, as a copy
    (see media.copy_track_to_user's docstring for why copy vs forward) with
    a caption linking back to the song page. Telegram private chat ids are
    just the user's own id, so `tg_user["id"]` (verified server-side from
    the Mini App's signed init data) IS the destination chat -- no lookup
    needed.

    Returns `{"sent": true}` on success, or `{"sent": false, "reason":
    "not_started"}` if the target has never opened a chat with the bot (or
    has blocked it) -- the frontend uses that specific reason to show a
    "start the bot first" warning instead of a generic failure message.
    Any other Telegram-side failure raises a 502."""
    row = await repo.get_track(track_id)
    if not row:
        raise HTTPException(404, "Track not found")
    if not row.get("chat_id") or not row.get("message_id"):
        raise HTTPException(404, "Track file unavailable")

    caption = await _build_share_caption(track_id, row)
    try:
        await copy_track_to_user(tg_user["id"], row["chat_id"], row["message_id"], caption)
    except TelegramSendError as exc:
        if exc.not_started:
            return {"sent": False, "reason": "not_started"}
        raise HTTPException(502, f"Failed to send track: {exc.description}")

    return {"sent": True}


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
    last_track_id: int | None = None,
    last_outcome: str | None = None,
    tg_user: TelegramUser | None = Depends(optional_telegram_user),
):
    """-> { prev, next, next_is_suggestion, next_source_label }, used by the
    player's skip buttons.

    For a signed-in user this both READS and WRITES: it records the current
    track into that user's default "listening history" playlist (creating
    the playlist on first use), which is what lets `prev` walk back through
    what they've actually played. Once the user reaches the live edge of
    that history, what `next` is depends on where they started listening
    from -- an artist page (or search results) keeps cascading through that
    artist then its related artists; a profile's shared/liked-tracks rail
    plays through in order and then pauses; the feed and top-tracks lists
    walk their own ordering; "Suggest me a song" stays a fresh engine pick
    every time -- see repo._get_next_for_active_program for the full
    rundown and repo.record_play_and_get_queue for how `context` carries
    this from one request to the next. `next_source_label` is what
    SongPage.jsx shows in place of "Now playing" ("By artists", "Sent by
    ...", etc.) to make that logic visible to the user.

    `last_track_id` / `last_outcome` ("completed" | "skipped") are an
    optional, purely behavioral hint about whatever was playing right
    before this track started -- see PlayerContext.jsx and
    repo.record_play_and_get_queue's docstring for exactly how (and how
    little) that gets used: an ephemeral nudge to the engine's next call,
    nothing stored.

    Guests (no valid Telegram session) fall back to the old global
    newest/oldest ordering, since there's no per-user history to build.
    """
    viewer_id = await _viewer_id(tg_user)
    if viewer_id:
        data = await repo.record_play_and_get_queue(
            track_id, viewer_id, context=context, last_track_id=last_track_id, last_outcome=last_outcome
        )
    else:
        data = await repo.get_global_track_queue(track_id)
    return {
        "prev": await serialize_track(data["prev"], viewer_id=viewer_id) if data.get("prev") else None,
        "next": await serialize_track(data["next"], viewer_id=viewer_id) if data.get("next") else None,
        "next_is_suggestion": bool(data.get("next_is_suggestion")),
        "next_source_label": data.get("next_source_label"),
    }


async def _stream_via_local_fallback(file_id: str, range_header: str | None):
    """Attempts playback of an oversized file through the Local Bot API
    Server (settings.telegram_local_api_base), which has a 2000MB download
    limit instead of the public API's 20MB. Returns an open TelegramStream
    on success, or None if no local server is configured or it also fails
    (not running, misconfigured, network error, or the file somehow still
    exceeds its limit too) -- callers treat None as "no fallback available"
    and fail clean rather than propagate a local-server-specific error."""
    try:
        url = await resolve_telegram_file_url_local(file_id)
    except (TelegramFileTooBigError, httpx.HTTPStatusError, httpx.TransportError):
        return None
    if not url:
        return None
    try:
        return await open_telegram_stream(url, range_header)
    except (httpx.HTTPStatusError, httpx.TransportError):
        return None


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
        except TelegramFileTooBigError:
            # Not a stale/invalid file_id -- a fresh one will hit the exact
            # same public-API size limit, so re-resolving via
            # resolve_message_file_id would just burn a forward-message
            # call for nothing. Try the Local Bot API Server fallback
            # (2000MB limit) instead before giving up.
            stream = await _stream_via_local_fallback(file_id, range_header)
            if stream:
                return stream
            raise HTTPException(
                413,
                "Track exceeds the 20MB Bot API download limit and can't be "
                "streamed. Configure TELEGRAM_LOCAL_API_BASE (a Local Bot "
                "API Server) to enable playback for large files.",
            )
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
    except TelegramFileTooBigError:
        # Persist the fresh file_id anyway -- it's valid, just for a file
        # too large for the public API -- so future attempts skip straight
        # to the local-fallback/fast-fail branch instead of re-forwarding
        # the message again.
        await repo.set_track_file_id(track_id, fresh_file_id)
        stream = await _stream_via_local_fallback(fresh_file_id, range_header)
        if stream:
            return stream
        raise HTTPException(
            413,
            "Track exceeds the 20MB Bot API download limit and can't be "
            "streamed. Configure TELEGRAM_LOCAL_API_BASE (a Local Bot API "
            "Server) to enable playback for large files.",
        )
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

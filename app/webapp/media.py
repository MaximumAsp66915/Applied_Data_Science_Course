"""
Cover images and audio are stored as Telegram `file_id`s (see tracks.file_id,
covers.file_id), not public URLs. Telegram file URLs are bot-token-scoped and
expire, so the frontend can't hit api.telegram.org directly -- instead every
cover/audio reference points at our own proxy route, which resolves the
file_id via Bot API `getFile` and streams the bytes through.

NOTE on file_id: values written at ingestion time (SUT_Music_bot.py) come
from the Telethon *userbot* (msg.document.id) -- that's an MTProto document
id, not a Bot-API file_id, so calling getFile with it 400s. The Bot API has
no "read message by id" call, so the only way to recover a real, usable
file_id for an already-archived message is to have the *bot* forward that
message once -- the returned Message object carries a fresh, valid file_id.
resolve_message_file_id() below does exactly that, using tracks.chat_id /
tracks.message_id. Callers persist the result back onto the track row so
this only ever runs once per track.

NOTE on streaming / seeking: open_telegram_stream() forwards the client's
Range header straight through to Telegram's file CDN and passes Telegram's
response status/headers straight back. Without this, the <audio> element has
no way to fetch an arbitrary byte offset, so setting `currentTime` on seek
just restarts playback from 0 (the browser can only "seek" within whatever
prefix of the file it already has buffered). This also means all Telegram
connection attempts happen in the ROUTE HANDLER (open_telegram_stream is
awaited before StreamingResponse is constructed), not inside the streamed
generator -- StreamingResponse has already sent headers to the client by the
time an async generator's body starts executing, so any exception raised
from inside a generator can no longer become a clean HTTP error, it just
blows up the response mid-stream (this is what earlier getFile 400s and
httpx.ConnectTimeouts were showing in the logs).
"""

import httpx

from .config import settings

TELEGRAM_API = "https://api.telegram.org"

# Telegram's file CDN can be slow to establish a connection under load;
# give it real headroom instead of httpx's 5s default, but don't hang forever.
_STREAM_TIMEOUT = httpx.Timeout(connect=15.0, read=30.0, write=15.0, pool=15.0)
_API_TIMEOUT = httpx.Timeout(10.0)

# Substring Telegram's Bot API puts in `description` when `getFile` refuses
# a file because it exceeds the (standard, non-local) Bot API's 20MB
# download limit. This is unrelated to file_id validity -- a fresh file_id
# for the same message will hit the exact same error, so callers must NOT
# treat this like a stale/invalid file_id and re-resolve.
_FILE_TOO_BIG_MARKER = "file is too big"


class TelegramFileTooBigError(Exception):
    """Raised by resolve_telegram_file_url() when Telegram's getFile rejects
    a file purely for exceeding the Bot API's download size limit (20MB on
    the standard API). Distinct from a generic HTTPStatusError so callers
    don't mistake it for a stale/invalid file_id and burn a re-resolve +
    retry loop that can only ever fail the same way again."""

    def __init__(self, file_id: str):
        super().__init__(f"File too big to download via Bot API: {file_id}")
        self.file_id = file_id


def cover_url_for(cover_id: int | None) -> str | None:
    if not cover_id:
        return None
    return f"/api/media/cover/{cover_id}"


def track_stream_path(track_id: int) -> str:
    return f"/api/tracks/{track_id}/stream"


async def resolve_telegram_file_url(file_id: str, *, base: str | None = None) -> str:
    """Calls Bot API getFile against `base` (public api.telegram.org by
    default), returns a short-lived direct download URL.

    Raises TelegramFileTooBigError if the file exceeds the download size
    limit of whichever server `base` points at (20MB on the standard public
    API; 2000MB on a Local Bot API Server run with --local -- see
    settings.telegram_local_api_base). A fresh file_id won't fix this
    against the SAME base, so callers should either retry against a
    different base or surface the error, not re-resolve the file_id.
    Raises httpx.HTTPStatusError for any other rejection (e.g. file_id is
    genuinely invalid/stale)."""
    base = (base or TELEGRAM_API).rstrip("/")
    async with httpx.AsyncClient(timeout=_API_TIMEOUT) as client:
        resp = await client.get(
            f"{base}/bot{settings.bot_token}/getFile",
            params={"file_id": file_id},
            timeout=_API_TIMEOUT,
        )
        if resp.status_code >= 400:
            description = (resp.json().get("description") or "") if resp.content else ""
            if _FILE_TOO_BIG_MARKER in description.lower():
                raise TelegramFileTooBigError(file_id)
            resp.raise_for_status()
        file_path = resp.json()["result"]["file_path"]
        return f"{base}/file/bot{settings.bot_token}/{file_path}"


async def resolve_telegram_file_url_local(file_id: str) -> str | None:
    """Same as resolve_telegram_file_url(), but against the Local Bot API
    Server configured via settings.telegram_local_api_base (2000MB download
    limit instead of the public API's 20MB). Returns None if no local
    server is configured, so callers can treat that as "fallback
    unavailable" with a plain `if`. Still raises TelegramFileTooBigError /
    httpx errors for an actually-configured server that itself fails."""
    if not settings.telegram_local_api_base:
        return None
    return await resolve_telegram_file_url(file_id, base=settings.telegram_local_api_base)


# In-memory cache for resolve_bot_username() below -- a bot's @username
# can't change without a restart happening anyway, so one getMe call per
# process lifetime is enough. None until the first successful resolve.
_bot_username_cache: str | None = None


async def resolve_bot_username() -> str | None:
    """The bot's own @username, used to build the Mini App deep links in
    download captions (routers/tracks.py's _build_share_caption). Prefers
    BOT_USERNAME from .env if it's been set by hand; otherwise resolves it
    once via Bot API `getMe` and caches it for the rest of the process, so
    captions still get real links even if that .env var is left blank.
    Returns None (caller falls back to a plain, link-less caption) if
    BOT_TOKEN is missing/invalid or the call fails."""
    global _bot_username_cache
    if settings.bot_username:
        return settings.bot_username
    if _bot_username_cache:
        return _bot_username_cache
    if not settings.bot_token:
        return None
    try:
        async with httpx.AsyncClient(timeout=_API_TIMEOUT) as client:
            resp = await client.get(f"{TELEGRAM_API}/bot{settings.bot_token}/getMe")
            resp.raise_for_status()
            username = resp.json().get("result", {}).get("username")
    except (httpx.HTTPStatusError, httpx.TransportError):
        return None
    if username:
        _bot_username_cache = username
    return username


class TelegramSendError(Exception):
    """Raised by copy_track_to_user() when Telegram refuses the send.

    `not_started` is True specifically when Telegram's error indicates the
    target user has never opened a chat with this bot (or has blocked it) --
    the one case the caller needs to distinguish from a generic failure, so
    it can tell the user to go start the bot first instead of just "download
    failed"."""

    def __init__(self, description: str, *, not_started: bool = False):
        super().__init__(description)
        self.description = description
        self.not_started = not_started


# Substrings Telegram's Bot API is known to put in `description` when a send
# fails specifically because the target has no open chat with the bot yet
# (never pressed Start), has blocked it, or the account is gone -- as
# opposed to some other, retry-worthy failure (network hiccup, bad
# chat/message id, rate limiting, etc).
_NOT_STARTED_MARKERS = (
    "bot can't initiate conversation",
    "bot was blocked by the user",
    "user is deactivated",
    "chat not found",
)


async def copy_track_to_user(user_chat_id: int, from_chat_id: int, message_id: int, caption: str) -> dict:
    """Delivers a track to `user_chat_id` (a private chat -- Telegram user
    ids double as their private chat id) via Bot API `copyMessage`, sourcing
    the audio from `from_chat_id`/`message_id` (tracks.chat_id/message_id).

    Deliberately copyMessage, not forwardMessage: a forward carries a
    "Forwarded from <channel>" header the user didn't ask to see, and
    forwardMessage can't touch the caption at all. copyMessage sends an
    independent copy of the same media with no such header, and lets us
    replace the caption outright -- exactly what the download button needs
    (see routers/tracks.py's build_share_caption()).

    Raises TelegramSendError (see above) if Telegram rejects the send."""
    async with httpx.AsyncClient(timeout=_API_TIMEOUT) as client:
        resp = await client.post(
            f"{TELEGRAM_API}/bot{settings.bot_token}/copyMessage",
            json={
                "chat_id": user_chat_id,
                "from_chat_id": from_chat_id,
                "message_id": message_id,
                "caption": caption,
                "parse_mode": "HTML",
            },
            timeout=_API_TIMEOUT,
        )
    data = resp.json()
    if resp.status_code >= 400 or not data.get("ok"):
        description = data.get("description") or f"HTTP {resp.status_code}"
        not_started = any(marker in description.lower() for marker in _NOT_STARTED_MARKERS)
        raise TelegramSendError(description, not_started=not_started)
    return data["result"]


async def resolve_message_file_id(chat_id: int, message_id: int) -> str | None:
    """Recovers a Bot-API-valid file_id for a message the bot never received
    live, by forwarding it (via the Bot API, back into the same chat) and
    reading the file_id off the returned Message object. One extra Telegram
    call, no re-run of the ingestion pipeline. Requires the bot account to
    be a member of `chat_id`."""
    async with httpx.AsyncClient(timeout=_API_TIMEOUT) as client:
        resp = await client.post(
            f"{TELEGRAM_API}/bot{settings.bot_token}/forwardMessage",
            json={
                "chat_id": chat_id,
                "from_chat_id": chat_id,
                "message_id": message_id,
                "disable_notification": True,
            },
            timeout=_API_TIMEOUT,
        )
        resp.raise_for_status()
        msg = resp.json()["result"]
        media = msg.get("audio") or msg.get("document") or msg.get("voice")
        return media["file_id"] if media else None


class TelegramStream:
    """Holds an already-established, already-validated connection to
    Telegram's file CDN, plus the httpx client that owns it. Both must be
    closed together once the response body has been fully sent -- see
    iter_and_close() below."""

    __slots__ = ("client", "response")

    def __init__(self, client: httpx.AsyncClient, response: httpx.Response):
        self.client = client
        self.response = response

    @property
    def status_code(self) -> int:
        return self.response.status_code

    @property
    def headers(self) -> httpx.Headers:
        return self.response.headers

    async def iter_and_close(self, chunk_size: int = 64 * 1024):
        try:
            async for chunk in self.response.aiter_bytes(chunk_size):
                yield chunk
        finally:
            await self.response.aclose()
            await self.client.aclose()


async def open_telegram_stream(url: str, range_header: str | None = None) -> TelegramStream:
    """Opens (and validates) the connection to Telegram's file CDN BEFORE
    any bytes are handed to the client -- so a slow/failed connection
    (ConnectTimeout, non-2xx/206 status) raises here, in the route handler,
    where it can still become a clean HTTPException instead of corrupting an
    already-started StreamingResponse.

    If range_header is provided (from the client's own Range request), it is
    forwarded as-is so Telegram serves a 206 Partial Content response,
    enabling real seeking in the <audio> element.
    """
    client = httpx.AsyncClient(timeout=_STREAM_TIMEOUT)
    try:
        headers = {"Range": range_header} if range_header else {}
        request = client.build_request("GET", url, headers=headers)
        response = await client.send(request, stream=True)
        if response.status_code >= 400:
            await response.aclose()
            await client.aclose()
            response.raise_for_status()
        return TelegramStream(client, response)
    except Exception:
        await client.aclose()
        raise

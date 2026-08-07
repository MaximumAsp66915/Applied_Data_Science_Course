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

NOTE on the Local Bot API Server (--local mode): a `telegram-bot-api` server
run with --local (see deploy/start.sh) answers `getFile` completely
differently from the public API. The public API's `file_path` is a relative
path meant to be appended to an HTTP download URL
(`{base}/file/bot{token}/{file_path}`). In --local mode, `file_path` is
instead an ABSOLUTE PATH ON THE LOCAL DISK (under --dir) -- the server
expects you to read the file directly, not download it over HTTP; hitting
`{base}/file/bot{token}/{file_path}` with that absolute path produces a
broken URL and a non-2xx response. resolve_telegram_file_url() below detects
this case and returns a LocalFilePath instead of a URL string;
open_telegram_stream() branches on that to read the file straight off disk
(with manual Range handling) via LocalFileStream, instead of making an httpx
request.
"""

import os
import re

import aiofiles
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


class LocalFilePath:
    """Marker wrapper for a getFile result that turned out to be an absolute
    on-disk path rather than a downloadable URL -- i.e. `base` was a Local
    Bot API Server running in --local mode (see module docstring). Kept
    distinct from a plain `str` so open_telegram_stream() can tell the two
    apart without re-guessing from the string's shape."""

    __slots__ = ("path",)

    def __init__(self, path: str):
        self.path = path


async def resolve_telegram_file_url(
    file_id: str, *, base: str | None = None
) -> str | LocalFilePath:
    """Calls Bot API getFile against `base` (public api.telegram.org by
    default).

    Returns either:
      - a short-lived direct HTTP download URL (str), for the public API or
        a local server NOT run with --local, or
      - a LocalFilePath, when `base` is a Local Bot API Server run with
        --local -- in that mode getFile's file_path is already an absolute
        path on local disk (see module docstring), so there is no HTTP
        download URL to build; callers must read the file directly.

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
        if base != TELEGRAM_API and os.path.isabs(file_path):
            # --local mode: file_path is already a path on local disk, not
            # something to append to a download URL.
            return LocalFilePath(file_path)
        return f"{base}/file/bot{settings.bot_token}/{file_path}"


async def resolve_telegram_file_url_local(file_id: str) -> str | LocalFilePath | None:
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


_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


class LocalFileStream:
    """Same interface as TelegramStream (status_code, headers,
    iter_and_close()), but reads bytes directly off local disk instead of
    over HTTP -- used for a Local Bot API Server run with --local, where
    getFile's file_path is already an absolute path on disk rather than a
    download URL (see module docstring). Range handling has to be done by
    hand here since there's no upstream HTTP server to forward the client's
    Range header to."""

    __slots__ = ("path", "_status_code", "_headers", "_start", "_length")

    def __init__(self, path: str, status_code: int, headers: dict, start: int, length: int):
        self.path = path
        self._status_code = status_code
        self._headers = headers
        self._start = start
        self._length = length

    @property
    def status_code(self) -> int:
        return self._status_code

    @property
    def headers(self) -> dict:
        return self._headers

    async def iter_and_close(self, chunk_size: int = 64 * 1024):
        remaining = self._length
        async with aiofiles.open(self.path, "rb") as f:
            await f.seek(self._start)
            while remaining > 0:
                chunk = await f.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk


async def _open_local_file_stream(path: str, range_header: str | None) -> LocalFileStream:
    """Builds a LocalFileStream for `path`, honoring a client Range header
    the same way Telegram's HTTP file CDN would (206 + Content-Range for a
    valid range, whole file + 200 otherwise) -- see LocalFileStream's
    docstring for why this has to be done by hand instead of forwarded."""
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise httpx.TransportError(f"local file not readable: {path}") from exc

    start, end = 0, size - 1
    status_code = 200
    match = _RANGE_RE.match(range_header) if range_header else None
    if match:
        start_str, end_str = match.groups()
        if start_str:
            start = int(start_str)
            end = int(end_str) if end_str else size - 1
        elif end_str:
            # suffix range, e.g. "bytes=-500" -> last 500 bytes
            start = max(0, size - int(end_str))
            end = size - 1
        end = min(end, size - 1)
        if 0 <= start <= end:
            status_code = 206
        else:
            start, end = 0, size - 1
            status_code = 200

    length = end - start + 1
    headers = {"content-length": str(length)}
    if status_code == 206:
        headers["content-range"] = f"bytes {start}-{end}/{size}"

    return LocalFileStream(path, status_code, headers, start, length)


async def open_telegram_stream(
    url: str | LocalFilePath, range_header: str | None = None
) -> TelegramStream | LocalFileStream:
    """Opens (and validates) the connection to Telegram's file CDN BEFORE
    any bytes are handed to the client -- so a slow/failed connection
    (ConnectTimeout, non-2xx/206 status) raises here, in the route handler,
    where it can still become a clean HTTPException instead of corrupting an
    already-started StreamingResponse.

    If range_header is provided (from the client's own Range request), it is
    forwarded as-is so Telegram serves a 206 Partial Content response,
    enabling real seeking in the <audio> element.

    If `url` is a LocalFilePath (--local mode Local Bot API Server -- see
    module docstring), there's no HTTP request to make at all: this opens
    the file straight off disk instead, applying the same Range semantics
    by hand via _open_local_file_stream().
    """
    if isinstance(url, LocalFilePath):
        return await _open_local_file_stream(url.path, range_header)

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
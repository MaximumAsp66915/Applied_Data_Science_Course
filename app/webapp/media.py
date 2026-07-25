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


def cover_url_for(cover_id: int | None) -> str | None:
    if not cover_id:
        return None
    return f"/api/media/cover/{cover_id}"


def track_stream_path(track_id: int) -> str:
    return f"/api/tracks/{track_id}/stream"


async def resolve_telegram_file_url(file_id: str) -> str:
    """Calls Bot API getFile, returns a short-lived direct download URL.
    Raises httpx.HTTPStatusError if file_id is invalid/stale."""
    async with httpx.AsyncClient(timeout=_API_TIMEOUT) as client:
        resp = await client.get(
            f"{TELEGRAM_API}/bot{settings.bot_token}/getFile",
            params={"file_id": file_id},
            timeout=_API_TIMEOUT,
        )
        resp.raise_for_status()
        file_path = resp.json()["result"]["file_path"]
        return f"{TELEGRAM_API}/file/bot{settings.bot_token}/{file_path}"


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

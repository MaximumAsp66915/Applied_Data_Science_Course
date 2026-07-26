"""
Thin async client for artist *cover art* specifically, via two services
chained together the way the sample script for this feature did:

  1. MusicBrainz (https://musicbrainz.org/doc/MusicBrainz_API) resolves an
     artist name -> MBID (MusicBrainz ID) -- fanart.tv only accepts lookups
     by MBID, not by name.
  2. fanart.tv (https://fanart.tv/api-docs/) returns actual artist images
     (thumb / background) for that MBID.

This exists because Last.fm's own artist.getInfo often comes back with no
usable image (or just its "no image" placeholder) even though everything
else about it -- bio, tags, related artists -- is solid. Last.fm stays the
source of truth for all of that (see lastfm.py); this module is used ONLY
to source the artist cover image, with Last.fm's image list kept as a
fallback in repository.py if fanart.tv comes up empty.

Rate limiting, two different flavors:

  * MusicBrainz enforces (and will start blocking clients that ignore) a
    hard 1 request/second limit for unauthenticated use, and asks for a
    descriptive User-Agent identifying the app -- see
    https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting. _MB_LIMITER
    below is the same token-bucket approach lastfm.py uses, just capped at
    1/sec instead of 5/sec.
  * fanart.tv doesn't publish a fixed requests/second number for project
    keys, but does return 429 with a `Retry-After` header if a key is used
    too aggressively. Rather than a second proactive limiter, `_fetch_fanart`
    honors that header reactively (bounded to a few attempts) -- this is
    the "respect the retry after" the request asked for.

Caching: both the resolved MBID and the fanart.tv result are cached (see
webapp/cache.py) -- an artist's MBID and image set essentially never
change, so a given artist should only ever cost one 1 req/sec MusicBrainz
round trip, not one per lookup.

If FANART_API_KEY isn't configured, get_artist_cover_url() simply returns
None so callers fall back to whatever else they have (Last.fm's image list,
or nothing).
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx

from .config import settings
from .cache import mbid_cache, fanart_cache

MUSICBRAINZ_URL = "https://musicbrainz.org/ws/2/artist/"
FANART_URL_TEMPLATE = "https://webservice.fanart.tv/v3/music/{mbid}"

# MusicBrainz asks automated clients to identify themselves with a real
# app name + contact so they can reach out instead of just banning an IP.
MUSICBRAINZ_USER_AGENT = "SUTMusicApp/1.0 (+https://t.me/SUT_Music_bot)"

MUSICBRAINZ_MAX_REQUESTS_PER_SECOND = 1

# fanart.tv 429 handling: how many times we'll wait-and-retry before giving
# up on this lookup for now (it'll simply be attempted again the next time
# enrichment runs for this artist).
FANART_MAX_RETRIES = 3
FANART_DEFAULT_RETRY_AFTER_SECONDS = 5.0


class _RateLimiter:
    """Token-bucket limiter: guarantees calls through this limiter never
    exceed `rate_per_second`, no matter how many callers show up in the same
    instant -- they simply queue and get spaced out. Identical approach to
    lastfm.py's _RateLimiter, duplicated rather than shared since the two
    services have very different (and independently tunable) rates."""

    def __init__(self, rate_per_second: float):
        self._interval = 1.0 / rate_per_second
        self._lock = asyncio.Lock()
        self._next_slot = 0.0

    async def wait(self):
        async with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._interval
            delay = slot - now
        if delay > 0:
            await asyncio.sleep(delay)


_mb_limiter = _RateLimiter(MUSICBRAINZ_MAX_REQUESTS_PER_SECOND)
_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10.0)
    return _client


async def _get_musicbrainz_mbid(artist_name: str) -> Optional[str]:
    """Resolves an artist name to a MusicBrainz ID, respecting the hard
    1 req/sec MusicBrainz enforces for unauthenticated clients. Cached
    indefinitely-ish (see cache.py's mbid_cache TTL) since an artist's MBID
    never changes."""
    cache_key = ("mbid", artist_name.strip().lower())
    cached = await mbid_cache.get(cache_key)
    if cached is not None:
        return cached

    await _mb_limiter.wait()
    try:
        response = await _get_client().get(
            MUSICBRAINZ_URL,
            params={"query": f"artist:{artist_name}", "fmt": "json", "limit": 1},
            headers={"User-Agent": MUSICBRAINZ_USER_AGENT},
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None

    artists = data.get("artists", [])
    mbid = artists[0].get("id") if artists else None
    if mbid:
        await mbid_cache.set(cache_key, mbid)
    return mbid


async def _fetch_fanart(mbid: str) -> Optional[dict]:
    """Fetches fanart.tv's music entry for an MBID. On a 429, sleeps for
    whatever `Retry-After` it sends back (falling back to a fixed delay if
    that header is missing/malformed) and tries again, up to
    FANART_MAX_RETRIES times, rather than hammering it or giving up
    immediately."""
    url = FANART_URL_TEMPLATE.format(mbid=mbid)
    params = {"api_key": settings.fanart_api_key}
    client = _get_client()

    for _ in range(FANART_MAX_RETRIES):
        try:
            response = await client.get(url, params=params)
        except httpx.HTTPError:
            return None

        if response.status_code == 429:
            retry_after_header = response.headers.get("Retry-After")
            try:
                delay = float(retry_after_header) if retry_after_header else FANART_DEFAULT_RETRY_AFTER_SECONDS
            except ValueError:
                delay = FANART_DEFAULT_RETRY_AFTER_SECONDS
            await asyncio.sleep(delay)
            continue

        if response.status_code != 200:
            return None

        try:
            return response.json()
        except ValueError:
            return None

    return None  # gave up after repeated 429s -- try again next enrichment pass


async def get_artist_cover_url(artist_name: str) -> Optional[str]:
    """Artist thumbnail/background URL for `artist_name`, via
    MusicBrainz -> fanart.tv. Returns None if fanart.tv isn't configured,
    the artist has no MBID, or fanart.tv has no art on file for it.

    Prefers `artistthumb` (a proper portrait-ish image) over
    `artistbackground` (a wide banner), matching the sample script this was
    built from.
    """
    if not artist_name or not settings.fanart_api_key:
        return None

    cache_key = ("fanart_cover", artist_name.strip().lower())
    cached = await fanart_cache.get(cache_key)
    if cached is not None:
        return cached

    mbid = await _get_musicbrainz_mbid(artist_name)
    if not mbid:
        return None

    data = await _fetch_fanart(mbid)
    if not data:
        return None

    thumbs = data.get("artistthumb") or []
    backgrounds = data.get("artistbackground") or []
    url = None
    if thumbs:
        url = thumbs[0].get("url")
    elif backgrounds:
        url = backgrounds[0].get("url")

    if url:
        await fanart_cache.set(cache_key, url)
    return url

"""
Thin async client for the Last.fm API (https://www.last.fm/api), adapted
from the sample script provided for this feature.

Two things every caller here gets "for free":

  * Rate limiting -- Last.fm allows up to ~5 requests/second. `_RateLimiter`
    below is a simple token-bucket so that even if a page full of tracks all
    need a Last.fm lookup at once (e.g. an artist page whose tracks have
    never been enriched before), calls queue up and go out no faster than
    the allowed rate instead of bursting and getting throttled/banned.
  * Caching -- every lookup is cached in `lastfm_cache` (see webapp/cache.py)
    for 6 hours, since artist/track metadata (bio, tags, cover art, related
    artists) essentially never changes on the timescale of this app. This is
    on top of (not instead of) the DB-level persistence in repository.py's
    enrich_artist_with_lastfm / get_track_description, which cache the
    result forever once written -- this in-memory cache mainly absorbs the
    burst of *new* lookups (e.g. many people opening a brand-new artist's
    page around the same time) before that DB write lands.

If LASTFM_API_KEY isn't configured, every function here simply returns None
so the rest of the app keeps working with just the data already in our own
database.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Optional

import httpx

from .config import settings
from .cache import lastfm_cache

LASTFM_BASE_URL = "https://ws.audioscrobbler.com/2.0/"

# Default "missing artwork" avatar hash Last.fm returns instead of omitting
# the image entirely -- filtered out so we never show it as if it were real
# cover art.
LASTFM_PLACEHOLDER_HASH = "2a96cbd8b46e442fc41c2b86b821562f"

MAX_REQUESTS_PER_SECOND = 5


def clean_html(raw_html: Optional[str]) -> str:
    """Strips HTML tags and the trailing "Read more on Last.fm" link Last.fm
    appends to every bio/wiki field, so it's safe to show directly in the UI."""
    if not raw_html:
        return ""
    text = raw_html.split("<a href=")[0]
    return re.sub(r"<[^>]+>", "", text).strip()


def sanitize_images(images: list[dict]) -> list[dict]:
    """Filters out Last.fm's placeholder "no image" entries."""
    valid = []
    for img in images or []:
        url = img.get("#text", "")
        if url and LASTFM_PLACEHOLDER_HASH not in url:
            valid.append(img)
    return valid


class _RateLimiter:
    """Token-bucket limiter: guarantees calls through this limiter never
    exceed `rate_per_second`, no matter how many callers show up in the same
    instant -- they simply queue and get spaced out."""

    def __init__(self, rate_per_second: int = MAX_REQUESTS_PER_SECOND):
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


_limiter = _RateLimiter()
_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            headers={"user-agent": "SUTMusic/1.0"},
            timeout=10.0,
        )
    return _client


async def _fetch(method: str, params: dict) -> Optional[dict]:
    if not settings.lastfm_api_key:
        return None

    payload = {
        "method": method,
        "api_key": settings.lastfm_api_key,
        "format": "json",
        **params,
    }
    await _limiter.wait()
    try:
        response = await _get_client().get(LASTFM_BASE_URL, params=payload)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if "error" in data:
        return None
    return data


def _as_list(value: Any) -> list:
    """Last.fm returns a single dict instead of a list when there's exactly
    one item (tags, similar artists, ...) -- normalize both shapes."""
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return value
    return []


async def get_artist_info(artist_name: str) -> Optional[dict]:
    """Extracts, cleans, and structures artist metadata: bio, tags/genres,
    cover images, and related ("similar") artists."""
    if not artist_name:
        return None
    cache_key = ("artist", artist_name.strip().lower())
    cached = await lastfm_cache.get(cache_key)
    if cached is not None:
        return cached

    data = await _fetch("artist.getInfo", {"artist": artist_name})
    if not data:
        return None
    artist = data.get("artist", {})

    tags_data = _as_list(artist.get("tags", {}).get("tag", []))
    similar_data = _as_list(artist.get("similar", {}).get("artist", []))
    stats = artist.get("stats", {})
    bio = artist.get("bio", {})

    result = {
        "name": artist.get("name"),
        "mbid": artist.get("mbid"),
        "url": artist.get("url"),
        "stats": {
            "listeners": int(stats.get("listeners") or 0),
            "playcount": int(stats.get("playcount") or 0),
        },
        "tags": [tag.get("name") for tag in tags_data if tag.get("name")],
        "similar_artists": [
            {
                "name": sim.get("name"),
                "url": sim.get("url"),
                "images": sanitize_images(sim.get("image", [])),
            }
            for sim in similar_data
        ],
        "images": sanitize_images(artist.get("image", [])),
        "bio": {
            "published": bio.get("published"),
            "summary": clean_html(bio.get("summary")),
            "content": clean_html(bio.get("content")),
        },
    }
    await lastfm_cache.set(cache_key, result)
    return result


async def get_track_info(artist_name: str, track_name: str) -> Optional[dict]:
    """Extracts, cleans, and structures track metadata: wiki/description,
    tags, and album art."""
    if not artist_name or not track_name:
        return None
    cache_key = ("track", artist_name.strip().lower(), track_name.strip().lower())
    cached = await lastfm_cache.get(cache_key)
    if cached is not None:
        return cached

    data = await _fetch("track.getInfo", {"artist": artist_name, "track": track_name})
    if not data:
        return None
    track = data.get("track", {})

    tags_data = _as_list(track.get("toptags", {}).get("tag", []))
    album = track.get("album", {})
    wiki = track.get("wiki", {})

    result = {
        "name": track.get("name"),
        "mbid": track.get("mbid"),
        "url": track.get("url"),
        "listeners": int(track.get("listeners") or 0),
        "playcount": int(track.get("playcount") or 0),
        "album": {
            "title": album.get("title"),
            "images": sanitize_images(album.get("image", [])),
        },
        "tags": [tag.get("name") for tag in tags_data if tag.get("name")],
        "wiki": {
            "published": wiki.get("published"),
            "summary": clean_html(wiki.get("summary")),
            "content": clean_html(wiki.get("content")),
        },
    }
    await lastfm_cache.set(cache_key, result)
    return result


async def get_related_artist_names(artist_name: str) -> list[str]:
    """Just the names Last.fm considers "similar" to this artist -- used by
    repository._suggest_unheard_track to prefer a related artist we already
    have indexed over a fully random one for the Next button."""
    info = await get_artist_info(artist_name)
    if not info:
        return []
    return [a["name"] for a in info.get("similar_artists", []) if a.get("name")]

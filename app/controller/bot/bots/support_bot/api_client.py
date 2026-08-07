"""
Thin async HTTP client around the webapp's own public search API
(``webapp/routers/search.py``). No DB models, no `model.*`/`db.*` imports on
purpose -- this process only ever needs what any other HTTP client of the
Mini App backend would have, which keeps it fully decoupled from (and safe
to run alongside, restart independently of) the Postgres-backed bot/webapp.
"""

import logging
from typing import Any

import httpx

from .config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class SearchUnavailable(Exception):
    """Raised when the webapp API can't be reached or errors out."""


async def search_tracks_and_artists(query: str, limit: int = 8) -> dict[str, list[Any]]:
    """GET /api/search?scope=all -> {"tracks": [...], "artists": [...]}.

    Deliberately drops the "users" list the API can also return -- the
    product ask is searching songs & artists, never Telegram users.
    """
    url = f"{settings.webapp_api_base_url.rstrip('/')}/api/search"
    params = {"q": query, "scope": "all", "limit": limit}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean bot reply
        logger.warning("search API call failed for query=%r: %s", query, exc)
        raise SearchUnavailable(str(exc)) from exc

    return {"tracks": data.get("tracks", []), "artists": data.get("artists", [])}

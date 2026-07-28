"""Thin async client for the standalone recommendation-engine microservice
(engine/main.py, see engine/README.md for the full contract). This is the
one place in the app that knows that HTTP contract -- routers/suggestions.py
and repository.py's _suggest_unheard_track both go through this instead of
hand-rolling an httpx call each, so the contract only has to be gotten
right once and both call sites automatically benefit from richer signal.

The engine is a separate process, reachable only over loopback (see
engine/README.md) -- SUGGESTION_ENGINE_URL should point at
http://127.0.0.1:8100 (its default port) in .env.

Every function here returns None/[] (never raises) on any failure -- not
configured, unreachable, timeout, bad response -- so callers can always
just fall through to their own in-house fallback without a try/except of
their own.
"""
from __future__ import annotations

import httpx

from .config import settings

# Generous enough for a cold model-load-adjacent request, but short enough
# that a hung/unreachable engine never noticeably stalls a track suggestion
# for the person waiting on it -- callers fall back to the in-house
# heuristic (repository.suggest_track_for_user / _suggest_unheard_track)
# well within the time it'd take anyone to notice.
_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


def _ids_param(ids: list[int] | None) -> str | None:
    ids = [str(int(i)) for i in (ids or []) if i is not None]
    return ",".join(ids) if ids else None


async def _get(path: str, params: dict) -> dict | None:
    if not settings.suggestion_engine_url:
        return None
    params = {k: v for k, v in params.items() if v is not None}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{settings.suggestion_engine_url.rstrip('/')}{path}", params=params
            )
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, ValueError):
        return None


async def suggest_one(
    user_id: int | None = None,
    reacted_artist_ids: list[int] | None = None,
    exclude_track_ids: list[int] | None = None,
    implicit_liked_track_id: int | None = None,
    implicit_disliked_track_id: int | None = None,
) -> dict | None:
    """A single next-track pick -> {"track_id": int, "reason": str,
    "source": str}, or None if the engine isn't configured/reachable/has
    nothing to offer.

    `implicit_liked_track_id` / `implicit_disliked_track_id` are a
    one-request-only nudge (a track that played to its end vs. one the
    user skipped past, with no explicit reaction of its own -- see
    repository.record_play_and_get_queue) -- the engine uses these only to
    shape THIS pick and never persists them anywhere."""
    data = await _get(
        "/suggest",
        {
            "user_id": user_id,
            "reacted_artist_ids": _ids_param(reacted_artist_ids),
            "exclude_track_ids": _ids_param(exclude_track_ids),
            "implicit_liked_track_id": implicit_liked_track_id,
            "implicit_disliked_track_id": implicit_disliked_track_id,
        },
    )
    if not data or not data.get("track_id"):
        return None
    return data


async def recommend_many(
    user_id: int | None = None,
    reacted_artist_ids: list[int] | None = None,
    exclude_track_ids: list[int] | None = None,
    top_k: int = 10,
) -> list[int]:
    """Ranked list of track_ids for a "for you" rail / prefetched queue --
    [] if the engine isn't configured/reachable/has nothing to offer."""
    data = await _get(
        "/recommend",
        {
            "user_id": user_id,
            "reacted_artist_ids": _ids_param(reacted_artist_ids),
            "exclude_track_ids": _ids_param(exclude_track_ids),
            "top_k": top_k,
        },
    )
    return (data or {}).get("track_ids") or []


async def onboarding_tracks(count: int = 5, exclude_track_ids: list[int] | None = None) -> list[int]:
    """Cold-start tracks for a brand-new user's first session (manual.txt
    section 5) -- [] if the engine isn't configured/reachable."""
    data = await _get(
        "/onboarding",
        {"count": count, "exclude_track_ids": _ids_param(exclude_track_ids)},
    )
    return (data or {}).get("track_ids") or []

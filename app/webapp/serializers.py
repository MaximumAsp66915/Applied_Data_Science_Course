"""
Turns raw rows (as returned by repository.py, mirroring the Postgres columns)
into the JSON shapes the frontend's api.js expects. Kept separate from
repository.py so the DB layer stays dumb and this stays the one place that
knows about the HTTP contract.
"""

from . import repository as repo
from .media import cover_url_for


async def serialize_track(t: dict, *, viewer_id: int | None = None) -> dict:
    """No-prefetch contract: this NEVER calls Last.fm and never awaits an
    enrichment job -- it reads whatever cover_id/metadata is already on the
    row and returns immediately. If that data hasn't been synced from
    Last.fm yet, `cover_url` comes back null and `cover_pending: true` is
    set alongside it, and a background job is dropped on the queue (see
    repository.enqueue_track_enrichment / webapp/enrichment_queue.py) so a
    worker can fill it in for next time. The frontend is expected to poll
    the same endpoint again after a short delay while `cover_pending` is
    true, and pick up the cover once it lands."""
    artists = await repo.get_track_artists(t.get("artists_id") or [])
    uploaders = await repo.get_users_by_ids(t.get("uploaded_by") or [])
    my_reaction = None
    if viewer_id:
        my_reaction = await repo.get_user_reaction(t["id"], viewer_id)

    cover_pending = repo.track_enrichment_pending(t)
    if cover_pending:
        repo.enqueue_track_enrichment(t)

    return {
        "id": t["id"],
        "title": t.get("title"),
        "performer": t.get("performer"),
        "duration": t.get("duration"),
        "cover_url": cover_url_for(t.get("cover_id")),
        "cover_pending": cover_pending,
        "likes_count": t.get("likes_count", 0),
        "dislikes_count": t.get("dislikes_count", 0),
        "reactions_count": t.get("reactions_count", 0),
        "score": float(t.get("score") or 0),
        "rank": t.get("rank"),
        "artists": [await serialize_artist_brief(a) for a in artists],
        "uploaders": [serialize_user_brief(u) for u in uploaders],
        "my_reaction": my_reaction,
        "created_at": t["created_at"].isoformat() if t.get("created_at") else None,
    }



async def serialize_artist_brief(a: dict) -> dict:
    """Same no-prefetch contract as serialize_track -- see its docstring.
    Brief cards only ever show a cover (never the bio), so only cover
    enrichment is considered/enqueued here."""
    _, cover_pending = repo.artist_enrichment_pending(a, want_description=False)
    if cover_pending:
        repo.enqueue_artist_enrichment(a["id"], a)
    return {
        "id": a["id"],
        "name": a.get("name"),
        "cover_url": await repo.get_artist_cover_fallback(a["id"], a),
        "cover_pending": cover_pending,
        "likes_count": a.get("likes_count", 0),
        "rank": a.get("rank"),
    }


async def serialize_artist_full(a: dict) -> dict:
    """Same no-prefetch contract -- see serialize_track's docstring. The
    full artist page also wants the bio, so description enrichment is
    considered/enqueued here too (brief-level cover enqueue still happens
    inside serialize_artist_brief; the queue dedupes so this never double
    schedules the same job)."""
    metadata = a.get("metadata") or {}
    description_pending, cover_pending = repo.artist_enrichment_pending(a)
    if description_pending or cover_pending:
        repo.enqueue_artist_enrichment(a["id"], a)
    return {
        **(await serialize_artist_brief(a)),
        "cover_pending": cover_pending,
        "description": a.get("description"),
        "description_pending": description_pending,
        "genres": metadata.get("genres") or [],
        "dislikes_count": a.get("dislikes_count", 0),
        "reactions_count": a.get("reactions_count", 0),
        "score": float(a.get("score") or 0),
    }


def serialize_user_brief(u: dict) -> dict:
    return {
        "user_id": str(u["user_id"]),
        "first_name": _latest(u.get("first_name")),
        "last_name": _latest(u.get("last_name")),
        "username": _latest(u.get("username")),
        "profile_photo": _latest(u.get("profile_photo")),
    }


def serialize_user_full(u: dict) -> dict:
    return {
        **serialize_user_brief(u),
        "is_premium": u.get("is_premium", False),
        "is_verified": u.get("is_verified", False),
        # Defaults to True (public) for rows written before is_public
        # existed -- see repository.is_profile_visible.
        "is_public": bool(u.get("is_public", True)),
    }


def serialize_relation_person(row: dict) -> dict:
    """Rows from repo.get_user_relations() carry raw JSONB history columns
    plus a `metric` (count or correlation %) tacked on by the SQL."""
    return {**serialize_user_brief(row), "metric": row.get("metric")}


def serialize_track_reaction(row: dict) -> dict:
    """One entry in the track page's swipe-up "who reacted" list."""
    return {
        **serialize_user_brief(row),
        "sentiment": row.get("sentiment"),
        "emoji": row.get("emoji"),
        "reacted_at": row["reacted_at"].isoformat() if row.get("reacted_at") else None,
    }


def _latest(jsonb_value):
    """username/first_name/last_name/profile_photo are stored as JSONB
    history arrays -- either plain scalars (internal DB: [{"value": ...}]) or
    already-unwrapped strings, depending on the path the row came from. The
    frontend just wants the current (latest) value either way."""
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

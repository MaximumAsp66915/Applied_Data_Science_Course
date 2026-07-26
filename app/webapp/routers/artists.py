from fastapi import APIRouter, Depends, HTTPException, Query

from .. import repository as repo
from ..serializers import serialize_artist_full, serialize_track
from ..telegram_auth import optional_telegram_user, TelegramUser

router = APIRouter(prefix="/api/artists", tags=["artists"])


async def _viewer_id(tg_user: TelegramUser | None) -> int | None:
    if not tg_user:
        return None
    viewer = await repo.get_user_by_chat_id(tg_user["id"])
    return viewer["user_id"] if viewer else None


@router.get("/{artist_id}")
async def get_artist(artist_id: int):
    """No-prefetch contract: returns immediately with whatever description/
    cover is already in the DB. If either is missing, serialize_artist_full
    sets the matching `..._pending` flag and queues a background Last.fm
    lookup (see repository.enqueue_artist_enrichment /
    webapp/enrichment_queue.py) instead of blocking this request on it. The
    frontend polls this endpoint again while a pending flag is set."""
    row = await repo.get_artist(artist_id)
    if not row:
        raise HTTPException(404, "Artist not found")
    return await serialize_artist_full(row)


@router.get("/{artist_id}/tracks")
async def get_artist_tracks(
    artist_id: int,
    limit: int = Query(20, le=50),
    offset: int = 0,
    tg_user: TelegramUser | None = Depends(optional_telegram_user),
):
    viewer_id = await _viewer_id(tg_user)
    rows = await repo.get_artist_tracks(artist_id, limit, offset)
    items = [await serialize_track(r, viewer_id=viewer_id) for r in rows]
    return {"items": items}

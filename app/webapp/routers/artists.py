from fastapi import APIRouter, HTTPException, Query

from .. import repository as repo
from ..serializers import serialize_artist_full, serialize_track

router = APIRouter(prefix="/api/artists", tags=["artists"])


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
async def get_artist_tracks(artist_id: int, limit: int = Query(20, le=50), offset: int = 0):
    rows = await repo.get_artist_tracks(artist_id, limit, offset)
    items = [await serialize_track(r) for r in rows]
    return {"items": items}

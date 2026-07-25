from fastapi import APIRouter, Query

from .. import repository as repo
from ..serializers import serialize_track, serialize_artist_brief, serialize_user_brief

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
async def search(
    q: str = Query(..., min_length=1),
    scope: str = Query("all", pattern="^(all|tracks|artists|users)$"),
    limit: int = Query(20, le=50),
    offset: int = 0,
):
    """GET /api/search?q=&scope=all|tracks|artists|users -> { tracks, artists, users }
    (only the requested scope(s) are populated; "all" fills every list)."""
    tracks, artists, users = [], [], []

    if scope in ("all", "tracks"):
        rows = await repo.search_tracks(q, limit, offset)
        tracks = [await serialize_track(r) for r in rows]

    if scope in ("all", "artists"):
        rows = await repo.search_artists(q, limit, offset)
        artists = [await serialize_artist_brief(r) for r in rows]

    if scope in ("all", "users"):
        rows = await repo.search_users(q, limit, offset)
        users = [serialize_user_brief(r) for r in rows]

    return {"tracks": tracks, "artists": artists, "users": users}

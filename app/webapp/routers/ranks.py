from fastapi import APIRouter, Query

from .. import repository as repo
from ..serializers import serialize_track, serialize_artist_brief, serialize_user_brief

router = APIRouter(prefix="/api/ranks", tags=["ranks"])


@router.get("")
async def get_ranks(scope: str = Query("users", pattern="^(users|tracks|artists)$")):
    """GET /api/ranks?scope=users|tracks|artists -> { items: [...] }, top 10."""
    if scope == "tracks":
        rows = await repo.get_top_tracks(limit=10)
        items = [await serialize_track(r) for r in rows]
    elif scope == "artists":
        rows = await repo.get_top_artists(limit=10)
        items = [await serialize_artist_brief(r) for r in rows]
    else:
        rows = await repo.get_top_users(limit=10)
        items = [
            {
                **serialize_user_brief(r),
                "total_received_likes": r.get("total_received_likes", 0),
                "total_received_dislikes": r.get("total_received_dislikes", 0),
                "score": float(r.get("score") or 0),
                "rank": r.get("rank"),
            }
            for r in rows
        ]
    return {"items": items}

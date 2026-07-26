from fastapi import APIRouter, Depends, Query

from .. import repository as repo
from ..serializers import serialize_track, serialize_artist_brief, serialize_user_brief
from ..telegram_auth import optional_telegram_user, TelegramUser

router = APIRouter(prefix="/api/search", tags=["search"])


async def _viewer_id(tg_user: TelegramUser | None) -> int | None:
    if not tg_user:
        return None
    viewer = await repo.get_user_by_chat_id(tg_user["id"])
    return viewer["user_id"] if viewer else None


@router.get("")
async def search(
    q: str = Query(..., min_length=1),
    scope: str = Query("all", pattern="^(all|tracks|artists|users)$"),
    limit: int = Query(20, le=50),
    offset: int = 0,
    tg_user: TelegramUser | None = Depends(optional_telegram_user),
):
    """GET /api/search?q=&scope=all|tracks|artists|users -> { tracks, artists, users }
    (only the requested scope(s) are populated; "all" fills every list)."""
    viewer_id = await _viewer_id(tg_user)
    tracks, artists, users = [], [], []

    if scope in ("all", "tracks"):
        rows = await repo.search_tracks(q, limit, offset)
        tracks = [await serialize_track(r, viewer_id=viewer_id) for r in rows]

    if scope in ("all", "artists"):
        rows = await repo.search_artists(q, limit, offset)
        artists = [await serialize_artist_brief(r) for r in rows]

    if scope in ("all", "users"):
        rows = await repo.search_users(q, limit, offset)
        users = [serialize_user_brief(r) for r in rows]

    return {"tracks": tracks, "artists": artists, "users": users}

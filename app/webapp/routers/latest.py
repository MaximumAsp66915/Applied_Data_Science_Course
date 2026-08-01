from fastapi import APIRouter, Depends, Query

from .. import repository as repo
from ..serializers import serialize_track, serialize_artist_brief
from ..telegram_auth import optional_telegram_user, TelegramUser

router = APIRouter(prefix="/api/latest", tags=["latest"])


async def _viewer_id(tg_user: TelegramUser | None) -> int | None:
    if not tg_user:
        return None
    viewer = await repo.get_user_by_chat_id(tg_user["id"])
    return viewer["user_id"] if viewer else None


@router.get("")
async def get_latest(
    scope: str = Query("tracks", pattern="^(tracks|artists)$"),
    tg_user: TelegramUser | None = Depends(optional_telegram_user),
):
    """GET /api/latest?scope=tracks|artists -> { items: [...] }, newest 10.

    Mirrors GET /api/ranks in shape (same top-10, same serializers) but
    ordered by created_at instead of likes_count -- powers the Latest page
    and, via the same underlying repo.get_latest_tracks/get_latest_artists
    used by the home feed's rails, stays consistent with what "Latest
    songs" / "Latest artists" on Home already shows.
    """
    viewer_id = await _viewer_id(tg_user)
    if scope == "artists":
        rows = await repo.get_latest_artists(limit=10)
        items = [await serialize_artist_brief(r) for r in rows]
    else:
        rows = await repo.get_latest_tracks(limit=10)
        items = [await serialize_track(r, viewer_id=viewer_id) for r in rows]
    return {"items": items}

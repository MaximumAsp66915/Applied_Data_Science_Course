from fastapi import APIRouter, Depends, Query

from .. import repository as repo
from ..serializers import serialize_track, serialize_artist_brief, serialize_user_brief
from ..telegram_auth import optional_telegram_user, TelegramUser

router = APIRouter(prefix="/api/ranks", tags=["ranks"])


async def _viewer_id(tg_user: TelegramUser | None) -> int | None:
    if not tg_user:
        return None
    viewer = await repo.get_user_by_chat_id(tg_user["id"])
    return viewer["user_id"] if viewer else None


@router.get("")
async def get_ranks(
    scope: str = Query("users", pattern="^(users|tracks|artists)$"),
    tg_user: TelegramUser | None = Depends(optional_telegram_user),
):
    """GET /api/ranks?scope=users|tracks|artists -> { items: [...] }, top 10."""
    viewer_id = await _viewer_id(tg_user)
    if scope == "tracks":
        rows = await repo.get_top_tracks(limit=10)
        items = [await serialize_track(r, viewer_id=viewer_id) for r in rows]
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

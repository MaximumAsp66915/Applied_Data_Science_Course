from fastapi import APIRouter, Depends

from ..telegram_auth import optional_telegram_user, TelegramUser
from .. import repository as repo
from ..serializers import serialize_track, serialize_artist_brief

router = APIRouter(prefix="/api/home", tags=["home"])


@router.get("/feed")
async def get_feed(tg_user: TelegramUser | None = Depends(optional_telegram_user)):
    """GET /api/home/feed -> { latest_tracks, latest_artists, top_artists }"""
    viewer_id = None
    if tg_user:
        viewer = await repo.get_user_by_chat_id(tg_user["id"])
        viewer_id = viewer["user_id"] if viewer else None

    latest_tracks = await repo.get_latest_tracks(limit=15)
    latest_artists = await repo.get_latest_artists(limit=15)
    top_artists = await repo.get_top_artists(limit=10)

    return {
        "latest_tracks": [await serialize_track(t, viewer_id=viewer_id) for t in latest_tracks],
        "latest_artists": [await serialize_artist_brief(a) for a in latest_artists],
        "top_artists": [await serialize_artist_brief(a) for a in top_artists],
    }

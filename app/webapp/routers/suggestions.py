from fastapi import APIRouter, Depends, HTTPException

from ..telegram_auth import optional_telegram_user, TelegramUser
from .. import repository as repo
from .. import engine_client
from ..serializers import serialize_track

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])


@router.get("/next")
async def get_suggestion(tg_user: TelegramUser | None = Depends(optional_telegram_user)):
    """GET /api/suggestions/next -> a track to play next, with an optional
    `reason` string. Asks the external recommendation engine (see
    engine/README.md) first -- passing along the viewer's liked artists and
    already-reacted-to tracks so it can give a real personalized pick even
    for a user outside its last training snapshot -- and falls back to a
    simple in-house pick (top-liked tracks the viewer hasn't reacted to
    yet) if the engine isn't configured, unreachable, or has nothing to
    offer."""
    viewer_id = None
    if tg_user:
        viewer = await repo.get_user_by_chat_id(tg_user["id"])
        viewer_id = viewer["user_id"] if viewer else None

    if viewer_id:
        reacted_artist_ids = await repo.get_liked_artist_ids(viewer_id)
        exclude_track_ids = await repo.get_reacted_track_ids(viewer_id)
        suggestion = await engine_client.suggest_one(
            user_id=viewer_id,
            reacted_artist_ids=reacted_artist_ids,
            exclude_track_ids=exclude_track_ids,
        )
    else:
        suggestion = await engine_client.suggest_one()

    if suggestion:
        row = await repo.get_track(suggestion["track_id"])
        if row:
            out = await serialize_track(row, viewer_id=viewer_id)
            if suggestion.get("reason"):
                out["reason"] = suggestion["reason"]
            return out

    row = await repo.suggest_track_for_user(viewer_id)
    if not row:
        raise HTTPException(404, "No tracks available to suggest yet")
    out = await serialize_track(row, viewer_id=viewer_id)
    out["reason"] = "Based on what the group loves right now"
    return out

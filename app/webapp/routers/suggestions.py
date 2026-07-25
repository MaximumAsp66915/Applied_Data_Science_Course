import httpx
from fastapi import APIRouter, Depends, HTTPException

from ..config import settings
from ..telegram_auth import optional_telegram_user, TelegramUser
from .. import repository as repo
from ..serializers import serialize_track

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])


@router.get("/next")
async def get_suggestion(tg_user: TelegramUser | None = Depends(optional_telegram_user)):
    """GET /api/suggestions/next -> a track to play next, with an optional
    `reason` string. Proxies to an external recommendation engine when
    `SUGGESTION_ENGINE_URL` is configured; otherwise falls back to a simple
    in-house pick (top-liked tracks the viewer hasn't reacted to yet)."""
    viewer_id = None
    if tg_user:
        viewer = await repo.get_user_by_chat_id(tg_user["id"])
        viewer_id = viewer["user_id"] if viewer else None

    if settings.suggestion_engine_url:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(
                    f"{settings.suggestion_engine_url.rstrip('/')}/suggest",
                    params={"user_id": viewer_id} if viewer_id else {},
                )
                resp.raise_for_status()
                data = resp.json()
                track_id = data.get("track_id") or data.get("id")
                row = await repo.get_track(track_id) if track_id else None
                if row:
                    out = await serialize_track(row, viewer_id=viewer_id)
                    if data.get("reason"):
                        out["reason"] = data["reason"]
                    return out
        except (httpx.HTTPError, ValueError, KeyError):
            pass  # fall through to the in-house fallback below

    row = await repo.suggest_track_for_user(viewer_id)
    if not row:
        raise HTTPException(404, "No tracks available to suggest yet")
    out = await serialize_track(row, viewer_id=viewer_id)
    out["reason"] = "Based on what the group loves right now"
    return out

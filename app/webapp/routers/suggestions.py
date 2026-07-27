from fastapi import APIRouter, Depends, HTTPException

from ..telegram_auth import optional_telegram_user, TelegramUser
from .. import repository as repo
from .. import engine_client
from ..serializers import serialize_track
from ..cache import recently_suggested_cache, recently_liked_artists_cache

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
    offer.

    Both the engine's pick and the in-house fallback are otherwise
    deterministic (or near enough) for a viewer whose reactions haven't
    changed since the last call -- so without tracking what we've already
    shown them, "try another" (and even just closing and reopening the
    app) would hand back the exact same track every time. recently_suggested_cache
    holds a short-lived, per-user list of picks so each new call excludes
    what the viewer was just shown, on top of what they've reacted to.

    On top of that, the exclude set also folds in the viewer's default
    listening-history playlist (their last 100 plays -- see
    repository.get_recent_history_exclude_ids) so a recently-heard track
    doesn't get suggested right back. The one carve-out: a history track
    is left eligible if its artist was liked in the *current session*
    (recently_liked_artists_cache) -- liking an artist is a strong enough
    signal to immediately reopen their catalog, even to something from
    days-old history."""
    viewer_id = None
    if tg_user:
        viewer = await repo.get_user_by_chat_id(tg_user["id"])
        viewer_id = viewer["user_id"] if viewer else None

    recently_shown = set(await recently_suggested_cache.get(viewer_id) or []) if viewer_id else set()

    if viewer_id:
        reacted_artist_ids = await repo.get_liked_artist_ids(viewer_id)
        session_liked_artist_ids = await recently_liked_artists_cache.get(viewer_id) or []
        recent_history_ids = await repo.get_recent_history_exclude_ids(
            viewer_id, liked_artist_ids=session_liked_artist_ids
        )
        exclude_track_ids = (
            set(await repo.get_reacted_track_ids(viewer_id) or [])
            | recently_shown
            | set(recent_history_ids)
        )
        suggestion = await engine_client.suggest_one(
            user_id=viewer_id,
            reacted_artist_ids=reacted_artist_ids,
            exclude_track_ids=list(exclude_track_ids),
        )
    else:
        suggestion = await engine_client.suggest_one()

    if suggestion:
        row = await repo.get_track(suggestion["track_id"])
        if row:
            out = await serialize_track(row, viewer_id=viewer_id)
            if suggestion.get("reason"):
                out["reason"] = suggestion["reason"]
            if viewer_id:
                await recently_suggested_cache.set_add_to_list(viewer_id, row["id"])
            return out

    row = await repo.suggest_track_for_user(viewer_id, exclude_ids=recently_shown)
    if not row:
        raise HTTPException(404, "No tracks available to suggest yet")
    out = await serialize_track(row, viewer_id=viewer_id)
    out["reason"] = "Based on what the group loves right now"
    if viewer_id:
        await recently_suggested_cache.set_add_to_list(viewer_id, row["id"])
    return out

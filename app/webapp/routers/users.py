from fastapi import APIRouter, Body, Depends, HTTPException, Query

from ..telegram_auth import require_telegram_user, optional_telegram_user, TelegramUser
from .. import repository as repo
from ..serializers import (
    serialize_user_full,
    serialize_user_brief,
    serialize_track,
    serialize_artist_brief,
    serialize_relation_person,
)

router = APIRouter(prefix="/api/users", tags=["users"])


async def _resolve_viewer_id(tg_user: TelegramUser | None) -> int | None:
    if not tg_user:
        return None
    viewer = await repo.get_user_by_chat_id(tg_user["id"])
    return viewer["user_id"] if viewer else None


@router.get("/me")
async def get_me(tg_user: TelegramUser = Depends(require_telegram_user)):
    """GET /api/users/me -- the logged-in user's own row (used on the profile
    page). Resolves the Telegram id from initData to our internal user_id."""
    row = await repo.get_user_by_chat_id(tg_user["id"])
    if not row:
        raise HTTPException(404, "User not found — call /api/auth/telegram first")
    return serialize_user_full(row)


@router.patch("/me/visibility")
async def set_my_visibility(
    payload: dict = Body(...),
    tg_user: TelegramUser = Depends(require_telegram_user),
):
    """PATCH /api/users/me/visibility -- body: { "is_public": bool }.
    Lets a user flip their own profile between public (anyone can open it
    from a name/avatar tap, see /{user_id}) and private (only they can)."""
    is_public = payload.get("is_public")
    if not isinstance(is_public, bool):
        raise HTTPException(400, "is_public must be a boolean")

    row = await repo.get_user_by_chat_id(tg_user["id"])
    if not row:
        raise HTTPException(404, "User not found — call /api/auth/telegram first")

    ok = await repo.set_user_visibility(row["user_id"], is_public)
    if not ok:
        raise HTTPException(500, "Failed to update visibility")

    row["is_public"] = is_public
    return serialize_user_full(row)


@router.get("/{user_id}")
async def get_user(user_id: int, tg_user: TelegramUser | None = Depends(optional_telegram_user)):
    """GET /api/users/{user_id} -- a user's profile (viewed via the dynamic
    profile button, or by tapping a name/avatar anywhere in the app).
    `user_id` here is our internal id (same one embedded in track uploader /
    relation payloads), not the raw Telegram id.

    Respects the owner's is_public setting: everyone can always see their
    own profile; a profile someone has set to private is shown to no one
    else, but the response still stays a 200 with just enough (name, avatar)
    to render a "this profile is private" state rather than a broken page."""
    row = await repo.get_user(user_id)
    if not row:
        raise HTTPException(404, "User not found")

    viewer_id = await _resolve_viewer_id(tg_user)
    if not repo.is_profile_visible(row, viewer_id):
        brief = serialize_user_brief(row)
        return {**brief, "is_public": False, "is_private_view": True}

    return serialize_user_full(row)


@router.get("/{user_id}/tracks")
async def get_user_tracks(
    user_id: int,
    limit: int = Query(20, le=50),
    offset: int = 0,
    tg_user: TelegramUser | None = Depends(optional_telegram_user),
):
    """GET /api/users/{user_id}/tracks -- songs this user personally
    uploaded, most popular (likes) first."""
    viewer_id = await _resolve_viewer_id(tg_user)
    owner_row = await repo.get_user(user_id)
    if not owner_row:
        raise HTTPException(404, "User not found")
    if not repo.is_profile_visible(owner_row, viewer_id):
        raise HTTPException(403, "This profile is private")

    rows = await repo.get_user_tracks(user_id, limit, offset)
    items = [await serialize_track(r, viewer_id=viewer_id) for r in rows]
    return {"items": items}


@router.get("/{user_id}/liked-tracks")
async def get_user_liked_tracks(
    user_id: int,
    limit: int = Query(20, le=50),
    offset: int = 0,
    tg_user: TelegramUser | None = Depends(optional_telegram_user),
):
    """GET /api/users/{user_id}/liked-tracks -- songs this user has liked,
    most popular first (the track-level counterpart to /relations'
    top_liked_artists). Also what the player walks through when a session
    starts from this rail -- see repository._next_profile_liked_track."""
    viewer_id = await _resolve_viewer_id(tg_user)
    owner_row = await repo.get_user(user_id)
    if not owner_row:
        raise HTTPException(404, "User not found")
    if not repo.is_profile_visible(owner_row, viewer_id):
        raise HTTPException(403, "This profile is private")

    rows = await repo.get_user_liked_tracks(user_id, limit, offset)
    items = [await serialize_track(r, viewer_id=viewer_id) for r in rows]
    return {"items": items}


@router.get("/{user_id}/stats")
async def get_user_stats(user_id: int, tg_user: TelegramUser | None = Depends(optional_telegram_user)):
    """GET /api/users/{user_id}/stats -- maps to `user_musicbot_state`:
    score, rank, totals, and trophies (from `metadata.trophies`)."""
    viewer_id = await _resolve_viewer_id(tg_user)
    owner_row = await repo.get_user(user_id)
    if not owner_row:
        raise HTTPException(404, "User not found")
    if not repo.is_profile_visible(owner_row, viewer_id):
        raise HTTPException(403, "This profile is private")

    row = await repo.get_user_stats(user_id)
    if not row:
        raise HTTPException(404, "No stats yet for this user")
    trophies = (row.get("metadata") or {}).get("trophies", [])
    return {
        "score": float(row.get("score") or 0),
        "rank": row.get("rank"),
        "total_likes": row.get("total_likes", 0),
        "total_dislikes": row.get("total_dislikes", 0),
        "total_reactions": row.get("total_reactions", 0),
        "total_received_likes": row.get("total_received_likes", 0),
        "total_received_dislikes": row.get("total_received_dislikes", 0),
        "total_received_reactions": row.get("total_received_reactions", 0),
        "total_uploaded_tracks": row.get("total_uploaded_tracks", 0),
        "trophies": trophies,
    }


@router.get("/{user_id}/relations")
async def get_user_relations(user_id: int, tg_user: TelegramUser | None = Depends(optional_telegram_user)):
    """GET /api/users/{user_id}/relations -- the "Community pulse" section:
    who reacts to this user the most (per direction), who this user reacts
    to the most (per direction), and their favorite artists."""
    viewer_id = await _resolve_viewer_id(tg_user)
    owner_row = await repo.get_user(user_id)
    if not owner_row:
        raise HTTPException(404, "User not found")
    if not repo.is_profile_visible(owner_row, viewer_id):
        raise HTTPException(403, "This profile is private")

    data = await repo.get_user_relations(user_id)
    return {
        "top_likers": [serialize_relation_person(r) for r in data["top_likers"]],
        "top_dislikers": [serialize_relation_person(r) for r in data["top_dislikers"]],
        "gave_most_likes_to": [serialize_relation_person(r) for r in data["gave_most_likes_to"]],
        "gave_most_dislikes_to": [serialize_relation_person(r) for r in data["gave_most_dislikes_to"]],
        "top_liked_artists": [await serialize_artist_brief(a) for a in data["top_liked_artists"]],
    }

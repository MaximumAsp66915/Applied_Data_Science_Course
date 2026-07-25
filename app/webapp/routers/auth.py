from fastapi import APIRouter, Depends

from ..telegram_auth import require_telegram_user, TelegramUser
from .. import repository as repo
from ..serializers import serialize_user_full

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/telegram")
async def login(tg_user: TelegramUser = Depends(require_telegram_user)):
    """
    POST /api/auth/telegram
    Header: X-Telegram-Init-Data (required)

    Verifies the signed initData, resolves/creates the matching Chat+User
    pair (same linkage the Telegram bot itself uses -- see
    repository.upsert_user_from_telegram), and returns the merged profile.
    Called once on app boot (see UserContext.jsx).

    Response: { "user": {...}, "is_new": bool }
    """
    existing = await repo.get_user_by_chat_id(tg_user["id"])
    row = await repo.upsert_user_from_telegram(tg_user)
    return {"user": {**serialize_user_full(row), "isGuest": False}, "is_new": existing is None}

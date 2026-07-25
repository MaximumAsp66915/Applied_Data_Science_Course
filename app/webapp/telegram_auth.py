"""
Verifies the `X-Telegram-Init-Data` header sent by the Mini App frontend.

Telegram signs the initData string with a key derived from the bot token, so
we can trust the `user` payload inside it (id, first_name, username, photo
url, etc.) without the client being able to forge it. This is what turns
"telegram_id the frontend claims to be" into "telegram_id the backend can
actually trust" -- never read the user id from a request body/query param.

Docs: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException

from .config import settings

MAX_AGE_SECONDS = 24 * 60 * 60  # reject stale sessions after a day


class TelegramUser(dict):
    """Parsed `user` object from initData, e.g. id/first_name/username/photo_url."""


def _check_signature(init_data: str, bot_token: str) -> dict:
    parsed = dict(parse_qsl(init_data, strict_parsing=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise ValueError("missing hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise ValueError("bad signature")

    return parsed


def verify_init_data(init_data: str) -> TelegramUser:
    if not init_data:
        raise ValueError("empty init data")

    parsed = _check_signature(init_data, settings.bot_token)

    auth_date = int(parsed.get("auth_date", "0"))
    if time.time() - auth_date > MAX_AGE_SECONDS:
        raise ValueError("init data expired")

    user_raw = parsed.get("user")
    if not user_raw:
        raise ValueError("no user in init data")

    return TelegramUser(json.loads(user_raw))


async def require_telegram_user(
    x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
) -> TelegramUser:
    """FastAPI dependency: attach to any route that needs to know *who* is calling.

    Usage:
        @router.get("/users/me")
        async def me(tg_user: TelegramUser = Depends(require_telegram_user)):
            ...
    """
    try:
        return verify_init_data(x_telegram_init_data)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid Telegram session: {exc}")


async def optional_telegram_user(
    x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
) -> TelegramUser | None:
    """Same as require_telegram_user, but returns None instead of 401 when
    there's no/invalid header — for endpoints that work for guests too but
    personalize (e.g. attach `my_reaction`) when a valid session is present."""
    if not x_telegram_init_data:
        return None
    try:
        return verify_init_data(x_telegram_init_data)
    except ValueError:
        return None
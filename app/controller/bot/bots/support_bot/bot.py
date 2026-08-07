import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .config import settings
from .handlers import router

logger = logging.getLogger(__name__)


def _build_session() -> AiohttpSession | None:
    """If a Local Bot API Server is configured (same one the webapp uses
    for oversized files, see config.py's `telegram_local_api_base`), route
    every request -- including the getUpdates long poll -- through it
    instead of the https://api.telegram.org default. Mixing the two for the
    same bot token is what causes TelegramConflictError / an unresponsive
    /start; see the long comment on that setting.
    """
    if not settings.telegram_local_api_base:
        return None

    api_server = TelegramAPIServer.from_base(settings.telegram_local_api_base, is_local=True)
    return AiohttpSession(api=api_server)


async def run() -> None:
    if not settings.token:
        raise RuntimeError(
            "No bot token configured -- set BOT_TOKEN (shared with the "
            "webapp) or SUPPORT_BOT_TOKEN in app/.env before starting the "
            "support bot."
        )

    bot = Bot(
        token=settings.token,
        session=_build_session(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logger.info(
        "SUT Music support bot starting (webapp API: %s, admin chat: %s, "
        "bot API server: %s)",
        settings.webapp_api_base_url,
        settings.admin_chat_id,
        settings.telegram_local_api_base or "https://api.telegram.org (cloud default)",
    )

    # Long polling, same choice already made for local/self-hosted
    # deployment in this project (no public HTTPS endpoint is assumed to
    # exist for a webhook -- see deploy/start.sh's cloudflared quick tunnel,
    # which is only for the frontend, not this bot).
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

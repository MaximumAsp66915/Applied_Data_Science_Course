import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .config import settings
from .handlers import router

logger = logging.getLogger(__name__)


async def run() -> None:
    if not settings.token:
        raise RuntimeError(
            "No bot token configured -- set BOT_TOKEN (shared with the "
            "webapp) or SUPPORT_BOT_TOKEN in app/.env before starting the "
            "support bot."
        )

    bot = Bot(token=settings.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logger.info(
        "SUT Music support bot starting (webapp API: %s, admin chat: %s)",
        settings.webapp_api_base_url,
        settings.admin_chat_id,
    )

    # Long polling, same choice already made for local/self-hosted
    # deployment in this project (no public HTTPS endpoint is assumed to
    # exist for a webhook -- see deploy/start.sh's cloudflared quick tunnel,
    # which is only for the frontend, not this bot).
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

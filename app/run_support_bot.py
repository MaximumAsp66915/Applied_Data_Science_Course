# run_support_bot.py
"""
Entry point for the SUT Music support bot -- a plain Telegram Bot API bot
(long polling, aiogram) that gives people search / report / info access to
SUT Music straight from a chat, without needing to open the Mini App.

This is a separate, independent process from the three already started in
deploy/start.sh (Telethon bot, webapp, frontend) plus the cloudflared
tunnel. It never touches the database -- it only calls the webapp's own
public /api/search endpoint over HTTP (see controller/bot/bots/support_bot/
api_client.py) -- so it can be started, stopped or restarted on its own
without any of the others noticing.

Run from the project root, exactly like main.py:

    python run_support_bot.py
"""

import asyncio
import logging

from dotenv import load_dotenv

load_dotenv()


async def main() -> None:
    from controller.bot.bots.support_bot.bot import run

    await run()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Support bot stopped (KeyboardInterrupt).")

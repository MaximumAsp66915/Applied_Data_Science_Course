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
import sys
import traceback

from dotenv import load_dotenv

load_dotenv()


async def main() -> None:
    from controller.bot.bots.support_bot.bot import run

    await run()


if __name__ == "__main__":
    # force=True: if anything imported above (dotenv, aiogram, etc.) already
    # attached a handler to the root logger, a plain basicConfig() call
    # silently becomes a no-op -- level/format get set up, nothing ever
    # prints, and every logger.info() call in bot.py/handlers.py (including
    # the "support bot starting" line) just vanishes with no error at all.
    # force=True guarantees this config actually takes effect. Needs
    # Python 3.8+.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    print("run_support_bot.py: starting up...", flush=True)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Support bot stopped (KeyboardInterrupt).")
    except BaseException:
        # Last-resort net: print()+flush bypasses logging entirely, so even
        # if logging is somehow still misconfigured (or stdout/stderr are
        # being redirected in a way that swallows one but not the other),
        # a crash here can never be completely silent again.
        print("run_support_bot.py: crashed with an unhandled exception:", flush=True)
        traceback.print_exc()
        sys.exit(1)
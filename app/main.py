# main.py
from dotenv import load_dotenv
import asyncio

from db.internal_db.user_internal_db import Internal_DB_User


load_dotenv()


async def main():
    from initializer.initialize import Initialize
    await Initialize.start()

    from controller.bot.bots.SUT_Music_bot import SUT_Music_bot
    # await SUT_Music_bot.collect_data()
    # from webapp.routers.search import search


    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        from utils.loggers.flag_logger import FlagLogger
        FlagLogger.background_flag(1, "--> KeyboardInterrupt received, shutting down...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        from utils.loggers.flag_logger import FlagLogger

        FlagLogger.background_flag(1, "--> KeyboardInterrupt received, shutting down...")

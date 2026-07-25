import asyncio

from utils.loggers.debug_logger import DebugLogger
from utils.loggers.error_logger import ErrorLogger

from db.db_initializer import DB_Initialize
from utils.loggers.flag_logger import FlagLogger


class Initialize:
    methods = [
        ErrorLogger.initialize,
        DebugLogger.initialize,
        FlagLogger.initialize,
        DB_Initialize.start,
    ]

    @classmethod
    async def start(cls):
        total_result = True
        methods = cls.methods
        for method in methods:
            result = await method()
            if not result:
                total_result = False
                ErrorLogger.background_log_error(-4, f"failed to initialize at {method}")
            else:
                ErrorLogger.background_log_error(-1, f"{method} was successful")

        await asyncio.sleep(3)

        return total_result

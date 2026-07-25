import asyncio
import logging
import traceback
from datetime import datetime
import aiosqlite
import threading
from pathlib import Path
from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEBUG_LOG_FILE = f"{PROJECT_ROOT}/utils/loggers/files/debugs/debug.log"
DEBUG_LOG_DB = f"{PROJECT_ROOT}/utils/loggers/files/debugs/debug.db"


class DebugLogger:
    _logger = logging.getLogger("debug_logger")
    _logger.setLevel(logging.DEBUG)

    LEVELS = {
        0: ['print_terminal'],
        1: ['print_terminal'],
        2: ['print_terminal', 'log_file'],
        3: ['print_terminal', 'log_file'],
        4: ['print_terminal', 'log_file', 'log_db'],
        5: ['print_terminal', 'log_file', 'log_db'],
        6: ['print_terminal', 'log_file', 'log_db', 'notify_admin'],
        7: ['print_terminal', 'log_file', 'log_db', 'notify_admin'],
        8: ['print_terminal', 'log_file', 'log_db', 'notify_admin'],
        9: ['print_terminal', 'log_file', 'log_db', 'notify_admin'],
        10: ['print_terminal', 'log_file', 'log_db', 'notify_admin']
    }

    ACTIVE_LEVEL = 1
    ACTIVE_THREADS = ["MainThread", "APIThread", "APISenderThread", "BotThread",
                      "QueueThread", "RiskyThread"]

    @classmethod
    async def initialize(cls) -> bool:
        try:
            with open(DEBUG_LOG_FILE, 'w'):
                pass
        except Exception as e:
            print(f"{Fore.RED}[DebugLogger Error] Failed to reset log file: {e}{Style.RESET_ALL}")

        file_handler = logging.FileHandler(DEBUG_LOG_FILE)
        formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s')
        file_handler.setFormatter(formatter)
        cls._logger.handlers = [file_handler]
        cls._logger.setLevel(logging.DEBUG)

        await cls._initialize_db()
        return True

    @staticmethod
    async def _initialize_db():
        async with aiosqlite.connect(DEBUG_LOG_DB) as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS debug_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread TEXT,
                    level INTEGER NOT NULL,
                    message TEXT,
                    trace TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await conn.commit()

    @classmethod
    async def log_debug(cls, level: int, message: str, exc: Exception = None, thread_name: str = None):
        thread = thread_name or threading.current_thread().name

        if level < cls.ACTIVE_LEVEL:
            return
        if cls.ACTIVE_THREADS and thread not in cls.ACTIVE_THREADS:
            return

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        trace = traceback.format_exc() if exc else ''

        actions = cls.LEVELS.get(level, [])
        for action in actions:
            method = getattr(cls, f"_do_{action}", None)
            if method:
                try:
                    await method(message, timestamp, thread, level, message, trace)
                except Exception as action_error:
                    print(f"{Fore.RED}[DebugLogger Internal Error] Action '{action}' failed: {action_error}{Style.RESET_ALL}")

    @classmethod
    def async_log_debug(cls, level: int, message: str, exc: Exception = None, thread_name: str = None):
        """Fire-and-forget async logging."""
        try:
            asyncio.create_task(cls.log_debug(level, message, exc, thread_name))
        except RuntimeError:
            print(f"{Fore.RED}[AsyncDebugLogger] No event loop running. Could not schedule async log.{Style.RESET_ALL}")

    # Output targets
    @staticmethod
    async def _do_print_terminal(full_message, timestamp, thread, level, message, trace):
        level_color = (
            Fore.GREEN if level <= 2 else
            Fore.YELLOW if level <= 5 else
            Fore.RED
        )

        timestamp_str = f"{Fore.CYAN}[{timestamp}]{Style.RESET_ALL}"
        terminal_tag = f"{Fore.BLUE}[DEBUG TERMINAL]{Style.RESET_ALL}"
        level_str = f"{level_color}LEVEL {level}{Style.RESET_ALL}"
        thread_str = f"{Fore.MAGENTA}(Thread: {thread}){Style.RESET_ALL}"

        header = f"{terminal_tag} {timestamp_str} {level_str} {thread_str}"

        print(f"\n{header}\n{message}\n")
        if trace:
            print(f"{Fore.LIGHTBLACK_EX}{trace}{Style.RESET_ALL}\n")

    @staticmethod
    async def _do_log_file(full_message, timestamp, thread, level, message, trace):
        log_entry = f"[Thread: {thread}] LEVEL {level}: {message}"
        DebugLogger._logger.debug(log_entry)
        if trace:
            DebugLogger._logger.debug(trace)

    @staticmethod
    async def _do_log_db(full_message, timestamp, thread, level, message, trace):
        try:
            async with aiosqlite.connect(DEBUG_LOG_DB) as conn:
                await conn.execute('''
                    INSERT INTO debug_logs (thread, level, message, trace, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                ''', (thread, int(level), str(message), str(trace), timestamp))
                await conn.commit()
        except Exception as e:
            print(f"{Fore.RED}[DebugLogger Error] Could not save to DB: {e}{Style.RESET_ALL}")

    @staticmethod
    async def _do_notify_admin(full_message, timestamp, thread, level, message, trace):
        print(f"{Fore.MAGENTA}[DEBUG ADMIN ALERT]: {message}{Style.RESET_ALL}")

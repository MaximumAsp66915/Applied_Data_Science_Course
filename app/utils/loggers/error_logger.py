import logging
import traceback
from datetime import datetime
import sys
import threading
from pathlib import Path
import aiosqlite
import aiofiles
from colorama import Fore, Style, init as colorama_init
import asyncio

colorama_init(autoreset=True)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ERROR_LOG_FILE = f"{PROJECT_ROOT}/utils/loggers/files/errors/error.log"
ERROR_LOG_DB = f"{PROJECT_ROOT}/utils/loggers/files/errors/error.db"


class ErrorLogger:
    _logger = logging.getLogger("error_logger")
    _logger.setLevel(logging.ERROR)

    LEVELS = {
        -4: ['print_terminal', 'log_file', 'log_db', 'notify_admin'],
        -3: ['print_terminal', 'log_file', 'log_db'],
        -2: ['print_terminal', 'log_file'],
        -1: ['print_terminal'],
        0:  ['print_terminal'],
        1:  ['print_terminal'],
        2:  ['print_terminal', 'log_file'],
        3:  ['print_terminal', 'log_file'],
        4:  ['print_terminal', 'log_file', 'log_db'],
        5:  ['print_terminal', 'log_file', 'log_db', 'notify_admin'],
        6:  ['print_terminal', 'log_file', 'log_db', 'notify_admin'],
        7:  ['print_terminal', 'log_file', 'log_db', 'notify_admin'],
        8:  ['print_terminal', 'log_file', 'log_db', 'notify_admin', 'restart'],
        9:  ['print_terminal', 'log_file', 'log_db', 'notify_admin', 'restart'],
        10: ['print_terminal', 'log_file', 'log_db', 'notify_admin', 'restart'],
    }

    @classmethod
    async def initialize(cls) -> bool:
        try:
            async with aiofiles.open(ERROR_LOG_FILE, 'w'):
                pass
        except Exception as e:
            print(f"{Fore.RED}[Logger Error] Failed to reset log file: {e}{Style.RESET_ALL}")

        file_handler = logging.FileHandler(ERROR_LOG_FILE)
        formatter = logging.Formatter('[%(asctime)s] [LEVEL %(levelno)s] %(message)s')
        file_handler.setFormatter(formatter)

        cls._logger.handlers = [file_handler]
        cls._logger.setLevel(logging.ERROR)

        await cls._initialize_db()
        cls._setup_global_exception_hook()
        return True

    @staticmethod
    async def _initialize_db():
        async with aiosqlite.connect(ERROR_LOG_DB) as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level INTEGER NOT NULL,
                    message TEXT,
                    traceback TEXT,
                    exception TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await conn.commit()

    @classmethod
    async def log_error(cls, level: int, message: str, exc: Exception = None):
        try:
            level = min(level, max(cls.LEVELS.keys()))
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            trace = traceback.format_exc() if exc else ''
            actions = cls.LEVELS.get(level, [])

            for action in actions:
                method = getattr(cls, f"_do_{action}", None)
                if method:
                    try:
                        await method(message, timestamp, level, message, trace)
                    except Exception as action_error:
                        print(f"{Fore.RED}[AsyncErrorLogger Internal Error] Action '{action}' failed: {action_error}{Style.RESET_ALL}")
        except Exception as log_error:
            print(f"{Fore.RED}[AsyncErrorLogger Fatal Error] Could not log error: {log_error}{Style.RESET_ALL}")

    @classmethod
    def background_log_error(cls, level: int, message: str, exc: Exception = None):
        """Fire-and-forget async logging."""
        try:
            asyncio.create_task(cls.log_error(level, message, exc))
        except RuntimeError:
            print(f"[AsyncErrorLogger] No event loop running. Could not schedule async log.\n"
                  f"level: [{level}], message: {message}, exception: {exc}")

    @staticmethod
    async def _do_print_terminal(full_message, timestamp, level, message, trace):
        level_color = (
            Fore.RED if level >= 5 else
            Fore.YELLOW if level >= 2 else
            Fore.GREEN if level >= -1 else
            Fore.BLUE
        )

        terminal_label = f"{Fore.MAGENTA}[ERROR TERMINAL]{Style.RESET_ALL}"
        timestamp_str = f"{Fore.CYAN}[{timestamp}]{Style.RESET_ALL}"
        level_str = f"{level_color}LEVEL {level}{Style.RESET_ALL}"

        label_type = "ERROR" if level > 0 else "LOG" if level == 0 else "INIT"
        header = f"{terminal_label} {timestamp_str} {level_str} {label_type}"

        print(f"\n{header}\n{message}\n")
        if trace:
            print(f"{Fore.LIGHTBLACK_EX}{trace}{Style.RESET_ALL}\n")

    @staticmethod
    async def _do_log_file(full_message, timestamp, level, message, trace):
        log_entry = f"LEVEL {level}: {message}"
        ErrorLogger._logger.error(log_entry)
        if trace:
            ErrorLogger._logger.error(trace)

    @staticmethod
    async def _do_log_db(full_message, timestamp, level, message, trace):
        try:
            async with aiosqlite.connect(ERROR_LOG_DB) as conn:
                await conn.execute('''
                    INSERT INTO errors (level, message, traceback, exception, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                ''', (level, str(message), str(trace), str(message), timestamp))
                await conn.commit()
        except Exception as e:
            print(f"{Fore.RED}[AsyncErrorLogger Error] Could not save to DB: {e}{Style.RESET_ALL}")

    @staticmethod
    async def _do_notify_admin(full_message, timestamp, level, message, trace):
        print(f"{Fore.MAGENTA}[ADMIN ALERT]: {full_message}{Style.RESET_ALL}")

    @staticmethod
    async def _do_restart(full_message, timestamp, level, message, trace):
        print(f"{Fore.LIGHTMAGENTA_EX}[SYSTEM]: Restart triggered due to critical failure.{Style.RESET_ALL}")

    @classmethod
    def _setup_global_exception_hook(cls, default_level=5):
        def handle_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            trace_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            cls.background_log_error(default_level, f"Uncaught exception: {trace_msg}", exc_value)

        sys.excepthook = handle_exception

        if hasattr(threading, "excepthook"):
            def thread_exception_handler(args):
                cls.background_log_error(default_level, f"Uncaught thread exception: {args.exc_value}", args.exc_value)
            threading.excepthook = thread_exception_handler

    @classmethod
    def setup_asyncio_exception_handler(cls, default_level=5):
        def handle_loop_exception(loop, context):
            msg = context.get("message")
            exception = context.get("exception")
            cls.background_log_error(default_level, f"{msg}", exception)

        try:
            loop = asyncio.get_event_loop()
            loop.set_exception_handler(handle_loop_exception)
        except Exception as e:
            print(f"{Fore.RED}[AsyncErrorLogger] Failed to set asyncio exception handler: {e}{Style.RESET_ALL}")

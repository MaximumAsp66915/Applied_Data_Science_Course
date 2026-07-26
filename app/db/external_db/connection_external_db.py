import asyncio
import inspect

import asyncpg

from db.postgreSQL_helper import PostgreSQL
from pathlib import Path
from typing import Optional, Callable
import json
import os
from cryptography.fernet import Fernet

from utils.loggers.error_logger import ErrorLogger
from utils.result import Result
from utils.time_manager import TimeManager

from functools import wraps

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSION_KEY_FILE = f"{PROJECT_ROOT}/db/external_db/external_db_key.key"
STRUCTURE_ROOT = f"{PROJECT_ROOT}/db/db_files/external_db_structure.json"


def db_connection_wrapper(func: Optional[Callable] = None,
                          require_connection: bool = False,
                          max_retries: int = 2):
    if func is None:
        def decorator(f):
            return db_connection_wrapper(f, require_connection=require_connection, max_retries=max_retries)
        return decorator

    is_async = inspect.iscoroutinefunction(func)

    @wraps(func)
    async def async_wrapper(self, *args, **kwargs):
        _before_method()
        result = Result(success=False, operation=func.__name__)

        for name, val in list(enumerate(args)) + list(kwargs.items()):
            if isinstance(val, Result) and not val.success:
                result.error_message = f"Aborted: input argument '{name}' for {func.__name__} received failed result:\n {val.error_message}"
                result.data = val.data
                _after_method(result)
                return result

        args = tuple(arg.data if isinstance(arg, Result) else arg for arg in args)
        kwargs = {k: v.data if isinstance(v, Result) else v for k, v in kwargs.items()}

        attempts = 0
        while attempts < max_retries:
            try:
                if require_connection:
                    connected = await self.connect() if inspect.iscoroutinefunction(self.connect) else self.connect()
                    if not connected:
                        raise Exception("Database connection failed in External_DB_Connection level.")

                data = await func(self, *args, **kwargs)

                if isinstance(data, Result):
                    _after_method(data)
                    return data

                result.success = True
                result.data = data
                break

            except Exception as e:
                attempts += 1
                if func.__name__ not in (self.make_connection.__name__, self.reset.__name__):
                    if isinstance(e, asyncpg.TooManyConnectionsError):
                        ErrorLogger.background_log_error(6, f"Too many connections, skipping reset.", e)
                        break  # Do not retry/reset here!
                    else:
                        if inspect.iscoroutinefunction(self.reset):
                            await self.reset()
                        else:
                            self.reset()
                if attempts == max_retries:
                    result.error_message = f"{type(e).__name__} Exceeded max retries: {str(e)}"
                    ErrorLogger.background_log_error(6, result.error_message, e)
                    break

        _after_method(result)
        return result

    @wraps(func)
    def sync_wrapper(self, *args, **kwargs):
        _before_method()
        result = Result(success=False, operation=func.__name__)

        try:
            for name, val in list(enumerate(args)) + list(kwargs.items()):
                if isinstance(val, Result) and not val.success:
                    result.error_message = f"Aborted: input argument '{name}' for {func.__name__} received failed result:\n {val.error_message}"
                    result.data = val.data
                    _after_method(result)
                    return result

            args = tuple(arg.data if isinstance(arg, Result) else arg for arg in args)
            kwargs = {k: v.data if isinstance(v, Result) else v for k, v in kwargs.items()}

            data = func(self, *args, **kwargs)

            if isinstance(data, Result):
                _after_method(data)
                return data

            result.success = True
            result.data = data

        except Exception as e:
            result.error_message = f"{type(e).__name__}: {str(e)}"
            ErrorLogger.background_log_error(6, result.error_message, e)

        _after_method(result)
        return result

    return async_wrapper if is_async else sync_wrapper


def _before_method():
    pass


def _after_method(result=None):
    pass


def generate_key():
    if not os.path.exists(SESSION_KEY_FILE):
        with open(SESSION_KEY_FILE, "wb") as key_file:
            key_file.write(Fernet.generate_key())


def load_key():
    with open(SESSION_KEY_FILE, "rb") as key_file:
        return key_file.read()


generate_key()
fernet = Fernet(load_key())


class External_DB_Connection(PostgreSQL):
    _lock = asyncio.Lock()

    def __init__(
            self,
            session_file: str,
            access_level: int = 0,
            host: Optional[str] = None,
            port: int = 5432,
            database: Optional[str] = None,
            user: Optional[str] = None,
            password: Optional[str] = None,
            timeout: int = 5,
            verbose: bool = False,
            session_duration: int = 300,
    ) -> None:

        super().__init__(self)  # Set _db_owner = self early!

        self._pool: Optional[asyncpg.pool.Pool] = None
        self.verbose = verbose
        self.session_duration = session_duration
        self.session_expiry: Optional[float] = None
        self.session_file = session_file
        self.access_level = access_level
        self.structure_root = STRUCTURE_ROOT
        if host is None and os.path.exists(session_file):
            self._load_session_from_file(session_file)
        else:
            self.conn_params = {
                "host": host,
                "database": database,
                "user": user,
                "password": password,
                "port": port,
                "timeout": timeout
            }

    @db_connection_wrapper
    async def _save_session_to_file(self):
        session_data = {
            "conn_params": self.conn_params,
            "verbose": self.verbose,
            "expires_at": (TimeManager().now_utc() + TimeManager().timedelta(seconds=self.session_duration)).timestamp()
        }
        encrypted = fernet.encrypt(json.dumps(session_data).encode())
        with open(self.session_file, "wb") as f:
            f.write(encrypted)

    @db_connection_wrapper
    def _load_session_from_file(self, session_file: str):
        with open(session_file, "rb") as f:
            data = json.loads(fernet.decrypt(f.read()).decode())
        self.conn_params = data["conn_params"]
        self.verbose = data["verbose"]
        self.session_expiry = data["expires_at"]

    @db_connection_wrapper
    async def _is_session_valid(self) -> bool:
        return self.session_expiry is not None and TimeManager().now_utc().timestamp() < self.session_expiry

    @db_connection_wrapper
    async def make_connection(self) -> Optional[asyncpg.Connection]:
        async def init_connection(conn):
            await conn.set_type_codec(
                'jsonb',
                encoder=json.dumps,
                decoder=json.loads,
                schema='pg_catalog',
                format='text'
            )

        sanitized_params = {
            'host': self.conn_params.get('host'),
            'database': self.conn_params.get('database'),
            'user': self.conn_params.get('user'),
            'password': self.conn_params.get('password'),
            'port': int(self.conn_params.get('port', 5432)),  # Ensure integer
            'command_timeout': float(self.conn_params.get('timeout', 5)),  # map correctly
            # 'ssl': 'require'  # <-- FORCE ASYNCPG TO USE TLS HANDSHAKE
        }
        self.pool = await asyncpg.create_pool(**sanitized_params, init=init_connection, max_inactive_connection_lifetime=3)
        await self._save_session_to_file()
        return self.pool

    @db_connection_wrapper
    async def connect(self) -> bool:
        if not await self._is_session_valid() or not self.pool:
            return await self.reset()
        return True

    @db_connection_wrapper
    async def reset(self) -> bool:
        async with External_DB_Connection._lock:
            try:
                if self.pool is None:
                    # Nothing to health-check yet (e.g. very first call in
                    # this process) -- skip straight to building one instead
                    # of calling .acquire() on None.
                    raise ConnectionError("no pool yet")
                async with asyncio.timeout(5):
                    async with self.pool.acquire() as conn:
                        await conn.fetchval("SELECT 1")
                    # DebugLogger.async_log_debug(1, f"Pool is Ok and does not need to be reset")
                return True  # Pool is OK, no reset
            except Exception as e:
                # ErrorLogger.async_log_error(6, f"Pool health check failed. Resetting pool...", e)
                await self.disconnect()
                await self.make_connection()
                return self.pool is not None

    @db_connection_wrapper
    async def disconnect(self):
        if self.pool and not self.pool._closed:
            await self.pool.close()
        self.pool = None
        # if os.path.exists(self.session_file):
        #     os.remove(self.session_file)

    @db_connection_wrapper
    async def check(self) -> bool:
        return await self._is_session_valid() and self.pool

    @db_connection_wrapper(require_connection=False)
    async def ping(self) -> Result:
        start = TimeManager().perf_counter()
        async with self.pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        end = TimeManager().perf_counter()
        return Result(True, "get_db_ping", "", round((end - start) * 1000, 3))



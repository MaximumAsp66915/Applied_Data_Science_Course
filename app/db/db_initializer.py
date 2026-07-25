import asyncio
import json
import os
from pathlib import Path
from cryptography.fernet import Fernet

from config import get_config
from db.external_db.connection_external_db import External_DB_Connection
from db.external_db.user_external_db import EXTERNAL_DB_SESSION, External_DB_User
from db.internal_db.connection_internal_db import Internal_DB_Connection
from db.internal_db.user_internal_db import Internal_DB_User, INTERNAL_DB_SESSION
from utils.loggers.error_logger import ErrorLogger

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KEY_FILE = f"{PROJECT_ROOT}/db/db_files/initialize.key"
DB_INITIALIZE_FILE = f"{PROJECT_ROOT}/db/db_files/initialize_session.session"


def generate_key():
    if not os.path.exists(KEY_FILE):
        with open(KEY_FILE, "wb") as key_file:
            key_file.write(Fernet.generate_key())


def load_key():
    with open(KEY_FILE, "rb") as key_file:
        return key_file.read()


generate_key()
fernet = Fernet(load_key())


class DB_Initialize:
    def __init__(self):
        with open(DB_INITIALIZE_FILE, "rb") as f:
            data = json.loads(fernet.decrypt(f.read()).decode())
        self.internal_db_parameter = data["internal_db"]
        self.external_db_parameter = data["external_db"]

    @staticmethod
    async def create_db_initialize_file():
        session_data = get_config().SESSION_DATA
        encrypted = fernet.encrypt(json.dumps(session_data).encode())
        with open(DB_INITIALIZE_FILE, "wb") as f:
            f.write(encrypted)

    @staticmethod
    async def start():
        total_result = True
        await DB_Initialize.create_db_initialize_file()
        db_initialize = DB_Initialize()
        if not await db_initialize.internal_db_initialize():
            ErrorLogger.background_log_error(-3, "Internal DB initialization failed")
            total_result = False

        if not await db_initialize.external_db_initialize():
            ErrorLogger.background_log_error(-3, "External DB initialization failed")
            total_result = False

        return total_result

    async def internal_db_initialize(self) -> bool:
        async with Internal_DB_User.lock:
            conn_params = self.internal_db_parameter["conn_params"]

            db = Internal_DB_Connection(
                session_file=INTERNAL_DB_SESSION,
                host=conn_params["host"],
                port=conn_params["port"],
                database=conn_params["database"],
                user=conn_params["user"],
                password=conn_params["password"],
                # timeout=conn_params["timeout"],
                verbose=self.internal_db_parameter["verbose"]
            )
            await db.make_connection()
            result = await db.ping()
            if not result.success:
                return False
            return True

    async def external_db_initialize(self) -> bool:
        async with External_DB_User.lock:
            conn_params = self.external_db_parameter["conn_params"]

            db = External_DB_Connection(
                session_file=EXTERNAL_DB_SESSION,
                host=conn_params["host"],
                port=conn_params["port"],
                database=conn_params["database"],
                user=conn_params["user"],
                password=conn_params["password"],
                # timeout=conn_params["timeout"],
                verbose=self.external_db_parameter["verbose"]
            )
            await db.make_connection()
            result = await db.ping()
            if not result.success:
                return False
            return True


if __name__ == "__main__":
    asyncio.run(DB_Initialize.create_db_initialize_file())

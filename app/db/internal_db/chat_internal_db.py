import asyncio

from db.internal_db.connection_internal_db import Internal_DB_Connection
from db.chat_db import Chat_DB
from pathlib import Path
from typing import Optional, Union

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INTERNAL_DB_SESSION = f"{PROJECT_ROOT}/db/internal_db/internal_db_session.session"


class Internal_DB_Chat(Chat_DB):
    _db_connection = None

    def __init__(self,
                 chat_id: Optional[Union[int, str]] = None
                 ) -> None:
        Chat_DB.__init__(self, self._db_connection, chat_id)
        if not Internal_DB_Chat._db_connection:
            Internal_DB_Chat._db_connection = Internal_DB_Connection(INTERNAL_DB_SESSION, 10)
        self.db = Internal_DB_Chat._db_connection
        self.instance = __class__ if chat_id is None else self
        self.chat_id = chat_id


async def main():
    result = await (Internal_DB_Chat().db.ping())
    print(result)

if __name__ == "__main__":
    asyncio.run(main())

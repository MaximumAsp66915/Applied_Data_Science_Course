import asyncio

from db.external_db.connection_external_db import External_DB_Connection
from db.chat_db import Chat_DB
from pathlib import Path
from typing import Optional, Union

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXTERNAL_DB_SESSION = f"{PROJECT_ROOT}/db/external_db/external_db_session.session"


class External_DB_Chat(Chat_DB):
    _db_connection = None

    def __init__(self,
                 chat_id: Optional[Union[int, str]] = None
                 ) -> None:
        Chat_DB.__init__(self, self._db_connection, chat_id)
        if not External_DB_Chat._db_connection:
            External_DB_Chat._db_connection = External_DB_Connection(EXTERNAL_DB_SESSION, 10)
        self.db = External_DB_Chat._db_connection
        self.instance = __class__ if chat_id is None else self
        self.chat_id = chat_id


async def main():
    result = await (External_DB_Chat().db.ping())
    print(result)

if __name__ == "__main__":
    asyncio.run(main())

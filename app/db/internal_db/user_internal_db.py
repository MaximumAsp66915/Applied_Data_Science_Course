import asyncio

from db.internal_db.connection_internal_db import Internal_DB_Connection
from db.user_db import User_DB
from pathlib import Path
from typing import Optional, Union

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INTERNAL_DB_SESSION = f"{PROJECT_ROOT}/db/internal_db/internal_db_session.session"


class Internal_DB_User(User_DB):
    _db_connection = None

    def __init__(self,
                 user_id: Optional[Union[int, str]] = None
                 ) -> None:
        User_DB.__init__(self, self._db_connection, user_id)
        if not Internal_DB_User._db_connection:
            Internal_DB_User._db_connection = Internal_DB_Connection(INTERNAL_DB_SESSION, 10)
        self.db = Internal_DB_User._db_connection
        self.instance = __class__ if user_id is None else self
        self.user_id = user_id


async def main():
    result = await (Internal_DB_User().db.ping())
    print(result)
    # print(Internal_DB_User().db.ping())

if __name__ == "__main__":
    asyncio.run(main())

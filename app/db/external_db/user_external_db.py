import asyncio

from db.external_db.connection_external_db import External_DB_Connection
from db.user_db import User_DB
from pathlib import Path
from typing import Optional, Union

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXTERNAL_DB_SESSION = f"{PROJECT_ROOT}/db/external_db/external_db_session.session"


class External_DB_User(User_DB):
    _db_connection = None

    def __init__(self,
                 user_id: Optional[Union[int, str]] = None
                 ) -> None:
        User_DB.__init__(self, self._db_connection, user_id)
        if not External_DB_User._db_connection:
            External_DB_User._db_connection = External_DB_Connection(EXTERNAL_DB_SESSION, 10)
        self.db = External_DB_User._db_connection
        self.instance = __class__ if user_id is None else self
        self.user_id = user_id


async def main():
    # print(await External_DB_User().db.make_connection())
    result = await (External_DB_User().db.ping())
    print(result)
    # print(External_DB_User().db.ping())

if __name__ == "__main__":
    asyncio.run(main())

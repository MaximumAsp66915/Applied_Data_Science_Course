import asyncio

from db.internal_db.connection_internal_db import Internal_DB_Connection
from db.SUTMusic_db.genre_db import Genre_DB
from pathlib import Path
from typing import Optional, Union

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INTERNAL_DB_SESSION = f"{PROJECT_ROOT}/db/internal_db/internal_db_session.session"

class Internal_DB_Genre(Genre_DB):
    _db_connection = None

    def __init__(self,
                 genre_id: Optional[Union[int, str]] = None
                 ) -> None:
        Genre_DB.__init__(self, self._db_connection, genre_id)
        if not Internal_DB_Genre._db_connection:
            Internal_DB_Genre._db_connection = Internal_DB_Connection(INTERNAL_DB_SESSION, 10)
        self.db = Internal_DB_Genre._db_connection
        self.instance = __class__ if genre_id is None else self
        self.genre_id = genre_id


async def main():
    # print(await Internal_DB_Genre().db.make_connection())
    result = await (Internal_DB_Genre().db.ping())
    print(result)
    # print(Internal_DB_Genre().db.ping())

if __name__ == "__main__":
    asyncio.run(main())

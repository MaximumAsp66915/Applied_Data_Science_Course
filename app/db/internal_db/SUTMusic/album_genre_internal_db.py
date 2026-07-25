import asyncio

from db.internal_db.connection_internal_db import Internal_DB_Connection
from db.SUTMusic_db.album_genre_db import AlbumGenre_DB
from pathlib import Path
from typing import Optional, Union

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INTERNAL_DB_SESSION = f"{PROJECT_ROOT}/db/internal_db/internal_db_session.session"

class Internal_DB_AlbumGenre(AlbumGenre_DB):
    _db_connection = None

    def __init__(self,
                 album_genre_id: Optional[Union[int, str]] = None
                 ) -> None:
        AlbumGenre_DB.__init__(self, self._db_connection, album_genre_id)
        if not Internal_DB_AlbumGenre._db_connection:
            Internal_DB_AlbumGenre._db_connection = Internal_DB_Connection(INTERNAL_DB_SESSION, 10)
        self.db = Internal_DB_AlbumGenre._db_connection
        self.instance = __class__ if album_genre_id is None else self
        self.album_genre_id = album_genre_id


async def main():
    # print(await Internal_DB_AlbumGenre().db.make_connection())
    # print(await Internal_DB_AlbumGenre().db.reset())
    result = await (Internal_DB_AlbumGenre().db.ping())
    print(result)
    # print(Internal_DB_AlbumGenre().db.ping())

if __name__ == "__main__":
    asyncio.run(main())

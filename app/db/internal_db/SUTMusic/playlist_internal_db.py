import asyncio

from db.internal_db.connection_internal_db import Internal_DB_Connection
from db.SUTMusic_db.playlist_db import Playlist_DB
from pathlib import Path
from typing import Optional, Union

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INTERNAL_DB_SESSION = f"{PROJECT_ROOT}/db/internal_db/internal_db_session.session"

class Internal_DB_Playlist(Playlist_DB):
    _db_connection = None

    def __init__(self,
                 playlist_id: Optional[Union[int, str]] = None
                 ) -> None:
        Playlist_DB.__init__(self, self._db_connection, playlist_id)
        if not Internal_DB_Playlist._db_connection:
            Internal_DB_Playlist._db_connection = Internal_DB_Connection(INTERNAL_DB_SESSION, 10)
        self.db = Internal_DB_Playlist._db_connection
        self.instance = __class__ if playlist_id is None else self
        self.playlist_id = playlist_id


async def main():
    # print(await Internal_DB_Playlist().db.make_connection())
    # print(await Internal_DB_Playlist().db.reset())
    result = await (Internal_DB_Playlist().db.ping())
    print(result)
    # print(Internal_DB_Playlist().db.ping())

if __name__ == "__main__":
    asyncio.run(main())

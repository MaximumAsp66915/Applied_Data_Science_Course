import asyncio

from db.internal_db.connection_internal_db import Internal_DB_Connection
from db.SUTMusic_db.track_db import Track_DB
from pathlib import Path
from typing import Optional, Union

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INTERNAL_DB_SESSION = f"{PROJECT_ROOT}/db/internal_db/internal_db_session.session"

class Internal_DB_Track(Track_DB):
    _db_connection = None

    def __init__(self,
                 track_id: Optional[Union[int, str]] = None
                 ) -> None:
        Track_DB.__init__(self, self._db_connection, track_id)
        if not Internal_DB_Track._db_connection:
            Internal_DB_Track._db_connection = Internal_DB_Connection(INTERNAL_DB_SESSION, 10)
        self.db = Internal_DB_Track._db_connection
        self.instance = __class__ if track_id is None else self
        self.track_id = track_id


async def main():
    # print(await Internal_DB_Track().db.make_connection())
    result = await (Internal_DB_Track().db.ping())
    print(result)
    # print(Internal_DB_Track().db.ping())

if __name__ == "__main__":
    asyncio.run(main())

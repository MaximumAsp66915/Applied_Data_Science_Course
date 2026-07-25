import asyncio

from db.internal_db.connection_internal_db import Internal_DB_Connection
from db.SUTMusic_db.track_comment_db import TrackComment_DB
from pathlib import Path
from typing import Optional, Union

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INTERNAL_DB_SESSION = f"{PROJECT_ROOT}/db/internal_db/internal_db_session.session"

class Internal_DB_TrackComment(TrackComment_DB):
    _db_connection = None

    def __init__(self,
                 track_comment_id: Optional[Union[int, str]] = None
                 ) -> None:
        TrackComment_DB.__init__(self, self._db_connection, track_comment_id)
        if not Internal_DB_TrackComment._db_connection:
            Internal_DB_TrackComment._db_connection = Internal_DB_Connection(INTERNAL_DB_SESSION, 10)
        self.db = Internal_DB_TrackComment._db_connection
        self.instance = __class__ if track_comment_id is None else self
        self.track_comment_id = track_comment_id


async def main():
    # print(await Internal_DB_TrackComment().db.make_connection())
    # print(await Internal_DB_TrackComment().db.reset())
    result = await (Internal_DB_TrackComment().db.ping())
    print(result)
    # print(Internal_DB_TrackComment().db.ping())

if __name__ == "__main__":
    asyncio.run(main())

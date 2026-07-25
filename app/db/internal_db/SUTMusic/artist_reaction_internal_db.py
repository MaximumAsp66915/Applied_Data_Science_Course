import asyncio

from db.internal_db.connection_internal_db import Internal_DB_Connection
from db.SUTMusic_db.artist_reaction_db import ArtistReaction_DB
from pathlib import Path
from typing import Optional, Union

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INTERNAL_DB_SESSION = f"{PROJECT_ROOT}/db/internal_db/internal_db_session.session"

class Internal_DB_ArtistReaction(ArtistReaction_DB):
    _db_connection = None

    def __init__(self,
                 artist_reaction_id: Optional[Union[int, str]] = None
                 ) -> None:
        ArtistReaction_DB.__init__(self, self._db_connection, artist_reaction_id)
        if not Internal_DB_ArtistReaction._db_connection:
            Internal_DB_ArtistReaction._db_connection = Internal_DB_Connection(INTERNAL_DB_SESSION, 10)
        self.db = Internal_DB_ArtistReaction._db_connection
        self.instance = __class__ if artist_reaction_id is None else self
        self.artist_reaction_id = artist_reaction_id


async def main():
    # print(await Internal_DB_ArtistReaction().db.make_connection())
    # print(await Internal_DB_ArtistReaction().db.reset())
    result = await (Internal_DB_ArtistReaction().db.ping())
    print(result)
    # print(Internal_DB_ArtistReaction().db.ping())

if __name__ == "__main__":
    asyncio.run(main())

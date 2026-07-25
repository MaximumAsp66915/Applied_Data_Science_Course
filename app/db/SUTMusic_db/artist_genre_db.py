import asyncio
from typing import Dict, Any, Optional, Tuple
from db.internal_db.connection_internal_db import Internal_DB_Connection
from utils.result import Result

# Field mapping configurations based on the 'artist_genres' database schema
scalar_fields = {
    "id",
    "artist_id",
    "genre_id",
    "confidence",
    "source",
    "updated_at",
}
array_fields = set()  # No array-type fields defined in this schema
jsonb_fields = set()  # No jsonb-type fields defined in this schema


class ArtistGenre_DB:
    # Class-level lock for managing shared asynchronous synchronization states if required
    lock = asyncio.Lock()

    def __init__(self, db: "Internal_DB_Connection" = None, entry_id: Optional[int] = None) -> None:
        """
        Initializes the low-level artist genre database access object.

        Args:
            db (Internal_DB_Connection, optional): Shared connection manager for database operations.
            entry_id (int, optional): The structural primary key 'id' of the artist_genres row.
        """
        self.entry_id = entry_id
        self.db = db

    async def get_genre_row(self, entry_id: Optional[int] = None) -> Optional[dict]:
        """
        Fetches the complete raw dictionary representation of a specific row from 'artist_genres'.
        """
        entry_id = entry_id or self.entry_id
        if entry_id is None:
            return None
        result = await self.db.get_row("artist_genres", {"id": entry_id})
        if result.success and result.data:
            return dict(result.data)
        return None

    async def get_genre_by_id(self, entry_id: Optional[int] = None) -> Optional["ArtistGenre_DB"]:
        """
        Verifies row existence and constructs a self-referential Instance mapped to the database ID.
        """
        entry_id = entry_id or self.entry_id
        if entry_id is None:
            return None
        result = await self.db.get_value("artist_genres", {"id": entry_id}, "id")
        if result.success and result.data:
            return ArtistGenre_DB(db=self.db, entry_id=result.data)
        return None

    async def search_genres(
            self,
            conditions: Dict[str, Tuple[str, Any]],
            fuzzy: bool = False,
            similarity_threshold: float = 0.7,
            limit: int = 10,
            order_by: str = "id",
            descending: bool = False,
    ) -> Optional[list["ArtistGenre_DB"]]:
        """
        Searches the 'artist_genres' table using arbitrary structured comparison conditions.
        """
        if conditions is None:
            return None
        result = await self.db.search_ids(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            table_name="artist_genres",
            id_column="id",
            order_by=order_by,
            descending=descending,
            scalar_fields=scalar_fields,
            array_fields=array_fields,
            jsonb_fields=jsonb_fields,
        )
        if result.success and result.data:
            for i in range(len(result.data)):
                result.data[i] = ArtistGenre_DB(db=self.db, entry_id=result.data[i])
            return result.data
        return None

    async def add_genre(self, genre_data: Dict[str, Any]) -> Result:
        """
        Executes an INSERT operation to construct a new row within the artist_genres relational dataset.
        """
        return await self.db.insert_and_return_id(
            table="artist_genres",
            row_data=genre_data
        )

    async def get_parameter_from_db(self, entry_id: Optional[int], param: str) -> Result:
        """
        Targets a unique specific column element out of a designated target artist genre association record.
        """
        entry_id = entry_id or self.entry_id
        if entry_id is None:
            return Result(False, "get_parameter", "Entry ID not provided", None)

        return await self.db.get_value("artist_genres", {"id": entry_id}, param)

    async def update_parameter(self, entry_id: Optional[int], param: str, value: Any) -> Result:
        """
        Executes a targeted UPDATE statement modifying an isolated row element inside the database.
        """
        entry_id = entry_id or self.entry_id
        if entry_id is None:
            return Result(False, "update_parameter", "Entry ID not provided", None)

        return await self.db.update_row(
            "artist_genres", {param: value}, {"id": entry_id}
        )

    async def delete_genre_by_id(self, entry_id: Optional[int] = None) -> Result:
        """
        Issues a hard DELETE statement aimed directly at removing the selected artist genre reference resource.
        """
        entry_id = entry_id or self.entry_id
        if entry_id is None:
            return Result(False, "delete_genre_by_id", "Entry ID not provided", None)

        return await self.db.delete_row("artist_genres", {"id": entry_id})

    def __repr__(self) -> str:
        """Returns readable debug logging context mapping runtime class identity metadata."""
        if self.entry_id is None:
            text = f"""[{self.__class__.__name__} Class attribution]"""
        else:
            text = f"""[{self.__class__.__name__} Object] -> artist genre entry: {self.entry_id} (from {self.db.__class__.__name__})"""
        return text
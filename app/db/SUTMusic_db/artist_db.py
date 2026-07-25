import asyncio
from typing import Dict, Any, Optional, Tuple
from psycopg2._json import Json
from db.internal_db.connection_internal_db import Internal_DB_Connection
from utils.result import Result

scalar_fields = {
    "id",
    "name",
    "cover_id",
    "description",
    "score",
    "rank",
    "likes_count",
    "dislikes_count",
    "reactions_count",
    "created_at",
    "updated_at",
}
array_fields = set()  # No array fields for artists
jsonb_fields = {
    "metadata",
}


class Artist_DB:
    lock = asyncio.Lock()

    def __init__(self, db: "Internal_DB_Connection" = None, artist_id: Optional[int] = None) -> None:
        self.artist_id = artist_id
        self.db = db

    async def get_artist_row(self, artist_id: Optional[int] = None) -> Optional[dict]:
        artist_id = artist_id or self.artist_id
        if artist_id is None:
            return None
        result = await self.db.get_row("artists", {"id": artist_id})
        if result.success and result.data:
            return dict(result.data)
        return None

    async def get_artist_by_id(self, artist_id: Optional[int] = None) -> Optional["Artist_DB"]:
        artist_id = artist_id or self.artist_id
        if artist_id is None:
            return None
        result = await self.db.get_value("artists", {"id": artist_id}, "id")
        if result.success and result.data:
            return Artist_DB(db=self.db, artist_id=result.data)
        return None

    async def search_artists(
        self,
        conditions: Dict[str, Tuple[str, Any]],
        fuzzy: bool = False,
        similarity_threshold: float = 0.7,
        limit: int = 10,
        order_by: str = "id",
        descending: bool = False,
    ) -> Optional[list["Artist_DB"]]:
        if conditions is None:
            return None
        result = await self.db.search_ids(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            table_name="artists",
            id_column="id",
            order_by=order_by,
            descending=descending,
            scalar_fields=scalar_fields,
            array_fields=array_fields,
            jsonb_fields=jsonb_fields,
        )
        if result.success and result.data:
            for i in range(len(result.data)):
                result.data[i] = Artist_DB(db=self.db, artist_id=result.data[i])
            return result.data
        return None

    async def add_artist(self, artist_data: Dict[str, Any]) -> Result:
        """
        Insert a new artist row into the artists table. Handles JSONB serialization.
        Args:
            artist_data (Dict[str, Any]): Dictionary of artist data.
        Returns:
            Result: Result object indicating success or failure.
        """
        return await self.db.insert_and_return_id(
            table="artists",
            row_data=artist_data
        )

    async def get_parameter_from_db(self, artist_id: Optional[int], param: str) -> Result:
        artist_id = artist_id or self.artist_id
        if artist_id is None:
            return Result(False, "get_parameter", "Artist ID not provided", None)

        return await self.db.get_value("artists", {"id": artist_id}, param)

    async def update_parameter(self, artist_id: Optional[int], param: str, value: Any) -> Result:
        artist_id = artist_id or self.artist_id
        if artist_id is None:
            return Result(False, "update_parameter", "Artist ID not provided", None)

        return await self.db.update_row(
            "artists", {param: value}, {"id": artist_id}, updated_at_column="updated_at"
        )

    async def delete_artist_by_id(self, artist_id: Optional[int] = None) -> Result:
        artist_id = artist_id or self.artist_id
        if artist_id is None:
            return Result(False, "delete_artist_by_id", "Artist ID not provided", None)

        return await self.db.delete_row("artists", {"id": artist_id})

    def __repr__(self) -> str:
        if self.artist_id is None:
            text = f"""[{self.__class__.__name__} Class attribution]"""
        else:
            text = f"""[{self.__class__.__name__} Object] -> artist: {self.artist_id} (from {self.db.__class__.__name__})"""
        return text
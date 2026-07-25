import asyncio
from typing import Dict, Any, Optional, Tuple
from psycopg2._json import Json
from db.internal_db.connection_internal_db import Internal_DB_Connection
from utils.result import Result
from datetime import datetime

scalar_fields = {
    "id",
    "title",
    "artist_id",
    "release_date",
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
array_fields = set()  # no array fields now
jsonb_fields = {
    "metadata",
}


class Album_DB:
    lock = asyncio.Lock()

    def __init__(self, db: "Internal_DB_Connection" = None, album_id: Optional[int] = None) -> None:
        self.album_id = album_id
        self.db = db

    async def get_album_row(self, album_id: Optional[int] = None) -> Optional[dict]:
        album_id = album_id or self.album_id
        if album_id is None:
            return None
        result = await self.db.get_row("albums", {"id": album_id})
        if result.success and result.data:
            return dict(result.data)
        return None

    async def get_album_by_id(self, album_id: Optional[int] = None) -> Optional["Album_DB"]:
        album_id = album_id or self.album_id
        if album_id is None:
            return None
        result = await self.db.get_value("albums", {"id": album_id}, "id")
        if result.success and result.data:
            return Album_DB(db=self.db, album_id=result.data)
        return None

    async def search_albums(
        self,
        conditions: Dict[str, Tuple[str, Any]],
        fuzzy: bool = False,
        similarity_threshold: float = 0.7,
        limit: int = 10,
        order_by: str = "id",
        descending: bool = False,
    ) -> Optional[list["Album_DB"]]:
        if conditions is None:
            return None
        result = await self.db.search_ids(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            table_name="albums",
            id_column="id",
            order_by=order_by,
            descending=descending,
            scalar_fields=scalar_fields,
            array_fields=array_fields,
            jsonb_fields=jsonb_fields,
        )
        if result.success and result.data:
            for i in range(len(result.data)):
                result.data[i] = Album_DB(db=self.db, album_id=result.data[i])
            return result.data
        return None

    async def add_album(self, album_data: Dict[str, Any]) -> Result:
        """
        Insert a new album row into the albums table. Handles JSONB and array serialization.
        Args:
            album_data (Dict[str, Any]): Dictionary of album data.
        Returns:
            Result: Result object indicating success or failure.
        """
        # Prepare values safely
        safe_data = {}
        for key, value in album_data.items():
            if key == "release_date" and isinstance(value, str):
                safe_data[key] = datetime.strptime(value, "%Y-%m-%d").date()
            elif key in array_fields:
                safe_data[key] = value  # leave native Python list
            else:
                safe_data[key] = value  # scalar value

        print(safe_data)
        return await self.db.insert_and_return_id(
            table="albums",
            row_data=safe_data
        )

    async def get_parameter_from_db(self, album_id: Optional[int], param: str) -> Result:
        album_id = album_id or self.album_id
        if album_id is None:
            return Result(False, "get_parameter", "Album ID not provided", None)

        return await self.db.get_value("albums", {"id": album_id}, param)

    async def update_parameter(self, album_id: Optional[int], param: str, value: Any) -> Result:
        album_id = album_id or self.album_id
        if album_id is None:
            return Result(False, "update_parameter", "Album ID not provided", None)

        if param == "release_date" and isinstance(value, str):
            value = datetime.strptime(value, "%Y-%m-%d").date()

        return await self.db.update_row(
            "albums", {param: value}, {"id": album_id}, updated_at_column="updated_at"
        )

    async def delete_album_by_id(self, album_id: Optional[int] = None) -> Result:
        album_id = album_id or self.album_id
        if album_id is None:
            return Result(False, "delete_album_by_id", "Album ID not provided", None)

        return await self.db.delete_row("albums", {"id": album_id})

    def __repr__(self) -> str:
        if self.album_id is None:
            text = f"""[{self.__class__.__name__} Class attribution]"""
        else:
            text = f"""[{self.__class__.__name__} Object] -> album: {self.album_id} (from {self.db.__class__.__name__})"""
        return text
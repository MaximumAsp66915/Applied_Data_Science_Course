import asyncio
from typing import Dict, Any, Optional, Tuple
from psycopg2._json import Json
from db.internal_db.connection_internal_db import Internal_DB_Connection
from utils.result import Result

scalar_fields = {
    "id",
    "file_id",
    "unique_file_id",
    "file_type",
    "mime_type",
    "extension",
    "title",
    "duration",
    "performer",
    "cover_id",
    "album_id",
    "chat_id",
    "message_id",
    "score",
    "rank",
    "likes_count",
    "dislikes_count",
    "reactions_count",
    "created_at",
    "updated_at",
}
array_fields = {
    "artists_id",  # Added here
    "uploaded_by"
}
jsonb_fields = {
    "metadata",
}


class Track_DB:
    lock = asyncio.Lock()

    def __init__(self, db: "Internal_DB_Connection" = None, track_id: Optional[int] = None) -> None:
        self.track_id = track_id
        self.db = db

    async def get_track_row(self, track_id: Optional[int] = None) -> Optional[dict]:
        track_id = track_id or self.track_id
        if track_id is None:
            return None
        result = await self.db.get_row("tracks", {"id": track_id})
        if result.success and result.data:
            return dict(result.data)
        return None

    async def get_track_by_id(self, track_id: Optional[int] = None) -> Optional["Track_DB"]:
        track_id = track_id or self.track_id
        if track_id is None:
            return None
        result = await self.db.get_value("tracks", {"id": track_id}, "id")
        if result.success and result.data:
            return Track_DB(db=self.db, track_id=result.data)
        return None

    async def search_tracks(
        self,
        conditions: Dict[str, Tuple[str, Any]],
        fuzzy: bool = False,
        similarity_threshold: float = 0.7,
        limit: int = 10,
        order_by: str = "id",
        descending: bool = False,
    ) -> Optional[list["Track_DB"]]:
        if conditions is None:
            return None
        result = await self.db.search_ids(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            table_name="tracks",
            id_column="id",
            order_by=order_by,
            descending=descending,
            scalar_fields=scalar_fields,
            array_fields=array_fields,
            jsonb_fields=jsonb_fields,
        )
        if result.success and result.data:
            for i in range(len(result.data)):
                result.data[i] = Track_DB(db=self.db, track_id=result.data[i])
            return result.data
        return None

    async def add_track(self, track_data: Dict[str, Any]) -> Result:
        """
        Insert a new track row into the tracks table. Handles JSONB serialization.
        Args:
            track_data (Dict[str, Any]): Dictionary of track values.
        Returns:
            Result: Result object indicating success or failure.
        """

        return await self.db.insert_and_return_id(
            table="tracks",
            row_data=track_data
        )

    async def get_parameter_from_db(self, track_id: Optional[int], param: str) -> Result:
        track_id = track_id or self.track_id
        if track_id is None:
            return Result(False, "get_parameter", "Track ID not provided", None)

        return await self.db.get_value("tracks", {"id": track_id}, param)

    async def update_parameter(self, track_id: Optional[int], param: str, value: Any) -> Result:
        track_id = track_id or self.track_id
        if track_id is None:
            return Result(False, "update_parameter", "Track ID not provided", None)

        return await self.db.update_row(
            "tracks", {param: value}, {"id": track_id}, updated_at_column="updated_at"
        )

    async def delete_track_by_id(self, track_id: Optional[int] = None) -> Result:
        track_id = track_id or self.track_id
        if track_id is None:
            return Result(False, "delete_track_by_id", "Track ID not provided", None)

        return await self.db.delete_row("tracks", {"id": track_id})

    def __repr__(self) -> str:
        if self.track_id is None:
            text = f"""[{self.__class__.__name__} Class attribution]"""
        else:
            text = f"""[{self.__class__.__name__} Object] -> track: {self.track_id} (from {self.db.__class__.__name__})"""
        return text
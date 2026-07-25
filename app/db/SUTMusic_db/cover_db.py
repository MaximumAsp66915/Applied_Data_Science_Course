import asyncio
from typing import Dict, Any, Optional, Tuple
from psycopg2._json import Json
from db.internal_db.connection_internal_db import Internal_DB_Connection
from utils.result import Result

scalar_fields = {
    "id",
    "file_id",
    "unique_file_id",
    "file_format",
    "mime_type",
    "file_size",
    "file_url",
    "width",
    "height",
    "uploaded_by",
    "source",
    "created_at",
    "updated_at",
}
array_fields = set()  # no array fields now
jsonb_fields = {
    "metadata",
}


class Cover_DB:
    lock = asyncio.Lock()

    def __init__(self, db: "Internal_DB_Connection" = None, cover_id: Optional[int] = None) -> None:
        self.cover_id = cover_id
        self.db = db

    async def get_cover_row(self, cover_id: Optional[int] = None) -> Optional[dict]:
        cover_id = cover_id or self.cover_id
        if cover_id is None:
            return None
        result = await self.db.get_row("covers", {"id": cover_id})
        if result.success and result.data:
            return dict(result.data)
        return None

    async def get_cover_by_id(self, cover_id: Optional[int] = None) -> Optional["Cover_DB"]:
        cover_id = cover_id or self.cover_id
        if cover_id is None:
            return None
        result = await self.db.get_value("covers", {"id": cover_id}, "id")
        if result.success and result.data:
            return Cover_DB(db=self.db, cover_id=result.data)
        return None

    async def search_covers(
        self,
        conditions: Dict[str, Tuple[str, Any]],
        fuzzy: bool = False,
        similarity_threshold: float = 0.7,
        limit: int = 10,
        order_by: str = "id",
        descending: bool = False,
    ) -> Optional[list["Cover_DB"]]:
        if conditions is None:
            return None
        result = await self.db.search_ids(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            table_name="covers",
            id_column="id",
            order_by=order_by,
            descending=descending,
            scalar_fields=scalar_fields,
            array_fields=array_fields,
            jsonb_fields=jsonb_fields,
        )
        if result.success and result.data:
            for i in range(len(result.data)):
                result.data[i] = Cover_DB(db=self.db, cover_id=result.data[i])
            return result.data
        return None

    async def add_cover(self, cover_data: Dict[str, Any]) -> Result:
        """
        Insert a new cover row into the cover table. Handles JSONB and array serialization.
        Args:
            cover_data (Dict[str, Any]): Dictionary of cover data.
        Returns:
            Result: Result object indicating success or failure.
        """

        return await self.db.insert_and_return_id(
            table="covers",
            row_data=cover_data
        )

    async def get_parameter_from_db(self, cover_id: Optional[int], param: str) -> Result:
        cover_id = cover_id or self.cover_id
        if cover_id is None:
            return Result(False, "get_parameter", "Cover ID not provided", None)

        return await self.db.get_value("covers", {"id": cover_id}, param)

    async def update_parameter(self, cover_id: Optional[int], param: str, value: Any) -> Result:
        cover_id = cover_id or self.cover_id
        if cover_id is None:
            return Result(False, "update_parameter", "Cover ID not provided", None)

        return await self.db.update_row(
            "covers", {param: value}, {"id": cover_id}, updated_at_column="updated_at"
        )

    async def delete_cover_by_id(self, cover_id: Optional[int] = None) -> Result:
        cover_id = cover_id or self.cover_id
        if cover_id is None:
            return Result(False, "delete_cover_by_id", "Cover ID not provided", None)

        return await self.db.delete_row("covers", {"id": cover_id})

    def __repr__(self) -> str:
        if self.cover_id is None:
            text = f"""[{self.__class__.__name__} Class attribution]"""
        else:
            text = f"""[{self.__class__.__name__} Object] -> cover: {self.cover_id} (from {self.db.__class__.__name__})"""
        return text
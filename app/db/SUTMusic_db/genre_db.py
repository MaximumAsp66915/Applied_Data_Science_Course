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
    "created_at",
    "updated_at",
}
array_fields = set()  # no array fields now
jsonb_fields = set()  # no jsonb fields now


class Genre_DB:
    lock = asyncio.Lock()

    def __init__(self, db: "Internal_DB_Connection" = None, genre_id: Optional[int] = None) -> None:
        self.genre_id = genre_id
        self.db = db

    async def get_genre_row(self, genre_id: Optional[int] = None) -> Optional[dict]:
        genre_id = genre_id or self.genre_id
        if genre_id is None:
            return None
        result = await self.db.get_row("genres", {"id": genre_id})
        if result.success and result.data:
            return dict(result.data)
        return None

    async def get_genre_by_id(self, genre_id: Optional[int] = None) -> Optional["Genre_DB"]:
        genre_id = genre_id or self.genre_id
        if genre_id is None:
            return None
        result = await self.db.get_value("genres", {"id": genre_id}, "id")
        if result.success and result.data:
            return Genre_DB(db=self.db, genre_id=result.data)
        return None

    async def search_genres(
        self,
        conditions: Dict[str, Tuple[str, Any]],
        fuzzy: bool = False,
        similarity_threshold: float = 0.7,
        limit: int = 10,
        order_by: str = "id",
        descending: bool = False,
    ) -> Optional[list["Genre_DB"]]:
        if conditions is None:
            return None
        result = await self.db.search_ids(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            table_name="genres",
            id_column="id",
            order_by=order_by,
            descending=descending,
            scalar_fields=scalar_fields,
            array_fields=array_fields,
            jsonb_fields=jsonb_fields,
        )
        if result.success and result.data:
            for i in range(len(result.data)):
                result.data[i] = Genre_DB(db=self.db, genre_id=result.data[i])
            return result.data
        return None

    async def add_genre(self, genre_data: Dict[str, Any]) -> Result:
        """
        Insert a new genre row into the genres table. Handles JSONB and array serialization.
        Args:
            genre_data (Dict[str, Any]): Dictionary of genre data.
        Returns:
            Result: Result object indicating success or failure.
        """
        return await self.db.insert_and_return_id(
            table="genres",
            row_data=genre_data
        )

    async def get_parameter_from_db(self, genre_id: Optional[int], param: str) -> Result:
        genre_id = genre_id or self.genre_id
        if genre_id is None:
            return Result(False, "get_parameter", "Genre ID not provided", None)

        return await self.db.get_value("genres", {"id": genre_id}, param)

    async def update_parameter(self, genre_id: Optional[int], param: str, value: Any) -> Result:
        genre_id = genre_id or self.genre_id
        if genre_id is None:
            return Result(False, "update_parameter", "Genre ID not provided", None)

        return await self.db.update_row(
            "genres", {param: value}, {"id": genre_id}, updated_at_column="updated_at"
        )

    async def delete_genre_by_id(self, genre_id: Optional[int] = None) -> Result:
        genre_id = genre_id or self.genre_id
        if genre_id is None:
            return Result(False, "delete_genre_by_id", "Genre ID not provided", None)

        return await self.db.delete_row("genres", {"id": genre_id})

    def __repr__(self) -> str:
        if self.genre_id is None:
            text = f"""[{self.__class__.__name__} Class attribution]"""
        else:
            text = f"""[{self.__class__.__name__} Object] -> genre: {self.genre_id} (from {self.db.__class__.__name__})"""
        return text
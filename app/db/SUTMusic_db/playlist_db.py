import asyncio
from typing import Dict, Any, Optional, Tuple
from psycopg2._json import Json
from db.internal_db.connection_internal_db import Internal_DB_Connection
from utils.result import Result

scalar_fields = {
    "id",
    "owner_id",
    "name",
    "description",
    "is_public",
    "cover_id",
    "score",
    "rank",
    "likes_count",
    "dislikes_count",
    "reactions_count",
    "created_at",
    "updated_at",
}
array_fields = set()
jsonb_fields = {
    "metadata",
}


class Playlist_DB:
    lock = asyncio.Lock()

    def __init__(self, db: "Internal_DB_Connection" = None, playlist_id: Optional[int] = None) -> None:
        self.playlist_id = playlist_id
        self.db = db

    async def get_playlist_row(self, playlist_id: Optional[int] = None) -> Optional[dict]:
        playlist_id = playlist_id or self.playlist_id
        if playlist_id is None:
            return None
        result = await self.db.get_row("playlists", {"id": playlist_id})
        if result.success and result.data:
            return dict(result.data)
        return None

    async def get_playlist_by_id(self, playlist_id: Optional[int] = None) -> Optional["Playlist_DB"]:
        playlist_id = playlist_id or self.playlist_id
        if playlist_id is None:
            return None
        result = await self.db.get_value("playlists", {"id": playlist_id}, "id")
        if result.success and result.data:
            return Playlist_DB(db=self.db, playlist_id=result.data)
        return None

    async def search_playlists(
        self,
        conditions: Dict[str, Tuple[str, Any]],
        fuzzy: bool = False,
        similarity_threshold: float = 0.7,
        limit: int = 10,
        order_by: str = "id",
        descending: bool = False,
    ) -> Optional[list["Playlist_DB"]]:
        if conditions is None:
            return None
        result = await self.db.search_ids(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            table_name="playlists",
            id_column="id",
            order_by=order_by,
            descending=descending,
            scalar_fields=scalar_fields,
            array_fields=array_fields,
            jsonb_fields=jsonb_fields,
        )
        if result.success and result.data:
            for i in range(len(result.data)):
                result.data[i] = Playlist_DB(db=self.db, playlist_id=result.data[i])
            return result.data
        return None

    async def add_playlist(self, playlist_data: Dict[str, Any]) -> Result:
        return await self.db.insert_and_return_id(
            table="playlists",
            row_data=playlist_data
        )

    async def get_parameter_from_db(self, playlist_id: Optional[int], param: str) -> Result:
        playlist_id = playlist_id or self.playlist_id
        if playlist_id is None:
            return Result(False, "get_parameter", "Playlist ID not provided", None)

        return await self.db.get_value("playlists", {"id": playlist_id}, param)

    async def update_parameter(self, playlist_id: Optional[int], param: str, value: Any) -> Result:
        playlist_id = playlist_id or self.playlist_id
        if playlist_id is None:
            return Result(False, "update_parameter", "Playlist ID not provided", None)

        return await self.db.update_row(
            "playlists", {param: value}, {"id": playlist_id}, updated_at_column="updated_at"
        )

    async def delete_playlist_by_id(self, playlist_id: Optional[int] = None) -> Result:
        playlist_id = playlist_id or self.playlist_id
        if playlist_id is None:
            return Result(False, "delete_playlist_by_id", "Playlist ID not provided", None)

        return await self.db.delete_row("playlists", {"id": playlist_id})

    def __repr__(self) -> str:
        if self.playlist_id is None:
            text = f"""[{self.__class__.__name__} Class attribution]"""
        else:
            text = f"""[{self.__class__.__name__} Object] -> playlist: {self.playlist_id} (from {self.db.__class__.__name__})"""
        return text
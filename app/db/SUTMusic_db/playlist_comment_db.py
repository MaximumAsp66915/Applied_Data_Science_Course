import asyncio
from typing import Dict, Any, Optional, Tuple
from db.internal_db.connection_internal_db import Internal_DB_Connection
from utils.result import Result

# Field mapping configurations based on the 'playlist_comments' database schema
scalar_fields = {
    "id",
    "playlist_id",
    "user_id",
    "comment",
    "commented_at",
}
array_fields = set()  # No array-type fields defined in this schema
jsonb_fields = set()  # No jsonb-type fields defined in this schema


class PlaylistComment_DB:
    # Class-level lock for managing shared asynchronous synchronization states if required
    lock = asyncio.Lock()

    def __init__(self, db: "Internal_DB_Connection" = None, comment_id: Optional[int] = None) -> None:
        """
        Initializes the low-level playlist comment database access object.

        Args:
            db (Internal_DB_Connection, optional): Shared connection manager for database operations.
            comment_id (int, optional): The structural primary key 'id' of the comment row.
        """
        self.comment_id = comment_id
        self.db = db

    async def get_comment_row(self, comment_id: Optional[int] = None) -> Optional[dict]:
        """
        Fetches the complete raw dictionary representation of a specific row from 'playlist_comments'.
        """
        comment_id = comment_id or self.comment_id
        if comment_id is None:
            return None
        result = await self.db.get_row("playlist_comments", {"id": comment_id})
        if result.success and result.data:
            return dict(result.data)
        return None

    async def get_comment_by_id(self, comment_id: Optional[int] = None) -> Optional["PlaylistComment_DB"]:
        """
        Verifies row existence and constructs a self-referential Instance mapped to the database ID.
        """
        comment_id = comment_id or self.comment_id
        if comment_id is None:
            return None
        result = await self.db.get_value("playlist_comments", {"id": comment_id}, "id")
        if result.success and result.data:
            return PlaylistComment_DB(db=self.db, comment_id=result.data)
        return None

    async def search_comments(
            self,
            conditions: Dict[str, Tuple[str, Any]],
            fuzzy: bool = False,
            similarity_threshold: float = 0.7,
            limit: int = 10,
            order_by: str = "id",
            descending: bool = False,
    ) -> Optional[list["PlaylistComment_DB"]]:
        """
        Searches the 'playlist_comments' table using arbitrary structured comparison conditions.
        """
        if conditions is None:
            return None
        result = await self.db.search_ids(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            table_name="playlist_comments",
            id_column="id",
            order_by=order_by,
            descending=descending,
            scalar_fields=scalar_fields,
            array_fields=array_fields,
            jsonb_fields=jsonb_fields,
        )
        if result.success and result.data:
            for i in range(len(result.data)):
                result.data[i] = PlaylistComment_DB(db=self.db, comment_id=result.data[i])
            return result.data
        return None

    async def add_comment(self, comment_data: Dict[str, Any]) -> Result:
        """
        Executes an INSERT operation to construct a new row within the playlist_comments relational dataset.
        """
        return await self.db.insert_and_return_id(
            table="playlist_comments",
            row_data=comment_data
        )

    async def get_parameter_from_db(self, comment_id: Optional[int], param: str) -> Result:
        """
        Targets a unique specific column element out of a designated target comment record.
        """
        comment_id = comment_id or self.comment_id
        if comment_id is None:
            return Result(False, "get_parameter", "Comment ID not provided", None)

        return await self.db.get_value("playlist_comments", {"id": comment_id}, param)

    async def update_parameter(self, comment_id: Optional[int], param: str, value: Any) -> Result:
        """
        Executes a targeted UPDATE statement modifying an isolated row element inside the database.
        """
        comment_id = comment_id or self.comment_id
        if comment_id is None:
            return Result(False, "update_parameter", "Comment ID not provided", None)

        return await self.db.update_row(
            "playlist_comments", {param: value}, {"id": comment_id}
        )

    async def delete_comment_by_id(self, comment_id: Optional[int] = None) -> Result:
        """
        Issues a hard DELETE statement aimed directly at removing the selected comment resource.
        """
        comment_id = comment_id or self.comment_id
        if comment_id is None:
            return Result(False, "delete_comment_by_id", "Comment ID not provided", None)

        return await self.db.delete_row("playlist_comments", {"id": comment_id})

    def __repr__(self) -> str:
        """Returns readable debug logging context mapping runtime class identity metadata."""
        if self.comment_id is None:
            text = f"""[{self.__class__.__name__} Class attribution]"""
        else:
            text = f"""[{self.__class__.__name__} Object] -> playlist comment: {self.comment_id} (from {self.db.__class__.__name__})"""
        return text
import asyncio
from typing import Dict, Any, Optional, Tuple
from psycopg2._json import Json
from db.internal_db.connection_internal_db import Internal_DB_Connection
from utils.result import Result

# Field mapping configurations based on the 'artist_comments' database schema
scalar_fields = {
    "id",
    "artist_id",
    "user_id",
    "comment",
    "commented_at",
}
array_fields = set()  # No array-type fields defined in this schema
jsonb_fields = set()  # No jsonb-type fields defined in this schema


class ArtistComment_DB:
    # Class-level lock for managing shared asynchronous synchronization states if required
    lock = asyncio.Lock()

    def __init__(self, db: "Internal_DB_Connection" = None, comment_id: Optional[int] = None) -> None:
        """
        Initializes the low-level artist comment database access object.

        Args:
            db (Internal_DB_Connection, optional): Shared connection manager for database operations.
            comment_id (int, optional): The structural primary key 'id' of the comment row.
        """
        self.comment_id = comment_id
        self.db = db

    async def get_comment_row(self, comment_id: Optional[int] = None) -> Optional[dict]:
        """
        Fetches the complete raw dictionary representation of a specific row from 'artist_comments'.

        Args:
            comment_id (int, optional): Fallback or override ID targeting the requested comment row.

        Returns:
            Optional[dict]: A raw dictionary representing the row columns, or None if not found/empty.
        """
        comment_id = comment_id or self.comment_id
        if comment_id is None:
            return None
        result = await self.db.get_row("artist_comments", {"id": comment_id})
        if result.success and result.data:
            return dict(result.data)
        return None

    async def get_comment_by_id(self, comment_id: Optional[int] = None) -> Optional["ArtistComment_DB"]:
        """
        Verifies row existence and constructs a self-referential Instance mapped to the database ID.

        Args:
            comment_id (int, optional): The target comment row identifier.

        Returns:
            Optional[ArtistComment_DB]: An instance tracking the verified column entry, or None.
        """
        comment_id = comment_id or self.comment_id
        if comment_id is None:
            return None
        result = await self.db.get_value("artist_comments", {"id": comment_id}, "id")
        if result.success and result.data:
            return ArtistComment_DB(db=self.db, comment_id=result.data)
        return None

    async def search_comments(
            self,
            conditions: Dict[str, Tuple[str, Any]],
            fuzzy: bool = False,
            similarity_threshold: float = 0.7,
            limit: int = 10,
            order_by: str = "id",
            descending: bool = False,
    ) -> Optional[list["ArtistComment_DB"]]:
        """
        Searches the 'artist_comments' table using arbitrary structured comparison conditions.

        Args:
            conditions (Dict[str, Tuple[str, Any]]): Mapping of field strings to comparison tuple expressions,
                                                     e.g., {"artist_id": ("=", 42)}
            fuzzy (bool): Evaluates whether approximate string matching logic should be activated.
            similarity_threshold (float): Precision parameter constraint for structural fuzzy filtering queries.
            limit (int): Constraints on the maximum allowed array slices returned from execution.
            order_by (str): The string column target designating sorting focus.
            descending (bool): Reverses output ordering when evaluated as True.

        Returns:
            Optional[list[ArtistComment_DB]]: A collection of materialized reference wrappers tracking matches.
        """
        if conditions is None:
            return None
        result = await self.db.search_ids(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            table_name="artist_comments",
            id_column="id",
            order_by=order_by,
            descending=descending,
            scalar_fields=scalar_fields,
            array_fields=array_fields,
            jsonb_fields=jsonb_fields,
        )
        if result.success and result.data:
            for i in range(len(result.data)):
                result.data[i] = ArtistComment_DB(db=self.db, comment_id=result.data[i])
            return result.data
        return None

    async def add_comment(self, comment_data: Dict[str, Any]) -> Result:
        """
        Executes an INSERT operation to construct a new row within the artist_comments relational dataset.

        Args:
            comment_data (Dict[str, Any]): Structural key-value arguments defining initial row state.

        Returns:
            Result: Utility wrapper containing execution flags and structural returning values.
        """
        return await self.db.insert_and_return_id(
            table="artist_comments",
            row_data=comment_data
        )

    async def get_parameter_from_db(self, comment_id: Optional[int], param: str) -> Result:
        """
        Targets a unique specific column element out of a designated target comment record.

        Args:
            comment_id (int, optional): Targeted database primary key reference identifier.
            param (str): Selected field string identifying the target table column metadata.

        Returns:
            Result: Encapsulated wrapper containing single-column data attributes.
        """
        comment_id = comment_id or self.comment_id
        if comment_id is None:
            return Result(False, "get_parameter", "Comment ID not provided", None)

        return await self.db.get_value("artist_comments", {"id": comment_id}, param)

    async def update_parameter(self, comment_id: Optional[int], param: str, value: Any) -> Result:
        """
        Executes a targeted UPDATE statement modifying an isolated row element inside the database.

        Args:
            comment_id (int, optional): Unique reference sequence matching the operational row.
            param (str): Chosen relational column name.
            value (Any): Primitive or specialized type parameter setting the replacement data field.

        Returns:
            Result: Status operational response execution object tracking database mutation state.
        """
        comment_id = comment_id or self.comment_id
        if comment_id is None:
            return Result(False, "update_parameter", "Comment ID not provided", None)

        return await self.db.update_row(
            "artist_comments", {param: value}, {"id": comment_id}
        )

    async def delete_comment_by_id(self, comment_id: Optional[int] = None) -> Result:
        """
        Issues a hard DELETE statement aimed directly at removing the selected comment resource.

        Args:
            comment_id (int, optional): Identifier targeting deletion extraction vectors.

        Returns:
            Result: Internal database execution operation report state.
        """
        comment_id = comment_id or self.comment_id
        if comment_id is None:
            return Result(False, "delete_comment_by_id", "Comment ID not provided", None)

        return await self.db.delete_row("artist_comments", {"id": comment_id})

    def __repr__(self) -> str:
        """Returns readable debug logging context mapping runtime class identity metadata."""
        if self.comment_id is None:
            text = f"""[{self.__class__.__name__} Class attribution]"""
        else:
            text = f"""[{self.__class__.__name__} Object] -> artist comment: {self.comment_id} (from {self.db.__class__.__name__})"""
        return text
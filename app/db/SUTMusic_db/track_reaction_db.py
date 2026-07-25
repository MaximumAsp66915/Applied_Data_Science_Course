import asyncio
from typing import Dict, Any, Optional, Tuple
from db.internal_db.connection_internal_db import Internal_DB_Connection
from utils.result import Result

# Field mapping configurations based on the 'track_reactions' database schema
scalar_fields = {
    "id",
    "track_id",
    "user_id",
    "reaction_id",
    "sentiment",
    "on_user_id",
    "message_id",
    "genre_id",
    "reacted_at",
}
array_fields = set()
jsonb_fields = set()


class TrackReaction_DB:
    lock = asyncio.Lock()

    def __init__(self, db: "Internal_DB_Connection" = None, entry_id: Optional[int] = None) -> None:
        """
        Initializes the low-level track reaction database access object.
        """
        self.entry_id = entry_id
        self.db = db

    async def get_reaction_row(self, entry_id: Optional[int] = None) -> Optional[dict]:
        """
        Fetches the complete raw dictionary representation of a specific row from 'track_reactions'.
        """
        entry_id = entry_id or self.entry_id
        if entry_id is None:
            return None
        result = await self.db.get_row("track_reactions", {"id": entry_id})
        if result.success and result.data:
            return dict(result.data)
        return None

    async def get_reaction_by_id(self, entry_id: Optional[int] = None) -> Optional["TrackReaction_DB"]:
        """
        Verifies row existence and constructs a self-referential Instance mapped to the database ID.
        """
        entry_id = entry_id or self.entry_id
        if entry_id is None:
            return None
        result = await self.db.get_value("track_reactions", {"id": entry_id}, "id")
        if result.success and result.data:
            return TrackReaction_DB(db=self.db, entry_id=result.data)
        return None

    async def search_from_reactions(
            self,
            conditions: Dict[str, Tuple[str, Any]],
            fuzzy: bool = False,
            return_column: str = "id",
            similarity_threshold: float = 0.7,
            limit: int = 10,
            order_by: str = "id",
            descending: bool = False,
    ) -> Optional[list]:
        """
        Searches the 'track_reactions' table using structured comparison conditions.
        """
        if conditions is None:
            return None
        result = await self.db.search_ids(
            conditions=conditions,
            fuzzy=fuzzy,
            id_column=return_column,
            similarity_threshold=similarity_threshold,
            limit=limit,
            table_name="track_reactions",
            order_by=order_by,
            descending=descending,
            scalar_fields=scalar_fields,
            array_fields=array_fields,
            jsonb_fields=jsonb_fields,
        )

        return result.data

    async def search_reactions(
            self,
            conditions: Dict[str, Tuple[str, Any]],
            fuzzy: bool = False,
            similarity_threshold: float = 0.7,
            limit: int = 10,
            order_by: str = "id",
            descending: bool = False,
    ) -> Optional[list["TrackReaction_DB"]]:
        """
        Searches the 'track_reactions' table using structured comparison conditions.
        """
        if conditions is None:
            return None
        result = await self.db.search_ids(
            conditions=conditions,
            fuzzy=fuzzy,
            id_column="id",
            similarity_threshold=similarity_threshold,
            limit=limit,
            table_name="track_reactions",
            order_by=order_by,
            descending=descending,
            scalar_fields=scalar_fields,
            array_fields=array_fields,
            jsonb_fields=jsonb_fields,
        )
        if result.success and result.data:
            for i in range(len(result.data)):
                result.data[i] = TrackReaction_DB(db=self.db, entry_id=result.data[i])
            return result.data
        return None

    async def add_reaction(self, reaction_data: Dict[str, Any]) -> Result:
        """
        Executes an INSERT operation to construct a new row within the track_reactions table.
        """
        return await self.db.insert_and_return_id(
            table="track_reactions",
            row_data=reaction_data
        )

    async def get_parameter_from_db(self, entry_id: Optional[int], param: str) -> Result:
        """
        Targets a unique specific column element out of a designated target reaction record.
        """
        entry_id = entry_id or self.entry_id
        if entry_id is None:
            return Result(False, "get_parameter", "Entry ID not provided", None)

        return await self.db.get_value("track_reactions", {"id": entry_id}, param)

    async def update_parameter(self, entry_id: Optional[int], param: str, value: Any) -> Result:
        """
        Executes a targeted UPDATE statement modifying an isolated row element inside the database.
        """
        entry_id = entry_id or self.entry_id
        if entry_id is None:
            return Result(False, "update_parameter", "Entry ID not provided", None)

        return await self.db.update_row(
            "track_reactions", {param: value}, {"id": entry_id}
        )

    async def delete_reaction_by_id(self, entry_id: Optional[int] = None) -> Result:
        """
        Issues a hard DELETE statement aimed directly at removing the selected reaction resource.
        """
        entry_id = entry_id or self.entry_id
        if entry_id is None:
            return Result(False, "delete_reaction_by_id", "Entry ID not provided", None)

        return await self.db.delete_row("track_reactions", {"id": entry_id})

    def __repr__(self) -> str:
        if self.entry_id is None:
            text = f"""[{self.__class__.__name__} Class attribution]"""
        else:
            text = f"""[{self.__class__.__name__} Object] -> track reaction entry: {self.entry_id} (from {self.db.__class__.__name__})"""
        return text
import asyncio
from typing import Dict, Any, Optional, Tuple
from db.internal_db.connection_internal_db import Internal_DB_Connection
from utils.result import Result
from psycopg2._json import Json

scalar_fields = {
    "id",
    "emoji",
    "sentiment",
    "score",
    "description",
}
array_fields = set()
jsonb_fields = set()


class ReactionType_DB:
    lock = asyncio.Lock()

    def __init__(self, db: "Internal_DB_Connection" = None, reaction_type_id: Optional[int] = None) -> None:
        self.reaction_type_id = reaction_type_id
        self.db = db

    async def get_reaction_row(self, reaction_type_id: Optional[int] = None) -> Optional[dict]:
        reaction_type_id = reaction_type_id or self.reaction_type_id
        if reaction_type_id is None:
            return None
        result = await self.db.get_row("reaction_types", {"id": reaction_type_id})
        if result.success and result.data:
            return dict(result.data)
        return None

    async def get_reaction_row_by_emoji(self, emoji: Optional[str] = None) -> Optional[dict]:
        if emoji is None:
            return None
        result = await self.db.get_row("reaction_types", {"emoji": emoji})
        if result.success and result.data:
            return dict(result.data)
        return None

    async def get_reaction_by_id(self, reaction_type_id: Optional[int] = None) -> Optional["ReactionType_DB"]:
        reaction_type_id = reaction_type_id or self.reaction_type_id
        if reaction_type_id is None:
            return None
        result = await self.db.get_value("reaction_types", {"id": reaction_type_id}, "id")
        if result.success and result.data:
            return ReactionType_DB(db=self.db, reaction_type_id=result.data)
        return None

    async def get_reaction_by_emoji(self, emoji: Optional[str] = None) -> Optional["ReactionType_DB"]:
        if emoji is None:
            return None
        result = await self.db.get_value("reaction_types", {"emoji": emoji}, "id")
        if result.success and result.data:
            return ReactionType_DB(db=self.db, reaction_type_id=result.data)
        return None

    async def search_reactions(
        self,
        conditions: Dict[str, Tuple[str, Any]],
        fuzzy: bool = False,
        similarity_threshold: float = 0.7,
        limit: int = 10,
        order_by: str = "id",
        descending: bool = False,
    ) -> Optional[list["ReactionType_DB"]]:
        if conditions is None:
            return None
        result = await self.db.search_ids(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            table_name="reaction_types",
            id_column="id",
            order_by=order_by,
            descending=descending,
            scalar_fields=scalar_fields,
            array_fields=array_fields,
            jsonb_fields=jsonb_fields,
        )
        if result.success and result.data:
            for i in range(len(result.data)):
                result.data[i] = ReactionType_DB(db=self.db, reaction_type_id=result.data[i])
            return result.data
        return None

    async def add_reaction(self, reaction_data: Dict[str, Any]) -> Result:
        return await self.db.insert_and_return_id(
            table="reaction_types",
            row_data=reaction_data
        )

    async def get_parameter_from_db(self, reaction_type_id: Optional[int], param: str) -> Result:
        reaction_type_id = reaction_type_id or self.reaction_type_id
        if reaction_type_id is None:
            return Result(False, "get_parameter", "Emoji not provided", None)

        return await self.db.get_value("reaction_types", {"id": reaction_type_id}, param)

    async def update_parameter(self, reaction_type_id: Optional[int], param: str, value: Any) -> Result:
        reaction_type_id = reaction_type_id or self.reaction_type_id
        if reaction_type_id is None:
            return Result(False, "update_parameter", "Emoji not provided", None)

        return await self.db.update_row(
            "reaction_types", {param: value}, {"id": reaction_type_id}
        )

    async def delete_reaction_by_emoji(self, reaction_type_id: Optional[int] = None) -> Result:
        reaction_type_id = reaction_type_id or self.reaction_type_id
        if reaction_type_id is None:
            return Result(False, "delete_reaction_by_emoji", "Emoji not provided", None)

        return await self.db.delete_row("reaction_types", {"id": reaction_type_id})

    def __repr__(self) -> str:
        if self.reaction_type_id is None:
            text = f"""[{self.__class__.__name__} Class attribution]"""
        else:
            text = f"""[{self.__class__.__name__} Object] -> reaction: {self.reaction_type_id} (from {self.db.__class__.__name__})"""
        return text
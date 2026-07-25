import asyncio
from typing import Dict, Any, Optional, Tuple
from psycopg2._json import Json
from db.internal_db.connection_internal_db import Internal_DB_Connection
from utils.result import Result

scalar_fields = {
    "id",
    "chat_id",
    "chat_type",
    "user_id",
    "linked_chat_id",
    "is_verified",
    "is_scam",
    "is_fake",
    "is_restricted",
    "created_at",
    "updated_at",
    "last_activity_at",
}

array_fields = set()  # none for now

jsonb_fields = {
    "title",
    "username",
    "first_name",
    "last_name",
    "bio",
    "description",
    "invite_link",
    "sticker_set_name",
    "permissions",
    "member_count",
    "extra_data",
}


class Chat_DB:
    lock = asyncio.Lock()

    def __init__(self, db: "Internal_DB_Connection" = None, chat_id: Optional[int] = None) -> None:
        self.chat_id = chat_id
        self.db = db

    async def get_chat_row(self, chat_id: Optional[int] = None) -> Optional[dict]:
        chat_id = chat_id or self.chat_id
        if chat_id is None:
            return None
        result = await self.db.get_row("chats", {"chat_id": chat_id})
        if result.success and result.data:
            return dict(result.data)
        return None

    async def get_chat_by_id(self, chat_id: Optional[int] = None) -> Optional["Chat_DB"]:
        chat_id = chat_id or self.chat_id
        if chat_id is None:
            return None
        result = await self.db.get_value("chats", {"chat_id": chat_id}, "chat_id")
        if result.success and result.data:
            return Chat_DB(db=self.db, chat_id=result.data)
        return None

    async def search_chats(
        self,
        conditions: Dict[str, Tuple[str, Any]],
        fuzzy: bool = False,
        similarity_threshold: float = 0.7,
        limit: int = 10,
        order_by: str = "id",
        descending: bool = False,
    ) -> Optional[list["Chat_DB"]]:
        if conditions is None:
            return None
        result = await self.db.search_ids(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            table_name="chats",
            id_column="chat_id",
            order_by=order_by,
            descending=descending,
            scalar_fields=scalar_fields,
            array_fields=array_fields,
            jsonb_fields=jsonb_fields,
        )
        if result.success and result.data:
            for i in range(len(result.data)):
                result.data[i] = Chat_DB(db=self.db, chat_id=result.data[i])
            return result.data
        return None

    async def add_chat(self, chat_data: Dict[str, Any]) -> Result:
        safe_data = {}
        for key, value in chat_data.items():
            if key in jsonb_fields:
                safe_data[key] = Json(value)
            elif key in array_fields:
                safe_data[key] = value
            else:
                safe_data[key] = value

        return await self.db.add_row(
            table_name="chats",
            row_data=safe_data,
            conflict_columns=["chat_id"]
        )

    async def get_parameter_from_db(self, chat_id: Optional[int], param: str) -> Result:
        chat_id = chat_id or self.chat_id
        if chat_id is None:
            return Result(False, "get_parameter", "Chat ID not provided", None)

        return await self.db.get_value("chats", {"chat_id": chat_id}, param)

    async def update_parameter(self, chat_id: Optional[int], param: str, value: Any) -> Result:
        chat_id = chat_id or self.chat_id
        if chat_id is None:
            return Result(False, "update_parameter", "Chat ID not provided", None)

        return await self.db.update_row(
            "chats", {param: value}, {"chat_id": chat_id}, updated_at_column="updated_at"
        )

    async def delete_chat_by_id(self, chat_id: Optional[int] = None) -> Result:
        chat_id = chat_id or self.chat_id
        if chat_id is None:
            return Result(False, "delete_chat_by_id", "Chat ID not provided", None)

        return await self.db.delete_row("chats", {"chat_id": chat_id})

    def __repr__(self) -> str:
        if self.chat_id is None:
            text = f"""[{self.__class__.__name__} Class attribution]"""
        else:
            text = f"""[{self.__class__.__name__} Object] -> chat: {self.chat_id} (from {self.db.__class__.__name__})"""
        return text

import asyncio
from typing import Dict, Any, Optional, Tuple
from psycopg2._json import Json
from db.internal_db.connection_internal_db import Internal_DB_Connection
from utils.result import Result

scalar_fields = {
    "user_id",
    "cover_id",
    "description",
    "total_likes",
    "total_dislikes",
    "total_reactions",
    "total_received_likes",
    "total_received_dislikes",
    "total_received_reactions",
    "total_uploaded_tracks",
    "score",
    "rank",
    "created_at",
    "updated_at",
}
array_fields = set()
jsonb_fields = {
    "recent_actions",
    "metadata",
}


class UserMusicBotState_DB:
    lock = asyncio.Lock()

    def __init__(self, db: "Internal_DB_Connection" = None, user_id: Optional[int] = None) -> None:
        self.user_id = user_id
        self.db = db

    async def get_state_row(self, user_id: Optional[int] = None) -> Optional[dict]:
        user_id = user_id or self.user_id
        if user_id is None:
            return None
        result = await self.db.get_row("user_musicbot_state", {"user_id": user_id})
        if result.success and result.data:
            return dict(result.data)
        return None

    async def get_state_by_user_id(self, user_id: Optional[int] = None) -> Optional["UserMusicBotState_DB"]:
        user_id = user_id or self.user_id
        if user_id is None:
            return None
        result = await self.db.get_value("user_musicbot_state", {"user_id": user_id}, "user_id")
        if result.success and result.data:
            return UserMusicBotState_DB(db=self.db, user_id=result.data)
        return None

    async def search_states(
        self,
        conditions: Dict[str, Tuple[str, Any]],
        fuzzy: bool = False,
        similarity_threshold: float = 0.7,
        limit: int = 10,
        order_by: str = "user_id",
        descending: bool = False,
    ) -> Optional[list["UserMusicBotState_DB"]]:
        if conditions is None:
            return None
        result = await self.db.search_ids(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            table_name="user_musicbot_state",
            id_column="user_id",
            order_by=order_by,
            descending=descending,
            scalar_fields=scalar_fields,
            array_fields=array_fields,
            jsonb_fields=jsonb_fields,
        )
        if result.success and result.data:
            for i in range(len(result.data)):
                result.data[i] = UserMusicBotState_DB(db=self.db, user_id=result.data[i])
            return result.data
        return None

    async def add_state(self, state_data: Dict[str, Any]) -> Result:
        # Since user_id is the explicit PRIMARY KEY, we pass it down
        safe_data = {}
        for key, value in state_data.items():
            if key in jsonb_fields:
                safe_data[key] = Json(value)
            elif key in array_fields:
                safe_data[key] = value
            else:
                safe_data[key] = value

        return await self.db.add_row(
            table_name="user_musicbot_state",
            row_data=safe_data,
            conflict_columns=["user_id"]
        )

    async def get_parameter_from_db(self, user_id: Optional[int], param: str) -> Result:
        user_id = user_id or self.user_id
        if user_id is None:
            return Result(False, "get_parameter", "User ID not provided", None)

        return await self.db.get_value("user_musicbot_state", {"user_id": user_id}, param)

    async def update_parameter(self, user_id: Optional[int], param: str, value: Any) -> Result:
        user_id = user_id or self.user_id
        if user_id is None:
            return Result(False, "update_parameter", "User ID not provided", None)

        return await self.db.update_row(
            "user_musicbot_state", {param: value}, {"user_id": user_id}, updated_at_column="updated_at"
        )

    async def delete_state_by_user_id(self, user_id: Optional[int] = None) -> Result:
        user_id = user_id or self.user_id
        if user_id is None:
            return Result(False, "delete_state_by_user_id", "User ID not provided", None)

        return await self.db.delete_row("user_musicbot_state", {"user_id": user_id})

    def __repr__(self) -> str:
        if self.user_id is None:
            text = f"""[{self.__class__.__name__} Class attribution]"""
        else:
            text = f"""[{self.__class__.__name__} Object] -> user: {self.user_id} (from {self.db.__class__.__name__})"""
        return text
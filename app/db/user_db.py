import asyncio
from typing import Dict, Any, Optional, Tuple
from psycopg2._json import Json
from db.internal_db.connection_internal_db import Internal_DB_Connection
from utils.result import Result

scalar_fields = {
    "id",
    "user_id",
    "language_code",
    "is_bot",
    "is_premium",
    "is_verified",
    "flag",
    "is_public",
    "created_at",
    "updated_at",
    "last_activity_at",
}
array_fields = set()  # no array fields now
jsonb_fields = {
    "username",
    "first_name",
    "last_name",
    "profile_photo",
    "bio",
    "birthday",
    "activity",
}


class User_DB:
    lock = asyncio.Lock()

    def __init__(self, db: "Internal_DB_Connection" = None, user_id: Optional[int] = None) -> None:
        self.user_id = user_id
        self.db = db

    async def get_user_row(self, user_id: Optional[int] = None) -> Optional[dict]:
        user_id = user_id or self.user_id
        if user_id is None:
            return None
        result = await self.db.get_row("users", {"user_id": user_id})
        if result.success and result.data:
            return dict(result.data)
        return None

    async def get_user_by_id(self, user_id: Optional[int] = None) -> Optional["User_DB"]:
        user_id = user_id or self.user_id
        if user_id is None:
            return None
        result = await self.db.get_value("users", {"user_id": user_id}, "user_id")
        if result.success and result.data:
            return User_DB(db=self.db, user_id=result.data)
        return None

    async def search_users(
        self,
        conditions: Dict[str, Tuple[str, Any]],
        fuzzy: bool = False,
        similarity_threshold: float = 0.7,
        limit: int = 10,
        order_by: str = "id",
        descending: bool = False,
    ) -> Optional[list["User_DB"]]:
        if conditions is None:
            return None
        result = await self.db.search_ids(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            table_name="users",
            id_column="user_id",
            order_by=order_by,
            descending=descending,
            scalar_fields=scalar_fields,
            array_fields=array_fields,
            jsonb_fields=jsonb_fields,
        )
        if result.success and result.data:
            for i in range(len(result.data)):
                result.data[i] = User_DB(db=self.db, user_id=result.data[i])
            return result.data
        return None

    async def add_user(self, user_data: Dict[str, Any]) -> Result:
        """
        Insert a new user row into the given table. Handles JSONB and array serialization.
        Args:
            user_data (Dict[str, Any]): Dictionary of user data.
        Returns:
            Result: Result object indicating success or failure.
        """
        # Prepare values safely
        safe_data = {}
        for key, value in user_data.items():
            if key in jsonb_fields:
                safe_data[key] = Json(value)
            elif key in array_fields:
                safe_data[key] = value  # leave native Python list
            else:
                safe_data[key] = value  # scalar value

        return await self.db.add_row(
            table_name="users",
            row_data=safe_data,
            conflict_columns=["user_id"]
        )

    async def get_parameter_from_db(self, user_id: Optional[int], param: str) -> Result:
        user_id = user_id or self.user_id
        if user_id is None:
            return Result(False, "get_parameter", "User ID not provided", None)

        return await self.db.get_value("users", {"user_id": user_id}, param)

    async def update_parameter(self, user_id: Optional[int], param: str, value: Any) -> Result:
        user_id = user_id or self.user_id
        if user_id is None:
            return Result(False, "update_parameter", "User ID not provided", None)

        return await self.db.update_row(
            "users", {param: value}, {"user_id": user_id}, updated_at_column="updated_at"
        )

    async def delete_user_by_id(self, user_id: Optional[int] = None) -> Result:
        user_id = user_id or self.user_id
        if user_id is None:
            return Result(False, "delete_user_by_id", "User ID not provided", None)

        return await self.db.delete_row("users", {"user_id": user_id})

    def __repr__(self) -> str:
        if self.user_id is None:
            text = f"""[{self.__class__.__name__} Class attribution]"""
        else:
            text = f"""[{self.__class__.__name__} Object] -> user: {self.user_id} (from {self.db.__class__.__name__})"""
        return text

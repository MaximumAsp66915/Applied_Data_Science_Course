import asyncio
from typing import Dict, Any, Optional, Tuple
from db.internal_db.connection_internal_db import Internal_DB_Connection
from utils.result import Result

scalar_fields = {
    "id",
    "target_user_id",
    "commented_by",
    "comment",
    "commented_at",
}
array_fields = set()
jsonb_fields = set()


class UserComment_DB:
    lock = asyncio.Lock()

    def __init__(self, db: "Internal_DB_Connection" = None, comment_id: Optional[int] = None) -> None:
        self.comment_id = comment_id
        self.db = db

    async def get_comment_row(self, comment_id: Optional[int] = None) -> Optional[dict]:
        comment_id = comment_id or self.comment_id
        if comment_id is None:
            return None
        result = await self.db.get_row("user_comments", {"id": comment_id})
        if result.success and result.data:
            return dict(result.data)
        return None

    async def get_comment_by_id(self, comment_id: Optional[int] = None) -> Optional["UserComment_DB"]:
        comment_id = comment_id or self.comment_id
        if comment_id is None:
            return None
        result = await self.db.get_value("user_comments", {"id": comment_id}, "id")
        if result.success and result.data:
            return UserComment_DB(db=self.db, comment_id=result.data)
        return None

    async def search_comments(
        self,
        conditions: Dict[str, Tuple[str, Any]],
        fuzzy: bool = False,
        similarity_threshold: float = 0.7,
        limit: int = 10,
        order_by: str = "id",
        descending: bool = False,
    ) -> Optional[list["UserComment_DB"]]:
        if conditions is None:
            return None
        result = await self.db.search_ids(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            table_name="user_comments",
            id_column="id",
            order_by=order_by,
            descending=descending,
            scalar_fields=scalar_fields,
            array_fields=array_fields,
            jsonb_fields=jsonb_fields,
        )
        if result.success and result.data:
            for i in range(len(result.data)):
                result.data[i] = UserComment_DB(db=self.db, comment_id=result.data[i])
            return result.data
        return None

    async def add_comment(self, comment_data: Dict[str, Any]) -> Result:
        return await self.db.insert_and_return_id(
            table="user_comments",
            row_data=comment_data
        )

    async def get_parameter_from_db(self, comment_id: Optional[int], param: str) -> Result:
        comment_id = comment_id or self.comment_id
        if comment_id is None:
            return Result(False, "get_parameter", "Comment ID not provided", None)

        return await self.db.get_value("user_comments", {"id": comment_id}, param)

    async def update_parameter(self, comment_id: Optional[int], param: str, value: Any) -> Result:
        comment_id = comment_id or self.comment_id
        if comment_id is None:
            return Result(False, "update_parameter", "Comment ID not provided", None)

        return await self.db.update_row(
            "user_comments", {param: value}, {"id": comment_id}
        )

    async def delete_comment_by_id(self, comment_id: Optional[int] = None) -> Result:
        comment_id = comment_id or self.comment_id
        if comment_id is None:
            return Result(False, "delete_comment_by_id", "Comment ID not provided", None)

        return await self.db.delete_row("user_comments", {"id": comment_id})

    def __repr__(self) -> str:
        if self.comment_id is None:
            text = f"""[{self.__class__.__name__} Class attribution]"""
        else:
            text = f"""[{self.__class__.__name__} Object] -> comment: {self.comment_id} (from {self.db.__class__.__name__})"""
        return text
import asyncio
from functools import wraps
from typing import Optional, Union, Any, Callable

from db.internal_db.SUTMusic.user_comment_internal_db import Internal_DB_UserComment
from utils.result import Result
from utils.schedule.dict_helper import AutoExpiringDict

LIST_OF_DICT_FIELDS = set()
DICT_FIELDS = set()
SCALAR_FIELDS = {
    "id",
    "target_user_id",
    "commented_by",
    "comment",
    "commented_at",
}

_in = Internal_DB_UserComment()

comment_param_cache = AutoExpiringDict(ttl_seconds=3600, cleanup_interval=300, max_keys=10000)


def make_hashable(obj):
    if isinstance(obj, dict):
        return tuple(sorted((k, make_hashable(v)) for k, v in obj.items()))
    elif isinstance(obj, list):
        return tuple(make_hashable(i) for i in obj)
    elif isinstance(obj, set):
        return tuple(sorted(make_hashable(i) for i in obj))
    elif isinstance(obj, tuple):
        return tuple(make_hashable(i) for i in obj)
    else:
        return obj


def build_cache_key(self, prefix: Optional[str], args: tuple, kwargs: dict, extra: tuple = ()) -> tuple:
    return (
        self.comment_id,
        prefix,
        make_hashable(extra),
    )


def cache_result(prefix: Optional[str] = None, extra_key: Optional[Callable[[tuple, dict], tuple]] = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            extra = extra_key(args, kwargs) if extra_key else ()
            key = build_cache_key(self, prefix, args, kwargs, extra)

            cached = await comment_param_cache.get(key)
            if cached is not None:
                return cached

            result = await func(self, *args, **kwargs)
            if result is not None:
                await comment_param_cache.set(key, result)
            return result

        return wrapper

    return decorator


def cache_update_dynamic(
        prefix: str,
        get_field: Callable[[tuple, dict], Any],
        get_value: Callable[[tuple, dict], Any],
        extra_key: Optional[Callable[[tuple, dict], tuple]] = None,
):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            result = await func(self, *args, **kwargs)

            if result is None or (isinstance(result, Result) and result.success):
                try:
                    value = get_value(args, kwargs)
                    extra = extra_key(args, kwargs) if extra_key else ()
                    key = build_cache_key(self, prefix, args, kwargs, extra)
                    await comment_param_cache.set(key, value)
                except Exception as e:
                    print(f"[⚠️ cache_update_dynamic] Failed to cache at comment func: {func.__name__} : {e}")
            return result

        return wrapper

    return decorator


class UserComment:
    _lock = asyncio.Lock()

    def __init__(self, comment_id: Optional[Union[int, str]] = None) -> None:
        self.comment_id = int(comment_id) if comment_id is not None else None

    @classmethod
    async def get_by_id(cls, comment_id: Union[int, str]) -> Optional["UserComment"]:
        obj = await _in.get_comment_by_id(int(comment_id))
        if obj:
            return UserComment(obj.comment_id)
        return None

    @classmethod
    async def search_comments(
            cls,
            conditions: dict,
            fuzzy: bool = False,
            similarity_threshold: float = 0.7,
            limit: int = 10,
            order_by: str = "id",
            descending: bool = False,
    ) -> Optional[list["UserComment"]]:
        objs = await _in.search_comments(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            order_by=order_by,
            descending=descending,
        )
        if objs:
            return [UserComment(obj.comment_id) for obj in objs]
        return None

    @classmethod
    async def create(cls, target_user_id: int, commented_by: int, comment: str) -> Result:
        if not comment or not comment.strip():
            return Result(False, "create", "Comment body cannot be empty", None)

        new_comment = {
            "target_user_id": target_user_id,
            "commented_by": commented_by,
            "comment": comment,
        }

        result = await _in.add_comment(new_comment)
        if result.success:
            comment_id = result.data
            result.data = UserComment(comment_id)
        return result

    # -------------------- Cached methods --------------------
    @cache_result(prefix="comment_param", extra_key=lambda args, kwargs: (args[0],))
    async def get_parameter(self, param: str) -> Any:
        result = await _in.get_parameter_from_db(self.comment_id, param)
        if not result.success or result.data is None:
            return None
        return result.data

    @cache_update_dynamic(
        prefix="comment_param",
        get_field=lambda args, kwargs: args[0],
        get_value=lambda args, kwargs: args[1],
        extra_key=lambda args, kwargs: (args[0],),
    )
    async def update_parameter(self, param: str, value: Any) -> Result:
        result = Result(True, "update_parameter", "", None)

        if param in SCALAR_FIELDS:
            if param == "comment" and (not value or not str(value).strip()):
                return Result(False, "update_parameter", "Comment body cannot be empty", None)
            await result.add_sub_result(await _in.update_parameter(self.comment_id, param, value))
        else:
            return Result(False, "update_parameter", f"Unknown parameter: {param}", None)

        return result

    async def delete(self) -> Result:
        return await _in.delete_comment_by_id(self.comment_id)


async def main():
    # Example comment test pipeline
    await UserComment.create(target_user_id=904730273476, commented_by=364226265960, comment="Great performance on the track!")

    # Quick structural check lookup
    comments = await UserComment.search_comments({"target_user_id": ("=", 904730273476)}, order_by="id", descending=True)
    if comments:
        comment_instance = comments[0]
        print(f"Loaded Comment ID: {comment_instance.comment_id}")
        print(await comment_instance.get_parameter("comment"))


if __name__ == "__main__":
    asyncio.run(main())
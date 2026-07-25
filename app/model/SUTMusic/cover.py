import asyncio
import time
from functools import wraps
from typing import Optional, Union, Any, Callable

from db.internal_db.SUTMusic.cover_internal_db import Internal_DB_Cover
from utils.result import Result
from utils.schedule.dict_helper import AutoExpiringDict
from utils.time_manager import TimeManager

# Field configurations based on covers schema
LIST_OF_DICT_FIELDS = set()  # No list-of-dict history fields for covers currently
DICT_FIELDS = {"metadata"}
SCALAR_FIELDS = {
    "id",
    "file_id",
    "unique_file_id",
    "file_format",
    "mime_type",
    "file_size",
    "file_url",
    "width",
    "height",
    "uploaded_by",
    "source",
    "created_at",
    "updated_at",
}

_in = Internal_DB_Cover()

cover_param_cache = AutoExpiringDict(ttl_seconds=3600, cleanup_interval=300, max_keys=10000)


def safe_get(index: int, key: str, args: tuple, kwargs: dict):
    try:
        return args[index]
    except IndexError:
        return kwargs.get(key)


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
        self.cover_id,
        prefix,
        make_hashable(extra),
    )


def cache_result(prefix: Optional[str] = None, extra_key: Optional[Callable[[tuple, dict], tuple]] = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            extra = extra_key(args, kwargs) if extra_key else ()
            key = build_cache_key(self, prefix, args, kwargs, extra)

            cached = await cover_param_cache.get(key)
            if cached is not None:
                return cached

            result = await func(self, *args, **kwargs)
            if result is not None:
                await cover_param_cache.set(key, result)
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
                    await cover_param_cache.set(key, value)
                except Exception as e:
                    print(f"[⚠️ cache_update_dynamic] Failed to cache at cover func: {func.__name__} : {e}")
            return result

        return wrapper

    return decorator


class Cover(Internal_DB_Cover):
    _lock = asyncio.Lock()

    def __init__(self, cover_id: Optional[Union[int, str]] = None) -> None:
        cover_id = int(cover_id)
        super().__init__(cover_id)
        self.cover_id = cover_id

    @classmethod
    async def get_by_id(cls, cover_id: Union[int, str]) -> Optional["Cover"]:
        obj = await _in.get_cover_by_id(int(cover_id))
        if obj:
            return Cover(obj.cover_id)
        return None

    @classmethod
    async def search_covers(
        cls,
        conditions: dict,
        fuzzy: bool = False,
        similarity_threshold: float = 0.7,
        limit: int = 10,
        order_by: str = "id",
        descending: bool = False,
    ) -> Optional[list["Cover"]]:
        objs = await _in.search_covers(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            order_by=order_by,
            descending=descending,
        )
        if objs:
            return [Cover(obj.cover_id) for obj in objs]

        return None

    @classmethod
    async def create(cls, uploaded_by: int, source: str, metadata: Optional[dict] = None) -> Result:
        new_cover = {
            "file_id": None,
            "unique_file_id": None,
            "file_format": None,
            "mime_type": None,
            "file_size": None,
            "file_url": None,
            "width": None,
            "height": None,
            "uploaded_by": uploaded_by,
            "source": source,
            "metadata": metadata or {},
        }

        result = await _in.add_cover(new_cover)
        if result.success:
            cover_id = result.data
            result.data = Cover(cover_id)
        return result

    # -------------------- Cached methods --------------------
    @cache_result(prefix="cover_param", extra_key=lambda args, kwargs: (args[0],))
    async def get_parameter(self, param: str) -> Any:
        result = await _in.get_parameter_from_db(self.cover_id, param)
        if not result.success or result.data is None:
            return None

        value = result.data

        if param in DICT_FIELDS:
            return value if isinstance(value, dict) else None
        elif param in SCALAR_FIELDS:
            return value

        return value

    @cache_update_dynamic(
        prefix="cover_param",
        get_field=lambda args, kwargs: args[0],  # param
        get_value=lambda args, kwargs: args[1],  # value
        extra_key=lambda args, kwargs: (args[0],),
    )
    async def update_parameter(self, param: str, value: Any) -> Result:
        result = Result(True, "update_parameter", "", None)

        if param in DICT_FIELDS:
            if not isinstance(value, dict):
                return Result(False, "update_parameter", f"{param} must be a dict", None)
            await result.add_sub_result(await _in.update_parameter(self.cover_id, param, value))

        elif param in SCALAR_FIELDS:
            await result.add_sub_result(await _in.update_parameter(self.cover_id, param, value))

        else:
            return Result(False, "update_parameter", f"Unknown parameter: {param}", None)

        return result

    async def erase_parameter(self, param: str) -> Result:
        if param in SCALAR_FIELDS:
            new_value = None
        elif param in DICT_FIELDS:
            new_value = {}
        else:
            return Result(False, "erase_parameter", f"Invalid parameter: {param}", None)

        return await _in.update_parameter(self.cover_id, param, new_value)

    async def assign_telegram_file(self, file_id: str, unique_file_id: str, file_size: int) -> Result:
        result = Result(True, "assign_telegram_file", "", None)
        await result.add_sub_result(await self.update_parameter("file_id", file_id))
        await result.add_sub_result(await self.update_parameter("unique_file_id", unique_file_id))
        await result.add_sub_result(await self.update_parameter("file_size", file_size))
        return result

    async def delete(self) -> Result:
        return await _in.delete_cover_by_id(self.cover_id)


async def main():
    # Example execution test wrapper
    # await Cover.create(491271371834, "telegram")
    cover = await Cover.get_by_id(1)

    print(await Cover.search_covers({"uploaded_by": ("=", 491271371834)}))

    if cover:
        print(await cover.update_parameter("metadata", {"test": {"test1": "test2"}}))
        print(await cover.get_parameter("metadata"))

        # print(await cover.update_parameter("file_format", "png"))
        # print(await cover.get_parameter("file_format"))

        # print(await cover.delete())




if __name__ == "__main__":
    asyncio.run(main())
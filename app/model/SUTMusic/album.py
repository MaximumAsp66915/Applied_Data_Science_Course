import asyncio
import time
from datetime import datetime
from functools import wraps
from typing import Optional, Union, Any, Callable

from db.internal_db.SUTMusic.album_internal_db import Internal_DB_Album
from utils.result import Result
from utils.schedule.dict_helper import AutoExpiringDict
from utils.time_manager import TimeManager

# Field configurations based on albums schema
LIST_OF_DICT_FIELDS = set()  # No list-of-dict history fields for albums currently
DICT_FIELDS = {"metadata"}
SCALAR_FIELDS = {
    "id",
    "title",
    "artist_id",
    "release_date",
    "cover_id",
    "description",
    "score",
    "rank",
    "likes_count",
    "dislikes_count",
    "reactions_count",
    "created_at",
    "updated_at",
}

_in = Internal_DB_Album()

album_param_cache = AutoExpiringDict(ttl_seconds=3600, cleanup_interval=300, max_keys=10000)


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
        self.album_id,
        prefix,
        make_hashable(extra),
    )


def cache_result(prefix: Optional[str] = None, extra_key: Optional[Callable[[tuple, dict], tuple]] = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            extra = extra_key(args, kwargs) if extra_key else ()
            key = build_cache_key(self, prefix, args, kwargs, extra)

            cached = await album_param_cache.get(key)
            if cached is not None:
                return cached

            result = await func(self, *args, **kwargs)
            if result is not None:
                await album_param_cache.set(key, result)
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
                    await album_param_cache.set(key, value)
                except Exception as e:
                    print(f"[⚠️ cache_update_dynamic] Failed to cache at album func: {func.__name__} : {e}")
            return result

        return wrapper

    return decorator


class Album(Internal_DB_Album):
    _lock = asyncio.Lock()

    def __init__(self, album_id: Optional[Union[int, str]] = None) -> None:
        album_id = int(album_id)
        super().__init__(album_id)
        self.album_id = album_id

    @classmethod
    async def get_by_id(cls, album_id: Union[int, str]) -> Optional["Album"]:
        obj = await _in.get_album_by_id(int(album_id))
        if obj:
            return Album(obj.album_id)
        return None

    @classmethod
    async def search_albums(
            cls,
            conditions: dict,
            fuzzy: bool = False,
            similarity_threshold: float = 0.7,
            limit: int = 10,
            order_by: str = "id",
            descending: bool = False,
    ) -> Optional[list["Album"]]:
        objs = await _in.search_albums(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            order_by=order_by,
            descending=descending,
        )
        if objs:
            return [Album(obj.album_id) for obj in objs]

        return None

    @classmethod
    async def create(
            cls,
            title: str,
            artist_id: Optional[int] = None,
            release_date: Optional[Any] = None,
            cover_id: Optional[int] = None,
            description: Optional[str] = None,
            metadata: Optional[dict] = None,
    ) -> Result:
        new_album = {
            "title": title,
            "artist_id": artist_id,
            "release_date": release_date,
            "cover_id": cover_id,
            "description": description,
            "score": 0.0,
            "rank": "unranked",
            "likes_count": 0,
            "dislikes_count": 0,
            "reactions_count": 0,
            "metadata": metadata or {},
        }

        result = await _in.add_album(new_album)
        if result.success:
            album_id = result.data
            result.data = Album(album_id)
        return result

    # -------------------- Cached methods --------------------
    @cache_result(prefix="album_param", extra_key=lambda args, kwargs: (args[0],))
    async def get_parameter(self, param: str) -> Any:
        result = await _in.get_parameter_from_db(self.album_id, param)
        if not result.success or result.data is None:
            return None

        value = result.data

        if param in DICT_FIELDS:
            return value if isinstance(value, dict) else None
        elif param in SCALAR_FIELDS:
            return value

        return value

    @cache_update_dynamic(
        prefix="album_param",
        get_field=lambda args, kwargs: args[0],  # param
        get_value=lambda args, kwargs: args[1],  # value
        extra_key=lambda args, kwargs: (args[0],),
    )
    async def update_parameter(self, param: str, value: Any) -> Result:
        result = Result(True, "update_parameter", "", None)

        if param in DICT_FIELDS:
            if not isinstance(value, dict):
                return Result(False, "update_parameter", f"{param} must be a dict", None)
            await result.add_sub_result(await _in.update_parameter(self.album_id, param, value))

        elif param in SCALAR_FIELDS:
            await result.add_sub_result(await _in.update_parameter(self.album_id, param, value))

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

        return await _in.update_parameter(self.album_id, param, new_value)

    async def update_counters(self, likes: int, dislikes: int, reactions: int) -> Result:
        result = Result(True, "update_counters", "", None)
        await result.add_sub_result(await self.update_parameter("likes_count", likes))
        await result.add_sub_result(await self.update_parameter("dislikes_count", dislikes))
        await result.add_sub_result(await self.update_parameter("reactions_count", reactions))
        return result

    async def delete(self) -> Result:
        return await _in.delete_album_by_id(self.album_id)


async def main():
    # Example execution test wrapper
    # Create an album record
    # create_res = await Album.create(
    #     title="The Dark Side of the Moon",
    #     artist_id=4,
    #     release_date="1973-03-01",
    #     description="Classic progressive rock album.",
    #     metadata={"tags": ["rock", "psychedelic"], "studio": "Abbey Road"}
    # )
    # print("Creation Result:", create_res.success)
    #
    # # Search for an existing album
    # search_results = await Album.search_albums({"title": ("=", "The Dark Side of the Moon")})
    # print("Search Result:", search_results)

    # Get by specific ID and interact with parameters
    album = await Album.get_by_id(4)
    if album:
        # Update a JSONB dict parameter
        print(await album.update_parameter("metadata", {"reissue": 2023, "remastered": True}))
        print("Updated Metadata:", await album.get_parameter("metadata"))

        # Update and get scalar parameters
        print(await album.update_parameter("title", "New Album Title"))
        print("Updated Title:", await album.get_parameter("title"))

        # Bulk modify transaction counters
        print(await album.update_counters(likes=150, dislikes=2, reactions=152))

        # Erase a description or parameter value
        print(await album.erase_parameter("description"))


if __name__ == "__main__":
    asyncio.run(main())
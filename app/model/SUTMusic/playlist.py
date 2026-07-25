import asyncio
import time
from functools import wraps
from typing import Optional, Union, Any, Callable

from db.internal_db.SUTMusic.playlist_internal_db import Internal_DB_Playlist
from utils.result import Result
from utils.schedule.dict_helper import AutoExpiringDict
from utils.time_manager import TimeManager

LIST_OF_DICT_FIELDS = set()
DICT_FIELDS = {"metadata"}
SCALAR_FIELDS = {
    "id",
    "owner_id",
    "name",
    "description",
    "is_public",
    "cover_id",
    "score",
    "rank",
    "likes_count",
    "dislikes_count",
    "reactions_count",
    "created_at",
    "updated_at",
}

_in = Internal_DB_Playlist()

playlist_param_cache = AutoExpiringDict(ttl_seconds=3600, cleanup_interval=300, max_keys=10000)


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
        self.playlist_id,
        prefix,
        make_hashable(extra),
    )


def cache_result(prefix: Optional[str] = None, extra_key: Optional[Callable[[tuple, dict], tuple]] = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            extra = extra_key(args, kwargs) if extra_key else ()
            key = build_cache_key(self, prefix, args, kwargs, extra)

            cached = await playlist_param_cache.get(key)
            if cached is not None:
                return cached

            result = await func(self, *args, **kwargs)
            if result is not None:
                await playlist_param_cache.set(key, result)
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
                    await playlist_param_cache.set(key, value)
                except Exception as e:
                    print(f"[⚠️ cache_update_dynamic] Failed to cache at playlist func: {func.__name__} : {e}")
            return result

        return wrapper

    return decorator


class Playlist(Internal_DB_Playlist):
    _lock = asyncio.Lock()

    def __init__(self, playlist_id: Optional[Union[int, str]] = None) -> None:
        playlist_id = int(playlist_id)
        super().__init__(playlist_id)
        self.playlist_id = playlist_id

    @classmethod
    async def get_by_id(cls, playlist_id: Union[int, str]) -> Optional["Playlist"]:
        obj = await _in.get_playlist_by_id(int(playlist_id))
        if obj:
            return Playlist(obj.playlist_id)
        return None

    @classmethod
    async def search_playlists(
        cls,
        conditions: dict,
        fuzzy: bool = False,
        similarity_threshold: float = 0.7,
        limit: int = 10,
        order_by: str = "id",
        descending: bool = False,
    ) -> Optional[list["Playlist"]]:
        objs = await _in.search_playlists(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            order_by=order_by,
            descending=descending,
        )
        if objs:
            return [Playlist(obj.playlist_id) for obj in objs]

        return None

    @classmethod
    async def create(
        cls,
        owner_id: int,
        name: str,
        description: Optional[str] = None,
        is_public: bool = False,
        cover_id: Optional[int] = None,
        metadata: Optional[dict] = None,
    ) -> Result:
        new_playlist = {
            "owner_id": owner_id,
            "name": name,
            "description": description,
            "is_public": is_public,
            "cover_id": cover_id,
            "score": 0.0,
            "rank": "unranked",
            "likes_count": 0,
            "dislikes_count": 0,
            "reactions_count": 0,
            "metadata": metadata or {},
        }

        result = await _in.add_playlist(new_playlist)
        if result.success:
            playlist_id = result.data
            result.data = Playlist(playlist_id)
        return result

    # -------------------- Cached methods --------------------
    @cache_result(prefix="playlist_param", extra_key=lambda args, kwargs: (args[0],))
    async def get_parameter(self, param: str) -> Any:
        result = await _in.get_parameter_from_db(self.playlist_id, param)
        if not result.success or result.data is None:
            return None

        value = result.data

        if param in DICT_FIELDS:
            return value if isinstance(value, dict) else None
        elif param in SCALAR_FIELDS:
            return value

        return value

    @cache_update_dynamic(
        prefix="playlist_param",
        get_field=lambda args, kwargs: args[0],
        get_value=lambda args, kwargs: args[1],
        extra_key=lambda args, kwargs: (args[0],),
    )
    async def update_parameter(self, param: str, value: Any) -> Result:
        result = Result(True, "update_parameter", "", None)

        if param in DICT_FIELDS:
            if not isinstance(value, dict):
                return Result(False, "update_parameter", f"{param} must be a dict", None)
            await result.add_sub_result(await _in.update_parameter(self.playlist_id, param, value))

        elif param in SCALAR_FIELDS:
            await result.add_sub_result(await _in.update_parameter(self.playlist_id, param, value))

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

        return await _in.update_parameter(self.playlist_id, param, new_value)

    async def update_counters(self, likes: int, dislikes: int, reactions: int) -> Result:
        result = Result(True, "update_counters", "", None)
        await result.add_sub_result(await self.update_parameter("likes_count", likes))
        await result.add_sub_result(await self.update_parameter("dislikes_count", dislikes))
        await result.add_sub_result(await self.update_parameter("reactions_count", reactions))
        return result

    async def delete(self) -> Result:
        return await _in.delete_playlist_by_id(self.playlist_id)


async def main():
    # Test creation
    await Playlist.create(owner_id=491271371834, name="My Rock Favorites", is_public=True)
    playlist = await Playlist.get_by_id(1)

    print(await Playlist.search_playlists({"owner_id": ("=", 491271371834)}))

    if playlist:
        print(await playlist.update_parameter("description", "Updated playlist description"))
        print(await playlist.get_parameter("description"))


if __name__ == "__main__":
    asyncio.run(main())
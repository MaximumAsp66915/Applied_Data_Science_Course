import asyncio
import time
from functools import wraps
from typing import Optional, Union, Any, Callable

from db.internal_db.SUTMusic.genre_internal_db import Internal_DB_Genre
from utils.result import Result
from utils.schedule.dict_helper import AutoExpiringDict
from utils.time_manager import TimeManager

# Field configurations based on genres schema
LIST_OF_DICT_FIELDS = set()  # No list-of-dict history fields for genres
DICT_FIELDS = set()          # No dict/JSONB fields for genres
SCALAR_FIELDS = {
    "id",
    "name",
    "cover_id",
    "description",
    "score",
    "rank",
    "created_at",
    "updated_at",
}

_in = Internal_DB_Genre()

genre_param_cache = AutoExpiringDict(ttl_seconds=3600, cleanup_interval=300, max_keys=10000)


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
        self.genre_id,
        prefix,
        make_hashable(extra),
    )


def cache_result(prefix: Optional[str] = None, extra_key: Optional[Callable[[tuple, dict], tuple]] = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            extra = extra_key(args, kwargs) if extra_key else ()
            key = build_cache_key(self, prefix, args, kwargs, extra)

            cached = await genre_param_cache.get(key)
            if cached is not None:
                return cached

            result = await func(self, *args, **kwargs)
            if result is not None:
                await genre_param_cache.set(key, result)
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
                    await genre_param_cache.set(key, value)
                except Exception as e:
                    print(f"[⚠️ cache_update_dynamic] Failed to cache at genre func: {func.__name__} : {e}")
            return result

        return wrapper

    return decorator


class Genre(Internal_DB_Genre):
    _lock = asyncio.Lock()

    def __init__(self, genre_id: Optional[Union[int, str]] = None) -> None:
        genre_id = int(genre_id)
        super().__init__(genre_id)
        self.genre_id = genre_id

    @classmethod
    async def get_by_id(cls, genre_id: Union[int, str]) -> Optional["Genre"]:
        obj = await _in.get_genre_by_id(int(genre_id))
        if obj:
            return Genre(obj.genre_id)
        return None

    @classmethod
    async def search_genres(
        cls,
        conditions: dict,
        fuzzy: bool = False,
        similarity_threshold: float = 0.7,
        limit: int = 10,
        order_by: str = "id",
        descending: bool = False,
    ) -> Optional[list["Genre"]]:
        objs = await _in.search_genres(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            order_by=order_by,
            descending=descending,
        )
        if objs:
            return [Genre(obj.genre_id) for obj in objs]

        return None

    @classmethod
    async def create(cls, name: str, cover_id: Optional[int] = None, description: Optional[str] = None) -> Result:
        new_genre = {
            "name": name,
            "cover_id": cover_id,
            "description": description,
            "score": 0.0,
            "rank": "unranked",
        }

        result = await _in.add_genre(new_genre)
        if result.success:
            genre_id = result.data
            result.data = Genre(genre_id)
        return result

    # -------------------- Cached methods --------------------
    @cache_result(prefix="genre_param", extra_key=lambda args, kwargs: (args[0],))
    async def get_parameter(self, param: str) -> Any:
        result = await _in.get_parameter_from_db(self.genre_id, param)
        if not result.success or result.data is None:
            return None

        value = result.data

        if param in SCALAR_FIELDS:
            return value

        return value

    @cache_update_dynamic(
        prefix="genre_param",
        get_field=lambda args, kwargs: args[0],  # param
        get_value=lambda args, kwargs: args[1],  # value
        extra_key=lambda args, kwargs: (args[0],),
    )
    async def update_parameter(self, param: str, value: Any) -> Result:
        result = Result(True, "update_parameter", "", None)

        if param in SCALAR_FIELDS:
            await result.add_sub_result(await _in.update_parameter(self.genre_id, param, value))
        else:
            return Result(False, "update_parameter", f"Unknown parameter: {param}", None)

        return result

    async def erase_parameter(self, param: str) -> Result:
        if param in SCALAR_FIELDS:
            new_value = None
        else:
            return Result(False, "erase_parameter", f"Invalid parameter: {param}", None)

        return await _in.update_parameter(self.genre_id, param, new_value)

    async def assign_ranking_metrics(self, score: float, rank: str) -> Result:
        result = Result(True, "assign_ranking_metrics", "", None)
        await result.add_sub_result(await self.update_parameter("score", score))
        await result.add_sub_result(await self.update_parameter("rank", rank))
        return result

    async def delete(self) -> Result:
        return await _in.delete_genre_by_id(self.genre_id)


async def main():
    # Example execution test wrapper
    await Genre.create("Rock", description="Rock music genre")
    genre = await Genre.get_by_id(1)

    print(await Genre.search_genres({"name": ("=", "Rock")}))

    if genre:
        print(await genre.update_parameter("description", "Updated description for Rock"))
        print(await genre.get_parameter("description"))


if __name__ == "__main__":
    asyncio.run(main())
import asyncio
import time
from functools import wraps
from typing import Optional, Union, Any, Callable

from db.internal_db.SUTMusic.artist_internal_db import Internal_DB_Artist
from model.SUTMusic.artist_reaction import ArtistReaction
from model.SUTMusic.reaction_type import ReactionType
from utils.result import Result
from utils.schedule.dict_helper import AutoExpiringDict
from utils.time_manager import TimeManager

# Field configurations based on artists schema
LIST_OF_DICT_FIELDS = set()  # No list-of-dict history fields for artists currently
DICT_FIELDS = {"metadata"}
SCALAR_FIELDS = {
    "id",
    "name",
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

_in = Internal_DB_Artist()

artist_param_cache = AutoExpiringDict(ttl_seconds=3600, cleanup_interval=300, max_keys=10000)


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
        self.artist_id,
        prefix,
        make_hashable(extra),
    )


def cache_result(prefix: Optional[str] = None, extra_key: Optional[Callable[[tuple, dict], tuple]] = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            extra = extra_key(args, kwargs) if extra_key else ()
            key = build_cache_key(self, prefix, args, kwargs, extra)

            cached = await artist_param_cache.get(key)
            if cached is not None:
                return cached

            result = await func(self, *args, **kwargs)
            if result is not None:
                await artist_param_cache.set(key, result)
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
                    await artist_param_cache.set(key, value)
                except Exception as e:
                    print(f"[⚠️ cache_update_dynamic] Failed to cache at artist func: {func.__name__} : {e}")
            return result

        return wrapper

    return decorator


class Artist(Internal_DB_Artist):
    _lock = asyncio.Lock()

    def __init__(self, artist_id: Optional[Union[int, str]] = None) -> None:
        artist_id = int(artist_id)
        super().__init__(artist_id)
        self.artist_id = artist_id
        self.obj_lock = asyncio.Lock()

    @classmethod
    async def get_by_id(cls, artist_id: Union[int, str]) -> Optional["Artist"]:
        obj = await _in.get_artist_by_id(int(artist_id))
        if obj:
            return Artist(obj.artist_id)
        return None

    @classmethod
    async def search_artists(
        cls,
        conditions: dict,
        fuzzy: bool = False,
        similarity_threshold: float = 0.7,
        limit: int = 10,
        order_by: str = "id",
        descending: bool = False,
    ) -> Optional[list["Artist"]]:
        objs = await _in.search_artists(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            order_by=order_by,
            descending=descending,
        )
        if objs:
            return [Artist(obj.artist_id) for obj in objs]

        return None

    @classmethod
    async def create(
        cls,
        name: str,
        cover_id: Optional[int] = None,
        description: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Result:
        new_artist = {
            "name": name,
            "cover_id": cover_id,
            "description": description,
            "score": 0.0,
            "rank": "unranked",
            "likes_count": 0,
            "dislikes_count": 0,
            "reactions_count": 0,
            "metadata": metadata or {},
        }

        result = await _in.add_artist(new_artist)
        if result.success:
            artist_id = result.data
            result.data = Artist(artist_id)
        return result

    async def update_count_by(self,
                              param: str,
                              value: int = 1) -> Result:

        if param not in ["likes_count", "dislikes_count", "reactions_count"]:
            return Result(False, "update_count_by",
                          "You can only provide one of the param as 'likes_count', 'dislikes_count', 'reactions_count'not other param",
                          None)
        async with self.obj_lock:
            count = await self.get_parameter(param)
            count = count + value
            return await self.update_parameter(param, count)

    async def received_like(self):
        return await self.update_count_by(param="likes_count", value=1)

    async def received_dislike(self):
        return await self.update_count_by(param="dislikes_count", value=1)

    async def received_reaction(self):
        return await self.update_count_by(param="reactions_count", value=1)

    # -------------------- Cached methods --------------------
    @cache_result(prefix="artist_param", extra_key=lambda args, kwargs: (args[0],))
    async def get_parameter(self, param: str) -> Any:
        result = await _in.get_parameter_from_db(self.artist_id, param)
        if not result.success or result.data is None:
            return None

        value = result.data

        if param in DICT_FIELDS:
            return value if isinstance(value, dict) else None
        elif param in SCALAR_FIELDS:
            return value

        return value

    @cache_update_dynamic(
        prefix="artist_param",
        get_field=lambda args, kwargs: args[0],  # param
        get_value=lambda args, kwargs: args[1],  # value
        extra_key=lambda args, kwargs: (args[0],),
    )
    async def update_parameter(self, param: str, value: Any) -> Result:
        result = Result(True, "update_parameter", "", None)

        if param in DICT_FIELDS:
            if not isinstance(value, dict):
                return Result(False, "update_parameter", f"{param} must be a dict", None)
            await result.add_sub_result(await _in.update_parameter(self.artist_id, param, value))

        elif param in SCALAR_FIELDS:
            await result.add_sub_result(await _in.update_parameter(self.artist_id, param, value))

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

        return await _in.update_parameter(self.artist_id, param, new_value)

    async def update_counters(self, likes: int, dislikes: int, reactions: int) -> Result:
        result = Result(True, "update_counters", "", None)
        await result.add_sub_result(await self.update_parameter("likes_count", likes))
        await result.add_sub_result(await self.update_parameter("dislikes_count", dislikes))
        await result.add_sub_result(await self.update_parameter("reactions_count", reactions))
        return result

    async def delete(self) -> Result:
        return await _in.delete_artist_by_id(self.artist_id)


async def main():
    # Example execution test wrapper
    async def process_single_artist(artist, likes, dislikes, semaphore):
        """Worker function to process a single artist concurrently while respecting the concurrency limit."""
        async with semaphore:
            # 1. Fetch all reactions for this artist
            artist_reactions = await ArtistReaction.search_reactions(
                conditions={"artist_id": ("=", artist.artist_id)}, limit=100000
            )
            if artist_reactions:
                print(f"Artist {artist.artist_id} - numReact: {len(artist_reactions)}")
                await artist.update_parameter("reactions_count", len(artist_reactions))

            # 2. Fetch likes
            artist_likes = await ArtistReaction.search_reactions(
                conditions={"artist_id": ("=", artist.artist_id), "reaction_id": ("IN", likes)}, limit=100000
            )
            if artist_likes:
                print(f"Artist {artist.artist_id} - numLike: {len(artist_likes)}")
                await artist.update_parameter("likes_count", len(artist_likes))

            # 3. Fetch dislikes
            artist_dislikes = await ArtistReaction.search_reactions(
                conditions={"artist_id": ("=", artist.artist_id), "reaction_id": ("IN", dislikes)}, limit=100000
            )
            if artist_dislikes:
                print(f"Artist {artist.artist_id} - numDislike: {len(artist_dislikes)}")
                await artist.update_parameter("dislikes_count", len(artist_dislikes))

    # Fetch initial reaction configurations
    like_reactions = await ReactionType.search_reactions(conditions={"sentiment": ("=", "like")}, limit=1000)
    likes = [reaction.reaction_type_id for reaction in like_reactions] if like_reactions else []

    dislike_reactions = await ReactionType.search_reactions(conditions={"sentiment": ("=", "dislike")}, limit=1000)
    dislikes = [reaction.reaction_type_id for reaction in dislike_reactions] if dislike_reactions else []

    print(f"Likes IDs: {likes}")
    print(f"Dislikes IDs: {dislikes}")

    all_artists = await Artist.search_artists(conditions={}, limit=100000)

    if all_artists:
        print(f"Total artists fetched: {len(all_artists)}")

        # Define the semaphore to restrict concurrency to 30 tasks max
        sem = asyncio.Semaphore(50)

        # Create an explicit list of tasks
        tasks = []
        for artist in all_artists:
            # We wrap our worker function in an asyncio task structure
            task = asyncio.create_task(process_single_artist(artist, likes, dislikes, sem))
            tasks.append(task)

        # Gather and run all tasks concurrently up to the semaphore's pool constraint
        await asyncio.gather(*tasks)
    # 1. Create an artist entry
    # create_res = await Artist.create(
    #     name="Hans Zimmer",
    #     description="Legendary film score composer.",
    #     metadata={"genres": ["Soundtrack", "Classical"], "active_since": 1977}
    # )
    # print("Artist Created Successfully:", create_res.success)
    # 
    # # 2. Search artists matching conditions
    # artists_found = await Artist.search_artists({"name": ("=", "Hans Zimmer")})
    # print("Search Result:", artists_found)
    # 
    # # 3. Simulate operational modifications on an retrieved instance
    # artist = await Artist.get_by_id(1)
    # if artist:
    #     # Update JSONB parameter
    #     print(await artist.update_parameter("metadata", {"touring": True}))
    #     print("Cached/Fetched Metadata:", await artist.get_parameter("metadata"))
    # 
    #     # Update and pull metrics
    #     print(await artist.update_counters(likes=1024, dislikes=5, reactions=1029))
    #     print("Artist Score:", await artist.get_parameter("score"))

        # Erase specific parameter value
        # print(await artist.erase_parameter("description"))


if __name__ == "__main__":
    asyncio.run(main())
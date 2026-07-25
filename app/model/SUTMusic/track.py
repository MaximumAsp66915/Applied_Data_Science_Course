import asyncio
import time
from functools import wraps
from typing import Optional, Union, Any, Callable

from db.internal_db.SUTMusic.track_internal_db import Internal_DB_Track
from model.SUTMusic.reaction_type import ReactionType
from model.SUTMusic.track_reaction import TrackReaction
from utils.result import Result
from utils.schedule.dict_helper import AutoExpiringDict
from utils.time_manager import TimeManager

# Field configurations based on tracks schema
# Field configurations based on tracks schema
LIST_OF_DICT_FIELDS = set()
DICT_FIELDS = {"metadata"}

ARRAY_FIELDS = {
    "artists_id",
    "uploaded_by"
}  # Added array field set

SCALAR_FIELDS = {
    "id",
    "file_id",
    "unique_file_id",
    "file_type",
    "mime_type",
    "extension",
    "title",
    "duration",
    "performer",
    "cover_id",
    "album_id",
    "chat_id",
    "message_id",
    "score",
    "rank",
    "likes_count",
    "dislikes_count",
    "reactions_count",
    "created_at",
    "updated_at",
}

_in = Internal_DB_Track()

track_param_cache = AutoExpiringDict(ttl_seconds=3600, cleanup_interval=300, max_keys=10000)


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
        self.track_id,
        prefix,
        make_hashable(extra),
    )


def cache_result(prefix: Optional[str] = None, extra_key: Optional[Callable[[tuple, dict], tuple]] = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            extra = extra_key(args, kwargs) if extra_key else ()
            key = build_cache_key(self, prefix, args, kwargs, extra)

            cached = await track_param_cache.get(key)
            if cached is not None:
                return cached

            result = await func(self, *args, **kwargs)
            if result is not None:
                await track_param_cache.set(key, result)
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
                    await track_param_cache.set(key, value)
                except Exception as e:
                    print(f"[⚠️ cache_update_dynamic] Failed to cache at track func: {func.__name__} : {e}")
            return result

        return wrapper

    return decorator


class Track(Internal_DB_Track):
    _lock = asyncio.Lock()

    def __init__(self, track_id: Optional[Union[int, str]] = None) -> None:
        track_id = int(track_id)
        super().__init__(track_id)
        self.track_id = track_id
        self.obj_lock = asyncio.Lock()

    @classmethod
    async def get_by_id(cls, track_id: Union[int, str]) -> Optional["Track"]:
        obj = await _in.get_track_by_id(int(track_id))
        if obj:
            return Track(obj.track_id)
        return None

    @classmethod
    async def search_tracks(
            cls,
            conditions: dict,
            fuzzy: bool = False,
            similarity_threshold: float = 0.7,
            limit: int = 10,
            order_by: str = "id",
            descending: bool = False,
    ) -> Optional[list["Track"]]:
        objs = await _in.search_tracks(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            order_by=order_by,
            descending=descending,
        )
        if objs:
            return [Track(obj.track_id) for obj in objs]

        return None

    @classmethod
    async def create(
            cls,
            file_id: str,
            unique_file_id: str,
            file_type: str,  # 'audio' or 'document'
            mime_type: Optional[str] = None,
            extension: Optional[str] = None,
            title: Optional[str] = None,
            duration: Optional[int] = None,
            performer: Optional[str] = None,
            cover_id: Optional[int] = None,
            album_id: Optional[int] = None,
            artists_id: Optional[list[int]] = None,  # Renamed and type hinted as list
            uploaded_by: Optional[list[int]] = None,
            chat_id: Optional[int] = None,
            message_id: Optional[int] = None,
            metadata: Optional[dict] = None,
    ) -> Result:
        if file_type not in ("audio", "document"):
            return Result(False, "create_track", "Invalid file_type: must be 'audio' or 'document'", None)

        new_track = {
            "file_id": file_id,
            "unique_file_id": unique_file_id,
            "file_type": file_type,
            "mime_type": mime_type,
            "extension": extension,
            "title": title,
            "duration": duration,
            "performer": performer,
            "cover_id": cover_id,
            "album_id": album_id,
            "artists_id": artists_id or [],  # Defaults to empty list matching database '{}'
            "uploaded_by": uploaded_by or [],
            "chat_id": chat_id,
            "message_id": message_id,
            "score": 0.0,
            "rank": "unranked",
            "likes_count": 0,
            "dislikes_count": 0,
            "reactions_count": 0,
            "metadata": metadata or {},
        }

        result = await _in.add_track(new_track)
        if result.success:
            track_id = result.data
            result.data = Track(track_id)
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
    @cache_result(prefix="track_param", extra_key=lambda args, kwargs: (args[0],))
    async def get_parameter(self, param: str) -> Any:
        result = await _in.get_parameter_from_db(self.track_id, param)
        if not result.success or result.data is None:
            return None

        value = result.data

        if param in DICT_FIELDS:
            return value if isinstance(value, dict) else None
        elif param in ARRAY_FIELDS:
            return value if isinstance(value, list) else []  # Handle array return
        elif param in SCALAR_FIELDS:
            return value

        return value

    @cache_update_dynamic(
        prefix="track_param",
        get_field=lambda args, kwargs: args[0],  # param
        get_value=lambda args, kwargs: args[1],  # value
        extra_key=lambda args, kwargs: (args[0],),
    )
    async def update_parameter(self, param: str, value: Any) -> Result:
        result = Result(True, "update_parameter", "", None)

        if param in DICT_FIELDS:
            if not isinstance(value, dict):
                return Result(False, "update_parameter", f"{param} must be a dict", None)
            await result.add_sub_result(await _in.update_parameter(self.track_id, param, value))

        elif param in ARRAY_FIELDS:
            if not isinstance(value, list):
                return Result(False, "update_parameter", f"{param} must be a list", None)
            await result.add_sub_result(await _in.update_parameter(self.track_id, param, value))

        elif param in SCALAR_FIELDS:
            if param == "file_type" and value not in ("audio", "document"):
                return Result(False, "update_parameter", "file_type must be 'audio' or 'document'", None)
            await result.add_sub_result(await _in.update_parameter(self.track_id, param, value))

        else:
            return Result(False, "update_parameter", f"Unknown parameter: {param}", None)

        return result

    async def erase_parameter(self, param: str) -> Result:
        if param in SCALAR_FIELDS:
            new_value = None
        elif param in DICT_FIELDS:
            new_value = {}
        elif param in ARRAY_FIELDS:
            new_value = []  # Clear list configuration
        else:
            return Result(False, "erase_parameter", f"Invalid parameter: {param}", None)

        return await _in.update_parameter(self.track_id, param, new_value)

    async def update_counters(self, likes: int, dislikes: int, reactions: int) -> Result:
        result = Result(True, "update_counters", "", None)
        await result.add_sub_result(await self.update_parameter("likes_count", likes))
        await result.add_sub_result(await self.update_parameter("dislikes_count", dislikes))
        await result.add_sub_result(await self.update_parameter("reactions_count", reactions))
        return result

    async def delete(self) -> Result:
        return await _in.delete_track_by_id(self.track_id)


async def main():
    # Example execution test wrapper
    # 1. Create a track record matching Telegram input signatures
    # create_res = await Track.create(
    #     file_id="CQACAgQAAxkBAAE...",
    #     unique_file_id="AgAD_AIAAh...",
    #     file_type="audio",
    #     mime_type="audio/mpeg",
    #     extension="mp3",
    #     title="Time",
    #     duration=421,
    #     performer="Pink Floyd",
    #     cover_id=2,
    #     album_id=4,
    #     artists_id=[12, 34],  # Updated: passing a list/array of artist IDs
    #     uploaded_by=148808174391,
    #     chat_id=7202859606,
    #     message_id=5532,
    #     metadata={"bitrate": 320000}
    # )
    # print("Track Creation Status:", create_res.success)
    # async def process_single_track(track, likes, dislikes, semaphore):
    #     """Worker function to process a single track concurrently while respecting the concurrency limit."""
    #     async with semaphore:
    #         # 1. Fetch all reactions for this track
    #         track_reactions = await TrackReaction.search_reactions(
    #             conditions={"track_id": ("=", track.track_id)}, limit=100000
    #         )
    #         if track_reactions:
    #             print(f"Track {track.track_id} - numReact: {len(track_reactions)}")
    #             await track.update_parameter("reactions_count", len(track_reactions))
    #
    #         # 2. Fetch likes
    #         track_likes = await TrackReaction.search_reactions(
    #             conditions={"track_id": ("=", track.track_id), "reaction_id": ("IN", likes)}, limit=100000
    #         )
    #         if track_likes:
    #             print(f"Track {track.track_id} - numLike: {len(track_likes)}")
    #             await track.update_parameter("likes_count", len(track_likes))
    #
    #         # 3. Fetch dislikes
    #         track_dislikes = await TrackReaction.search_reactions(
    #             conditions={"track_id": ("=", track.track_id), "reaction_id": ("IN", dislikes)}, limit=100000
    #         )
    #         if track_dislikes:
    #             print(f"Track {track.track_id} - numDislike: {len(track_dislikes)}")
    #             await track.update_parameter("dislikes_count", len(track_dislikes))
    #
    # # Fetch initial reaction configurations
    # like_reactions = await ReactionType.search_reactions(conditions={"sentiment": ("=", "like")}, limit=1000)
    # likes = [reaction.reaction_type_id for reaction in like_reactions] if like_reactions else []
    #
    # dislike_reactions = await ReactionType.search_reactions(conditions={"sentiment": ("=", "dislike")}, limit=1000)
    # dislikes = [reaction.reaction_type_id for reaction in dislike_reactions] if dislike_reactions else []
    #
    # print(f"Likes IDs: {likes}")
    # print(f"Dislikes IDs: {dislikes}")
    #
    # all_tracks = await Track.search_tracks(conditions={}, limit=100000)
    #
    # if all_tracks:
    #     print(f"Total tracks fetched: {len(all_tracks)}")
    #
    #     # Define the semaphore to restrict concurrency to 30 tasks max
    #     sem = asyncio.Semaphore(30)
    #
    #     # Create an explicit list of tasks
    #     tasks = []
    #     for track in all_tracks:
    #         # We wrap our worker function in an asyncio task structure
    #         task = asyncio.create_task(process_single_track(track, likes, dislikes, sem))
    #         tasks.append(task)
    #
    #     # Gather and run all tasks concurrently up to the semaphore's pool constraint
    #     await asyncio.gather(*tasks)


    # 2. Query structural tracking criteria (such as explicit Telegram identification constraint)
    tracks_found = await Track.search_tracks({"uploaded_by": ("contains", 874158820580)})
    print("Search matches:", tracks_found)
    #
    # # 3. Dynamic cache parameter manipulations
    # track = await Track.get_by_id(1)
    # if track:
    #     # Test updating scalar parameter
    #     print("Update Title Status:", await track.update_parameter("title", "Time (2023 Remaster)"))
    #     print("Cached Title:", await track.get_parameter("title"))
    #
    #     # Test updating and retrieving the new array parameter
    #     print("Update Artists Status:", await track.update_parameter("artists_id", [12, 34, 56]))
    #     print("Cached Artists Array:", await track.get_parameter("artists_id"))
    #
    #     # Test updating counters
    #     print("Update Counters Status:", await track.update_counters(likes=52, dislikes=0, reactions=52))
    #     print("Metadata Dictionary:", await track.get_parameter("metadata"))

if __name__ == "__main__":
    asyncio.run(main())

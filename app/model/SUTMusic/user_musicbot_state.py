import asyncio
import time
from functools import wraps
from typing import Optional, Union, Any, Callable, List

from sqlalchemy.engine import url
from collections import Counter
from db.internal_db.SUTMusic.user_musicbot_state_internal_db import Internal_DB_UserMusicBotState
from model.SUTMusic.artist import Artist
from model.SUTMusic.artist_reaction import ArtistReaction
from model.SUTMusic.track import Track
from model.SUTMusic.track_reaction import TrackReaction
from model.objects.user import User
from utils.result import Result
from utils.schedule.dict_helper import AutoExpiringDict
from utils.time_manager import TimeManager

LIST_OF_DICT_FIELDS = set()
DICT_FIELDS = {"metadata"}
LIST_FIELDS = {"recent_actions"}  # Holds JSONB arrays
SCALAR_FIELDS = {
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

_in = Internal_DB_UserMusicBotState()

state_param_cache = AutoExpiringDict(ttl_seconds=3600, cleanup_interval=300, max_keys=10000)


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
        self.user_id,
        prefix,
        make_hashable(extra),
    )


def cache_result(prefix: Optional[str] = None, extra_key: Optional[Callable[[tuple, dict], tuple]] = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            extra = extra_key(args, kwargs) if extra_key else ()
            key = build_cache_key(self, prefix, args, kwargs, extra)

            cached = await state_param_cache.get(key)
            if cached is not None:
                return cached

            result = await func(self, *args, **kwargs)
            if result is not None:
                await state_param_cache.set(key, result)
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
                    await state_param_cache.set(key, value)
                except Exception as e:
                    print(f"[⚠️ cache_update_dynamic] Failed to cache at state func: {func.__name__} : {e}")
            return result

        return wrapper

    return decorator


class UserMusicBotState:
    _lock = asyncio.Lock()

    def __init__(self, user_id: Optional[Union[int, str]] = None) -> None:
        user_id = int(user_id)
        self.user_id = user_id
        self.obj_lock = asyncio.Lock()

    @classmethod
    async def get_by_user_id(cls, user_id: Union[int, str]) -> Optional["UserMusicBotState"]:
        obj = await _in.get_state_by_user_id(int(user_id))
        if obj:
            return UserMusicBotState(obj.user_id)
        return None

    @classmethod
    async def search_states(
            cls,
            conditions: dict,
            fuzzy: bool = False,
            similarity_threshold: float = 0.7,
            limit: int = 10,
            order_by: str = "user_id",
            descending: bool = False,
    ) -> Optional[list["UserMusicBotState"]]:
        objs = await _in.search_states(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            order_by=order_by,
            descending=descending,
        )
        if objs:
            return [UserMusicBotState(obj.user_id) for obj in objs]

        return None

    @classmethod
    async def create(
            cls,
            user_id: int,
            cover_id: Optional[int] = None,
            description: Optional[str] = None,
            recent_actions: Optional[list] = None,
            metadata: Optional[dict] = None,
    ) -> Result:

        async with UserMusicBotState._lock:
            chats = await cls.search_states({"user_id": ("=", user_id)}, limit=1)
            if chats is not None or isinstance(chats, list) and len(chats) > 0:
                return Result(False, "create", "Duplicated user_id", None)
        new_state = {
            "user_id": user_id,
            "cover_id": cover_id,
            "description": description,
            "total_likes": 0,
            "total_dislikes": 0,
            "total_reactions": 0,
            "total_received_likes": 0,
            "total_received_dislikes": 0,
            "total_received_reactions": 0,
            "total_uploaded_tracks": 0,
            "score": 0.0,
            "rank": "unranked",
            "recent_actions": recent_actions or [],
            "metadata": metadata or {},
        }

        result = await _in.add_state(new_state)
        result.data = UserMusicBotState(user_id)
        return result

    async def add_action(self, new_action: str, timestamp: bool = False) -> Result:
        new_action = f"{new_action} - {TimeManager().tehran_now().isoformat()}" if timestamp else str(new_action)
        async with self.obj_lock:
            actions = await self.get_parameter("recent_actions")
            actions.append(new_action)
            return await self.update_parameter("recent_actions", actions)

    async def update_count_by(self,
                              param: str,
                              value: int = 1) -> Result:
        
        if param not in ["total_likes", "total_dislikes", "total_reactions", "total_received_likes", "total_received_dislikes", "total_received_reactions", "total_uploaded_tracks",]:
            return Result(False, "update_count_by", "You can only provide one of the param as 'total_likes', 'total_dislikes', 'total_reactions', 'total_received_likes', 'total_received_dislikes', 'total_received_reactions', 'total_uploaded_tracks' not other param", None)
        async with self.obj_lock:
            count = await self.get_parameter(param)
            count = count + value
            return await self.update_parameter(param, count)

    async def received_like(self,
                            from_track_id: Optional[int] = None,
                            from_playlist_id: Optional[int] = None,
                            from_album_id: Optional[int] = None,
                            from_artist_id: Optional[Union[int, list]] = None,
                            from_user_id: Optional[int] = None,
                            reaction_id: Optional[int] = None,
                            timestamp: bool = False) -> Result:

        result = Result(True, "received_like", "", None)
        new_action = f"received_like:{f' track({from_track_id})' if from_track_id else ''}{f' artist({from_artist_id})' if from_artist_id else ''}{f' album({from_album_id})' if from_album_id else ''}{f' playlist({from_playlist_id})' if from_playlist_id else ''}{f' reaction({reaction_id})' if reaction_id else ''}{f' user({from_user_id})' if from_user_id else ''} - {TimeManager().tehran_now()}"
        await result.add_sub_result(await self.add_action(new_action, timestamp=timestamp))
        await result.add_sub_result(await self.update_count_by(param="total_received_likes", value=1))
        await result.add_sub_result(await self.update_count_by(param="total_received_reactions", value=1))
        return result
    
    async def received_dislike(self,
                            from_track_id: Optional[int] = None,
                            from_playlist_id: Optional[int] = None,
                            from_album_id: Optional[int] = None,
                            from_artist_id: Optional[Union[int, list]] = None,
                            from_user_id: Optional[int] = None,
                            reaction_id: Optional[int] = None,
                            timestamp: bool = False) -> Result:

        result = Result(True, "received_dislike", "", None)
        new_action = f"received_dislike:{f' track({from_track_id})' if from_track_id else ''}{f' artist({from_artist_id})' if from_artist_id else ''}{f' album({from_album_id})' if from_album_id else ''}{f' playlist({from_playlist_id})' if from_playlist_id else ''}{f' reaction({reaction_id})' if reaction_id else ''}{f' user({from_user_id})' if from_user_id else ''} - {TimeManager().tehran_now()}"
        await result.add_sub_result(await self.add_action(new_action, timestamp=timestamp))
        await result.add_sub_result(await self.update_count_by(param="total_received_dislikes", value=1))
        await result.add_sub_result(await self.update_count_by(param="total_received_reactions", value=1))
        return result
    
    async def received_reaction(self,
                            from_track_id: Optional[int] = None,
                            from_playlist_id: Optional[int] = None,
                            from_album_id: Optional[int] = None,
                            from_artist_id: Optional[Union[int, list]] = None,
                            from_user_id: Optional[int] = None,
                                reaction_id: Optional[int] = None,
                            timestamp: bool = False) -> Result:

        result = Result(True, "received_reaction", "", None)
        new_action = f"received_reaction:{f' track({from_track_id})' if from_track_id else ''}{f' artist({from_artist_id})' if from_artist_id else ''}{f' album({from_album_id})' if from_album_id else ''}{f' playlist({from_playlist_id})' if from_playlist_id else ''}{f' reaction({reaction_id})' if reaction_id else ''}{f' user({from_user_id})' if from_user_id else ''} - {TimeManager().tehran_now()}"
        await result.add_sub_result(await self.add_action(new_action, timestamp=timestamp))
        await result.add_sub_result(await self.update_count_by(param="total_received_reactions", value=1))
        return result

    async def sent_like(self,
                            to_track_id: Optional[int] = None,
                            to_playlist_id: Optional[int] = None,
                            to_album_id: Optional[int] = None,
                            to_artist_id: Optional[Union[int, list]] = None,
                            to_user_id: Optional[int] = None,
                        reaction_id: Optional[int] = None,
                            timestamp: bool = False) -> Result:

        result = Result(True, "received_like", "", None)
        new_action = f"sent_like:{f' track({to_track_id})' if to_track_id else ''}{f' artist({to_artist_id})' if to_artist_id else ''}{f' album({to_album_id})' if to_album_id else ''}{f' playlist({to_playlist_id})' if to_playlist_id else ''}{f' reaction({reaction_id})' if reaction_id else ''}{f' user({to_user_id})' if to_user_id else ''} - {TimeManager().tehran_now()}"
        await result.add_sub_result(await self.add_action(new_action, timestamp=timestamp))
        await result.add_sub_result(await self.update_count_by(param="total_likes", value=1))
        await result.add_sub_result(await self.update_count_by(param="total_reactions", value=1))
        return result

    async def sent_dislike(self,
                               to_track_id: Optional[int] = None,
                               to_playlist_id: Optional[int] = None,
                               to_album_id: Optional[int] = None,
                               to_artist_id: Optional[Union[int, list]] = None,
                               to_user_id: Optional[int] = None,
                           reaction_id: Optional[int] = None,
                               timestamp: bool = False) -> Result:

        result = Result(True, "received_dislike", "", None)
        new_action = f"sent_dislike:{f' track({to_track_id})' if to_track_id else ''}{f' artist({to_artist_id})' if to_artist_id else ''}{f' album({to_album_id})' if to_album_id else ''}{f' playlist({to_playlist_id})' if to_playlist_id else ''}{f' reaction({reaction_id})' if reaction_id else ''}{f' user({to_user_id})' if to_user_id else ''} - {TimeManager().tehran_now()}"
        await result.add_sub_result(await self.add_action(new_action, timestamp=timestamp))
        await result.add_sub_result(await self.update_count_by(param="total_dislikes", value=1))
        await result.add_sub_result(await self.update_count_by(param="total_reactions", value=1))
        return result

    async def sent_reaction(self,
                                to_track_id: Optional[int] = None,
                                to_playlist_id: Optional[int] = None,
                                to_album_id: Optional[int] = None,
                                to_artist_id: Optional[Union[int, list]] = None,
                                to_user_id: Optional[int] = None,
                            reaction_id: Optional[int] = None,
                                timestamp: bool = False) -> Result:

        result = Result(True, "received_reaction", "", None)
        new_action = f"sent_reaction:{f' track({to_track_id})' if to_track_id else ''}{f' artist({to_artist_id})' if to_artist_id else ''}{f' album({to_album_id})' if to_album_id else ''}{f' playlist({to_playlist_id})' if to_playlist_id else ''}{f' reaction({reaction_id})' if reaction_id else ''}{f' user({to_user_id})' if to_user_id else ''} - {TimeManager().tehran_now()}"
        await result.add_sub_result(await self.add_action(new_action, timestamp=timestamp))
        await result.add_sub_result(await self.update_count_by(param="total_reactions", value=1))
        return result

    async def uploaded_track(self,
                             track_id: Optional[int] = None,
                             artist_id: Optional[Union[int, list]] = None,
                             album_id: Optional[int] = None,
                             playlist_id: Optional[int] = None,
                             timestamp: bool = False) -> Result:

        result = Result(True, "uploaded_track", "", None)
        new_action = f"uploaded_reaction:{f' track({track_id})' if track_id else ''}{f' artist({artist_id})' if artist_id else ''}{f' album({album_id})' if album_id else ''}{f' playlist({playlist_id})' if playlist_id else ''} - {TimeManager().tehran_now()}"
        await result.add_sub_result(await self.add_action(new_action, timestamp=timestamp))
        await result.add_sub_result(await self.update_count_by(param="total_uploaded_tracks", value=1))
        return result


    # -------------------- Cached methods --------------------
    @cache_result(prefix="state_param", extra_key=lambda args, kwargs: (args[0],))
    async def get_parameter(self, param: str) -> Any:
        result = await _in.get_parameter_from_db(self.user_id, param)
        if not result.success or result.data is None:
            return None

        value = result.data

        if param in DICT_FIELDS:
            return value if isinstance(value, dict) else None
        elif param in LIST_FIELDS:
            return value if isinstance(value, list) else None
        elif param in SCALAR_FIELDS:
            return value

        return value

    @cache_update_dynamic(
        prefix="state_param",
        get_field=lambda args, kwargs: args[0],
        get_value=lambda args, kwargs: args[1],
        extra_key=lambda args, kwargs: (args[0],),
    )
    async def update_parameter(self, param: str, value: Any) -> Result:
        result = Result(True, "update_parameter", "", None)

        if param in DICT_FIELDS:
            if not isinstance(value, dict):
                return Result(False, "update_parameter", f"{param} must be a dict", None)
            await result.add_sub_result(await _in.update_parameter(self.user_id, param, value))

        elif param in LIST_FIELDS:
            if not isinstance(value, list):
                return Result(False, "update_parameter", f"{param} must be a list", None)
            await result.add_sub_result(await _in.update_parameter(self.user_id, param, value))

        elif param in SCALAR_FIELDS:
            await result.add_sub_result(await _in.update_parameter(self.user_id, param, value))

        else:
            return Result(False, "update_parameter", f"Unknown parameter: {param}", None)

        return result

    async def erase_parameter(self, param: str) -> Result:
        if param in SCALAR_FIELDS:
            new_value = None
        elif param in DICT_FIELDS:
            new_value = {}
        elif param in LIST_FIELDS:
            new_value = []
        else:
            return Result(False, "erase_parameter", f"Invalid parameter: {param}", None)

        return await _in.update_parameter(self.user_id, param, new_value)

    async def sync_metrics(self, likes: int, dislikes: int, reactions: int) -> Result:
        result = Result(True, "sync_metrics", "", None)
        await result.add_sub_result(await self.update_parameter("total_likes", likes))
        await result.add_sub_result(await self.update_parameter("total_dislikes", dislikes))
        await result.add_sub_result(await self.update_parameter("total_reactions", reactions))
        return result

    async def delete(self) -> Result:
        return await _in.delete_state_by_user_id(self.user_id)

    async def get_uploaded_tracks(self, at_least_count: int = 1, exact_count: bool = False, limit: int = 1000) -> list:
        uploaded_tracks = []
        if at_least_count == 1 and not exact_count:
            uploaded_tracks = await Track.search_tracks({"uploaded_by": ("contains", self.user_id)}, limit=limit)
        elif at_least_count > 1 and not exact_count:
            uploaded_tracks = await Track.search_tracks({"uploaded_by": ("count>=", (self.user_id, at_least_count))}, limit=limit)
        elif at_least_count > 1 and exact_count:
            uploaded_tracks = await Track.search_tracks({"uploaded_by": ("count=", (self.user_id, at_least_count))}, limit=limit)

        return uploaded_tracks or []

    @staticmethod
    async def common_uploaded_tracks_between(user_ids: list[int]) -> list:
        uploaded_tracks = await Track.search_tracks({"uploaded_by": ("contains", user_ids)})
        return uploaded_tracks or []

    async def _fetch_entities(
            self,
            raw_ids: List[Any],
            getter_func: Callable[[Any], Any],
            unique: bool,
            sort: bool,
            target_limit: int
    ) -> List[Any]:
        """Generic helper to sort, deduplicate, and fetch DB models, bounded by target_limit."""
        valid_ids = [i for i in raw_ids if i is not None]
        if not valid_ids:
            return []

        if sort:
            counts = Counter(valid_ids)
            if unique:
                ordered_ids = [item_id for item_id, _ in counts.most_common()]
            else:
                ordered_ids = []
                for item_id, count in counts.most_common():
                    ordered_ids.extend([item_id] * count)
        else:
            if unique:
                ordered_ids = list(dict.fromkeys(valid_ids))
            else:
                ordered_ids = valid_ids

        # Fetch model instances sequentially, breaking early if target_limit is reached
        results = []
        for item_id in ordered_ids:
            item = await getter_func(item_id)
            if item is not None:
                results.append(item)
                if len(results) >= target_limit:
                    break

        return results

    async def _execute_reaction_search(
            self,
            reaction_cls: Any,
            conditions: dict,
            return_column: str,
            getter_func: Callable[[Any], Any],
            unique: bool,
            sort: bool,
            limit: int
    ) -> List[Any]:
        """Iteratively expands DB search limit (×100 up to 1,000,000) until output reaches requested limit."""
        MAX_SEARCH_CAPACITY = 1_000_000
        search_limit = min(limit * 100, MAX_SEARCH_CAPACITY)

        while True:
            raw_ids = await reaction_cls.search_from_reactions(
                conditions=conditions,
                return_column=return_column,
                limit=search_limit
            ) or []

            results = await self._fetch_entities(raw_ids, getter_func, unique, sort, limit)

            # Return if target reached or max capacity reached
            if len(results) >= limit or search_limit >= MAX_SEARCH_CAPACITY:
                return results[:limit]

            # Scale search window for the next attempt
            search_limit = min(search_limit * 1000, MAX_SEARCH_CAPACITY)

    # --- TRACK METHODS ---

    async def gave_like_on_tracks(self, unique: bool = False, sort: bool = False, limit: int = 10) -> list:
        return await self._execute_reaction_search(
            TrackReaction, {"user_id": ("=", self.user_id), "sentiment": ("=", "like")},
            "track_id", Track.get_by_id, unique, sort, limit
        )

    async def gave_dislike_on_tracks(self, unique: bool = False, sort: bool = False, limit: int = 10) -> list:
        return await self._execute_reaction_search(
            TrackReaction, {"user_id": ("=", self.user_id), "sentiment": ("=", "dislike")},
            "track_id", Track.get_by_id, unique, sort, limit
        )

    async def gave_reaction_on_tracks(self, unique: bool = False, sort: bool = False, limit: int = 10) -> list:
        return await self._execute_reaction_search(
            TrackReaction, {"user_id": ("=", self.user_id)},
            "track_id", Track.get_by_id, unique, sort, limit
        )

    async def got_like_from_tracks(self, unique: bool = False, sort: bool = False, limit: int = 10) -> list:
        return await self._execute_reaction_search(
            TrackReaction, {"on_user_id": ("=", self.user_id), "sentiment": ("=", "like")},
            "track_id", Track.get_by_id, unique, sort, limit
        )

    async def got_dislike_from_tracks(self, unique: bool = False, sort: bool = False, limit: int = 10) -> list:
        return await self._execute_reaction_search(
            TrackReaction, {"on_user_id": ("=", self.user_id), "sentiment": ("=", "dislike")},
            "track_id", Track.get_by_id, unique, sort, limit
        )

    async def got_reaction_from_tracks(self, unique: bool = False, sort: bool = False, limit: int = 10) -> list:
        return await self._execute_reaction_search(
            TrackReaction, {"on_user_id": ("=", self.user_id)},
            "track_id", Track.get_by_id, unique, sort, limit
        )

    # --- ARTIST METHODS ---

    async def gave_like_to_artists(self, unique: bool = False, sort: bool = False, limit: int = 10) -> list:
        return await self._execute_reaction_search(
            ArtistReaction, {"user_id": ("=", self.user_id), "sentiment": ("=", "like")},
            "artist_id", Artist.get_by_id, unique, sort, limit
        )

    async def gave_dislike_to_artists(self, unique: bool = False, sort: bool = False, limit: int = 10) -> list:
        return await self._execute_reaction_search(
            ArtistReaction, {"user_id": ("=", self.user_id), "sentiment": ("=", "dislike")},
            "artist_id", Artist.get_by_id, unique, sort, limit
        )

    async def gave_reaction_to_artists(self, unique: bool = False, sort: bool = False, limit: int = 10) -> list:
        return await self._execute_reaction_search(
            ArtistReaction, {"user_id": ("=", self.user_id)},
            "artist_id", Artist.get_by_id, unique, sort, limit
        )

    async def got_like_from_artists(self, unique: bool = False, sort: bool = False, limit: int = 10) -> list:
        return await self._execute_reaction_search(
            ArtistReaction, {"on_user_id": ("=", self.user_id), "sentiment": ("=", "like")},
            "artist_id", Artist.get_by_id, unique, sort, limit
        )

    async def got_dislike_from_artists(self, unique: bool = False, sort: bool = False, limit: int = 10) -> list:
        return await self._execute_reaction_search(
            ArtistReaction, {"on_user_id": ("=", self.user_id), "sentiment": ("=", "dislike")},
            "artist_id", Artist.get_by_id, unique, sort, limit
        )

    async def got_reaction_from_artists(self, unique: bool = False, sort: bool = False, limit: int = 10) -> list:
        return await self._execute_reaction_search(
            ArtistReaction, {"on_user_id": ("=", self.user_id)},
            "artist_id", Artist.get_by_id, unique, sort, limit
        )

    # --- USER METHODS ---

    async def gave_like_to_users(self, unique: bool = False, sort: bool = False, limit: int = 10) -> list:
        return await self._execute_reaction_search(
            TrackReaction, {"user_id": ("=", self.user_id), "sentiment": ("=", "like")},
            "on_user_id", UserMusicBotState.get_by_user_id, unique, sort, limit
        )

    async def gave_dislike_to_users(self, unique: bool = False, sort: bool = False, limit: int = 10) -> list:
        return await self._execute_reaction_search(
            TrackReaction, {"user_id": ("=", self.user_id), "sentiment": ("=", "dislike")},
            "on_user_id", UserMusicBotState.get_by_user_id, unique, sort, limit
        )

    async def gave_reaction_to_users(self, unique: bool = False, sort: bool = False, limit: int = 10) -> list:
        return await self._execute_reaction_search(
            TrackReaction, {"user_id": ("=", self.user_id)},
            "on_user_id", UserMusicBotState.get_by_user_id, unique, sort, limit
        )

    async def got_like_by_users(self, unique: bool = False, sort: bool = False, limit: int = 10) -> list:
        return await self._execute_reaction_search(
            TrackReaction, {"on_user_id": ("=", self.user_id), "sentiment": ("=", "like")},
            "user_id", UserMusicBotState.get_by_user_id, unique, sort, limit
        )

    async def got_dislike_by_users(self, unique: bool = False, sort: bool = False, limit: int = 10) -> list:
        return await self._execute_reaction_search(
            TrackReaction, {"on_user_id": ("=", self.user_id), "sentiment": ("=", "dislike")},
            "user_id", UserMusicBotState.get_by_user_id, unique, sort, limit
        )

    async def got_reaction_by_users(self, unique: bool = False, sort: bool = False, limit: int = 10) -> list:
        return await self._execute_reaction_search(
            TrackReaction, {"on_user_id": ("=", self.user_id)},
            "user_id", UserMusicBotState.get_by_user_id, unique, sort, limit
        )

async def main():
    # Example state usage workflow
    # user_id = 491271371834
    # await UserMusicBotState.create(user_id=user_id, description="Active listener state")
    # states = await UserMusicBotState.search_states(conditions={}, limit=20, order_by="total_received_likes" ,descending=True)
    # if states:
    #     for state in states:
    #         user = await User.get_by_id(state.user_id)
    #         print(await user.get_parameter("username"))
    user_stat = await UserMusicBotState.get_by_user_id(438071472030)
    artists = await user_stat.got_like_from_artists(sort=True, unique=True, limit=100)
    print(artists)
    for artist in artists:
        print(await artist.get_parameter("name"))
    # tracks = await user_stat.uploaded_tracks()
    # print(len(tracks))
    # print(await user_stat.get_parameter("total_uploaded_tracks"))
    # print(len(await user_stat.uploaded_tracks(2)))
    # print(len(await user_stat.uploaded_tracks(3, True)))
    # print(len(await user_stat.uploaded_tracks(4)))

    # state = await UserMusicBotState.get_by_user_id(user_id)

    # if state:
    #     print(await state.add_action("test", True))
    #     print(await state.get_parameter("recent_actions"))
        # print(await state.update_parameter("recent_actions", ["liked_track_102", "shared_playlist_5"]))
        # print(await state.get_parameter("recent_actions"))


if __name__ == "__main__":
    asyncio.run(main())
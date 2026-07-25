import asyncio
from functools import wraps
from typing import Optional, Union, Any, Callable, Dict, Tuple

from db.internal_db.SUTMusic.playlist_tracks_internal_db import Internal_DB_PlaylistTracks
from utils.result import Result
from utils.schedule.dict_helper import AutoExpiringDict

SCALAR_FIELDS = {
    "id",
    "playlist_id",
    "track_id",
    "position",
    "added_at",
}

_in = Internal_DB_PlaylistTracks()
playlist_track_cache = AutoExpiringDict(ttl_seconds=3600, cleanup_interval=300, max_keys=10000)


def make_hashable(obj):
    if isinstance(obj, dict):
        return tuple(sorted((k, make_hashable(v)) for k, v in obj.items()))
    elif isinstance(obj, (list, set, tuple)):
        return tuple(make_hashable(i) for i in obj)
    else:
        return obj


def build_cache_key(self, prefix: Optional[str], args: tuple, kwargs: dict, extra: tuple = ()) -> tuple:
    return (self.entry_id, prefix, make_hashable(extra))


def cache_result(prefix: Optional[str] = None, extra_key: Optional[Callable[[tuple, dict], tuple]] = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            extra = extra_key(args, kwargs) if extra_key else ()
            key = build_cache_key(self, prefix, args, kwargs, extra)

            cached = await playlist_track_cache.get(key)
            if cached is not None:
                return cached

            result = await func(self, *args, **kwargs)
            if result is not None:
                await playlist_track_cache.set(key, result)
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
                    await playlist_track_cache.set(key, value)
                except Exception as e:
                    print(f"[⚠️ cache_update_dynamic] Failed to cache at playlist track func: {func.__name__} : {e}")
            return result

        return wrapper

    return decorator


class PlaylistTracks:
    _lock = asyncio.Lock()

    def __init__(self, entry_id: Optional[Union[int, str]] = None) -> None:
        """
        High-level business-logic wrapper abstracting a playlist track lifecycle.
        """
        self.entry_id = int(entry_id) if entry_id is not None else None

    @classmethod
    async def get_by_id(cls, entry_id: Union[int, str]) -> Optional["PlaylistTracks"]:
        obj = await _in.get_playlist_track_by_id(int(entry_id))
        if obj:
            return PlaylistTracks(obj.entry_id)
        return None

    @classmethod
    async def search_playlist_tracks(
            cls,
            conditions: dict,
            fuzzy: bool = False,
            similarity_threshold: float = 0.7,
            limit: int = 10,
            order_by: str = "id",
            descending: bool = False,
    ) -> Optional[list["PlaylistTracks"]]:
        objs = await _in.search_playlist_tracks(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            order_by=order_by,
            descending=descending,
        )
        if objs:
            return [PlaylistTracks(obj.entry_id) for obj in objs]
        return None

    @classmethod
    async def create(
            cls,
            playlist_id: int,
            track_id: int,
            position: int = 0
    ) -> Result:
        if playlist_id is None or track_id is None:
            return Result(False, "create", "Both playlist_id and track_id must be provided", None)

        new_track_mapping = {
            "playlist_id": playlist_id,
            "track_id": track_id,
            "position": position
        }

        result = await _in.add_playlist_track(new_track_mapping)
        if result.success:
            entry_id = result.data
            result.data = PlaylistTracks(entry_id)
        return result

    # -------------------- Cached methods --------------------
    @cache_result(prefix="playlist_track_param", extra_key=lambda args, kwargs: (args[0],))
    async def get_parameter(self, param: str) -> Any:
        result = await _in.get_parameter_from_db(self.entry_id, param)
        if not result.success or result.data is None:
            return None
        return result.data

    @cache_update_dynamic(
        prefix="playlist_track_param",
        get_field=lambda args, kwargs: args[0],
        get_value=lambda args, kwargs: args[1],
        extra_key=lambda args, kwargs: (args[0],),
    )
    async def update_parameter(self, param: str, value: Any) -> Result:
        result = Result(True, "update_parameter", "", None)

        if param in SCALAR_FIELDS:
            if param in {"playlist_id", "track_id"} and value is None:
                return Result(False, "update_parameter", f"{param} field cannot be blank", None)

            await result.add_sub_result(await _in.update_parameter(self.entry_id, param, value))
        else:
            return Result(False, "update_parameter", f"Unknown parameter: {param}", None)

        return result

    async def delete(self) -> Result:
        return await _in.delete_playlist_track_by_id(self.entry_id)


async def main():
    # -------------------------------------------------------------------------
    # Test 1: Verification of Mapping Creation Constraints & Success Execution
    # -------------------------------------------------------------------------
    print("--- Test 1: Adding Track to Playlist ---")

    sample_playlist_id = 1
    sample_track_id = 7
    sample_position = 1

    creation_result = await PlaylistTracks.create(
        playlist_id=sample_playlist_id,
        track_id=sample_track_id,
        position=sample_position
    )
    print(f"Creation Result Status: {creation_result.success}")

    if not creation_result.success:
        print(f"Stopping tests. Insertion execution failed: {creation_result.message}")
        return

    track_instance: PlaylistTracks = creation_result.data
    target_id = track_instance.entry_id
    print(f"Successfully generated dynamic model instance. Assigned ID: {target_id}")

    # -------------------------------------------------------------------------
    # Test 2: Verification of Record Retrieval by Primary Key (`get_by_id`)
    # -------------------------------------------------------------------------
    print("\n--- Test 2: Retrieving Instance via get_by_id ---")

    fetched_entry = await PlaylistTracks.get_by_id(target_id)
    if fetched_entry:
        print(f"✅ Pass: Successfully reloaded object instance matching ID: {fetched_entry.entry_id}")
    else:
        print("❌ Fail: Unable to find or extract record based on the specified unique key indicator.")

    # -------------------------------------------------------------------------
    # Test 3: Parameter Resolution & Cache Layer Ingestion Checking
    # -------------------------------------------------------------------------
    print("\n--- Test 3: Verifying Parameter Access Operations ---")

    extracted_position = await track_instance.get_parameter("position")
    print(f"Extracted Mapping Position Parameter: '{extracted_position}'")

    print("Requesting attribute a second time to exercise cache retrieval pathways...")
    cached_position_read = await track_instance.get_parameter("position")
    print(f"Cached Element Contents Match Initial Read: {cached_position_read == extracted_position}")

    # -------------------------------------------------------------------------
    # Test 4: Structured Data Filtering, Querying, & Lookups (`search_playlist_tracks`)
    # -------------------------------------------------------------------------
    print("\n--- Test 4: Executing Structured Queries & Lookups ---")

    query_conditions = {
        "playlist_id": ("=", sample_playlist_id)
    }

    search_results = await PlaylistTracks.search_playlist_tracks(
        conditions=query_conditions,
        limit=5,
        order_by="position",
        descending=False
    )

    if search_results:
        print(f"✅ Pass: Search matching query found {len(search_results)} records.")
        for item in search_results:
            print(f" -> Found matching PlaylistTracks Entry ID: {item.entry_id}")
    else:
        print("❌ Fail: Query parameter matching execution returned empty collection sequence.")

    # -------------------------------------------------------------------------
    # Test 5: Parameter Mutation & Cache Invalidation Synchronization Flow
    # -------------------------------------------------------------------------
    print("\n--- Test 5: Testing Field Updates & Memory Sync Pipelines ---")

    updated_position_value = 2

    update_response = await track_instance.update_parameter("position", updated_position_value)
    print(f"Update Method Transaction Success Flag: {update_response.success}")

    post_update_read = await track_instance.get_parameter("position")
    print(f"Post-Update Local Parameter Verification Value: '{post_update_read}'")

    if post_update_read == updated_position_value:
        print("✅ Pass: Dynamic parameter modifications updated smoothly.")
    else:
        print("❌ Fail: Synchronization parsing mismatch inside local cache engine state tracking blocks.")

    # -------------------------------------------------------------------------
    # Test 6: Resource Termination Cleanup Validation Sequence (`delete`)
    # -------------------------------------------------------------------------
    print("\n--- Test 6: Executing Object Record Termination Steps ---")

    deletion_response = await track_instance.delete()
    print(f"Deletion Transaction Processing Status Flag: {deletion_response.success}")

    post_deletion_lookup = await PlaylistTracks.get_by_id(target_id)
    if post_deletion_lookup is None:
        print("✅ Pass: Model instance tracking verified records successfully removed from storage layers completely.")
    else:
        print("❌ Fail: Relational records footprint found lingering post teardown execution sequences.")


if __name__ == "__main__":
    asyncio.run(main())
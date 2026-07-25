import asyncio
from functools import wraps
from typing import Optional, Union, Any, Callable

# Importing the explicit database reference context mapping interface implemented above
from db.internal_db.SUTMusic.playlist_comment_internal_db import Internal_DB_PlaylistComment
from utils.result import Result
from utils.schedule.dict_helper import AutoExpiringDict

# Field configurations based closely on playlist_comments architectural relational layouts
LIST_OF_DICT_FIELDS = set()
DICT_FIELDS = set()
SCALAR_FIELDS = {
    "id",
    "playlist_id",
    "user_id",
    "comment",
    "commented_at",
}

# Materializing low-level baseline mapping interfaces
_in = Internal_DB_PlaylistComment()

# Internal structural caching dictionary tracking transient parameter values to minimize database load
playlist_comment_cache = AutoExpiringDict(ttl_seconds=3600, cleanup_interval=300, max_keys=10000)


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

            cached = await playlist_comment_cache.get(key)
            if cached is not None:
                return cached

            result = await func(self, *args, **kwargs)
            if result is not None:
                await playlist_comment_cache.set(key, result)
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
                    await playlist_comment_cache.set(key, value)
                except Exception as e:
                    print(f"[⚠️ cache_update_dynamic] Failed to cache at playlist comment func: {func.__name__} : {e}")
            return result
        return wrapper
    return decorator


class PlaylistComment:
    _lock = asyncio.Lock()

    def __init__(self, comment_id: Optional[Union[int, str]] = None) -> None:
        """
        High-level business-logic wrapper abstracting a playlist comment entity lifecycle.
        """
        self.comment_id = int(comment_id) if comment_id is not None else None

    @classmethod
    async def get_by_id(cls, comment_id: Union[int, str]) -> Optional["PlaylistComment"]:
        obj = await _in.get_comment_by_id(int(comment_id))
        if obj:
            return PlaylistComment(obj.comment_id)
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
    ) -> Optional[list["PlaylistComment"]]:
        objs = await _in.search_comments(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            order_by=order_by,
            descending=descending,
        )
        if objs:
            return [PlaylistComment(obj.comment_id) for obj in objs]
        return None

    @classmethod
    async def create(cls, playlist_id: int, user_id: int, comment: str) -> Result:
        if not comment or not comment.strip():
            return Result(False, "create", "Comment cannot be blank", None)

        new_comment = {
            "playlist_id": playlist_id,
            "user_id": user_id,
            "comment": comment,
        }

        result = await _in.add_comment(new_comment)
        if result.success:
            comment_id = result.data
            result.data = PlaylistComment(comment_id)
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
                return Result(False, "update_parameter", "Comment cannot be blank", None)
            await result.add_sub_result(await _in.update_parameter(self.comment_id, param, value))
        else:
            return Result(False, "update_parameter", f"Unknown parameter: {param}", None)

        return result

    async def delete(self) -> Result:
        return await _in.delete_comment_by_id(self.comment_id)


async def main():
    # -------------------------------------------------------------------------
    # Test 1: Verification of Comment Creation Constraints & Success Execution
    # -------------------------------------------------------------------------
    print("--- Test 1: Creating Playlist Comment Records ---")

    sample_playlist_id = 1
    sample_user_id = 491271371834
    initial_comment_body = "This curation flows perfectly!"

    creation_result = await PlaylistComment.create(
        playlist_id=sample_playlist_id,
        user_id=sample_user_id,
        comment=initial_comment_body
    )
    print(f"Creation Result Status: {creation_result.success}")

    if not creation_result.success:
        print(f"Stopping execution tests. Insertion execution failed: {creation_result.message}")
        return

    comment_instance: PlaylistComment = creation_result.data
    target_id = comment_instance.comment_id
    print(f"Successfully generated dynamic model instance. Assigned ID: {target_id}")

    blank_test = await PlaylistComment.create(playlist_id=sample_playlist_id, user_id=sample_user_id, comment="   ")
    print(f"Blank input rejection constraint verified successfully: {not blank_test.success}")

    # -------------------------------------------------------------------------
    # Test 2: Verification of Record Retrieval by Primary Key (`get_by_id`)
    # -------------------------------------------------------------------------
    print("\n--- Test 2: Retrieving Instance via get_by_id ---")

    fetched_comment = await PlaylistComment.get_by_id(target_id)
    if fetched_comment:
        print(f"✅ Pass: Successfully reloaded object instance matching ID: {fetched_comment.comment_id}")
    else:
        print("❌ Fail: Unable to find or extract record based on the specified unique key indicator.")

    # -------------------------------------------------------------------------
    # Test 3: Parameter Resolution & Cache Layer Ingestion Checking
    # -------------------------------------------------------------------------
    print("\n--- Test 3: Verifying Parameter Access Operations ---")

    extracted_text = await comment_instance.get_parameter("comment")
    print(f"Extracted Comment Body Content: '{extracted_text}'")

    extracted_playlist_id = await comment_instance.get_parameter("playlist_id")
    print(f"Extracted Associated Playlist ID Reference: {extracted_playlist_id}")

    print("Requesting attribute a second time to exercise cache retrieval pathways...")
    cached_text_read = await comment_instance.get_parameter("comment")
    print(f"Cached Element Contents Match Initial Read: {cached_text_read == extracted_text}")

    # -------------------------------------------------------------------------
    # Test 4: Structured Data Filtering, Querying, & Lookups (`search_comments`)
    # -------------------------------------------------------------------------
    print("\n--- Test 4: Executing Structured Queries & Lookups ---")

    query_conditions = {
        "playlist_id": ("=", sample_playlist_id),
        "user_id": ("=", sample_user_id)
    }

    search_results = await PlaylistComment.search_comments(
        conditions=query_conditions,
        limit=5,
        order_by="id",
        descending=True
    )

    if search_results:
        print(f"✅ Pass: Search matching query found {len(search_results)} records.")
        for item in search_results:
            print(f" -> Found matching Comment Record Instance ID: {item.comment_id}")
    else:
        print("❌ Fail: Query parameter matching execution returned empty collection sequence.")

    # -------------------------------------------------------------------------
    # Test 5: Parameter Mutation & Cache Invalidation Synchronization Flow
    # -------------------------------------------------------------------------
    print("\n--- Test 5: Testing Field Updates & Memory Sync Pipelines ---")

    updated_comment_body = "Rewriting comment parameter string contents for testing purposes."

    update_response = await comment_instance.update_parameter("comment", updated_comment_body)
    print(f"Update Method Transaction Success Flag: {update_response.success}")

    post_update_read = await comment_instance.get_parameter("comment")
    print(f"Post-Update Local Parameter Verification Value: '{post_update_read}'")

    if post_update_read == updated_comment_body:
        print("✅ Pass: Dynamic parameter modifications updated smoothly.")
    else:
        print("❌ Fail: Synchronization parsing mismatch inside local cache engine state tracking blocks.")

    invalid_update_attempt = await comment_instance.update_parameter("comment", "")
    print(f"Blank value rejection constraint inside update verified: {not invalid_update_attempt.success}")

    # -------------------------------------------------------------------------
    # Test 6: Resource Termination Cleanup Validation Sequence (`delete`)
    # -------------------------------------------------------------------------
    print("\n--- Test 6: Executing Object Record Termination Steps ---")

    deletion_response = await comment_instance.delete()
    print(f"Deletion Transaction Processing Status Flag: {deletion_response.success}")

    post_deletion_lookup = await PlaylistComment.get_by_id(target_id)
    if post_deletion_lookup is None:
        print("✅ Pass: Model instance tracking verified records successfully removed from storage layers completely.")
    else:
        print("❌ Fail: Relational records footprint found lingering post teardown execution sequences.")

if __name__ == "__main__":
    asyncio.run(main())
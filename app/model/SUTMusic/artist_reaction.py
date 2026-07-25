import asyncio
from functools import wraps
from typing import Optional, Union, Any, Callable, Dict, Tuple

from db.internal_db.SUTMusic.artist_reaction_internal_db import Internal_DB_ArtistReaction
from utils.result import Result
from utils.schedule.dict_helper import AutoExpiringDict

SCALAR_FIELDS = {
    "id",
    "artist_id",
    "user_id",
    "reaction_id",
    "sentiment",
    "on_user_id",
    "message_id",
    "reacted_at",
}

VALID_SENTIMENTS = {"like", "dislike", "neutral"}

_in = Internal_DB_ArtistReaction()
artist_reaction_cache = AutoExpiringDict(ttl_seconds=3600, cleanup_interval=300, max_keys=10000)


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

            cached = await artist_reaction_cache.get(key)
            if cached is not None:
                return cached

            result = await func(self, *args, **kwargs)
            if result is not None:
                await artist_reaction_cache.set(key, result)
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
                    await artist_reaction_cache.set(key, value)
                except Exception as e:
                    print(f"[⚠️ cache_update_dynamic] Failed to cache at artist reaction func: {func.__name__} : {e}")
            return result
        return wrapper
    return decorator


class ArtistReaction:
    _lock = asyncio.Lock()

    def __init__(self, entry_id: Optional[Union[int, str]] = None) -> None:
        """
        High-level business-logic wrapper abstracting an artist reaction lifecycle.
        """
        self.entry_id = int(entry_id) if entry_id is not None else None

    @classmethod
    async def get_by_id(cls, entry_id: Union[int, str]) -> Optional["ArtistReaction"]:
        obj = await _in.get_reaction_by_id(int(entry_id))
        if obj:
            return ArtistReaction(obj.entry_id)
        return None

    @classmethod
    async def search_from_reactions(
            cls,
            conditions: dict,
            fuzzy: bool = False,
            return_column: str = "id",
            similarity_threshold: float = 0.7,
            limit: int = 10,
            order_by: str = "id",
            descending: bool = False,
    ) -> Optional[list]:
        objs = await _in.search_from_reactions(
            conditions=conditions,
            fuzzy=fuzzy,
            return_column=return_column,
            similarity_threshold=similarity_threshold,
            limit=limit,
            order_by=order_by,
            descending=descending,
        )

        return objs

    @classmethod
    async def search_reactions(
            cls,
            conditions: dict,
            fuzzy: bool = False,
            similarity_threshold: float = 0.7,
            limit: int = 10,
            order_by: str = "id",
            descending: bool = False,
    ) -> Optional[list["ArtistReaction"]]:
        objs = await _in.search_reactions(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            order_by=order_by,
            descending=descending,
        )
        if objs:
            return [ArtistReaction(obj.entry_id) for obj in objs]
        return None

    @classmethod
    async def create(
        cls,
        artist_id: int,
        user_id: Optional[int] = None,
        reaction_id: Optional[int] = None,
        sentiment: Optional[str] = None,
        on_user_id: Optional[int] = None,
        message_id: Optional[int] = None
    ) -> Result:
        if sentiment and sentiment not in VALID_SENTIMENTS:
            return Result(False, "create", f"Sentiment must be one of {VALID_SENTIMENTS}", None)
        if not reaction_id:
            return Result(False, "create", "Reaction column field cannot be blank", None)
        
        artist_reaction = await cls.search_reactions(conditions={"reaction_id": ("=", reaction_id),
                                                                "user_id": ("=", user_id),
                                                                "artist_id": ("=", artist_id)},
                                                    limit=1)
        if artist_reaction and len(artist_reaction) > 0:
            return Result(True, "create", f"Track reaction already exists: {artist_reaction}", artist_reaction[0])

        new_reaction_mapping = {
            "artist_id": artist_id,
            "user_id": user_id,
            "reaction_id": reaction_id,
            "sentiment": sentiment,
            "on_user_id": on_user_id,
            "message_id": message_id
        }

        result = await _in.add_reaction(new_reaction_mapping)
        if result.success:
            entry_id = result.data
            result.data = ArtistReaction(entry_id)
        return result

    # -------------------- Cached methods --------------------
    @cache_result(prefix="reaction_param", extra_key=lambda args, kwargs: (args[0],))
    async def get_parameter(self, param: str) -> Any:
        result = await _in.get_parameter_from_db(self.entry_id, param)
        if not result.success or result.data is None:
            return None
        return result.data

    @cache_update_dynamic(
        prefix="reaction_param",
        get_field=lambda args, kwargs: args[0],
        get_value=lambda args, kwargs: args[1],
        extra_key=lambda args, kwargs: (args[0],),
    )
    async def update_parameter(self, param: str, value: Any) -> Result:
        result = Result(True, "update_parameter", "", None)

        if param in SCALAR_FIELDS:
            if param == "sentiment" and value and value not in VALID_SENTIMENTS:
                return Result(False, "update_parameter", f"Sentiment must be one of {VALID_SENTIMENTS}", None)

            await result.add_sub_result(await _in.update_parameter(self.entry_id, param, value))
        else:
            return Result(False, "update_parameter", f"Unknown parameter: {param}", None)

        return result

    async def delete(self) -> Result:
        return await _in.delete_reaction_by_id(self.entry_id)


async def main():
    # -------------------------------------------------------------------------
    # Test 1: Verification of Mapping Creation Constraints & Success Execution
    # -------------------------------------------------------------------------
    # print("--- Test 1: Creating Artist Reaction Records ---")
    #
    # sample_artist_id = 4
    # sample_user_id = 615917499502
    # sample_reaction = 1
    # sample_sentiment = "like"
    # sample_on_user_id = 6057721454
    # sample_message_id = 789
    #
    # creation_result = await ArtistReaction.create(
    #     artist_id=sample_artist_id,
    #     user_id=sample_user_id,
    #     reaction_id=sample_reaction,
    #     sentiment=sample_sentiment,
    #     on_user_id=sample_on_user_id,
    #     message_id=sample_message_id
    # )
    # print(f"Creation Result Status: {creation_result.success}")
    print(await ArtistReaction.search_reactions(conditions={"artist_id": ("=", 104), "user_id": ("=", 616554609597), "reaction_id": ("=", 75)}))

    # if not creation_result.success:
    #     print(f"Stopping tests. Insertion execution failed: {creation_result.message}")
    #     return
    #
    # reaction_instance: ArtistReaction = creation_result.data
    # target_id = reaction_instance.entry_id
    # print(f"Successfully generated dynamic model instance. Assigned ID: {target_id}")
    #
    # # Test sentiment CHECK constraint boundary enforcement
    # boundary_test = await ArtistReaction.create(
    #     artist_id=sample_artist_id, user_id=sample_user_id, reaction="👍", sentiment="invalid_sentiment"
    # )
    # print(f"Invalid domain verification check rejection verified: {not boundary_test.success}")
    #
    # # -------------------------------------------------------------------------
    # # Test 2: Verification of Record Retrieval by Primary Key (`get_by_id`)
    # # -------------------------------------------------------------------------
    # print("\n--- Test 2: Retrieving Instance via get_by_id ---")
    #
    # fetched_reaction = await ArtistReaction.get_by_id(target_id)
    # if fetched_reaction:
    #     print(f"✅ Pass: Successfully reloaded object instance matching ID: {fetched_reaction.entry_id}")
    # else:
    #     print("❌ Fail: Unable to find or extract record based on the specified unique key indicator.")
    #
    # # -------------------------------------------------------------------------
    # # Test 3: Parameter Resolution & Cache Layer Ingestion Checking
    # # -------------------------------------------------------------------------
    # print("\n--- Test 3: Verifying Parameter Access Operations ---")
    #
    # extracted_reaction = await reaction_instance.get_parameter("reaction")
    # print(f"Extracted Mapping Reaction Parameter: '{extracted_reaction}'")
    #
    # extracted_sentiment = await reaction_instance.get_parameter("sentiment")
    # print(f"Extracted Association Sentiment Measure: '{extracted_sentiment}'")
    #
    # print("Requesting attribute a second time to exercise cache retrieval pathways...")
    # cached_reaction_read = await reaction_instance.get_parameter("reaction")
    # print(f"Cached Element Contents Match Initial Read: {cached_reaction_read == extracted_reaction}")
    #
    # # -------------------------------------------------------------------------
    # # Test 4: Structured Data Filtering, Querying, & Lookups (`search_reactions`)
    # # -------------------------------------------------------------------------
    # print("\n--- Test 4: Executing Structured Queries & Lookups ---")
    #
    # query_conditions = {
    #     "artist_id": ("=", sample_artist_id),
    #     "sentiment": ("=", sample_sentiment)
    # }
    #
    # search_results = await ArtistReaction.search_reactions(
    #     conditions=query_conditions,
    #     limit=5,
    #     order_by="id",
    #     descending=True
    # )
    #
    # if search_results:
    #     print(f"✅ Pass: Search matching query found {len(search_results)} records.")
    #     for item in search_results:
    #         print(f" -> Found matching Reaction Entry ID: {item.entry_id}")
    # else:
    #     print("❌ Fail: Query parameter matching execution returned empty collection sequence.")
    #
    # # -------------------------------------------------------------------------
    # # Test 5: Parameter Mutation & Cache Invalidation Synchronization Flow
    # # -------------------------------------------------------------------------
    # print("\n--- Test 5: Testing Field Updates & Memory Sync Pipelines ---")
    #
    # updated_sentiment_value = "neutral"
    #
    # update_response = await reaction_instance.update_parameter("sentiment", updated_sentiment_value)
    # print(f"Update Method Transaction Success Flag: {update_response.success}")
    #
    # post_update_read = await reaction_instance.get_parameter("sentiment")
    # print(f"Post-Update Local Parameter Verification Value: '{post_update_read}'")
    #
    # if post_update_read == updated_sentiment_value:
    #     print("✅ Pass: Dynamic parameter modifications updated smoothly.")
    # else:
    #     print("❌ Fail: Synchronization parsing mismatch inside local cache engine state tracking blocks.")
    #
    # invalid_update_attempt = await reaction_instance.update_parameter("sentiment", "disliked")
    # print(f"Out-of-bounds update rejection verified: {not invalid_update_attempt.success}")
    #
    # # -------------------------------------------------------------------------
    # # Test 6: Resource Termination Cleanup Validation Sequence (`delete`)
    # # -------------------------------------------------------------------------
    # print("\n--- Test 6: Executing Object Record Termination Steps ---")
    #
    # deletion_response = await reaction_instance.delete()
    # print(f"Deletion Transaction Processing Status Flag: {deletion_response.success}")
    #
    # post_deletion_lookup = await ArtistReaction.get_by_id(target_id)
    # if post_deletion_lookup is None:
    #     print("✅ Pass: Model instance tracking verified records successfully removed from storage layers completely.")
    # else:
    #     print("❌ Fail: Relational records footprint found lingering post teardown execution sequences.")


if __name__ == "__main__":
    asyncio.run(main())
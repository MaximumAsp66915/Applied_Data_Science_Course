import asyncio
from functools import wraps
from typing import Optional, Union, Any, Callable

# Importing the explicit database reference context mapping interface implemented above
from db.internal_db.SUTMusic.artist_genre_internal_db import Internal_DB_ArtistGenre
from utils.result import Result
from utils.schedule.dict_helper import AutoExpiringDict

# Field configurations based closely on artist_genres architectural relational layouts
LIST_OF_DICT_FIELDS = set()
DICT_FIELDS = set()
SCALAR_FIELDS = {
    "id",
    "artist_id",
    "genre_id",
    "confidence",
    "source",
    "updated_at",
}

# Materializing low-level baseline mapping interfaces
_in = Internal_DB_ArtistGenre()

# Internal structural caching dictionary tracking transient parameter values to minimize database load
artist_genre_cache = AutoExpiringDict(ttl_seconds=3600, cleanup_interval=300, max_keys=10000)


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
        self.entry_id,
        prefix,
        make_hashable(extra),
    )


def cache_result(prefix: Optional[str] = None, extra_key: Optional[Callable[[tuple, dict], tuple]] = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            extra = extra_key(args, kwargs) if extra_key else ()
            key = build_cache_key(self, prefix, args, kwargs, extra)

            cached = await artist_genre_cache.get(key)
            if cached is not None:
                return cached

            result = await func(self, *args, **kwargs)
            if result is not None:
                await artist_genre_cache.set(key, result)
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
                    await artist_genre_cache.set(key, value)
                except Exception as e:
                    print(f"[⚠️ cache_update_dynamic] Failed to cache at artist genre func: {func.__name__} : {e}")
            return result
        return wrapper
    return decorator


class ArtistGenre:
    _lock = asyncio.Lock()

    def __init__(self, entry_id: Optional[Union[int, str]] = None) -> None:
        """
        High-level business-logic wrapper abstracting an artist genre relationship lifecycle.
        """
        self.entry_id = int(entry_id) if entry_id is not None else None

    @classmethod
    async def get_by_id(cls, entry_id: Union[int, str]) -> Optional["ArtistGenre"]:
        obj = await _in.get_genre_by_id(int(entry_id))
        if obj:
            return ArtistGenre(obj.entry_id)
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
    ) -> Optional[list["ArtistGenre"]]:
        objs = await _in.search_genres(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            order_by=order_by,
            descending=descending,
        )
        if objs:
            return [ArtistGenre(obj.entry_id) for obj in objs]
        return None

    @classmethod
    async def create(cls, artist_id: int, genre_id: int, confidence: float = 1.0, source: str = "llm") -> Result:
        if confidence < 0.0 or confidence > 1.0:
            return Result(False, "create", "Confidence score must be between 0.0 and 1.0", None)
        if not source or not source.strip():
            return Result(False, "create", "Source field cannot be blank", None)

        new_genre_mapping = {
            "artist_id": artist_id,
            "genre_id": genre_id,
            "confidence": confidence,
            "source": source.strip(),
        }

        result = await _in.add_genre(new_genre_mapping)
        if result.success:
            entry_id = result.data
            result.data = ArtistGenre(entry_id)
        return result

    # -------------------- Cached methods --------------------
    @cache_result(prefix="genre_param", extra_key=lambda args, kwargs: (args[0],))
    async def get_parameter(self, param: str) -> Any:
        result = await _in.get_parameter_from_db(self.entry_id, param)
        if not result.success or result.data is None:
            return None
        return result.data

    @cache_update_dynamic(
        prefix="genre_param",
        get_field=lambda args, kwargs: args[0],
        get_value=lambda args, kwargs: args[1],
        extra_key=lambda args, kwargs: (args[0],),
    )
    async def update_parameter(self, param: str, value: Any) -> Result:
        result = Result(True, "update_parameter", "", None)

        if param in SCALAR_FIELDS:
            if param == "confidence" and (value is None or not (0.0 <= float(value) <= 1.0)):
                return Result(False, "update_parameter", "Confidence score must be between 0.0 and 1.0", None)
            if param == "source" and (not value or not str(value).strip()):
                return Result(False, "update_parameter", "Source field cannot be blank", None)

            await result.add_sub_result(await _in.update_parameter(self.entry_id, param, value))
        else:
            return Result(False, "update_parameter", f"Unknown parameter: {param}", None)

        return result

    async def delete(self) -> Result:
        return await _in.delete_genre_by_id(self.entry_id)


async def main():
    # -------------------------------------------------------------------------
    # Test 1: Verification of Mapping Creation Constraints & Success Execution
    # -------------------------------------------------------------------------
    print("--- Test 1: Creating Artist Genre Association Records ---")

    sample_artist_id = 4
    sample_genre_id = 2
    initial_confidence = 0.95
    initial_source = "llm"

    creation_result = await ArtistGenre.create(
        artist_id=sample_artist_id,
        genre_id=sample_genre_id,
        confidence=initial_confidence,
        source=initial_source
    )
    print(f"Creation Result Status: {creation_result.success}")

    if not creation_result.success:
        print(f"Stopping execution tests. Insertion execution failed: {creation_result.message}")
        return

    genre_instance: ArtistGenre = creation_result.data
    target_id = genre_instance.entry_id
    print(f"Successfully generated dynamic model instance. Assigned ID: {target_id}")

    # Test numerical value boundary enforcement constraints
    boundary_test = await ArtistGenre.create(artist_id=sample_artist_id, genre_id=sample_genre_id, confidence=1.5)
    print(f"Invalid range boundary rejection verified successfully: {not boundary_test.success}")

    # -------------------------------------------------------------------------
    # Test 2: Verification of Record Retrieval by Primary Key (`get_by_id`)
    # -------------------------------------------------------------------------
    print("\n--- Test 2: Retrieving Instance via get_by_id ---")

    fetched_genre = await ArtistGenre.get_by_id(target_id)
    if fetched_genre:
        print(f"✅ Pass: Successfully reloaded object instance matching ID: {fetched_genre.entry_id}")
    else:
        print("❌ Fail: Unable to find or extract record based on the specified unique key indicator.")

    # -------------------------------------------------------------------------
    # Test 3: Parameter Resolution & Cache Layer Ingestion Checking
    # -------------------------------------------------------------------------
    print("\n--- Test 3: Verifying Parameter Access Operations ---")

    extracted_source = await genre_instance.get_parameter("source")
    print(f"Extracted Mapping Source Parameter: '{extracted_source}'")

    extracted_confidence = await genre_instance.get_parameter("confidence")
    print(f"Extracted Association Confidence Measure: {extracted_confidence}")

    print("Requesting attribute a second time to exercise cache retrieval pathways...")
    cached_source_read = await genre_instance.get_parameter("source")
    print(f"Cached Element Contents Match Initial Read: {cached_source_read == extracted_source}")

    # -------------------------------------------------------------------------
    # Test 4: Structured Data Filtering, Querying, & Lookups (`search_genres`)
    # -------------------------------------------------------------------------
    print("\n--- Test 4: Executing Structured Queries & Lookups ---")

    query_conditions = {
        "artist_id": ("=", sample_artist_id),
        "source": ("=", initial_source)
    }

    search_results = await ArtistGenre.search_genres(
        conditions=query_conditions,
        limit=5,
        order_by="id",
        descending=True
    )

    if search_results:
        print(f"✅ Pass: Search matching query found {len(search_results)} records.")
        for item in search_results:
            print(f" -> Found matching Association Entry ID: {item.entry_id}")
    else:
        print("❌ Fail: Query parameter matching execution returned empty collection sequence.")

    # -------------------------------------------------------------------------
    # Test 5: Parameter Mutation & Cache Invalidation Synchronization Flow
    # -------------------------------------------------------------------------
    print("\n--- Test 5: Testing Field Updates & Memory Sync Pipelines ---")

    updated_source_value = "manual"

    update_response = await genre_instance.update_parameter("source", updated_source_value)
    print(f"Update Method Transaction Success Flag: {update_response.success}")

    post_update_read = await genre_instance.get_parameter("source")
    print(f"Post-Update Local Parameter Verification Value: '{post_update_read}'")

    if post_update_read == updated_source_value:
        print("✅ Pass: Dynamic parameter modifications updated smoothly.")
    else:
        print("❌ Fail: Synchronization parsing mismatch inside local cache engine state tracking blocks.")

    invalid_update_attempt = await genre_instance.update_parameter("confidence", -0.5)
    print(f"Out-of-bounds update rejection verified: {not invalid_update_attempt.success}")

    # -------------------------------------------------------------------------
    # Test 6: Resource Termination Cleanup Validation Sequence (`delete`)
    # -------------------------------------------------------------------------
    print("\n--- Test 6: Executing Object Record Termination Steps ---")

    deletion_response = await genre_instance.delete()
    print(f"Deletion Transaction Processing Status Flag: {deletion_response.success}")

    post_deletion_lookup = await ArtistGenre.get_by_id(target_id)
    if post_deletion_lookup is None:
        print("✅ Pass: Model instance tracking verified records successfully removed from storage layers completely.")
    else:
        print("❌ Fail: Relational records footprint found lingering post teardown execution sequences.")


if __name__ == "__main__":
    asyncio.run(main())
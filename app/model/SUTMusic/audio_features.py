import asyncio
from functools import wraps
from typing import Optional, Union, Any, Callable, Dict, Tuple

from db.internal_db.SUTMusic.audio_features_internal_db import Internal_DB_AudioFeatures
from utils.result import Result
from utils.schedule.dict_helper import AutoExpiringDict

SCALAR_FIELDS = {
    "id",
    "track_id",
    "bpm",
    "key",
    "mode",
    "duration_ms",
    "loudness",
    "energy",
    "danceability",
    "acousticness",
    "instrumentalness",
    "liveness",
    "speechiness",
    "valence",
    "inferred_genre_id",
    "model_version",
    "created_at",
    "updated_at",
}
JSONB_FIELDS = {
    "llm_prediction",
}

_in = Internal_DB_AudioFeatures()
audio_features_cache = AutoExpiringDict(ttl_seconds=3600, cleanup_interval=300, max_keys=10000)


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

            cached = await audio_features_cache.get(key)
            if cached is not None:
                return cached

            result = await func(self, *args, **kwargs)
            if result is not None:
                await audio_features_cache.set(key, result)
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
                    await audio_features_cache.set(key, value)
                except Exception as e:
                    print(f"[⚠️ cache_update_dynamic] Failed to cache at audio features func: {func.__name__} : {e}")
            return result
        return wrapper
    return decorator


class AudioFeatures:
    _lock = asyncio.Lock()

    def __init__(self, entry_id: Optional[Union[int, str]] = None) -> None:
        """
        High-level business-logic wrapper abstracting an audio features record lifecycle.
        """
        self.entry_id = int(entry_id) if entry_id is not None else None

    @classmethod
    async def get_by_id(cls, entry_id: Union[int, str]) -> Optional["AudioFeatures"]:
        obj = await _in.get_feature_by_id(int(entry_id))
        if obj:
            return AudioFeatures(obj.entry_id)
        return None

    @classmethod
    async def search_features(
            cls,
            conditions: dict,
            fuzzy: bool = False,
            similarity_threshold: float = 0.7,
            limit: int = 10,
            order_by: str = "id",
            descending: bool = False,
    ) -> Optional[list["AudioFeatures"]]:
        objs = await _in.search_features(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            order_by=order_by,
            descending=descending,
        )
        if objs:
            return [AudioFeatures(obj.entry_id) for obj in objs]
        return None

    @classmethod
    async def create(
        cls,
        track_id: int,
        bpm: Optional[float] = None,
        key: Optional[str] = None,
        mode: Optional[str] = None,
        duration_ms: Optional[int] = None,
        loudness: Optional[float] = None,
        energy: Optional[float] = None,
        danceability: Optional[float] = None,
        acousticness: Optional[float] = None,
        instrumentalness: Optional[float] = None,
        liveness: Optional[float] = None,
        speechiness: Optional[float] = None,
        valence: Optional[float] = None,
        inferred_genre_id: Optional[int] = None,
        llm_prediction: Optional[dict] = None,
        model_version: str = "v1"
    ) -> Result:
        if track_id is None:
            return Result(False, "create", "track_id parameter field cannot be blank", None)

        new_features_mapping = {
            "track_id": track_id,
            "bpm": bpm,
            "key": key,
            "mode": mode,
            "duration_ms": duration_ms,
            "loudness": loudness,
            "energy": energy,
            "danceability": danceability,
            "acousticness": acousticness,
            "instrumentalness": instrumentalness,
            "liveness": liveness,
            "speechiness": speechiness,
            "valence": valence,
            "inferred_genre_id": inferred_genre_id,
            "llm_prediction": llm_prediction if llm_prediction is not None else {},
            "model_version": model_version
        }

        result = await _in.add_features(new_features_mapping)
        if result.success:
            entry_id = result.data
            result.data = AudioFeatures(entry_id)
        return result

    # -------------------- Cached methods --------------------
    @cache_result(prefix="features_param", extra_key=lambda args, kwargs: (args[0],))
    async def get_parameter(self, param: str) -> Any:
        result = await _in.get_parameter_from_db(self.entry_id, param)
        if not result.success or result.data is None:
            return None
        return result.data

    @cache_update_dynamic(
        prefix="features_param",
        get_field=lambda args, kwargs: args[0],
        get_value=lambda args, kwargs: args[1],
        extra_key=lambda args, kwargs: (args[0],),
    )
    async def update_parameter(self, param: str, value: Any) -> Result:
        result = Result(True, "update_parameter", "", None)

        if param in SCALAR_FIELDS or param in JSONB_FIELDS:
            if param == "track_id" and value is None:
                return Result(False, "update_parameter", "track_id field cannot be blank", None)

            await result.add_sub_result(await _in.update_parameter(self.entry_id, param, value))
        else:
            return Result(False, "update_parameter", f"Unknown parameter: {param}", None)

        return result

    async def delete(self) -> Result:
        return await _in.delete_features_by_id(self.entry_id)


async def main():
    # -------------------------------------------------------------------------
    # Test 1: Verification of Mapping Creation Constraints & Success Execution
    # -------------------------------------------------------------------------
    print("--- Test 1: Creating Audio Features Records ---")

    sample_track_id = 7
    sample_bpm = 124.5
    sample_key = "G# Minor"
    sample_mode = "Minor"
    sample_duration_ms = 215000
    sample_loudness = -5.4
    sample_energy = 0.85
    sample_danceability = 0.78
    sample_llm_prediction = {"primary_mood": "energetic", "instruments": ["synth", "drum_machine"]}

    creation_result = await AudioFeatures.create(
        track_id=sample_track_id,
        bpm=sample_bpm,
        key=sample_key,
        mode=sample_mode,
        duration_ms=sample_duration_ms,
        loudness=sample_loudness,
        energy=sample_energy,
        danceability=sample_danceability,
        llm_prediction=sample_llm_prediction
    )
    print(f"Creation Result Status: {creation_result.success}")

    if not creation_result.success:
        print(f"Stopping tests. Insertion execution failed: {creation_result.message}")
        return

    features_instance: AudioFeatures = creation_result.data
    target_id = features_instance.entry_id
    print(f"Successfully generated dynamic model instance. Assigned ID: {target_id}")

    # -------------------------------------------------------------------------
    # Test 2: Verification of Record Retrieval by Primary Key (`get_by_id`)
    # -------------------------------------------------------------------------
    print("\n--- Test 2: Retrieving Instance via get_by_id ---")

    fetched_features = await AudioFeatures.get_by_id(target_id)
    if fetched_features:
        print(f"✅ Pass: Successfully reloaded object instance matching ID: {fetched_features.entry_id}")
    else:
        print("❌ Fail: Unable to find or extract record based on the specified unique key indicator.")

    # -------------------------------------------------------------------------
    # Test 3: Parameter Resolution & Cache Layer Ingestion Checking
    # -------------------------------------------------------------------------
    print("\n--- Test 3: Verifying Parameter Access Operations ---")

    extracted_bpm = await features_instance.get_parameter("bpm")
    print(f"Extracted Mapping BPM Parameter: '{extracted_bpm}'")

    extracted_pred = await features_instance.get_parameter("llm_prediction")
    print(f"Extracted Association LLM Prediction Measure: '{extracted_pred}'")

    print("Requesting attribute a second time to exercise cache retrieval pathways...")
    cached_bpm_read = await features_instance.get_parameter("bpm")
    print(f"Cached Element Contents Match Initial Read: {cached_bpm_read == extracted_bpm}")

    # -------------------------------------------------------------------------
    # Test 4: Structured Data Filtering, Querying, & Lookups (`search_features`)
    # -------------------------------------------------------------------------
    print("\n--- Test 4: Executing Structured Queries & Lookups ---")

    query_conditions = {
        "track_id": ("=", sample_track_id),
        "mode": ("=", sample_mode)
    }

    search_results = await AudioFeatures.search_features(
        conditions=query_conditions,
        limit=5,
        order_by="id",
        descending=True
    )

    if search_results:
        print(f"✅ Pass: Search matching query found {len(search_results)} records.")
        for item in search_results:
            print(f" -> Found matching Features Entry ID: {item.entry_id}")
    else:
        print("❌ Fail: Query parameter matching execution returned empty collection sequence.")

    # -------------------------------------------------------------------------
    # Test 5: Parameter Mutation & Cache Invalidation Synchronization Flow
    # -------------------------------------------------------------------------
    print("\n--- Test 5: Testing Field Updates & Memory Sync Pipelines ---")

    updated_bpm_value = 126.0

    update_response = await features_instance.update_parameter("bpm", updated_bpm_value)
    print(f"Update Method Transaction Success Flag: {update_response.success}")

    post_update_read = await features_instance.get_parameter("bpm")
    print(f"Post-Update Local Parameter Verification Value: '{post_update_read}'")

    if float(post_update_read) == updated_bpm_value:
        print("✅ Pass: Dynamic parameter modifications updated smoothly.")
    else:
        print("❌ Fail: Synchronization parsing mismatch inside local cache engine state tracking blocks.")

    # -------------------------------------------------------------------------
    # Test 6: Resource Termination Cleanup Validation Sequence (`delete`)
    # -------------------------------------------------------------------------
    print("\n--- Test 6: Executing Object Record Termination Steps ---")

    deletion_response = await features_instance.delete()
    print(f"Deletion Transaction Processing Status Flag: {deletion_response.success}")

    post_deletion_lookup = await AudioFeatures.get_by_id(target_id)
    if post_deletion_lookup is None:
        print("✅ Pass: Model instance tracking verified records successfully removed from storage layers completely.")
    else:
        print("❌ Fail: Relational records footprint found lingering post teardown execution sequences.")


if __name__ == "__main__":
    asyncio.run(main())
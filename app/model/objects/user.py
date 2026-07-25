import time
from functools import wraps

from db.external_db.user_external_db import External_DB_User
from db.internal_db.user_internal_db import Internal_DB_User
import asyncio
from typing import Optional, Union, Any, Callable

from model.objects.chat import Chat
from utils.result import Result
from utils.schedule.dict_helper import AutoExpiringDict
from utils.time_manager import TimeManager


LIST_OF_DICT_FIELDS = {
    "username", "first_name", "last_name", "profile_photo", "bio", "activity"
}

DICT_FIELDS = {
    "birthday"
}

SCALAR_FIELDS = {
    "id", "user_id", "language_code", "is_bot", "is_premium",
    "is_verified", "flag", "is_public", "created_at", "updated_at", "last_activity_at"
}


_in = Internal_DB_User()
_ex = External_DB_User()


user_param_cache = AutoExpiringDict(ttl_seconds=3600, cleanup_interval=300, max_keys=10000)


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
        make_hashable(extra),  # optional field-based sub-key
    )


def cache_result(prefix: Optional[str] = None,
                 extra_key: Optional[Callable[[tuple, dict], tuple]] = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            extra = extra_key(args, kwargs) if extra_key else ()
            key = build_cache_key(self, prefix, args, kwargs, extra)

            cached = await user_param_cache.get(key)
            if cached is not None:
                return cached

            result = await func(self, *args, **kwargs)
            if result is not None:
                await user_param_cache.set(key, result)
            return result

        return wrapper

    return decorator


def cache_update_dynamic(prefix: str,
                         get_field: Callable[[tuple, dict], Any],
                         get_value: Callable[[tuple, dict], Any],
                         extra_key: Optional[Callable[[tuple, dict], tuple]] = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            result = await func(self, *args, **kwargs)

            if result is None or (isinstance(result, Result) and result.success):
                try:
                    value = get_value(args, kwargs)
                    extra = extra_key(args, kwargs) if extra_key else ()
                    key = build_cache_key(self, prefix, args, kwargs, extra)
                    await user_param_cache.set(key, value)
                except Exception as e:
                    print(f"[⚠️ cache_update_dynamic] Failed to cache at user func: {func.__name__} : {e}")
            return result

        return wrapper

    return decorator


class User(Internal_DB_User, External_DB_User):
    _lock = asyncio.Lock()

    def __init__(self,
                 user_id: Optional[Union[int, str]] = None
                 ) -> None:
        user_id = int(user_id)
        super().__init__(user_id)
        self.user_id = user_id

    @classmethod
    async def get_by_id(cls, user_id: Union[int, str]) -> Optional["User"]:
        obj = await _in.get_user_by_id(int(user_id))
        if obj:
            return User(obj.user_id)
        obj = await _ex.get_user_by_id(int(user_id))
        if obj:
            return User(obj.user_id)
        return None

    @classmethod
    async def search_users(
        cls,
        conditions: dict,
        fuzzy: bool = False,
        similarity_threshold: float = 0.7,
        limit: int = 10,
        order_by: str = "id",
        descending: bool = False,
    ) -> Optional[list["User"]]:
        objs = await _in.search_users(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            order_by=order_by,
            descending=descending,
        )
        if objs:
            return [User(obj.user_id) for obj in objs]

        objs = await _ex.search_users(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            order_by=order_by,
            descending=descending,
        )
        if objs:
            return [User(obj.user_id) for obj in objs]

        return None

    @classmethod
    async def create(cls) -> Result:
        async with User._lock:
            user_id = (await _ex.db.generate_unique_user_id()).data
        if user_id is None:
            return Result(False, "make_primary_user", "failed at making user or user_number", None)
        new_user = {
            "user_id": user_id,
            "username": [],
            "first_name": [],
            "last_name": [],
            "profile_photo": [],
            "bio": [],
            "birthday": {},
            "language_code": "en",
            "is_bot": False,
            "is_premium": False,
            "is_verified": False,
            "flag": False,
            "is_public": True,
            "activity": [],
        }
        result = await _ex.add_user(new_user)
        if result.success:
            new_user = {
                "user_id": user_id,
                "username": [],
                "first_name": [],
                "last_name": [],
                "profile_photo": [],
                "bio": [],
                "birthday": {},
                "language_code": "en",
                "is_bot": False,
                "is_premium": False,
                "is_verified": False,
                "flag": False,
                "is_public": True,
                "activity": [],
            }
            result = await _in.add_user(new_user)
            result.data = User(user_id)
            return result
        return result

    # -------------------- Cached methods --------------------
    @cache_result(prefix="user_param", extra_key=lambda args, kwargs: (args[0],))
    async def get_parameter(self, param: str) -> Any:
        result = await _in.get_parameter_from_db(self.user_id, param)
        if not result.success or result.data is None:
            result = await _ex.get_parameter_from_db(self.user_id, param)
            if not result.success or result.data is None:
                return None

        value = result.data

        if param in LIST_OF_DICT_FIELDS:
            if isinstance(value, list) and value:
                last_entry = value[-1]
                return last_entry.get("value") if isinstance(last_entry, dict) else None
            return None

        elif param in DICT_FIELDS:
            return value if isinstance(value, dict) else None

        elif param in SCALAR_FIELDS:
            return value

        # fallback (unknown param)
        return value

    @cache_result(
        prefix="user_param_all",
        extra_key=lambda args, kwargs: (args[0],),  # param
    )
    async def get_all_parameter(self, param: str) -> Optional[list[Any]]:
        """
        Retrieve all values from a list-of-dicts field.
        Each entry is expected to be a dict containing at least a "value" key.
        """
        if param not in LIST_OF_DICT_FIELDS:
            return None  # or raise ValueError(f"{param} is not a list-of-dict field")

        result = await _in.get_parameter_from_db(self.user_id, param)
        if not result.success or not isinstance(result.data, list):
            result = await _ex.get_parameter_from_db(self.user_id, param)
            if not result.success or not isinstance(result.data, list):
                return None

        values = []
        for entry in result.data:
            if isinstance(entry, dict) and "value" in entry:
                values.append(entry["value"])

        return values if values else None

    @cache_result(
        prefix="user_param_full",
        extra_key=lambda args, kwargs: (args[0],),  # param
    )
    async def get_full_parameter(self, param: str) -> Optional[list[dict]]:
        """
        Retrieve the full content of a list-of-dicts field.
        Returns the entire list of dicts as stored in the database.

        Args:
            param (str): The column name (must be in LIST_OF_DICT_FIELDS).

        Returns:
            Optional[list[dict]]: Full list of dict entries, or None if invalid/empty.
        """
        if param not in LIST_OF_DICT_FIELDS:
            return None  # or raise ValueError(f"{param} is not a list-of-dict field")

        result = await _ex.get_parameter_from_db(self.user_id, param)
        if not result.success or not isinstance(result.data, list):
            return None

        return result.data if result.data else None

    @cache_update_dynamic(
        prefix="user_param",
        get_field=lambda args, kwargs: args[0],  # param
        get_value=lambda args, kwargs: args[1],  # value
        extra_key=lambda args, kwargs: (args[0],),
    )
    async def update_parameter(self, param: str, value: Any, valid: bool = None) -> Result:
        result = Result(True, "update_parameter", "", None)

        if param in LIST_OF_DICT_FIELDS:
            if valid is None:
                current = await self.get_parameter(param)
                if current and current == value:
                    return Result(True, "update_parameter", "No update needed (value unchanged)", current)
            if valid is None:
                valid = False
            ex_current = await self.get_full_parameter(param)
            ex_history = ex_current if (ex_current and isinstance(ex_current, list)) else []
            if (
                    ex_history
                    and isinstance(ex_history[-1], dict)
                    and ex_history[-1].get("value") == value
                    and ex_history[-1].get("valid") == valid
            ):
                return Result(True, "update_parameter", "No update needed (value unchanged)", ex_history)

            in_current = await _in.get_parameter_from_db(self.user_id, param)
            in_history = in_current.data if (in_current.success and isinstance(in_current.data, list)) else []
            # Append new entry
            new_entry = {"value": value}
            updated_list = in_history + [new_entry]
            await result.add_sub_result(await _in.update_parameter(self.user_id, param, updated_list))

            new_entry = {"value": value, "time_stamp": TimeManager().tehran_now().isoformat(), "valid": valid}
            updated_list = ex_history + [new_entry]
            await result.add_sub_result(await _ex.update_parameter(self.user_id, param, updated_list))

        elif param in DICT_FIELDS:
            if not isinstance(value, dict):
                return Result(False, "update_parameter", f"{param} must be a dict", None)
            await result.add_sub_result(await _in.update_parameter(self.user_id, param, value))
            await result.add_sub_result(await _ex.update_parameter(self.user_id, param, value))

        elif param in SCALAR_FIELDS:
            await result.add_sub_result(await _in.update_parameter(self.user_id, param, value))
            await result.add_sub_result(await _ex.update_parameter(self.user_id, param, value))

        else:
            return Result(False, "update_parameter", f"Unknown parameter: {param}", None)

        # -------------------------
        # Invalidate other caches
        # -------------------------
        for prefix in ["user_param_all", "user_param_full"]:
            key = build_cache_key(self, prefix, (), {}, (param,))
            await user_param_cache.delete_key(key)

        return result

    async def erase_parameter(self, param: str) -> Result:
        """
        Erase the value of a parameter by blanking its cell.
        Behavior depends on the field type:
          - Scalar fields → set to NULL
          - Dict fields   → set to {}
          - List-of-dict fields → set to []

        Args:
            param (str): The column name to erase.

        Returns:
            Result: Database operation result.
        """
        if param in SCALAR_FIELDS:
            new_value = None
        elif param in DICT_FIELDS:
            new_value = {}
        elif param in LIST_OF_DICT_FIELDS:
            new_value = []
        else:
            return Result(False, "erase_parameter", f"Invalid parameter: {param}", None)

        return await _in.update_parameter(self.user_id, param, new_value)

    async def assign_user_fields(self, first_name: str, last_name: str, username: str) -> Result:
        result = Result(True, "assign_user_fields", "", None)
        await result.add_sub_result(await self.update_parameter("first_name", first_name, valid=False))
        await result.add_sub_result(await self.update_parameter("last_name", last_name, valid=False))
        await result.add_sub_result(await self.update_parameter("username", username, valid=False))
        return result

    async def delete(self) -> Result:
        return await _in.delete_user_by_id(self.user_id)


async def main():
    # user = (await (User.create())).data
    # print(user)
    # print(await User.get_by_id(766500571840))
    # user = await User.get_by_id(766500571840)
    # print(await user.assign_user_fields("Mohammad", "SA", "Allwjbn"))
    start = time.time()
    all_users = await User.search_users(conditions={}, limit=10000)
    tasks = []
    print(len(all_users))
    for user in all_users:
        if not await Chat.search_chats(conditions={"user_id": ("=", user.user_id)}):
            print(user.user_id)
            tasks.append(asyncio.create_task(_in.delete_user_by_id(user.user_id)))
            tasks.append(asyncio.create_task(_ex.delete_user_by_id(user.user_id)))

    await asyncio.gather(*tasks)
    # print(await user.get_full_parameter("username"))
    # print(await user.update_parameter("username", None))
    # for i in range(50000):
        # print(await user.get_parameter("username"))
        # print(await user.update_parameter("username", "Allwjbn"))

    end = time.time()
    print(f"Elapsed: {end - start:.4f} seconds")
    # print(await user.get_parameter("username"))
    # print(await user.update_parameter("username", "Allwjbn"))
    # print(await user.get_parameter("username"))


if __name__ == "__main__":
    asyncio.run(main())

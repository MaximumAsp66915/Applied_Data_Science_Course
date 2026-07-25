import asyncio
from functools import wraps
from typing import Optional, Union, Any, Callable

from db.external_db.chat_external_db import External_DB_Chat
from db.internal_db.chat_internal_db import Internal_DB_Chat
from utils.result import Result
from utils.schedule.dict_helper import AutoExpiringDict
from utils.time_manager import TimeManager

_in = Internal_DB_Chat()
_ex = External_DB_Chat()


LIST_OF_DICT_FIELDS = {
    "title", "username", "first_name", "last_name",
    "bio", "description", "invite_link", "sticker_set_name",
    "member_count"
}

DICT_FIELDS = {
    "permissions", "extra_data"
}

SCALAR_FIELDS = {
    "id", "chat_id", "chat_type", "user_id", "linked_chat_id",
    "is_verified", "is_scam", "is_fake", "is_restricted",
    "created_at", "updated_at", "last_activity_at"
}


chat_param_cache = AutoExpiringDict(ttl_seconds=3600, cleanup_interval=300, max_keys=10000)


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
        self.chat_id,
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

            cached = await chat_param_cache.get(key)
            # print(878787878787878787,
            #       chat_param_cache.data.keys())
            if cached is not None:
                return cached

            result = await func(self, *args, **kwargs)
            if result is not None:
                await chat_param_cache.set(key, result)

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
                    await chat_param_cache.set(key, value)
                except Exception as e:
                    print(f"[⚠️ cache_update_dynamic] Failed to cache at chat func: {func.__name__} : {e}")
            return result
        return wrapper
    return decorator


class Chat(Internal_DB_Chat, External_DB_Chat):
    _lock = asyncio.Lock()

    def __init__(self, chat_id: Optional[Union[int, str]] = None) -> None:
        chat_id = int(chat_id)
        super().__init__(chat_id)
        self.chat_id = chat_id

    # -------------------- Retrieval --------------------
    @classmethod
    async def get_by_id(cls, chat_id: Union[int, str]) -> Optional["Chat"]:
        obj = await _in.get_chat_by_id(int(chat_id))
        if obj:
            return Chat(obj.chat_id)
        obj = await _ex.get_chat_by_id(int(chat_id))
        if obj:
            return Chat(obj.chat_id)
        return None

    @classmethod
    async def search_chats(
        cls,
        conditions: dict,
        fuzzy: bool = False,
        similarity_threshold: float = 0.7,
        limit: int = 10,
        order_by: str = "id",
        descending: bool = False,
    ) -> Optional[list["Chat"]]:
        objs = await _in.search_chats(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            order_by=order_by,
            descending=descending,
        )
        if objs:
            return [Chat(obj.chat_id) for obj in objs]

        objs = await _ex.search_chats(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            order_by=order_by,
            descending=descending,
        )
        if objs:
            return [Chat(obj.chat_id) for obj in objs]

        return None

    @classmethod
    async def get_user_by_chat_id(cls, chat_id):
        chat = await cls.get_by_id(chat_id)
        if chat:
            user_id = await chat.get_parameter("user_id")
            if user_id:
                from model.objects.user import User
                return User(user_id)

        return None

    @classmethod
    async def create(cls, chat_id: int, chat_type: str) -> Result:
        async with Chat._lock:
            chats = await cls.search_chats({"chat_id": ("=", chat_id)}, limit=1)
            if chats is not None or isinstance(chats, list) and len(chats) > 0:
                return Result(False, "create", "Duplicated chat_id", None)
            new_chat = {
                "chat_id": chat_id,
                "chat_type": chat_type,
                "user_id": None,
                "title": [],
                "username": [],
                "first_name": [],
                "last_name": [],
                "bio": [],
                "description": [],
                "invite_link": [],
                "sticker_set_name": [],
                "permissions": {},
                "member_count": [],
                "is_verified": False,
                "is_scam": False,
                "is_fake": False,
                "is_restricted": False,
                "metadata": {},
            }
            result = await _ex.add_chat(new_chat)
            if result.success:
                result = await _in.add_chat(new_chat)
                result.data = Chat(chat_id)
                return result
            return result

    # -------------------- Cached methods --------------------
    @cache_result(prefix="chat_param", extra_key=lambda args, kwargs: (args[0],))
    async def get_parameter(self, param: str) -> Any:
        result = await _in.get_parameter_from_db(self.chat_id, param)
        if not result.success or result.data is None:
            result = await _ex.get_parameter_from_db(self.chat_id, param)
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
        return value  # fallback

    @cache_result(prefix="chat_param_all", extra_key=lambda args, kwargs: (args[0],))
    async def get_all_parameter(self, param: str) -> Optional[list[Any]]:
        if param not in LIST_OF_DICT_FIELDS:
            return None
        result = await _in.get_parameter_from_db(self.chat_id, param)
        if not result.success or not isinstance(result.data, list):
            result = await _ex.get_parameter_from_db(self.chat_id, param)
            if not result.success or not isinstance(result.data, list):
                return None
        return [entry["value"] for entry in result.data if isinstance(entry, dict) and "value" in entry] or None

    @cache_result(prefix="chat_param_full", extra_key=lambda args, kwargs: (args[0],))
    async def get_full_parameter(self, param: str) -> Optional[list[dict]]:
        if param not in LIST_OF_DICT_FIELDS:
            return None
        result = await _ex.get_parameter_from_db(self.chat_id, param)
        if not result.success or not isinstance(result.data, list):
            return None
        return result.data if result.data else None

    @cache_update_dynamic(
        prefix="chat_param",
        get_field=lambda args, kwargs: args[0],
        get_value=lambda args, kwargs: args[1],
        extra_key=lambda args, kwargs: (args[0],),
    )
    async def update_parameter(self, param: str, value: Any, valid: bool = None) -> Result:
        result = Result(True, "update_parameter", "", None)

        if param in LIST_OF_DICT_FIELDS:
            if valid is None:
                current = await self.get_parameter(param)
                if current and current == value:
                    return Result(True, "update_parameter", "No update needed (value unchanged)", current)
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

            in_current = await _in.get_parameter_from_db(self.chat_id, param)
            in_history = in_current.data if (in_current.success and isinstance(in_current.data, list)) else []

            # Internal DB update
            new_entry = {"value": value}
            updated_list = in_history + [new_entry]
            await result.add_sub_result(await _in.update_parameter(self.chat_id, param, updated_list))

            # External DB update
            new_entry = {"value": value, "time_stamp": TimeManager().tehran_now().isoformat(), "valid": valid}
            updated_list = ex_history + [new_entry]
            await result.add_sub_result(await _ex.update_parameter(self.chat_id, param, updated_list))

        elif param in DICT_FIELDS:
            if not isinstance(value, dict):
                return Result(False, "update_parameter", f"{param} must be a dict", None)
            await result.add_sub_result(await _in.update_parameter(self.chat_id, param, value))
            await result.add_sub_result(await _ex.update_parameter(self.chat_id, param, value))

        elif param in SCALAR_FIELDS:
            await result.add_sub_result(await _in.update_parameter(self.chat_id, param, value))
            await result.add_sub_result(await _ex.update_parameter(self.chat_id, param, value))

        else:
            return Result(False, "update_parameter", f"Unknown parameter: {param}", None)

        # Invalidate related caches
        for prefix in ["chat_param_all", "chat_param_full"]:
            key = build_cache_key(self, prefix, (), {}, (param,))
            await chat_param_cache.delete_key(key)

        return result

    async def erase_parameter(self, param: str) -> Result:
        if param in SCALAR_FIELDS:
            new_value = None
        elif param in DICT_FIELDS:
            new_value = {}
        elif param in LIST_OF_DICT_FIELDS:
            new_value = []
        else:
            return Result(False, "erase_parameter", f"Invalid parameter: {param}", None)

        return await _in.update_parameter(self.chat_id, param, new_value)

    async def assign_user_id(self, user_id: int) -> Result:
        return await self.update_parameter("user_id", user_id)

    async def assign_chat_fields(self,
                                 title: Optional[str] = None,
                                 first_name: Optional[str] = None,
                                 last_name: Optional[str] = None,
                                 username: Optional[str] = None) -> Result:
        result = Result(True, "assign_chat_fields", "", None)
        if title is not None:
            await result.add_sub_result(await self.update_parameter("title", title, valid=True))
        if first_name is not None:
            await result.add_sub_result(await self.update_parameter("first_name", first_name, valid=True))
        if last_name is not None:
            await result.add_sub_result(await self.update_parameter("last_name", last_name, valid=True))
        if username is not None:
            await result.add_sub_result(await self.update_parameter("username", username, valid=True))

        return result

    # -------------------- Delete --------------------
    async def delete(self) -> Result:
        return await _in.delete_chat_by_id(self.chat_id)


async def main():
    print("Starting Chat Class Test...")
    all_chats = await Chat.search_chats(conditions={}, limit=10000)
    print(len(all_chats))

    # chat = await Chat.create(384273793, "private")
    # chat = await Chat.get_by_id(384273793)
    # print(chat)
    # user = await Chat.get_user_by_chat_id(384273793)
    # print(user)
    # print(await user.update_parameter("first_name", None))
    # print(await chat.assign_chat_fields(None, "Mohammad", "SA", "Allwjbn"))
    # await chat.assign_user_id(766500571840)

if __name__ == "__main__":
    asyncio.run(main())

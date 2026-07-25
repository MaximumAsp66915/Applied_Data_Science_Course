import time
import asyncio
from collections import OrderedDict
import inspect


class AutoExpiringDict:
    def __init__(self, ttl_seconds=3600, cleanup_interval=300, max_keys=1000):
        self.ttl = ttl_seconds
        self.max_keys = max_keys
        self.data = OrderedDict()
        self.lock = asyncio.Lock()
        self._cleanup_interval = cleanup_interval
        self._cleanup_task = None

    def _normalize_key(self, key):
        """Ensure key is a tuple if two keys are given, else return as is."""
        if isinstance(key, tuple):
            return key
        return key

    async def set(self, key, value):
        await self._ensure_cleanup_started()
        async with self.lock:
            now = time.time()
            norm_key = self._normalize_key(key)
            self.data[norm_key] = (now, value)
            self.data.move_to_end(norm_key)
            await self._enforce_limits()

    async def set_add_to_list(self, key, value):
        await self._ensure_cleanup_started()
        async with self.lock:
            now = time.time()
            norm_key = self._normalize_key(key)
            data = await self.get(norm_key)
            if data is None:
                data = []
            if not isinstance(data, list):
                data = [data]
            data.append(value)
            self.data[norm_key] = (now, data)
            self.data.move_to_end(norm_key)
            await self._enforce_limits()

    async def get(self, key):
        await self._ensure_cleanup_started()
        norm_key = self._normalize_key(key)
        item = self.data.get(norm_key)
        if item:
            ts, val = item
            if time.time() - ts < self.ttl:
                return val
            else:
                del self.data[norm_key]
        return None

    async def delete_key(self, key):
        norm_key = self._normalize_key(key)
        if norm_key in self.data:
            del self.data[norm_key]

    async def delete_value(self, value):
        async with self.lock:
            keys_to_delete = [k for k, v in self.data.items()
                              if hasattr(v[1], "file_system_entity_id") and v[1].file_system_entity_id == value]
            for k in keys_to_delete:
                del self.data[k]

    def delete(self):
        self.data.clear()

    async def _ensure_cleanup_started(self):
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._auto_cleanup())

    async def _enforce_limits(self):
        while len(self.data) > self.max_keys:
            self.data.popitem(last=False)

    async def _auto_cleanup(self):
        while True:
            await asyncio.sleep(self._cleanup_interval)
            await self._cleanup()

    async def _cleanup(self):
        now = time.time()
        async with self.lock:
            expired_keys = [k for k, (ts, _) in self.data.items() if now - ts > self.ttl]
            for k in expired_keys:
                del self.data[k]


class DualExpiryDict:
    def __init__(self, idle_ttl=300, max_ttl=4200, cleanup_interval=60, max_keys=1000, delete_func=None):
        self.idle_ttl = idle_ttl
        self.max_ttl = max_ttl
        self.max_keys = max_keys
        self.delete_func = delete_func

        self.data = OrderedDict()  # key -> [created_at, last_accessed, value]
        self.lock = asyncio.Lock()
        self._cleanup_interval = cleanup_interval
        self._cleanup_task = None

    async def _trigger_delete_func(self, value):
        """Executes the cleanup callback (e.g., session.close()) if provided."""
        if self.delete_func and value is not None:
            try:
                if inspect.iscoroutinefunction(self.delete_func):
                    await self.delete_func(value)
                else:
                    self.delete_func(value)
            except Exception as e:
                print(f"Error during cleanup callback: {e}")

    async def delete_key(self, key):
        """Manually remove a key and trigger its cleanup function."""
        async with self.lock:
            if key in self.data:
                _, _, value = self.data.pop(key)
                await self._trigger_delete_func(value)

    async def clear_all(self):
        """Clear all entries and trigger cleanup for every item."""
        async with self.lock:
            tasks = [self._trigger_delete_func(val) for _, _, val in self.data.values()]
            if tasks:
                await asyncio.gather(*tasks)
            self.data.clear()

    async def set(self, key, value):
        await self._ensure_cleanup_started()
        async with self.lock:
            # If key exists, clean up the old value before overwriting
            if key in self.data:
                _, _, old_value = self.data[key]
                await self._trigger_delete_func(old_value)

            now = time.time()
            self.data[key] = [now, now, value]
            self.data.move_to_end(key)
            await self._enforce_limits()

    async def get(self, key):
        await self._ensure_cleanup_started()
        async with self.lock:
            if key not in self.data:
                return None

            created_at, last_accessed, value = self.data[key]
            now = time.time()

            expired_max = self.max_ttl and (now - created_at > self.max_ttl)
            expired_idle = self.idle_ttl and (now - last_accessed > self.idle_ttl)

            if expired_max or expired_idle:
                self.data.pop(key)
                await self._trigger_delete_func(value)
                return None

            # Update last access time
            self.data[key][1] = now
            self.data.move_to_end(key)
            return value

    async def _cleanup(self):
        """Background task logic to find and remove expired keys."""
        now = time.time()
        to_delete = []

        async with self.lock:
            for k, (created_at, last_accessed, value) in self.data.items():
                if (self.max_ttl and now - created_at > self.max_ttl) or \
                        (self.idle_ttl and now - last_accessed > self.idle_ttl):
                    to_delete.append((k, value))

            for k, val in to_delete:
                if k in self.data:
                    self.data.pop(k)
                await self._trigger_delete_func(val)

    async def _enforce_limits(self):
        while len(self.data) > self.max_keys:
            _, (_, _, value) = self.data.popitem(last=False)
            await self._trigger_delete_func(value)

    async def _ensure_cleanup_started(self):
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._auto_cleanup())

    async def _auto_cleanup(self):
        while True:
            await asyncio.sleep(self._cleanup_interval)
            await self._cleanup()

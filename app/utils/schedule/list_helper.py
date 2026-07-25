import time
import asyncio
from collections import deque


class AutoExpiringList:
    def __init__(self, ttl_seconds=3600, cleanup_interval=300, max_len=100):
        self.ttl = ttl_seconds
        self.max_len = max_len
        self.data = deque()  # stores (timestamp, value)
        self.lock = asyncio.Lock()
        self._cleanup_interval = cleanup_interval
        self._cleanup_task = None

    async def append(self, value):
        await self._ensure_cleanup_started()
        async with self.lock:
            now = time.time()
            self.data.append((now, value))
            while len(self.data) > self.max_len:
                self.data.popleft()

    async def all(self):
        await self._ensure_cleanup_started()
        now = time.time()
        async with self.lock:
            self.data = deque([(ts, v) for ts, v in self.data if now - ts <= self.ttl])
            return [v for ts, v in self.data]

    async def get(self, index):
        await self._ensure_cleanup_started()
        now = time.time()
        async with self.lock:
            if index < 0 or index >= len(self.data):
                return None
            ts, v = self.data[index]
            if now - ts <= self.ttl:
                return v
            return None

    async def clear(self):
        async with self.lock:
            self.data.clear()

    async def _ensure_cleanup_started(self):
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._auto_cleanup())

    async def _auto_cleanup(self):
        while True:
            await asyncio.sleep(self._cleanup_interval)
            await self._cleanup()

    async def _cleanup(self):
        now = time.time()
        async with self.lock:
            self.data = deque([(ts, v) for ts, v in self.data if now - ts <= self.ttl])

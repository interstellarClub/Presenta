import asyncio
import time
from collections import defaultdict


class LocalRateLimiter:
    backend = "local"

    def __init__(self) -> None:
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def allow(self, key: str, limit: int, window_s: int) -> bool:
        now = time.monotonic()
        async with self._lock:
            stamps = [stamp for stamp in self._buckets[key] if now - stamp < window_s]
            if len(stamps) >= limit:
                self._buckets[key] = stamps
                return False
            stamps.append(now)
            self._buckets[key] = stamps
            return True

    async def reset(self, key: str) -> None:
        async with self._lock:
            self._buckets.pop(key, None)


class RedisRateLimiter:
    backend = "redis"

    def __init__(self, url: str) -> None:
        import redis.asyncio as redis

        self.client = redis.from_url(url, decode_responses=True)

    async def allow(self, key: str, limit: int, window_s: int) -> bool:
        try:
            current = await self.client.incr(key)
            if current == 1:
                await self.client.expire(key, window_s)
            return int(current) <= limit
        except Exception:
            return True

    async def reset(self, key: str) -> None:
        try:
            await self.client.delete(key)
        except Exception:
            return


def build_limiter() -> LocalRateLimiter | RedisRateLimiter:
    from app.core.config import settings

    if settings.queue_backend == "arq":
        try:
            return RedisRateLimiter(settings.redis_url)
        except Exception:
            return LocalRateLimiter()
    return LocalRateLimiter()


limiter = build_limiter()
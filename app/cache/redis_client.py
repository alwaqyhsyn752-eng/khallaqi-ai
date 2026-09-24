"""Redis client + atomic rate limiter (Lua-script based)."""
from __future__ import annotations

from typing import Optional, Tuple

import redis.asyncio as aioredis

from app.config import settings
from app.exceptions import CacheError
from app.logging_config import get_logger

log = get_logger(__name__)

_redis: Optional[aioredis.Redis] = None


# ─────────────────────────────────────────────────────────────────
# Atomic rate-limit script (sliding window per-user, two counters)
# ─────────────────────────────────────────────────────────────────
_RATE_LIMIT_LUA = """
local minute_key = KEYS[1]
local hour_key   = KEYS[2]
local per_min    = tonumber(ARGV[1])
local per_hour   = tonumber(ARGV[2])

local m = tonumber(redis.call('GET', minute_key) or '0')
local h = tonumber(redis.call('GET', hour_key)   or '0')

if m >= per_min then
    return {0, m, h}
end
if h >= per_hour then
    return {0, m, h}
end

m = redis.call('INCR', minute_key)
if m == 1 then redis.call('EXPIRE', minute_key, 60) end

h = redis.call('INCR', hour_key)
if h == 1 then redis.call('EXPIRE', hour_key, 3600) end

return {1, m, h}
"""


class RedisClient:
    """Thin wrapper around redis.asyncio with helpers."""

    def __init__(self, client: aioredis.Redis) -> None:
        self._r = client

    async def get(self, key: str) -> Optional[str]:
        v = await self._r.get(key)
        if v is None:
            return None
        return v.decode() if isinstance(v, bytes) else v

    async def set(
        self,
        key: str,
        value: str,
        ttl: Optional[int] = None,
    ) -> None:
        await self._r.set(key, value, ex=ttl)

    async def delete(self, *keys: str) -> int:
        if not keys:
            return 0
        return int(await self._r.delete(*keys))

    async def exists(self, key: str) -> bool:
        return bool(await self._r.exists(key))

    async def incr(self, key: str, ttl: Optional[int] = None) -> int:
        val = int(await self._r.incr(key))
        if ttl and val == 1:
            await self._r.expire(key, ttl)
        return val

    async def ping(self) -> bool:
        try:
            return bool(await self._r.ping())
        except Exception:
            return False

    async def rate_limit_check(
        self,
        user_id: str,
        per_min: int,
        per_hour: int,
    ) -> Tuple[bool, int, int]:
        """Return (allowed, remaining_min, remaining_hour)."""
        minute_key = f"rl:m:{user_id}"
        hour_key = f"rl:h:{user_id}"

        try:
            result = await self._r.eval(
                _RATE_LIMIT_LUA,
                2,
                minute_key,
                hour_key,
                per_min,
                per_hour,
            )
            allowed = bool(int(result[0]))
            used_min = int(result[1])
            used_hour = int(result[2])
            return (
                allowed,
                max(0, per_min - used_min),
                max(0, per_hour - used_hour),
            )
        except Exception:
            log.exception("redis.rate_limit_failed")
            # Fail-open: allow the request but log
            return True, per_min, per_hour


async def init_redis() -> None:
    """Initialize the global Redis connection pool."""
    global _redis

    if _redis is not None:
        return

    try:
        _redis = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=False,
            max_connections=settings.redis_max_connections,
            socket_timeout=5,
            socket_connect_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        await _redis.ping()
        log.info("redis.initialized", url=settings.redis_url.split("@")[-1])
    except Exception as e:
        log.warning("redis.init_failed", error=str(e))
        _redis = None


async def close_redis() -> None:
    """Close the Redis connection pool."""
    global _redis
    if _redis is not None:
        try:
            await _redis.close()
            log.info("redis.closed")
        except Exception:
            log.exception("redis.close_failed")
        finally:
            _redis = None


def get_redis() -> Optional[RedisClient]:
    """Return the RedisClient wrapper, or None if Redis is unavailable."""
    if _redis is None:
        return None
    return RedisClient(_redis)


def is_redis_available() -> bool:
    """Check if Redis is connected."""
    return _redis is not None

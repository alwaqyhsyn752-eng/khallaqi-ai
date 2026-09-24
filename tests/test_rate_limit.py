"""Tests for rate limiting logic."""
from __future__ import annotations

import pytest

from app.exceptions import RateLimitError
from app.services.rate_limit_service import RateLimitService


class FakeRedis:
    """Deterministic Redis stub for tests."""

    def __init__(self, allowed: bool = True, rem_min: int = 19, rem_hour: int = 499):
        self._allowed = allowed
        self._rem_min = rem_min
        self._rem_hour = rem_hour
        self.calls = 0

    async def rate_limit_check(self, user_id: str, per_min: int, per_hour: int):
        self.calls += 1
        return self._allowed, self._rem_min, self._rem_hour


class FakeDBRepo:
    """DB fallback stub."""

    def __init__(self, ok: bool = True):
        self._ok = ok

    async def check_and_record(self, user_id: str):
        if self._ok:
            return True, 19, 499, None
        return False, 0, 0, "تجاوز الحد"


@pytest.mark.asyncio
async def test_redis_allows_request() -> None:
    svc = RateLimitService(redis=FakeRedis(allowed=True), db_repo=FakeDBRepo())
    rem_min, rem_hour = await svc.check("u1")
    assert rem_min >= 0
    assert rem_hour >= 0


@pytest.mark.asyncio
async def test_redis_blocks_when_exceeded() -> None:
    svc = RateLimitService(redis=FakeRedis(allowed=False), db_repo=FakeDBRepo())
    with pytest.raises(RateLimitError):
        await svc.check("u2")


@pytest.mark.asyncio
async def test_fallback_to_db_when_redis_missing() -> None:
    svc = RateLimitService(redis=None, db_repo=FakeDBRepo(ok=True))
    rem_min, rem_hour = await svc.check("u3")
    assert rem_min == 19


@pytest.mark.asyncio
async def test_db_fallback_blocks() -> None:
    svc = RateLimitService(redis=None, db_repo=FakeDBRepo(ok=False))
    with pytest.raises(RateLimitError):
        await svc.check("u4")

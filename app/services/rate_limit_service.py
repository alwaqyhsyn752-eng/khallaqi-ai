"""Rate-limit service — Redis first, DB fallback."""
from __future__ import annotations

from typing import Optional, Tuple

from app.cache.redis_client import RedisClient
from app.config import get_settings
from app.db.repositories.stats import RateLimitRepository
from app.exceptions import RateLimitError
from app.logging_config import get_logger

log = get_logger(__name__)


class RateLimitService:
    """Combines Redis (fast) and DB (fallback) rate limiting."""

    def __init__(
        self,
        redis: Optional[RedisClient],
        db_repo: RateLimitRepository,
    ) -> None:
        self._redis = redis
        self._db = db_repo

    async def check(self, user_id: str) -> Tuple[int, int]:
        """Enforce rate limits. Returns (remaining_min, remaining_hour).

        Uses Redis when available, DB otherwise.
        Raises:
            RateLimitError: when the user exceeds their quota.
        """
        s = get_settings()
        per_min = s.rate_limit_per_min
        per_hour = s.rate_limit_per_hour

        # ─── Try Redis ───
        if self._redis is not None:
            try:
                allowed, rem_min, rem_hour = await self._redis.rate_limit_check(
                    user_id, per_min, per_hour
                )
                if not allowed:
                    raise RateLimitError(
                        "تجاوزت حد الطلبات المسموح",
                        details={"remaining_min": rem_min, "remaining_hour": rem_hour},
                    )
                return rem_min, rem_hour
            except RateLimitError:
                raise
            except Exception:
                log.exception("rate_limit.redis_failed")

        # ─── DB fallback ───
        try:
            ok, rem_min, rem_hour, err = await self._db.check_and_record(user_id)
            if not ok:
                raise RateLimitError(
                    err or "تجاوزت الحد",
                    details={"remaining_min": rem_min, "remaining_hour": rem_hour},
                )
            return rem_min, rem_hour
        except RateLimitError:
            raise
        except Exception as e:
            log.exception("rate_limit.db_failed")
            # Fail-open on infra errors so the app stays usable
            return per_min, per_hour

    async def peek(self, user_id: str) -> Tuple[int, int]:
        """Return current remaining counts without consuming a token."""
        s = get_settings()
        if self._redis is not None:
            try:
                allowed, rem_min, rem_hour = await self._redis.rate_limit_check(
                    user_id, s.rate_limit_per_min, s.rate_limit_per_hour
                )
                return rem_min, rem_hour
            except Exception:
                pass
        return s.rate_limit_per_min, s.rate_limit_per_hour

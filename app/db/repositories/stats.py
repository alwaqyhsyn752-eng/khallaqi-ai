"""Stats + rate-limit repositories."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy import delete, func, select

from app.config import settings
from app.db.repositories.base import BaseRepository
from app.logging_config import get_logger
from app.models.db_models import RateLimit, StatsEvent

log = get_logger(__name__)


class StatsRepository(BaseRepository[StatsEvent]):
    """Async repository for aggregated stats events."""

    model = StatsEvent

    async def log(self, user_id: str, event: str, meta: Optional[dict] = None) -> None:
        """Record an event. Never raises."""
        try:
            await self.create(
                user_id=user_id,
                event=event,
                meta=json.dumps(meta or {}, ensure_ascii=False),
                created_at=datetime.utcnow(),
            )
        except Exception:
            log.exception("stats.log_failed")

    async def summary(self, user_id: str) -> dict:
        """Return aggregated stats for the user."""
        from app.models.db_models import Chat, Message

        chats_count = await self._scalar(
            select(func.count()).select_from(Chat).where(Chat.user_id == user_id)
        )
        messages_count = await self._scalar(
            select(func.count())
            .select_from(Message)
            .join(Chat, Chat.id == Message.chat_id)
            .where(Chat.user_id == user_id)
        )
        assistant_count = await self._scalar(
            select(func.count())
            .select_from(Message)
            .join(Chat, Chat.id == Message.chat_id)
            .where(Chat.user_id == user_id, Message.role == "assistant")
        )
        memory_count = await self._scalar(
            select(func.count())
            .select_from(StatsEvent)
            .where(StatsEvent.user_id == user_id)  # placeholder; replaced below
        )
        # Real memory count
        from app.models.db_models import UserMemory
        memory_count = await self._scalar(
            select(func.count())
            .select_from(UserMemory)
            .where(UserMemory.user_id == user_id)
        )

        provider_rows = await self.session.execute(
            select(Message.source, func.count(Message.id))
            .join(Chat, Chat.id == Message.chat_id)
            .where(Chat.user_id == user_id, Message.source.isnot(None))
            .group_by(Message.source)
        )
        by_provider = {row[0]: int(row[1]) for row in provider_rows.all()}

        return {
            "chats_count": chats_count,
            "messages_count": messages_count,
            "assistant_count": assistant_count,
            "memory_count": memory_count,
            "by_provider": by_provider,
        }

    async def _scalar(self, stmt) -> int:
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)


class RateLimitRepository(BaseRepository[RateLimit]):
    """Async repository for rate limiting via DB.

    Note: Redis-backed rate limiting is implemented in `app.cache.redis_client`.
    This DB fallback is used when Redis is unavailable.
    """

    model = RateLimit

    async def check_and_record(
        self, user_id: str
    ) -> Tuple[bool, int, int, Optional[str]]:
        """Return (ok, remaining_min, remaining_hour, error_msg)."""
        now = datetime.utcnow()
        hour_ago = now - timedelta(hours=1)
        minute_ago = now - timedelta(minutes=1)

        hour_count = await self._count_since(user_id, hour_ago)
        min_count = await self._count_since(user_id, minute_ago)

        if min_count >= settings.rate_limit_per_min:
            return (
                False,
                0,
                max(0, settings.rate_limit_per_hour - hour_count),
                f"تجاوزت حد {settings.rate_limit_per_min} رسالة/دقيقة. انتظر قليلاً.",
            )
        if hour_count >= settings.rate_limit_per_hour:
            return (
                False,
                0,
                0,
                f"تجاوزت حد {settings.rate_limit_per_hour} رسالة/ساعة. انتظر.",
            )

        await self.create(user_id=user_id, timestamp=now)
        await self._cleanup(now - timedelta(hours=2))

        return (
            True,
            settings.rate_limit_per_min - min_count - 1,
            settings.rate_limit_per_hour - hour_count - 1,
            None,
        )

    async def _count_since(self, user_id: str, since: datetime) -> int:
        stmt = (
            select(func.count())
            .select_from(RateLimit)
            .where(RateLimit.user_id == user_id, RateLimit.timestamp > since)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def _cleanup(self, before: datetime) -> None:
        """Delete stale rate-limit rows."""
        await self.session.execute(
            delete(RateLimit).where(RateLimit.timestamp < before)
        )

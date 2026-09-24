"""Memory repository — long-term user preferences."""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import delete, select

from app.db.repositories.base import BaseRepository
from app.logging_config import get_logger
from app.models.db_models import UserMemory

log = get_logger(__name__)


class MemoryRepository(BaseRepository[UserMemory]):
    """Async repository for user memory."""

    model = UserMemory

    async def set_value(
        self,
        user_id: str,
        key: str,
        value: str,
        category: str = "general",
        confidence: float = 1.0,
    ) -> UserMemory:
        """Upsert a memory entry."""
        stmt = select(UserMemory).where(
            UserMemory.user_id == user_id, UserMemory.key == key
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            existing.value = value
            existing.category = category
            existing.confidence = confidence
            existing.updated_at = datetime.utcnow()
            await self.session.flush()
            return existing

        return await self.create(
            user_id=user_id,
            key=key,
            value=value,
            category=category,
            confidence=confidence,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

    async def list_for_user(
        self, user_id: str, limit: int = 100
    ) -> Sequence[UserMemory]:
        """List all memory entries for a user, newest first."""
        stmt = (
            select(UserMemory)
            .where(UserMemory.user_id == user_id)
            .order_by(UserMemory.updated_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_value(self, user_id: str, key: str) -> Optional[str]:
        """Fetch a single memory value."""
        stmt = select(UserMemory.value).where(
            UserMemory.user_id == user_id, UserMemory.key == key
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_value(self, user_id: str, key: str) -> bool:
        """Delete a specific memory entry."""
        stmt = delete(UserMemory).where(
            UserMemory.user_id == user_id, UserMemory.key == key
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return bool(result.rowcount)

    async def delete_all_for_user(self, user_id: str) -> int:
        """Delete all memory entries for a user. Returns count."""
        stmt = delete(UserMemory).where(UserMemory.user_id == user_id)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return int(result.rowcount or 0)

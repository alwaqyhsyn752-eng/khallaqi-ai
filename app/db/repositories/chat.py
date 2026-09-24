"""Chat & Message repositories."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional, Sequence

from sqlalchemy import desc, func, or_, select

from app.db.repositories.base import BaseRepository
from app.logging_config import get_logger
from app.models.db_models import Chat, Message

log = get_logger(__name__)


class ChatRepository(BaseRepository[Chat]):
    """Async repository for chats."""

    model = Chat

    async def create_chat(self, user_id: str, title: str = "محادثة جديدة") -> Chat:
        """Create a new chat."""
        chat_id = str(uuid.uuid4())
        chat = await self.create(
            id=chat_id,
            user_id=user_id,
            title=title,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        log.info("chat.created", chat_id=chat_id, user_id=user_id)
        return chat

    async def list_by_user(self, user_id: str, limit: int = 100) -> Sequence[Chat]:
        """List all chats for a user, newest first."""
        stmt = (
            select(Chat)
            .where(Chat.user_id == user_id)
            .order_by(desc(Chat.updated_at))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def find_by_id_and_user(self, chat_id: str, user_id: str) -> Optional[Chat]:
        """Fetch a chat only if it belongs to the user (ownership check)."""
        stmt = select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def belongs_to_user(self, chat_id: str, user_id: str) -> bool:
        """Fast ownership check without loading the row."""
        stmt = select(Chat.id).where(Chat.id == chat_id, Chat.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def rename(self, chat_id: str, user_id: str, title: str) -> bool:
        """Rename a chat owned by the user."""
        chat = await self.find_by_id_and_user(chat_id, user_id)
        if chat is None:
            return False
        chat.title = title[:80]
        chat.updated_at = datetime.utcnow()
        await self.session.flush()
        return True

    async def delete_chat(self, chat_id: str, user_id: str) -> bool:
        """Delete a chat and its messages."""
        chat = await self.find_by_id_and_user(chat_id, user_id)
        if chat is None:
            return False
        await self.session.delete(chat)
        await self.session.flush()
        log.info("chat.deleted", chat_id=chat_id, user_id=user_id)
        return True

    async def search(self, user_id: str, query: str, limit: int = 30) -> List[dict]:
        """Full-text-ish search across the user's messages."""
        pattern = f"%{query}%"
        stmt = (
            select(Chat.id, Chat.title, Chat.updated_at, Message.content)
            .join(Message, Message.chat_id == Chat.id)
            .where(
                Chat.user_id == user_id,
                or_(
                    Message.content.ilike(pattern),
                    Chat.title.ilike(pattern),
                ),
            )
            .order_by(desc(Chat.updated_at))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        rows = result.all()

        results: List[dict] = []
        seen: set[str] = set()
        for chat_id, title, updated_at, content in rows:
            if chat_id in seen:
                continue
            seen.add(chat_id)
            snippet = self._make_snippet(content, query)
            results.append(
                {
                    "chat_id": chat_id,
                    "title": title,
                    "updated_at": str(updated_at),
                    "snippet": snippet,
                }
            )
        return results

    @staticmethod
    def _make_snippet(content: str, query: str) -> str:
        """Build a short snippet around the query match."""
        if not content:
            return ""
        idx = content.lower().find(query.lower())
        if idx < 0:
            return content[:100] + ("..." if len(content) > 100 else "")
        start = max(0, idx - 40)
        end = min(len(content), idx + len(query) + 60)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(content) else ""
        return f"{prefix}{content[start:end]}{suffix}"


class MessageRepository(BaseRepository[Message]):
    """Async repository for messages."""

    model = Message

    async def add(
        self,
        chat_id: str,
        role: str,
        content: str,
        message_type: str = "text",
        media_data: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Message:
        """Add a message to a chat and bump the chat's updated_at."""
        msg = await self.create(
            chat_id=chat_id,
            role=role,
            content=content,
            message_type=message_type,
            media_data=media_data,
            source=source,
            created_at=datetime.utcnow(),
        )
        # Bump chat timestamp
        chat = await self.session.get(Chat, chat_id)
        if chat is not None:
            chat.updated_at = datetime.utcnow()
        return msg

    async def list_for_chat(self, chat_id: str, limit: int = 50) -> Sequence[Message]:
        """Return the last `limit` messages ordered by id ASC."""
        stmt = (
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.id.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_for_chat(self, chat_id: str) -> int:
        """Count messages in a chat."""
        stmt = select(func.count()).select_from(Message).where(Message.chat_id == chat_id)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def provider_usage(self, user_id: str) -> dict:
        """Return {provider: count} for the given user."""
        stmt = (
            select(Message.source, func.count(Message.id))
            .join(Chat, Chat.id == Message.chat_id)
            .where(Chat.user_id == user_id, Message.source.isnot(None))
            .group_by(Message.source)
        )
        result = await self.session.execute(stmt)
        return {row[0]: int(row[1]) for row in result.all()}

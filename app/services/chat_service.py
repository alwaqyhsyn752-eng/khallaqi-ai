"""Chat service — orchestrates the full chat business flow."""
from __future__ import annotations

from typing import AsyncIterator, List, Optional, Tuple

from app.db.repositories.chat import ChatRepository, MessageRepository
from app.db.repositories.stats import StatsRepository
from app.exceptions import NotFoundError, UnauthorizedError, ValidationError
from app.logging_config import get_logger
from app.models.db_models import Chat, Message
from app.prompts.system_prompt import get_system_prompt
from app.services.ai.base import AIResponse, ChatMessage
from app.services.ai.router import AIRouter
from app.services.memory_service import MemoryService

log = get_logger(__name__)


class ChatService:
    """High-level chat orchestration."""

    def __init__(
        self,
        router: AIRouter,
        chat_repo: ChatRepository,
        message_repo: MessageRepository,
        memory_service: MemoryService,
        stats_repo: StatsRepository,
    ) -> None:
        self._router = router
        self._chats = chat_repo
        self._messages = message_repo
        self._memory = memory_service
        self._stats = stats_repo

    # ═══════════════════════════════════════════════════════════════
    # Chat lifecycle
    # ═══════════════════════════════════════════════════════════════
    async def create_chat(self, user_id: str) -> Chat:
        """Create a new chat."""
        return await self._chats.create_chat(user_id)

    async def list_chats(self, user_id: str):
        """List chats for a user."""
        return await self._chats.list_by_user(user_id)

    async def delete_chat(self, chat_id: str, user_id: str) -> bool:
        """Delete a chat owned by the user."""
        return await self._chats.delete_chat(chat_id, user_id)

    async def get_messages(self, chat_id: str, user_id: str) -> List[Message]:
        """Return messages after verifying ownership."""
        if not await self._chats.belongs_to_user(chat_id, user_id):
            raise UnauthorizedError("غير مصرح بالوصول لهذه المحادثة")
        return list(await self._messages.list_for_chat(chat_id, limit=200))

    async def search(self, user_id: str, query: str):
        """Full-text-ish search."""
        return await self._chats.search(user_id, query)

    # ═══════════════════════════════════════════════════════════════
    # Send message — non-streaming
    # ═══════════════════════════════════════════════════════════════
    async def send_text(
        self,
        chat_id: str,
        user_id: str,
        message: str,
    ) -> Tuple[AIResponse, str]:
        """Handle a plain text message.

        Returns:
            (AIResponse, full_reply_text)
        Raises:
            UnauthorizedError / ValidationError / AIProviderError
        """
        if not message.strip():
            raise ValidationError("الرسالة فارغة")
        await self._ensure_owned(chat_id, user_id)
        await self._maybe_generate_title(chat_id, user_id, message)

        # Persist user message
        await self._messages.add(chat_id, "user", message, message_type="text")

        # Build the conversation history
        history = await self._build_history(chat_id)
        memory_ctx = await self._memory.build_context(user_id)
        system_prompt = get_system_prompt() + (
            "\n\n" + memory_ctx if memory_ctx else ""
        )

        # Call the AI
        response = await self._router.generate(history, system_prompt)

        # Persist assistant reply
        await self._messages.add(
            chat_id,
            "assistant",
            response.text,
            message_type="text",
            source=response.source,
        )

        # Best-effort memory extraction
        try:
            await self._memory.extract_and_save(user_id, message, response.text)
        except Exception:
            log.exception("chat.memory_extract_failed")

        # Analytics
        try:
            await self._stats.log(
                user_id,
                "chat.text",
                {"source": response.source, "len": len(response.text)},
            )
        except Exception:
            pass

        return response, response.text

    # ═══════════════════════════════════════════════════════════════
    # Send message — streaming
    # ═══════════════════════════════════════════════════════════════
    async def stream_text(
        self,
        chat_id: str,
        user_id: str,
        message: str,
    ) -> AsyncIterator[Tuple[str, str]]:
        """Handle a text message with streaming.

        Yields:
            (event, data) tuples where event is one of:
                "provider"  — the provider name (emitted once)
                "chunk"     — a token chunk
                "done"      — final event with full text length
        """
        if not message.strip():
            raise ValidationError("الرسالة فارغة")
        await self._ensure_owned(chat_id, user_id)
        await self._maybe_generate_title(chat_id, user_id, message)

        await self._messages.add(chat_id, "user", message, message_type="text")

        history = await self._build_history(chat_id)
        memory_ctx = await self._memory.build_context(user_id)
        system_prompt = get_system_prompt() + (
            "\n\n" + memory_ctx if memory_ctx else ""
        )

        full_text_parts: List[str] = []
        provider_name: Optional[str] = None

        async for kind, value in self._router.stream(history, system_prompt):
            if kind == "__provider__":
                provider_name = value
                yield ("provider", value)
            else:
                full_text_parts.append(value)
                yield ("chunk", value)

        full_text = "".join(full_text_parts)

        # Persist assistant reply
        await self._messages.add(
            chat_id,
            "assistant",
            full_text,
            message_type="text",
            source=provider_name,
        )

        # Memory + analytics (best-effort)
        try:
            await self._memory.extract_and_save(user_id, message, full_text)
        except Exception:
            log.exception("chat.stream.memory_failed")

        try:
            await self._stats.log(
                user_id,
                "chat.stream",
                {"source": provider_name, "len": len(full_text)},
            )
        except Exception:
            pass

        yield ("done", str(len(full_text)))

    # ═══════════════════════════════════════════════════════════════
    # Send message — vision
    # ═══════════════════════════════════════════════════════════════
    async def send_vision(
        self,
        chat_id: str,
        user_id: str,
        message: str,
        image_base64: str,
        image_type: str = "image/jpeg",
    ) -> Tuple[AIResponse, str]:
        """Handle an image message."""
        await self._ensure_owned(chat_id, user_id)
        text = message.strip() or "حلل هذه الصورة"
        await self._maybe_generate_title(chat_id, user_id, text)

        # Persist user message with the image
        await self._messages.add(
            chat_id,
            "user",
            text,
            message_type="image",
            media_data=image_base64,
        )

        memory_ctx = await self._memory.build_context(user_id)
        system_prompt = get_system_prompt() + (
            "\n\n" + memory_ctx if memory_ctx else ""
        )

        response = await self._router.vision(
            text,
            image_base64,
            image_type,
            system_prompt,
        )

        await self._messages.add(
            chat_id,
            "assistant",
            response.text,
            message_type="text",
            source=response.source,
        )

        try:
            await self._memory.extract_and_save(user_id, text, response.text)
        except Exception:
            log.exception("chat.vision.memory_failed")

        try:
            await self._stats.log(user_id, "chat.vision", {"source": response.source})
        except Exception:
            pass

        return response, response.text

    # ═══════════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════════
    async def _ensure_owned(self, chat_id: str, user_id: str) -> None:
        """Verify chat exists and belongs to the user."""
        if not await self._chats.belongs_to_user(chat_id, user_id):
            raise UnauthorizedError("غير مصرح بالوصول لهذه المحادثة")

    async def _maybe_generate_title(
        self, chat_id: str, user_id: str, first_message: str
    ) -> None:
        """Set the chat title from the first message."""
        count = await self._messages.count_for_chat(chat_id)
        if count > 0:
            return
        title = first_message.strip().replace("\n", " ")[:60]
        if len(first_message) > 60:
            title += "..."
        await self._chats.rename(chat_id, user_id, title)

    async def _build_history(
        self, chat_id: str, limit: int = 30
    ) -> List[ChatMessage]:
        """Fetch recent messages and convert to AI history."""
        rows = await self._messages.list_for_chat(chat_id, limit=limit)
        out: List[ChatMessage] = []
        for m in rows:
            if m.role not in ("user", "assistant"):
                continue
            if m.message_type == "video_pending":
                continue  # skip internal states
            out.append(ChatMessage(role=m.role, content=m.content))
        return out

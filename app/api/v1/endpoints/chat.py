"""Chat endpoints: list, create, get, delete, send, stream."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from app.db.repositories import ChatRepository, MemoryRepository, StatsRepository
from app.db.repositories.chat import MessageRepository
from app.dependencies import (
    ChatRepoDep,
    MemoryRepoDep,
    SessionDep,
    StatsRepoDep,
    UserIDDep,
)
from app.exceptions import NotFoundError, UnauthorizedError, ValidationError
from app.logging_config import get_logger
from app.models.schemas import (
    ChatListOut,
    ChatOut,
    ChatRequest,
    ChatResponseOut,
    DeleteChatRequest,
    MessageOut,
    NewChatRequest,
)
from app.services.ai.router import AIRouter, get_ai_router
from app.services.chat_service import ChatService
from app.services.memory_service import MemoryService
from app.services.rate_limit_service import RateLimitService
from app.cache.redis_client import get_redis
from app.db.repositories.stats import RateLimitRepository

log = get_logger(__name__)

router = APIRouter(tags=["chat"])


# ═══════════════════════════════════════════════════════════════════
# Service factory
# ═══════════════════════════════════════════════════════════════════
def _build_chat_service(
    session,
    chat_repo: ChatRepository,
    memory_repo: MemoryRepository,
    stats_repo: StatsRepository,
    router_ai: AIRouter,
) -> ChatService:
    """Construct a ChatService with all needed dependencies."""
    message_repo = MessageRepository(session=session)
    memory_service = MemoryService(memory_repo)
    return ChatService(
        router=router_ai,
        chat_repo=chat_repo,
        message_repo=message_repo,
        memory_service=memory_service,
        stats_repo=stats_repo,
    )


def _build_rate_limit_service(session) -> RateLimitService:
    """Construct a RateLimitService (Redis-first, DB-fallback)."""
    return RateLimitService(
        redis=get_redis(),
        db_repo=RateLimitRepository(session=session),
    )


# ═══════════════════════════════════════════════════════════════════
# List / Create / Get / Delete
# ═══════════════════════════════════════════════════════════════════
@router.get("/chats", response_model=ChatListOut, summary="List user chats")
async def list_chats(
    user_id: UserIDDep,
    chat_repo: ChatRepoDep,
) -> ChatListOut:
    """Return all chats belonging to the user, newest first."""
    chats = await chat_repo.list_by_user(user_id)
    return ChatListOut(
        chats=[
            ChatOut(
                id=c.id,
                title=c.title,
                created_at=str(c.created_at),
                updated_at=str(c.updated_at),
            )
            for c in chats
        ]
    )


@router.post(
    "/chats/new",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new chat",
)
async def new_chat(
    payload: NewChatRequest,
    chat_repo: ChatRepoDep,
) -> dict:
    """Create a new empty chat and return its ID."""
    chat = await chat_repo.create_chat(payload.user_id)
    return {"chat_id": chat.id, "title": chat.title}


@router.get(
    "/chats/{chat_id}",
    summary="Get chat messages",
)
async def get_chat(
    chat_id: str,
    user_id: UserIDDep,
    session: SessionDep,
    chat_repo: ChatRepoDep,
    memory_repo: MemoryRepoDep,
    stats_repo: StatsRepoDep,
) -> dict:
    """Return all messages in a chat (ownership enforced)."""
    ai_router = get_ai_router()
    svc = _build_chat_service(session, chat_repo, memory_repo, stats_repo, ai_router)
    messages = await svc.get_messages(chat_id, user_id)
    return {
        "messages": [
            MessageOut(
                role=m.role,
                content=m.content,
                type=m.message_type or "text",
                media=m.media_data,
                source=m.source,
            ).model_dump()
            for m in messages
        ]
    }


@router.delete(
    "/chats/{chat_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a chat",
)
async def delete_chat(
    chat_id: str,
    payload: DeleteChatRequest,
    chat_repo: ChatRepoDep,
) -> dict:
    """Delete a chat and all its messages."""
    ok = await chat_repo.delete_chat(chat_id, payload.user_id)
    if not ok:
        raise NotFoundError("المحادثة غير موجودة أو لا تملكها")
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════
# Send message — non-streaming
# ═══════════════════════════════════════════════════════════════════
@router.post(
    "/chat",
    response_model=ChatResponseOut,
    summary="Send a message (non-streaming)",
)
async def send_message(
    payload: ChatRequest,
    session: SessionDep,
    chat_repo: ChatRepoDep,
    memory_repo: MemoryRepoDep,
    stats_repo: StatsRepoDep,
) -> ChatResponseOut:
    """Send a message and receive a complete response."""
    if not payload.message.strip() and not payload.image:
        raise ValidationError("لا يوجد نص ولا صورة")

    rl = _build_rate_limit_service(session)
    rem_min, rem_hour = await rl.check(payload.user_id)

    ai_router = get_ai_router()
    svc = _build_chat_service(session, chat_repo, memory_repo, stats_repo, ai_router)

    if payload.image:
        response, text = await svc.send_vision(
            payload.chat_id,
            payload.user_id,
            payload.message,
            payload.image,
            payload.image_type,
        )
    else:
        response, text = await svc.send_text(
            payload.chat_id,
            payload.user_id,
            payload.message,
        )

    return ChatResponseOut(
        response=text,
        source=response.source,
        type="text",
        remaining_min=rem_min,
        remaining_hour=rem_hour,
    )


# ═══════════════════════════════════════════════════════════════════
# Send message — streaming (SSE)
# ═══════════════════════════════════════════════════════════════════
@router.post(
    "/chat/stream",
    summary="Send a message (SSE streaming)",
)
async def stream_message(
    payload: ChatRequest,
    session: SessionDep,
    chat_repo: ChatRepoDep,
    memory_repo: MemoryRepoDep,
    stats_repo: StatsRepoDep,
) -> StreamingResponse:
    """Send a message and stream tokens via Server-Sent Events."""

    async def _sse_event(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    # ─── Preflight checks ───
    if not payload.message.strip():
        async def err_gen():
            yield await _sse_event(
                {"error": "الرسالة فارغة", "code": "validation_error"}
            )
        return StreamingResponse(err_gen(), media_type="text/event-stream")

    # ─── Rate limit ───
    try:
        rl = _build_rate_limit_service(session)
        rem_min, rem_hour = await rl.check(payload.user_id)
    except Exception as e:
        async def err_gen():
            yield await _sse_event({"error": str(e)[:200], "code": "rate_limit"})
        return StreamingResponse(err_gen(), media_type="text/event-stream")

    ai_router = get_ai_router()
    svc = _build_chat_service(session, chat_repo, memory_repo, stats_repo, ai_router)

    # ─── Stream generator ───
    async def event_stream() -> AsyncIterator[str]:
        try:
            async for kind, value in svc.stream_text(
                payload.chat_id,
                payload.user_id,
                payload.message,
            ):
                if kind == "provider":
                    yield await _sse_event({"provider": value})
                elif kind == "chunk":
                    yield await _sse_event({"chunk": value})
                elif kind == "done":
                    yield await _sse_event(
                        {
                            "done": True,
                            "length": value,
                            "remaining_min": rem_min,
                            "remaining_hour": rem_hour,
                        }
                    )
        except Exception as e:
            log.exception("stream_generator_failed")
            yield await _sse_event(
                {"error": str(e)[:200], "code": "stream_error"}
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
  )

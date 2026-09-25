"""Chat endpoints: list, create, get, delete, send, stream."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from app.db.repositories import (
    ChatRepository,
    MemoryRepository,
    StatsRepository,
)
from app.db.repositories.chat import MessageRepository
from app.db.repositories.stats import RateLimitRepository
from app.dependencies import (
    ChatRepoDep,
    MemoryRepoDep,
    SessionDep,
    StatsRepoDep,
    UserIDDep,
)
from app.exceptions import (
    KhallaqiError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
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

log = get_logger(__name__)

router = APIRouter(tags=["chat"])


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
# Send message — streaming (SSE) — opens its OWN session
# ═══════════════════════════════════════════════════════════════════
@router.post(
    "/chat/stream",
    summary="Send a message (SSE streaming)",
)
async def stream_message(payload: ChatRequest) -> StreamingResponse:
    """Send a message and stream tokens via Server-Sent Events.

    NOTE: This endpoint does NOT use FastAPI's SessionDep, because the
    dependency-managed session would be closed before the streaming
    generator finishes. Instead, we open our own session inside the
    generator and close it when streaming completes.
    """
    from app.db.engine import get_session_factory

    async def _sse(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    # ─── Preflight validation (no DB) ───
    if not payload.message.strip():
        async def err_gen():
            yield await _sse({"error": "الرسالة فارغة", "code": "validation_error"})
        return StreamingResponse(
            err_gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ─── Stream generator (owns its session) ───
    async def event_stream() -> AsyncIterator[str]:
        session = None
        try:
            factory = get_session_factory()
            session = factory()

            # Build repositories bound to THIS session
            chat_repo = ChatRepository(session=session)
            memory_repo = MemoryRepository(session=session)
            stats_repo = StatsRepository(session=session)
            message_repo = MessageRepository(session=session)

            # ─── Rate limit ───
            try:
                rl = RateLimitService(
                    redis=get_redis(),
                    db_repo=RateLimitRepository(session=session),
                )
                rem_min, rem_hour = await rl.check(payload.user_id)
            except Exception as e:
                log.warning("stream.rate_limit_failed", error=str(e)[:150])
                rem_min, rem_hour = 0, 0

            # ─── Ownership ───
            if not await chat_repo.belongs_to_user(payload.chat_id, payload.user_id):
                yield await _sse({"error": "غير مصرح", "code": "unauthorized"})
                return

            # ─── First-message title ───
            try:
                count = await message_repo.count_for_chat(payload.chat_id)
                if count == 0:
                    title = payload.message.strip().replace("\n", " ")[:60]
                    if len(payload.message) > 60:
                        title += "..."
                    await chat_repo.rename(payload.chat_id, payload.user_id, title)
                    await session.commit()
            except Exception:
                log.exception("stream.title_failed")
                await session.rollback()

            # ─── Persist user message ───
            await message_repo.add(
                payload.chat_id, "user", payload.message, message_type="text"
            )
            await session.commit()

            # ─── Prepare services ───
            ai_router = get_ai_router()
            memory_service = MemoryService(memory_repo)
            svc = ChatService(
                router=ai_router,
                chat_repo=chat_repo,
                message_repo=message_repo,
                memory_service=memory_service,
                stats_repo=stats_repo,
            )

            # ─── Stream tokens ───
            async for kind, value in svc.stream_text(
                payload.chat_id,
                payload.user_id,
                payload.message,
            ):
                if kind == "provider":
                    yield await _sse({"provider": value})
                elif kind == "chunk":
                    yield await _sse({"chunk": value})
                elif kind == "done":
                    yield await _sse(
                        {
                            "done": True,
                            "length": value,
                            "remaining_min": rem_min,
                            "remaining_hour": rem_hour,
                        }
                    )

        except KhallaqiError as e:
            log.warning("stream.khallaqi_error", code=e.error_code, msg=e.message)
            yield await _sse({"error": e.message, "code": e.error_code})
        except Exception as e:
            log.exception("stream.unexpected_error")
            yield await _sse(
                {"error": f"خطأ غير متوقع: {str(e)[:150]}", "code": "stream_error"}
            )
        finally:
            if session is not None:
                try:
                    await session.close()
                except Exception:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
"""Dependency injection providers for FastAPI."""
from __future__ import annotations

from typing import Annotated, AsyncGenerator, Optional

from fastapi import Depends, Header, HTTPException
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_client import RedisClient, get_redis, is_redis_available
from app.config import Settings, get_settings
from app.db.engine import get_session
from app.db.repositories import (
    ChatRepository,
    MemoryRepository,
    RateLimitRepository,
    StatsRepository,
)
from app.exceptions import ValidationError
from app.logging_config import get_logger

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Settings
# ═══════════════════════════════════════════════════════════════════
def settings_dep() -> Settings:
    """Return the app settings singleton."""
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]


# ═══════════════════════════════════════════════════════════════════
# Database session
# ═══════════════════════════════════════════════════════════════════
async def session_dep() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession for the duration of a request."""
    async for session in get_session():
        yield session


SessionDep = Annotated[AsyncSession, Depends(session_dep)]


# ═══════════════════════════════════════════════════════════════════
# Repositories
# ═══════════════════════════════════════════════════════════════════
def chat_repo_dep(session: SessionDep) -> ChatRepository:
    """Chat repository bound to the current session."""
    return ChatRepository(session=session)


def memory_repo_dep(session: SessionDep) -> MemoryRepository:
    """Memory repository bound to the current session."""
    return MemoryRepository(session=session)


def stats_repo_dep(session: SessionDep) -> StatsRepository:
    """Stats repository bound to the current session."""
    return StatsRepository(session=session)


def rate_limit_repo_dep(session: SessionDep) -> RateLimitRepository:
    """Rate limit repository (DB fallback)."""
    return RateLimitRepository(session=session)


ChatRepoDep = Annotated[ChatRepository, Depends(chat_repo_dep)]
MemoryRepoDep = Annotated[MemoryRepository, Depends(memory_repo_dep)]
StatsRepoDep = Annotated[StatsRepository, Depends(stats_repo_dep)]
RateLimitRepoDep = Annotated[RateLimitRepository, Depends(rate_limit_repo_dep)]


# ═══════════════════════════════════════════════════════════════════
# Redis
# ═══════════════════════════════════════════════════════════════════
def redis_dep() -> Optional[RedisClient]:
    """Return the Redis client, or None if unavailable."""
    return get_redis()


RedisDep = Annotated[Optional[RedisClient], Depends(redis_dep)]


# ═══════════════════════════════════════════════════════════════════
# Auth / User ID extraction
# ═══════════════════════════════════════════════════════════════════
async def user_id_header_dep(
    x_user_id: Annotated[Optional[str], Header(alias="X-User-ID")] = None,
) -> Optional[str]:
    """Extract user-id from the X-User-ID header, if present."""
    if x_user_id:
        return x_user_id.strip()[:64]
    return None


async def require_user_id(
    x_user_id: Annotated[Optional[str], Header(alias="X-User-ID")] = None,
) -> str:
    """Require X-User-ID header. Raise 400 if missing."""
    if not x_user_id or not x_user_id.strip():
        raise ValidationError("الترويسة X-User-ID مطلوبة")
    return x_user_id.strip()[:64]


UserIDDep = Annotated[str, Depends(require_user_id)]
OptionalUserIDDep = Annotated[Optional[str], Depends(user_id_header_dep)]


# ═══════════════════════════════════════════════════════════════════
# Request ID
# ═══════════════════════════════════════════════════════════════════
def request_id_dep(request: Request) -> str:
    """Return the current request-id (set by middleware)."""
    return getattr(request.state, "request_id", "")


RequestIDDep = Annotated[str, Depends(request_id_dep)]


# ═══════════════════════════════════════════════════════════════════
# Aggregate dependency — common per-request bundle
# ═══════════════════════════════════════════════════════════════════
class RequestContext:
    """Bundle of common per-request dependencies."""

    def __init__(
        self,
        settings: Settings,
        session: AsyncSession,
        redis: Optional[RedisClient],
        request_id: str,
        chat_repo: ChatRepository,
        memory_repo: MemoryRepository,
        stats_repo: StatsRepository,
    ) -> None:
        self.settings = settings
        self.session = session
        self.redis = redis
        self.request_id = request_id
        self.chat_repo = chat_repo
        self.memory_repo = memory_repo
        self.stats_repo = stats_repo


async def context_dep(
    settings: SettingsDep,
    session: SessionDep,
    redis: RedisDep,
    request_id: RequestIDDep,
) -> RequestContext:
    """Build a single RequestContext bundle for handlers that need many deps."""
    return RequestContext(
        settings=settings,
        session=session,
        redis=redis,
        request_id=request_id,
        chat_repo=ChatRepository(session=session),
        memory_repo=MemoryRepository(session=session),
        stats_repo=StatsRepository(session=session),
    )


ContextDep = Annotated[RequestContext, Depends(context_dep)]

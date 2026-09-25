"""Async SQLAlchemy engine — production-grade configuration."""
from __future__ import annotations

from typing import Any, AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.exceptions import DatabaseError
from app.logging_config import get_logger

log = get_logger(__name__)

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _build_engine_kwargs() -> dict[str, Any]:
    """Build engine kwargs based on the database dialect."""
    url = settings.database_url
    base: dict[str, Any] = {
        "echo": settings.log_level == "DEBUG",
        "future": True,
        "pool_pre_ping": True,
    }

    if url.startswith("postgresql"):
        base.update(
            {
                "pool_size": settings.db_pool_size,
                "max_overflow": settings.db_max_overflow,
                "pool_timeout": settings.db_pool_timeout,
                "pool_recycle": 1800,
            }
        )
    elif url.startswith("sqlite"):
        base.update({"pool_pre_ping": False})

    return base


async def init_engine() -> None:
    """Initialize the global async engine + session factory + tables."""
    global _engine, _session_factory

    if _engine is not None:
        return

    try:
        _engine = create_async_engine(settings.database_url, **_build_engine_kwargs())
        _session_factory = async_sessionmaker(
            bind=_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
        log.info("db.engine.initialized", url_scheme=settings.database_url.split(":")[0])

        from app.models.db_models import Base

        try:
            async with _engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            log.info("db.tables.ready")
        except Exception as e:
            if "already exists" in str(e).lower():
                log.info("db.tables.already_exist")
            else:
                log.exception("db.tables.failed")
                raise
    except Exception as e:
        log.exception("db.engine.init_failed")
        raise DatabaseError(f"Failed to initialize engine: {e}") from e


async def close_engine() -> None:
    """Dispose the engine and release all connections."""
    global _engine, _session_factory

    if _engine is not None:
        try:
            await _engine.dispose()
            log.info("db.engine.closed")
        except Exception:
            log.exception("db.engine.close_failed")
        finally:
            _engine = None
            _session_factory = None


def get_engine() -> AsyncEngine:
    """Return the global engine. Raises if not initialized."""
    if _engine is None:
        raise DatabaseError("Engine not initialized. Call init_engine() first.")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the global session factory."""
    if _session_factory is None:
        raise DatabaseError("Session factory not initialized.")
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an AsyncSession with auto-commit/rollback."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
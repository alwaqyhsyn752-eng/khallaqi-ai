"""Shared pytest fixtures."""
from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Force test-mode env vars BEFORE importing the app
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("GEMINI_API_KEY", "")
os.environ.setdefault("GROQ_API_KEY", "")
os.environ.setdefault("OPENROUTER_API_KEY", "")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890")

from app.config import get_settings  # noqa: E402
from app.models.db_models import Base  # noqa: E402


# ═══════════════════════════════════════════════════════════════════
# Event loop
# ═══════════════════════════════════════════════════════════════════
@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Session-scoped event loop."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ═══════════════════════════════════════════════════════════════════
# Database
# ═══════════════════════════════════════════════════════════════════
@pytest_asyncio.fixture
async def test_engine():
    """In-memory SQLite async engine for tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=None,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncIterator[AsyncSession]:
    """Provide a transactional session per test."""
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ═══════════════════════════════════════════════════════════════════
# Settings
# ═══════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    """Clear lru_cache between tests so env changes apply."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ═══════════════════════════════════════════════════════════════════
# HTTP client
# ═══════════════════════════════════════════════════════════════════
@pytest_asyncio.fixture
async def client(test_engine, monkeypatch) -> AsyncIterator[AsyncClient]:
    """FastAPI test client with overridden DB dependency."""
    # Patch the engine used by the app
    import app.db.engine as engine_mod

    engine_mod._engine = test_engine
    engine_mod._session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    # Import app AFTER patching to avoid real startup
    from app.main import create_app

    application = create_app()

    transport = ASGITransport(app=application)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-User-ID": "test-user"}
    ) as ac:
        yield ac


# ═══════════════════════════════════════════════════════════════════
# Sample data
# ═══════════════════════════════════════════════════════════════════
@pytest.fixture
def sample_user_id() -> str:
    """A stable test user ID."""
    return "test-user-001"


@pytest.fixture
def sample_chat_payload(sample_user_id: str) -> dict:
    """A valid chat creation payload."""
    return {"user_id": sample_user_id}

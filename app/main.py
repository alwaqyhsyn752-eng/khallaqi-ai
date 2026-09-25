"""FastAPI application factory + lifespan + middleware wiring."""
from __future__ import annotations

import contextlib
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import v1_router
from app.cache.redis_client import close_redis, init_redis
from app.config import get_settings
from app.db.engine import close_engine, init_engine
from app.exceptions import KhallaqiError
from app.logging_config import configure_logging, get_logger
from app.middleware import (
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    TimingMiddleware,
    register_exception_handler,
)
from app.models.db_models import Base
from app.services.ai.router import get_ai_router

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Lifespan — startup / shutdown
# ═══════════════════════════════════════════════════════════════════
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup/shutdown: DB, Redis, AI clients, tables."""
    s = get_settings()
    log.info(
        "app.startup",
        version=s.version,
        env=s.environment,
        gemini=bool(s.gemini_api_key),
        groq=bool(s.groq_api_key),
        openrouter=bool(s.openrouter_api_key),
        azure=bool(s.azure_speech_key),
    )

    # ─── Startup ───
    await init_engine()

    # Always ensure tables exist (idempotent, safe for all environments).
    try:
        from app.db.engine import get_engine
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log.info("db.tables.ready")
    except Exception:
        log.exception("db.tables.failed")

    await init_redis()
    get_ai_router()  # Warm up providers

    yield

    # ─── Shutdown ───
    log.info("app.shutdown.begin")
    with contextlib.suppress(Exception):
        await get_ai_router().close()
    with contextlib.suppress(Exception):
        await close_redis()
    with contextlib.suppress(Exception):
        await close_engine()
    log.info("app.shutdown.done")


# ═══════════════════════════════════════════════════════════════════
# App factory
# ═══════════════════════════════════════════════════════════════════
def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    configure_logging()
    s = get_settings()

    app = FastAPI(
        title=s.ai_name,
        version=s.version,
        description=f"مساعد برمجي وأمني — {s.developer_name}",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ─── CORS ───
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Response-Time"],
    )

    # ─── GZip ───
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # ─── Custom middlewares (order matters: outermost first) ───
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(TimingMiddleware)
    app.add_middleware(RequestIDMiddleware)

    # ─── Exception handlers ───
    register_exception_handler(app)

    # ─── Static files (for CSS/JS assets if any) ───
    import os
    if os.path.isdir("app/static"):
        app.mount("/static", StaticFiles(directory="app/static"), name="static")

    # ─── Routers ───
    app.include_router(v1_router)

    # ─── Legacy (unversioned) aliases to keep existing frontend working ───
    _register_legacy_routes(app)

    # ─── Root health at `/` handled by system_ep; add favicon ───
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return JSONResponse(content={}, status_code=204)

    return app


# ═══════════════════════════════════════════════════════════════════
# Legacy aliases — map old paths to new v1 routes
# ═══════════════════════════════════════════════════════════════════
def _register_legacy_routes(app: FastAPI) -> None:
    """Re-expose v1 routes at the old unversioned paths for compat."""
    from app.api.v1.endpoints import (
        chat as chat_ep,
        export as export_ep,
        memory as memory_ep,
        search as search_ep,
        stats as stats_ep,
        system as system_ep,
        tts as tts_ep,
        video as video_ep,
    )

    app.include_router(system_ep.router, include_in_schema=False)
    app.include_router(chat_ep.router, include_in_schema=False)
    app.include_router(memory_ep.router, include_in_schema=False)
    app.include_router(stats_ep.router, include_in_schema=False)
    app.include_router(search_ep.router, include_in_schema=False)
    app.include_router(export_ep.router, include_in_schema=False)
    app.include_router(tts_ep.router, include_in_schema=False)
    app.include_router(video_ep.router, include_in_schema=False)


# ═══════════════════════════════════════════════════════════════════
# Root app for gunicorn (gunicorn app.main:app)
# ═══════════════════════════════════════════════════════════════════
app = create_app()

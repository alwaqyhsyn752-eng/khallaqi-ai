"""FastAPI application factory + lifespan + middleware wiring."""
from __future__ import annotations

import contextlib
import os
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.v1 import v1_router
from app.cache.redis_client import close_redis, init_redis
from app.config import get_settings
from app.db.engine import close_engine, init_engine
from app.logging_config import configure_logging, get_logger
from app.middleware import (
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    TimingMiddleware,
    register_exception_handler,
)
from app.services.ai.router import get_ai_router

log = get_logger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup/shutdown."""
    s = get_settings()
    log.info(
        "app.startup",
        version=s.version,
        env=s.environment,
        gemini=bool(s.gemini_api_key),
        groq=bool(s.groq_api_key),
    )

    # ─── Startup ───
    await init_engine()
    await init_redis()
    get_ai_router()

    # ─── Bootstrap default admin account ───
    try:
        from app.db.engine import get_session_factory
        from app.services.admin_service import AdminService

        factory = get_session_factory()
        async with factory() as _s:
            try:
                await AdminService(session=_s).bootstrap_default_admin()
                log.info("admin.bootstrap_done")
            finally:
                await _s.close()
    except Exception:
        log.exception("admin.bootstrap_failed")

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

    # ─── Middleware ───
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(TimingMiddleware)
    app.add_middleware(RequestIDMiddleware)

    # ─── Exception handlers ───
    register_exception_handler(app)

    # ─── Static files ───
    if os.path.isdir("app/static"):
        app.mount("/static", StaticFiles(directory="app/static"), name="static")

    # ─── Templates ───
    templates = Jinja2Templates(directory="app/templates")

    # ─── Admin dashboard page ───
    @app.get("/admin", include_in_schema=False)
    async def admin_dashboard(request: Request):
        return templates.TemplateResponse(
            "admin.html",
            {
                "request": request,
                "ai_name": s.ai_name,
                "developer_name": s.developer_name,
            },
        )

    # ─── Main routers ───
    app.include_router(v1_router)

    # ─── Legacy (unversioned) aliases ───
    from app.api.v1.endpoints import (
        admin as admin_ep,
        chat as chat_ep,
        export as export_ep,
        memory as memory_ep,
        search as search_ep,
        stats as stats_ep,
        system as system_ep,
        tts as tts_ep,
        video as video_ep,
    )

    # Admin router also at unversioned path (so /api/admin/... and /admin/... work)
    app.include_router(admin_ep.router, prefix="/api", include_in_schema=False)

    # Legacy UI routes
    app.include_router(system_ep.router, include_in_schema=False)
    app.include_router(chat_ep.router, include_in_schema=False)
    app.include_router(memory_ep.router, include_in_schema=False)
    app.include_router(stats_ep.router, include_in_schema=False)
    app.include_router(search_ep.router, include_in_schema=False)
    app.include_router(export_ep.router, include_in_schema=False)
    app.include_router(tts_ep.router, include_in_schema=False)
    app.include_router(video_ep.router, include_in_schema=False)

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return JSONResponse(content={}, status_code=204)

    return app


app = create_app()

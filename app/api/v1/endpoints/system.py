"""System endpoints: root page + health + status."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app.cache.redis_client import get_redis
from app.config import get_settings
from app.dependencies import SessionDep
from app.logging_config import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["system"])

_templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request) -> HTMLResponse:
    """Serve the single-page UI."""
    s = get_settings()
    return _templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "ai_name": s.ai_name,
            "developer_name": s.developer_name,
            "version": s.version,
        },
    )


@router.get("/health", summary="Liveness probe")
async def health() -> dict:
    """Fast liveness probe — returns 200 if the process is alive."""
    return {"status": "ok"}


@router.get("/status", summary="Full system status")
async def status(session: SessionDep) -> JSONResponse:
    """Return detailed system status: DB, Redis, providers, features."""
    s = get_settings()

    # ─── DB check ───
    db_ok = False
    db_error = ""
    try:
        result = await session.execute(text("SELECT 1"))
        result.scalar_one()
        db_ok = True
    except Exception as e:
        db_error = str(e)[:200]

    # ─── Redis check ───
    redis = get_redis()
    redis_ok = False
    if redis is not None:
        try:
            redis_ok = await redis.ping()
        except Exception:
            redis_ok = False

    return JSONResponse(
        {
            "ai_name": s.ai_name,
            "developer_name": s.developer_name,
            "version": s.version,
            "environment": s.environment,
            "database": (
                "postgresql"
                if s.database_url.startswith("postgres")
                else "sqlite"
            ),
            "db_ok": db_ok,
            "db_error": db_error,
            "redis_ok": redis_ok,
            "providers": {
                "gemini": bool(s.gemini_api_key),
                "groq": bool(s.groq_api_key),
                "openrouter": bool(s.openrouter_api_key),
            },
            "features": {
                "text": s.has_any_ai_provider,
                "streaming": True,
                "vision": bool(s.gemini_api_key),
                "video": bool(s.gemini_api_key),
                "tts_local": True,
                "tts_azure": bool(s.azure_speech_key),
                "memory": True,
                "search": True,
                "export": True,
                "rate_limit": True,
                "stats": True,
            },
            "rate_limits": {
                "per_minute": s.rate_limit_per_min,
                "per_hour": s.rate_limit_per_hour,
            },
        }
    )

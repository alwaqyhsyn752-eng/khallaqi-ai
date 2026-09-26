"""Aggregate all v1 endpoints into a single router."""
from __future__ import annotations

from fastapi import APIRouter

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

v1_router = APIRouter(prefix="/api/v1")

v1_router.include_router(system_ep.router)
v1_router.include_router(chat_ep.router)
v1_router.include_router(memory_ep.router)
v1_router.include_router(stats_ep.router)
v1_router.include_router(search_ep.router)
v1_router.include_router(export_ep.router)
v1_router.include_router(tts_ep.router)
v1_router.include_router(video_ep.router)
v1_router.include_router(admin_ep.router)

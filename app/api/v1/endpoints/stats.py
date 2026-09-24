"""Stats endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import StatsRepoDep, UserIDDep
from app.logging_config import get_logger
from app.models.schemas import StatsOut

log = get_logger(__name__)

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=StatsOut, summary="User statistics")
async def get_user_stats(
    user_id: UserIDDep,
    stats_repo: StatsRepoDep,
) -> StatsOut:
    """Return aggregated usage statistics for the user."""
    summary = await stats_repo.summary(user_id)
    return StatsOut(
        chats_count=summary.get("chats_count", 0),
        messages_count=summary.get("messages_count", 0),
        assistant_count=summary.get("assistant_count", 0),
        memory_count=summary.get("memory_count", 0),
        by_provider=summary.get("by_provider", {}),
    )

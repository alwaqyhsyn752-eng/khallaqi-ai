"""Search endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.db.repositories import ChatRepository
from app.dependencies import ChatRepoDep, UserIDDep
from app.logging_config import get_logger
from app.models.schemas import SearchOut, SearchResultOut

log = get_logger(__name__)

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchOut, summary="Search chats")
async def search(
    user_id: UserIDDep,
    chat_repo: ChatRepoDep,
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(default=30, ge=1, le=100),
) -> SearchOut:
    """Full-text-ish search across the user's messages."""
    results = await chat_repo.search(user_id, q, limit=limit)
    return SearchOut(
        results=[SearchResultOut(**r) for r in results]
    )

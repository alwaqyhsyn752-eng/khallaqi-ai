"""Memory endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.db.repositories import MemoryRepository
from app.dependencies import MemoryRepoDep, UserIDDep
from app.logging_config import get_logger
from app.models.schemas import MemoryListOut, MemoryOut, MemorySetRequest

log = get_logger(__name__)

router = APIRouter(tags=["memory"])


@router.get("/memory", response_model=MemoryListOut, summary="List memory entries")
async def list_memory(
    user_id: UserIDDep,
    memory_repo: MemoryRepoDep,
) -> MemoryListOut:
    """Return all memory entries for the current user."""
    entries = await memory_repo.list_for_user(user_id)
    return MemoryListOut(
        memory=[
            MemoryOut(
                key=e.key,
                value=e.value,
                category=e.category,
                confidence=e.confidence,
            )
            for e in entries
        ]
    )


@router.post(
    "/memory",
    status_code=status.HTTP_201_CREATED,
    summary="Set a memory entry",
)
async def set_memory(
    payload: MemorySetRequest,
    memory_repo: MemoryRepoDep,
) -> dict:
    """Upsert a memory entry."""
    entry = await memory_repo.set_value(
        payload.user_id,
        payload.key,
        payload.value,
        payload.category,
    )
    return {
        "status": "ok",
        "key": entry.key,
        "value": entry.value,
        "category": entry.category,
    }


@router.delete(
    "/memory",
    status_code=status.HTTP_200_OK,
    summary="Delete memory entry or all",
)
async def delete_memory(
    user_id: UserIDDep,
    memory_repo: MemoryRepoDep,
    key: str | None = Query(default=None, max_length=100),
) -> dict:
    """Delete one key (if provided) or every entry for the user."""
    if key:
        ok = await memory_repo.delete_value(user_id, key)
        if not ok:
            return {"status": "not_found", "key": key}
        return {"status": "ok", "deleted": 1}
    count = await memory_repo.delete_all_for_user(user_id)
    return {"status": "ok", "deleted": count}

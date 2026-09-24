"""Video generation endpoints."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.db.repositories import ChatRepository
from app.db.repositories.chat import MessageRepository
from app.dependencies import ChatRepoDep, SessionDep
from app.logging_config import get_logger
from app.models.schemas import GenerateVideoRequest, VideoStatusRequest
from app.services.ai.router import get_ai_router
from app.services.video_service import VideoService

log = get_logger(__name__)

router = APIRouter(tags=["video"])


@router.post("/generate-video", summary="Start a video generation job")
async def generate_video(
    payload: GenerateVideoRequest,
    session: SessionDep,
    chat_repo: ChatRepoDep,
):
    """Start a Veo video generation job."""
    service = VideoService(router=get_ai_router())
    try:
        result = await service.start(payload.prompt)
    except Exception as e:
        return JSONResponse(
            {
                "error": str(e)[:200],
                "hint": "Veo يتطلب تفعيلاً خاصاً من Google.",
            }
        )

    # Persist into the chat if possible
    if payload.chat_id and payload.user_id:
        try:
            if await chat_repo.belongs_to_user(payload.chat_id, payload.user_id):
                msg_repo = MessageRepository(session=session)
                await msg_repo.add(
                    payload.chat_id,
                    "user",
                    f"🎬 طلب فيديو: {payload.prompt}",
                    message_type="text",
                )
                await msg_repo.add(
                    payload.chat_id,
                    "assistant",
                    f"جاري توليد الفيديو... {result['operation']}",
                    message_type="video_pending",
                    media_data=result["operation"],
                )
        except Exception:
            log.exception("video.persist_failed")

    return {"status": "pending", "operation": result["operation"], "model": result["model"]}


@router.post("/video-status", summary="Check video generation status")
async def video_status(payload: VideoStatusRequest):
    """Check a video generation job."""
    service = VideoService(router=get_ai_router())
    try:
        status_data = await service.status(payload.operation)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]})

    done = bool(status_data.get("done"))
    if not done:
        return {"done": False, "status": "still_processing"}

    url = service.extract_url(status_data)
    return {"done": True, "video_url": url}

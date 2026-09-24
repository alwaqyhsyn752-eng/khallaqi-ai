"""TTS endpoints — text-to-speech via Azure."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from app.config import get_settings
from app.dependencies import SessionDep
from app.logging_config import get_logger
from app.models.schemas import TTSRequest, TTSVoicesOut
from app.services.tts_service import TTSService

log = get_logger(__name__)

router = APIRouter(tags=["tts"])


@router.post("/tts", summary="Synthesize speech from text")
async def synthesize(
    payload: TTSRequest,
    session: SessionDep,
):
    """Return MP3 audio for the provided text.

    If Azure is not configured, returns 200 with a fallback hint so the
    frontend can use Web Speech API.
    """
    s = get_settings()
    if not s.azure_speech_key:
        return JSONResponse(
            {
                "error": "AZURE_SPEECH_KEY غير معيّن",
                "fallback": "web_speech",
                "hint": "استخدم window.speechSynthesis في المتصفح",
            }
        )

    service = TTSService()
    try:
        audio = await service.synthesize(payload.text, payload.voice)
        return Response(
            content=audio,
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "no-cache",
                "Content-Length": str(len(audio)),
            },
        )
    except Exception as e:
        log.warning("tts.synthesize_failed", error=str(e)[:150])
        return JSONResponse(
            {"error": str(e)[:150], "fallback": "web_speech"}
        )
    finally:
        await service.close()


@router.get("/tts/voices", response_model=TTSVoicesOut, summary="List TTS voices")
async def list_voices() -> TTSVoicesOut:
    """Return the supported voices."""
    service = TTSService()
    try:
        return TTSVoicesOut(**service.list_voices())
    finally:
        await service.close()

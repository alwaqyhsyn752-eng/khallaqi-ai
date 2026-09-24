"""Video generation service — wraps the AI router's video capability."""
from __future__ import annotations

from typing import Optional

from app.exceptions import VideoError
from app.logging_config import get_logger
from app.services.ai.router import AIRouter

log = get_logger(__name__)


class VideoService:
    """Handles video generation lifecycle."""

    def __init__(self, router: AIRouter) -> None:
        self._router = router

    async def start(self, prompt: str) -> dict:
        """Start a video generation job.

        Returns:
            {"operation": "...", "model": "..."}
        Raises:
            VideoError: if all providers fail.
        """
        try:
            return await self._router.video(prompt)
        except Exception as e:
            log.warning("video.start_failed", error=str(e)[:120])
            raise VideoError(f"فشل توليد الفيديو: {e}") from e

    async def status(self, operation: str) -> dict:
        """Check a video generation job.

        Returns the provider's raw status payload:
        {"done": bool, "response": {...}} or {"done": False}.
        """
        try:
            return await self._router.video_status(operation)
        except Exception as e:
            raise VideoError(f"فشل الاستعلام عن الفيديو: {e}") from e

    @staticmethod
    def extract_url(status: dict) -> Optional[str]:
        """Extract the video URL from the raw status payload, if ready."""
        if not status.get("done"):
            return None
        response = status.get("response", {}) or {}
        samples = (
            response.get("generateVideoResponse", {}).get("generatedSamples", [])
            or []
        )
        if not samples:
            return None
        return samples[0].get("video", {}).get("uri")

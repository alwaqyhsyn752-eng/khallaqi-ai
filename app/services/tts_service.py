"""Text-to-Speech service — Azure Cognitive Services."""
from __future__ import annotations

from typing import Optional

import httpx

from app.config import get_settings
from app.exceptions import TTSError
from app.logging_config import get_logger

log = get_logger(__name__)

_SSML_TEMPLATE = """<speak version='1.0' xml:lang='ar-SA'>
    <voice xml:lang='ar-SA' name='{voice}'>
        <prosody rate='0.95' pitch='0.95'>{text}</prosody>
    </voice>
</speak>"""


class TTSService:
    """Async Azure Text-to-Speech service."""

    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        s = get_settings()
        self._key = s.azure_speech_key
        self._region = s.azure_speech_region
        self._default_voice = s.azure_voice_ar
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=20.0, pool=10.0),
        )
        self._owns_client = client is None

    @property
    def available(self) -> bool:
        """True when the Azure key is configured."""
        return bool(self._key)

    async def close(self) -> None:
        """Close HTTP client if we created it."""
        if self._owns_client:
            await self._client.aclose()

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
    ) -> bytes:
        """Convert text to MP3 audio. Raises TTSError on failure."""
        if not self._key:
            raise TTSError("AZURE_SPEECH_KEY غير معيّن")

        voice = voice or self._default_voice
        clean = (
            text.replace("```", " ")
            .replace("`", " ")
            .replace("#", "")
            .replace("*", "")
            .replace("_", " ")
        )[:2000]

        ssml = _SSML_TEMPLATE.format(voice=voice, text=clean)
        url = f"https://{self._region}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            "Ocp-Apim-Subscription-Key": self._key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
            "User-Agent": "KhallaqiAI/16.0",
        }

        try:
            r = await self._client.post(url, headers=headers, content=ssml.encode("utf-8"))
            if r.status_code != 200:
                raise TTSError(
                    f"Azure TTS failed ({r.status_code}): {r.text[:200]}"
                )
            return r.content
        except httpx.HTTPError as e:
            raise TTSError(f"Azure TTS error: {e}") from e

    def list_voices(self) -> dict:
        """Return the supported voices for the UI."""
        return {
            "azure_enabled": self.available,
            "current": self._default_voice,
            "saudi_male_voices": ["ar-SA-HamedNeural"],
            "other_arabic": [
                "ar-EG-ShakirNeural",
                "ar-AE-HamdanNeural",
                "ar-JO-TaimNeural",
                "ar-KW-FahedNeural",
                "ar-QA-RashidNeural",
            ],
        }

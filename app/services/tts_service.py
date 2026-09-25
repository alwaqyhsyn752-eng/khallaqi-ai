"""Text-to-Speech service — Azure Cognitive Services (Saudi young voice)."""
from __future__ import annotations

from typing import Optional

import httpx

from app.config import get_settings
from app.exceptions import TTSError
from app.logging_config import get_logger

log = get_logger(__name__)

# SSML with Saudi young male voice:
#  - voice: ar-SA-HamedNeural (only Saudi male voice available on Azure)
#  - style: "chat" (friendly, casual — makes him sound younger)
#  - pitch: +8% (higher pitch = younger voice)
#  - rate:  +5% (slightly faster = energetic young speaker)
_SSML_TEMPLATE = """<speak version='1.0' xml:lang='ar-SA'
    xmlns:mstts='https://www.w3.org/2001/mstts'>
    <voice xml:lang='ar-SA' name='{voice}'>
        <mstts:express-as style='chat' styledegree='1.2'>
            <prosody rate='+5%' pitch='+8%'>{text}</prosody>
        </mstts:express-as>
    </voice>
</speak>"""

# Fallback SSML (in case Azure rejects the "chat" style for Saudi voice)
_SSML_FALLBACK = """<speak version='1.0' xml:lang='ar-SA'>
    <voice xml:lang='ar-SA' name='{voice}'>
        <prosody rate='+5%' pitch='+8%'>{text}</prosody>
    </voice>
</speak>"""


class TTSService:
    """Async Azure Text-to-Speech service with Saudi young male voice."""

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

    def _build_ssml(self, voice: str, text: str) -> str:
        """Build SSML with Saudi young voice settings."""
        return _SSML_TEMPLATE.format(voice=voice, text=text)

    def _build_fallback_ssml(self, voice: str, text: str) -> str:
        """Build simplified SSML without style (if primary fails)."""
        return _SSML_FALLBACK.format(voice=voice, text=text)

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
    ) -> bytes:
        """Convert text to MP3 audio with Saudi young male voice.

        Raises:
            TTSError: on any failure.
        """
        if not self._key:
            raise TTSError("AZURE_SPEECH_KEY غير معيّن")

        voice = voice or self._default_voice

        # Clean text: strip markdown and code blocks
        clean = (
            text.replace("```", " ")
            .replace("`", " ")
            .replace("#", "")
            .replace("*", "")
            .replace("_", " ")
        )[:2000]

        url = f"https://{self._region}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            "Ocp-Apim-Subscription-Key": self._key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
            "User-Agent": "KhallaqiAI/16.0",
        }

        # Try with style first
        try:
            ssml = self._build_ssml(voice, clean)
            r = await self._client.post(
                url, headers=headers, content=ssml.encode("utf-8")
            )
            if r.status_code == 200:
                log.info("tts.synthesized", voice=voice, styled=True, len=len(r.content))
                return r.content

            # If style not supported for this voice → fallback
            if r.status_code == 400:
                log.warning("tts.style_rejected", voice=voice, trying_fallback=True)
                ssml = self._build_fallback_ssml(voice, clean)
                r2 = await self._client.post(
                    url, headers=headers, content=ssml.encode("utf-8")
                )
                if r2.status_code == 200:
                    log.info("tts.synthesized", voice=voice, styled=False, len=len(r2.content))
                    return r2.content
                raise TTSError(
                    f"Azure TTS failed ({r2.status_code}): {r2.text[:200]}"
                )

            raise TTSError(
                f"Azure TTS failed ({r.status_code}): {r.text[:200]}"
            )
        except httpx.HTTPError as e:
            raise TTSError(f"Azure TTS error: {e}") from e

    def list_voices(self) -> dict:
        """Return the supported voices for the UI."""
        return {
            "azure_enabled": self.available,
            "current": self._default_voice,
            "current_style": "شاب سعودي (chat + pitch +8% + rate +5%)",
            "saudi_male_voices": ["ar-SA-HamedNeural"],
            "other_arabic": [
                "ar-EG-ShakirNeural",
                "ar-AE-HamdanNeural",
                "ar-JO-TaimNeural",
                "ar-KW-FahedNeural",
                "ar-QA-RashidNeural",
            ],
        }

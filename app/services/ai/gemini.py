"""Google Gemini provider — text, streaming, vision, video."""
from __future__ import annotations

import json
import time
from typing import AsyncIterator, List, Optional

import httpx

from app.config import get_settings
from app.exceptions import AIProviderError
from app.logging_config import get_logger
from app.services.ai.base import (
    AIProvider,
    AIResponse,
    ChatMessage,
    ProviderCapability,
)

log = get_logger(__name__)

TEXT_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
]
VISION_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-flash-latest",
]
VIDEO_MODELS = [
    "veo-3.1-generate-preview",
    "veo-3.1-fast-generate-preview",
]

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(AIProvider):
    """Async Gemini provider using httpx.AsyncClient with connection pooling."""

    name = "gemini"
    capabilities = frozenset({
        ProviderCapability.TEXT,
        ProviderCapability.STREAMING,
        ProviderCapability.VISION,
        ProviderCapability.VIDEO,
    })

    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        s = get_settings()
        self._api_key = s.gemini_api_key
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
        self._owns_client = client is None

    @property
    def available(self) -> bool:
        """True when the API key is set."""
        return bool(self._api_key)

    async def close(self) -> None:
        """Close the HTTP client if we created it."""
        if self._owns_client:
            await self._client.aclose()

    # ─── Text ───
    async def generate(
        self,
        history: List[ChatMessage],
        system_prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 4096,
    ) -> AIResponse:
        """Non-streaming text generation across fallback models."""
        if not self._api_key:
            raise AIProviderError("GEMINI_API_KEY غير معيّن")

        contents = [
            {
                "role": "user" if m.role == "user" else "model",
                "parts": [{"text": m.content}],
            }
            for m in history
            if m.role in ("user", "assistant")
        ]
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        last_error: Optional[str] = None
        for model in TEXT_MODELS:
            url = f"{_BASE_URL}/{model}:generateContent?key={self._api_key}"
            start = time.perf_counter()
            try:
                r = await self._client.post(url, json=payload)
                if r.status_code != 200:
                    last_error = f"{model} → {r.status_code}"
                    log.warning("gemini.text.http_error", model=model, status=r.status_code)
                    continue
                data = r.json()
                parts = data["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts).strip()
                latency = int((time.perf_counter() - start) * 1000)
                return AIResponse(
                    text=text,
                    provider="gemini",
                    model=model,
                    latency_ms=latency,
                )
            except (httpx.TimeoutException, httpx.HTTPError) as e:
                last_error = f"{model} → {type(e).__name__}"
                log.warning("gemini.text.exception", model=model, error=str(e)[:120])
                continue

        raise AIProviderError(f"Gemini text failed: {last_error}")

    # ─── Streaming ───
    async def stream(
        self,
        history: List[ChatMessage],
        system_prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream tokens from Gemini."""
        if not self._api_key:
            raise AIProviderError("GEMINI_API_KEY غير معيّن")

        contents = [
            {
                "role": "user" if m.role == "user" else "model",
                "parts": [{"text": m.content}],
            }
            for m in history
            if m.role in ("user", "assistant")
        ]
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        last_error: Optional[str] = None
        for model in TEXT_MODELS:
            url = f"{_BASE_URL}/{model}:streamGenerateContent?alt=sse&key={self._api_key}"
            try:
                async with self._client.stream("POST", url, json=payload) as r:
                    if r.status_code != 200:
                        last_error = f"{model} → {r.status_code}"
                        continue
                    async for line in r.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            d = json.loads(data_str)
                            parts = d.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                            if parts and "text" in parts[0]:
                                yield parts[0]["text"]
                        except json.JSONDecodeError:
                            continue
                    return
            except (httpx.TimeoutException, httpx.HTTPError) as e:
                last_error = f"{model} → {type(e).__name__}"
                log.warning("gemini.stream.exception", model=model, error=str(e)[:120])
                continue

        raise AIProviderError(f"Gemini stream failed: {last_error}")

    # ─── Vision ───
    async def vision(
        self,
        prompt: str,
        image_base64: str,
        mime_type: str = "image/jpeg",
        system_prompt: str = "",
    ) -> AIResponse:
        """Analyze an image."""
        if not self._api_key:
            raise AIProviderError("GEMINI_API_KEY غير معيّن")
        if "," in image_base64:
            image_base64 = image_base64.split(",", 1)[1]

        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]} if system_prompt else None,
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt or "حلل هذه الصورة بالتفصيل."},
                        {"inline_data": {"mime_type": mime_type, "data": image_base64}},
                    ],
                }
            ],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
        }
        if payload["systemInstruction"] is None:
            del payload["systemInstruction"]

        last_error: Optional[str] = None
        for model in VISION_MODELS:
            url = f"{_BASE_URL}/{model}:generateContent?key={self._api_key}"
            start = time.perf_counter()
            try:
                r = await self._client.post(url, json=payload)
                if r.status_code != 200:
                    last_error = f"{model} → {r.status_code}"
                    continue
                data = r.json()
                parts = data["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts).strip()
                latency = int((time.perf_counter() - start) * 1000)
                return AIResponse(
                    text=text,
                    provider="gemini-vision",
                    model=model,
                    latency_ms=latency,
                )
            except (httpx.TimeoutException, httpx.HTTPError) as e:
                last_error = f"{model} → {type(e).__name__}"
                continue

        raise AIProviderError(f"Gemini vision failed: {last_error}")

    # ─── Video ───
    async def video(self, prompt: str) -> dict:
        """Start a Veo generation job."""
        if not self._api_key:
            raise AIProviderError("GEMINI_API_KEY غير معيّن")

        payload = {
            "instances": [{"prompt": prompt}],
            "parameters": {
                "aspectRatio": "16:9",
                "personGeneration": "allow_adult",
            },
        }
        last_error: Optional[str] = None
        for model in VIDEO_MODELS:
            url = f"{_BASE_URL}/{model}:predictLongRunning?key={self._api_key}"
            try:
                r = await self._client.post(url, json=payload)
                if r.status_code != 200:
                    last_error = f"{model} → {r.status_code}"
                    continue
                d = r.json()
                op = d.get("name")
                if op:
                    return {"operation": op, "model": model}
            except (httpx.TimeoutException, httpx.HTTPError) as e:
                last_error = f"{model} → {type(e).__name__}"
                continue

        raise AIProviderError(f"Gemini video failed: {last_error}")

    async def video_status(self, operation: str) -> dict:
        """Check the status of a Veo operation."""
        if not self._api_key:
            raise AIProviderError("GEMINI_API_KEY غير معيّن")
        url = f"https://generativelanguage.googleapis.com/v1beta/{operation}?key={self._api_key}"
        try:
            r = await self._client.get(url)
            if r.status_code != 200:
                raise AIProviderError(f"Video status HTTP {r.status_code}")
            return r.json()
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            raise AIProviderError(f"Video status failed: {e}") from e

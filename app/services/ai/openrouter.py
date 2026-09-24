"""OpenRouter provider — unified access to many models."""
from __future__ import annotations

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

MODELS = [
    "google/gemini-2.0-flash-exp:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
]

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(AIProvider):
    """Async OpenRouter provider (fallback tier)."""

    name = "openrouter"
    capabilities = frozenset({
        ProviderCapability.TEXT,
        ProviderCapability.STREAMING,
    })

    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        s = get_settings()
        self._api_key = s.openrouter_api_key
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
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

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://khallaqi.app",
            "X-Title": "Khallaqi AI",
        }

    async def generate(
        self,
        history: List[ChatMessage],
        system_prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 4096,
    ) -> AIResponse:
        """Non-streaming text generation."""
        if not self._api_key:
            raise AIProviderError("OPENROUTER_API_KEY غير معيّن")

        messages = [{"role": "system", "content": system_prompt}] + [
            m.as_dict() for m in history
        ]

        last_error: Optional[str] = None
        for model in MODELS:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            start = time.perf_counter()
            try:
                r = await self._client.post(_ENDPOINT, headers=self._headers(), json=payload)
                if r.status_code != 200:
                    last_error = f"{model} → {r.status_code}"
                    continue
                data = r.json()
                text = data["choices"][0]["message"]["content"].strip()
                latency = int((time.perf_counter() - start) * 1000)
                return AIResponse(
                    text=text,
                    provider="openrouter",
                    model=model,
                    latency_ms=latency,
                )
            except (httpx.TimeoutException, httpx.HTTPError) as e:
                last_error = f"{model} → {type(e).__name__}"
                continue

        raise AIProviderError(f"OpenRouter failed: {last_error}")

    async def stream(
        self,
        history: List[ChatMessage],
        system_prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream (falls back to full generation since OR's free tier may not stream)."""
        response = await self.generate(
            history,
            system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        yield response.text

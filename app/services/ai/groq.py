"""Groq provider — ultra-fast inference via OpenAI-compatible API."""
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

MODELS = [
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
]

_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider(AIProvider):
    """Async Groq provider."""

    name = "groq"
    capabilities = frozenset({
        ProviderCapability.TEXT,
        ProviderCapability.STREAMING,
    })

    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        s = get_settings()
        self._api_key = s.groq_api_key
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=90.0, write=30.0, pool=10.0),
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
            raise AIProviderError("GROQ_API_KEY غير معيّن")

        messages = [{"role": "system", "content": system_prompt}] + [
            m.as_dict() for m in history
        ]
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

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
                r = await self._client.post(_ENDPOINT, headers=headers, json=payload)
                if r.status_code == 401:
                    raise AIProviderError("Groq API key invalid")
                if r.status_code != 200:
                    last_error = f"{model} → {r.status_code}"
                    log.warning("groq.text.http_error", model=model, status=r.status_code)
                    continue
                data = r.json()
                text = data["choices"][0]["message"]["content"].strip()
                usage = data.get("usage", {})
                latency = int((time.perf_counter() - start) * 1000)
                return AIResponse(
                    text=text,
                    provider="groq",
                    model=model,
                    latency_ms=latency,
                    tokens_in=usage.get("prompt_tokens"),
                    tokens_out=usage.get("completion_tokens"),
                )
            except (httpx.TimeoutException, httpx.HTTPError) as e:
                last_error = f"{model} → {type(e).__name__}"
                continue

        raise AIProviderError(f"Groq text failed: {last_error}")

    # ─── Streaming ───
    async def stream(
        self,
        history: List[ChatMessage],
        system_prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream tokens from Groq."""
        if not self._api_key:
            raise AIProviderError("GROQ_API_KEY غير معيّن")

        messages = [{"role": "system", "content": system_prompt}] + [
            m.as_dict() for m in history
        ]
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        last_error: Optional[str] = None
        for model in MODELS:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            }
            try:
                async with self._client.stream(
                    "POST", _ENDPOINT, headers=headers, json=payload
                ) as r:
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
                            delta = d.get("choices", [{}])[0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
                        except json.JSONDecodeError:
                            continue
                    return
            except (httpx.TimeoutException, httpx.HTTPError) as e:
                last_error = f"{model} → {type(e).__name__}"
                continue

        raise AIProviderError(f"Groq stream failed: {last_error}")

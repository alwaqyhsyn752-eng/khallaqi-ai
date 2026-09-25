"""Unfil AI provider — unrestricted models, zero tracking (OpenAI-compatible)."""
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
    "unfil-uncensored-xl",
    "hermes-3-405b",
    "deepseek-v3-uncensored",
]

_ENDPOINT = "https://api.unfil.ai/v1/chat/completions"


class UnfilProvider(AIProvider):
    """Async Unfil AI provider — permissionless, privacy-first."""

    name = "unfil"
    capabilities = frozenset({
        ProviderCapability.TEXT,
        ProviderCapability.STREAMING,
    })

    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        s = get_settings()
        self._api_key = getattr(s, "unfil_api_key", "")
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
        self._owns_client = client is None

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def generate(
        self,
        history: List[ChatMessage],
        system_prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 4096,
    ) -> AIResponse:
        if not self._api_key:
            raise AIProviderError("UNFIL_API_KEY غير معيّن")

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
                r = await self._client.post(
                    _ENDPOINT, headers=self._headers(), json=payload
                )
                if r.status_code == 401:
                    raise AIProviderError("Unfil API key invalid")
                if r.status_code != 200:
                    last_error = f"{model} → {r.status_code}"
                    continue
                data = r.json()
                text = data["choices"][0]["message"]["content"].strip()
                latency = int((time.perf_counter() - start) * 1000)
                return AIResponse(
                    text=text, provider="unfil", model=model, latency_ms=latency
                )
            except (httpx.TimeoutException, httpx.HTTPError) as e:
                last_error = f"{model} → {type(e).__name__}"
                continue

        raise AIProviderError(f"Unfil failed: {last_error}")

    async def stream(
        self,
        history: List[ChatMessage],
        system_prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        if not self._api_key:
            raise AIProviderError("UNFIL_API_KEY غير معيّن")

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
                "stream": True,
            }
            try:
                async with self._client.stream(
                    "POST", _ENDPOINT, headers=self._headers(), json=payload
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

        raise AIProviderError(f"Unfil stream failed: {last_error}")

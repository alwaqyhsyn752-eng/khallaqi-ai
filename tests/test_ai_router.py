"""Tests for the AI router + circuit breaker."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.exceptions import AllProvidersFailedError, AIProviderError
from app.services.ai.base import AIResponse, ChatMessage, ProviderCapability
from app.services.ai.router import AIRouter, CircuitBreaker


class FakeProvider:
    """Stub provider with configurable behaviour."""

    def __init__(self, name: str, fail: bool = False, available: bool = True):
        self.name = name
        self._fail = fail
        self.available = available
        self.capabilities = frozenset({
            ProviderCapability.TEXT,
            ProviderCapability.STREAMING,
        })
        self.call_count = 0

    def supports(self, cap: ProviderCapability) -> bool:
        return cap in self.capabilities

    async def generate(self, *args, **kwargs):
        self.call_count += 1
        if self._fail:
            raise AIProviderError(f"{self.name} failed")
        return AIResponse(text=f"hi from {self.name}", provider=self.name, model="m")

    async def stream(self, *args, **kwargs):
        self.call_count += 1
        if self._fail:
            raise AIProviderError(f"{self.name} failed")
        yield "hello"

    async def vision(self, *args, **kwargs):
        raise NotImplementedError

    async def video(self, *args, **kwargs):
        raise NotImplementedError

    async def video_status(self, *args, **kwargs):
        raise NotImplementedError

    async def close(self):
        return None


def test_circuit_breaker_opens_after_threshold() -> None:
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    assert not cb.is_open
    cb.record_failure()
    cb.record_failure()
    assert not cb.is_open
    cb.record_failure()
    assert cb.is_open


def test_circuit_breaker_resets_on_success() -> None:
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)
    cb.record_failure()
    cb.record_success()
    assert not cb.is_open


@pytest.mark.asyncio
async def test_router_uses_first_healthy_provider() -> None:
    providers = {
        "gemini": FakeProvider("gemini"),
        "groq": FakeProvider("groq"),
    }
    router = AIRouter(providers=providers)
    resp = await router.generate([ChatMessage("user", "hi")], "sys")
    assert resp.provider == "gemini"
    assert providers["groq"].call_count == 0


@pytest.mark.asyncio
async def test_router_falls_back_when_first_fails() -> None:
    providers = {
        "gemini": FakeProvider("gemini", fail=True),
        "groq": FakeProvider("groq"),
    }
    router = AIRouter(providers=providers)
    resp = await router.generate([ChatMessage("user", "hi")], "sys")
    assert resp.provider == "groq"


@pytest.mark.asyncio
async def test_router_raises_when_all_fail() -> None:
    providers = {
        "gemini": FakeProvider("gemini", fail=True),
        "groq": FakeProvider("groq", fail=True),
    }
    router = AIRouter(providers=providers)
    with pytest.raises(AllProvidersFailedError):
        await router.generate([ChatMessage("user", "hi")], "sys")


@pytest.mark.asyncio
async def test_router_skips_unavailable_provider() -> None:
    providers = {
        "gemini": FakeProvider("gemini", available=False),
        "groq": FakeProvider("groq"),
    }
    router = AIRouter(providers=providers)
    resp = await router.generate([ChatMessage("user", "hi")], "sys")
    assert resp.provider == "groq"


@pytest.mark.asyncio
async def test_router_streaming_emits_provider_marker() -> None:
    providers = {"gemini": FakeProvider("gemini")}
    router = AIRouter(providers=providers)
    events = []
    async for kind, value in router.stream([ChatMessage("user", "hi")], "sys"):
        events.append((kind, value))
    assert ("__provider__", "gemini") in events
    assert ("chunk", "hello") in events

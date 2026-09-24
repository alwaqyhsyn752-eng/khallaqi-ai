"""AI Router — selects provider, handles circuit breaking and fallback."""
from __future__ import annotations

import time
from typing import AsyncIterator, Dict, List, Optional

from app.config import get_settings
from app.exceptions import AllProvidersFailedError
from app.logging_config import get_logger
from app.services.ai.base import (
    AIProvider,
    AIResponse,
    ChatMessage,
    ProviderCapability,
)
from app.services.ai.gemini import GeminiProvider
from app.services.ai.groq import GroqProvider
from app.services.ai.openrouter import OpenRouterProvider

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────
# Circuit breaker — per provider, prevents hammering dead services
# ─────────────────────────────────────────────────────────────────
class CircuitBreaker:
    """Simple circuit breaker with failure threshold + cooldown."""

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: int = 60) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures = 0
        self._open_until: float = 0.0

    @property
    def is_open(self) -> bool:
        """True if the breaker is currently open (provider should be skipped)."""
        if self._open_until == 0.0:
            return False
        if time.time() >= self._open_until:
            # cooldown expired — half-open
            self._open_until = 0.0
            self._failures = 0
            return False
        return True

    def record_success(self) -> None:
        """Reset failure counter on success."""
        self._failures = 0
        self._open_until = 0.0

    def record_failure(self) -> None:
        """Increment failure counter, open breaker if threshold exceeded."""
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._open_until = time.time() + self.cooldown_seconds
            log.warning(
                "circuit_breaker.opened",
                failures=self._failures,
                cooldown=self.cooldown_seconds,
            )


# ─────────────────────────────────────────────────────────────────
# Router
# ─────────────────────────────────────────────────────────────────
class AIRouter:
    """Orchestrates multiple AI providers with fallback + circuit breaking.

    Order of preference for each capability is defined in _order_for().
    """

    def __init__(self, providers: Optional[Dict[str, AIProvider]] = None) -> None:
        self._providers: Dict[str, AIProvider] = providers or {
            "gemini": GeminiProvider(),
            "groq": GroqProvider(),
            "openrouter": OpenRouterProvider(),
        }
        self._breakers: Dict[str, CircuitBreaker] = {
            name: CircuitBreaker() for name in self._providers
        }

    async def close(self) -> None:
        """Close all provider HTTP clients."""
        for provider in self._providers.values():
            try:
                await provider.close()
            except Exception:
                log.exception("provider.close_failed", provider=provider.name)

    # ─── Provider selection ───
    def _order_for(self, capability: ProviderCapability) -> List[str]:
        """Return provider names in preference order for a capability."""
        if capability == ProviderCapability.VISION:
            return ["gemini"]
        if capability == ProviderCapability.VIDEO:
            return ["gemini"]
        # Default text/streaming order
        return ["gemini", "groq", "openrouter"]

    def _candidates(
        self, capability: ProviderCapability
    ) -> List[AIProvider]:
        """Return available + enabled + non-open providers for a capability."""
        out: List[AIProvider] = []
        for name in self._order_for(capability):
            provider = self._providers.get(name)
            if provider is None:
                continue
            if not getattr(provider, "available", True):
                continue
            if not provider.supports(capability):
                continue
            if self._breakers[name].is_open:
                log.info("provider.skipped.circuit_open", provider=name)
                continue
            out.append(provider)
        return out

    # ─── Text ───
    async def generate(
        self,
        history: List[ChatMessage],
        system_prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 4096,
    ) -> AIResponse:
        """Generate a response, trying providers in order."""
        errors: List[str] = []
        for provider in self._candidates(ProviderCapability.TEXT):
            try:
                resp = await provider.generate(
                    history,
                    system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                self._breakers[provider.name].record_success()
                return resp
            except Exception as e:
                self._breakers[provider.name].record_failure()
                errors.append(f"{provider.name}: {str(e)[:100]}")
                log.warning("provider.generate_failed", provider=provider.name, error=str(e)[:120])
                continue
        raise AllProvidersFailedError(
            "جميع مزودي الذكاء الاصطناعي فشلوا",
            details={"errors": errors},
        )

    # ─── Streaming ───
    async def stream(
        self,
        history: List[ChatMessage],
        system_prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 4096,
    ) -> AsyncIterator[tuple[str, str]]:
        """Stream from the first working provider.

        Yields (provider_name, chunk) tuples. The provider name is only
        yielded once, on the first chunk, so the caller can record source.
        """
        errors: List[str] = []
        for provider in self._candidates(ProviderCapability.STREAMING):
            try:
                first = True
                async for chunk in provider.stream(
                    history,
                    system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    if first:
                        first = False
                        # Emit provider marker
                        yield ("__provider__", provider.name)
                    yield ("chunk", chunk)
                self._breakers[provider.name].record_success()
                return
            except Exception as e:
                self._breakers[provider.name].record_failure()
                errors.append(f"{provider.name}: {str(e)[:100]}")
                log.warning("provider.stream_failed", provider=provider.name, error=str(e)[:120])
                continue

        raise AllProvidersFailedError(
            "جميع مزودي البث فشلوا",
            details={"errors": errors},
        )

    # ─── Vision ───
    async def vision(
        self,
        prompt: str,
        image_base64: str,
        mime_type: str = "image/jpeg",
        system_prompt: str = "",
    ) -> AIResponse:
        """Analyze an image via the first capable provider."""
        errors: List[str] = []
        for provider in self._candidates(ProviderCapability.VISION):
            try:
                resp = await provider.vision(
                    prompt, image_base64, mime_type, system_prompt
                )
                self._breakers[provider.name].record_success()
                return resp
            except Exception as e:
                self._breakers[provider.name].record_failure()
                errors.append(f"{provider.name}: {str(e)[:100]}")
                continue
        raise AllProvidersFailedError(
            "لا يوجد مزود يدعم تحليل الصور متاح",
            details={"errors": errors},
        )

    # ─── Video ───
    async def video(self, prompt: str) -> dict:
        """Start a video generation job."""
        errors: List[str] = []
        for provider in self._candidates(ProviderCapability.VIDEO):
            try:
                result = await provider.video(prompt)
                self._breakers[provider.name].record_success()
                return result
            except Exception as e:
                self._breakers[provider.name].record_failure()
                errors.append(f"{provider.name}: {str(e)[:100]}")
                continue
        raise AllProvidersFailedError(
            "لا يوجد مزود يدعم توليد الفيديو متاح",
            details={"errors": errors},
        )

    async def video_status(self, operation: str) -> dict:
        """Check a video generation operation status."""
        for provider in self._candidates(ProviderCapability.VIDEO):
            try:
                return await provider.video_status(operation)
            except Exception:
                continue
        raise AllProvidersFailedError("فشل الاستعلام عن حالة الفيديو")


# ─────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────
_router: Optional[AIRouter] = None


def get_ai_router() -> AIRouter:
    """Return the process-wide AIRouter singleton."""
    global _router
    if _router is None:
        _router = AIRouter()
        s = get_settings()
        log.info(
            "ai_router.initialized",
            gemini=bool(s.gemini_api_key),
            groq=bool(s.groq_api_key),
            openrouter=bool(s.openrouter_api_key),
        )
    return _router

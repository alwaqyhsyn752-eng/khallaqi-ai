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


class CircuitBreaker:
    """Simple circuit breaker with failure threshold + cooldown."""

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: int = 60) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures = 0
        self._open_until: float = 0.0

    @property
    def is_open(self) -> bool:
        if self._open_until == 0.0:
            return False
        if time.time() >= self._open_until:
            self._open_until = 0.0
            self._failures = 0
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._open_until = 0.0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._open_until = time.time() + self.cooldown_seconds
            log.warning(
                "circuit_breaker.opened",
                failures=self._failures,
                cooldown=self.cooldown_seconds,
            )


def _humanize_error(provider_name: str, err: Exception) -> str:
    """Convert a provider error into a short Arabic-friendly hint."""
    msg = str(err)
    low = msg.lower()

    if "policy" in low or "safety" in low or "blocked" in low:
        return "تم رفض الطلب من مزوّد الذكاء (سياسة الاستخدام)."
    if "quota" in low or "rate" in low or "429" in low:
        return "تجاوز الحد المسموح مؤقتاً (Rate Limit)."
    if "timeout" in low or "timed out" in low:
        return "انتهت مهلة الاتصال بمزوّد الذكاء."
    if "api_key" in low or "401" in low or "unauthorized" in low:
        return "مفتاح المزوّد غير صالح أو منتهي."
    if "connect" in low or "network" in low:
        return "تعذّر الاتصال بخدمة الذكاء."
    return f"فشل الاتصال بمزوّد {provider_name}."


class AIRouter:
    """Orchestrates multiple AI providers with fallback + circuit breaking."""

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
        for provider in self._providers.values():
            try:
                await provider.close()
            except Exception:
                log.exception("provider.close_failed", provider=provider.name)

    def _order_for(self, capability: ProviderCapability) -> List[str]:
        if capability == ProviderCapability.VISION:
            return ["gemini"]
        if capability == ProviderCapability.VIDEO:
            return ["gemini"]
        return ["gemini", "groq", "openrouter"]

    def _candidates(self, capability: ProviderCapability) -> List[AIProvider]:
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

    async def generate(
        self,
        history: List[ChatMessage],
        system_prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 4096,
    ) -> AIResponse:
        errors: List[str] = []
        hints: List[str] = []
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
                hints.append(_humanize_error(provider.name, e))
                log.warning(
                    "provider.generate_failed",
                    provider=provider.name,
                    error=str(e)[:120],
                )
                continue

        raise AllProvidersFailedError(
            "تعذّر الحصول على رد من مزوّدي الذكاء. "
            + (hints[0] if hints else "حدث خطأ غير متوقّع. جرّب إعادة صياغة الطلب.")
            + " إذا استمرت المشكلة، أعد صياغة الطلب أو انتظر دقيقة.",
            details={"errors": errors},
        )

    async def stream(
        self,
        history: List[ChatMessage],
        system_prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 4096,
    ) -> AsyncIterator[tuple[str, str]]:
        errors: List[str] = []
        hints: List[str] = []
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
                        yield ("__provider__", provider.name)
                    yield ("chunk", chunk)
                self._breakers[provider.name].record_success()
                return
            except Exception as e:
                self._breakers[provider.name].record_failure()
                errors.append(f"{provider.name}: {str(e)[:100]}")
                hints.append(_humanize_error(provider.name, e))
                log.warning(
                    "provider.stream_failed",
                    provider=provider.name,
                    error=str(e)[:120],
                )
                continue

        raise AllProvidersFailedError(
            "تعذّر بدء البث من مزوّدي الذكاء. "
            + (hints[0] if hints else "حدث خطأ غير متوقّع.")
            + " جرّب إعادة صياغة الطلب.",
            details={"errors": errors},
        )

    async def vision(
        self,
        prompt: str,
        image_base64: str,
        mime_type: str = "image/jpeg",
        system_prompt: str = "",
    ) -> AIResponse:
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
            "لا يوجد مزوّد متاح لتحليل الصور حالياً. جرّب لاحقاً.",
            details={"errors": errors},
        )

    async def video(self, prompt: str) -> dict:
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
            "خدمة توليد الفيديو غير مفعّلة على حسابك حالياً.",
            details={"errors": errors},
        )

    async def video_status(self, operation: str) -> dict:
        for provider in self._candidates(ProviderCapability.VIDEO):
            try:
                return await provider.video_status(operation)
            except Exception:
                continue
        raise AllProvidersFailedError("تعذّر الاستعلام عن حالة الفيديو.")


_router: Optional[AIRouter] = None


def get_ai_router() -> AIRouter:
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

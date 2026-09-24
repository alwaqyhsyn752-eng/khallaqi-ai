"""Custom application exceptions — a single hierarchy."""
from __future__ import annotations

from typing import Any, Optional


class KhallaqiError(Exception):
    """Base class for all application errors."""

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self) -> dict:
        """Serialize to API-friendly dict."""
        out: dict = {"error": self.message, "code": self.error_code}
        if self.details is not None:
            out["details"] = self.details
        return out


# ─── 4xx Client Errors ───
class ValidationError(KhallaqiError):
    """Invalid input from client."""
    status_code = 400
    error_code = "validation_error"


class AuthenticationError(KhallaqiError):
    """Missing or invalid credentials."""
    status_code = 401
    error_code = "authentication_error"


class UnauthorizedError(KhallaqiError):
    """Authenticated but not allowed."""
    status_code = 403
    error_code = "unauthorized"


class NotFoundError(KhallaqiError):
    """Resource does not exist."""
    status_code = 404
    error_code = "not_found"


class ConflictError(KhallaqiError):
    """Conflict with current state."""
    status_code = 409
    error_code = "conflict"


class RateLimitError(KhallaqiError):
    """Too many requests."""
    status_code = 429
    error_code = "rate_limited"


# ─── 5xx Server Errors ───
class DatabaseError(KhallaqiError):
    """Database operation failed."""
    status_code = 500
    error_code = "database_error"


class CacheError(KhallaqiError):
    """Cache operation failed."""
    status_code = 500
    error_code = "cache_error"


class ExternalServiceError(KhallaqiError):
    """External service call failed."""
    status_code = 502
    error_code = "external_service_error"


class AIProviderError(ExternalServiceError):
    """AI provider call failed."""
    error_code = "ai_provider_error"


class AllProvidersFailedError(AIProviderError):
    """All AI providers failed."""
    error_code = "all_providers_failed"


class TTSError(ExternalServiceError):
    """TTS operation failed."""
    error_code = "tts_error"


class VideoError(ExternalServiceError):
    """Video generation failed."""
    error_code = "video_error"

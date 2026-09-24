"""Application configuration using Pydantic Settings."""
from __future__ import annotations

from functools import lru_cache
from typing import List, Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralised, typed, validated application settings.

    All values are loaded from environment variables or a .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── Application ───
    ai_name: str = "الخلاقي"
    developer_name: str = "حسين غلاب"
    version: str = "16.0.0"
    environment: Literal["development", "staging", "production"] = "production"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    port: int = Field(default=8000, ge=1, le=65535)
    workers: int = Field(default=2, ge=1, le=16)

    # ─── Security ───
    secret_key: str = Field(default="change-me-in-production", min_length=16)
    allowed_origins: str = "*"

    # ─── AI Providers ───
    gemini_api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""

    # ─── Azure TTS ───
    azure_speech_key: str = ""
    azure_speech_region: str = "westeurope"
    azure_voice_ar: str = "ar-SA-HamedNeural"

    # ─── Database ───
    database_url: str = "sqlite+aiosqlite:///./khallaqi.db"
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=20, ge=0, le=100)
    db_pool_timeout: int = Field(default=30, ge=1, le=300)

    # ─── Redis ───
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = Field(default=50, ge=1, le=500)

    # ─── Rate Limiting ───
    rate_limit_per_min: int = Field(default=20, ge=1)
    rate_limit_per_hour: int = Field(default=500, ge=1)

    # ─── Limits ───
    max_msg_len: int = Field(default=8000, ge=100)
    max_content_length: int = Field(default=32 * 1024 * 1024, ge=1024)

    # ─── Observability ───
    sentry_dsn: Optional[str] = None
    otel_enabled: bool = False

    @property
    def origins_list(self) -> List[str]:
        """Parse ALLOWED_ORIGINS as a list."""
        if self.allowed_origins == "*":
            return ["*"]
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        """True when running in production."""
        return self.environment == "production"

    @property
    def has_any_ai_provider(self) -> bool:
        """True when at least one AI provider key is configured."""
        return bool(
            self.gemini_api_key or self.groq_api_key or self.openrouter_api_key
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance."""
    return Settings()


# Convenience alias for backward compatibility
settings = get_settings()

"""Pydantic v2 schemas for API I/O."""
from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ═══════════════════════════════════════════════════════════════════
# Base
# ═══════════════════════════════════════════════════════════════════
class BaseSchema(BaseModel):
    """Base Pydantic schema with common config."""

    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
        extra="ignore",
    )


# ═══════════════════════════════════════════════════════════════════
# Chat Requests
# ═══════════════════════════════════════════════════════════════════
class NewChatRequest(BaseSchema):
    """Request to create a new chat."""

    user_id: str = Field(..., min_length=1, max_length=64)


class DeleteChatRequest(BaseSchema):
    """Request to delete a chat."""

    user_id: str = Field(..., min_length=1, max_length=64)


class ChatRequest(BaseSchema):
    """Request to send a message."""

    message: str = Field(default="", max_length=8000)
    chat_id: str = Field(..., min_length=1, max_length=100)
    user_id: str = Field(..., min_length=1, max_length=64)
    image: Optional[str] = Field(default=None, description="Base64 image")
    image_type: str = Field(default="image/jpeg", max_length=50)

    @field_validator("user_id")
    @classmethod
    def _truncate_user_id(cls, v: str) -> str:
        return v.strip()[:64]


# ═══════════════════════════════════════════════════════════════════
# Chat Responses
# ═══════════════════════════════════════════════════════════════════
class MessageOut(BaseSchema):
    """A single message in a chat."""

    role: Literal["user", "assistant"]
    content: str
    type: str = "text"
    media: Optional[str] = None
    source: Optional[str] = None


class ChatOut(BaseSchema):
    """Chat metadata."""

    id: str
    title: str
    created_at: str
    updated_at: str


class ChatListOut(BaseSchema):
    """List of chats."""

    chats: List[ChatOut]


class ChatResponseOut(BaseSchema):
    """Response after sending a message."""

    response: str
    source: Optional[str] = None
    type: str = "text"
    remaining_min: int = 0
    remaining_hour: int = 0


# ═══════════════════════════════════════════════════════════════════
# Memory
# ═══════════════════════════════════════════════════════════════════
class MemorySetRequest(BaseSchema):
    """Request to set a memory entry."""

    user_id: str = Field(..., min_length=1, max_length=64)
    key: str = Field(..., min_length=1, max_length=100)
    value: str = Field(..., min_length=1, max_length=500)
    category: str = Field(default="general", max_length=30)


class MemoryOut(BaseSchema):
    """A memory entry."""

    key: str
    value: str
    category: str
    confidence: float


class MemoryListOut(BaseSchema):
    """List of memory entries."""

    memory: List[MemoryOut]


# ═══════════════════════════════════════════════════════════════════
# Search
# ═══════════════════════════════════════════════════════════════════
class SearchResultOut(BaseSchema):
    """A search result."""

    chat_id: str
    title: str
    updated_at: str
    snippet: str


class SearchOut(BaseSchema):
    """Search results wrapper."""

    results: List[SearchResultOut]


# ═══════════════════════════════════════════════════════════════════
# Stats
# ═══════════════════════════════════════════════════════════════════
class StatsOut(BaseSchema):
    """User stats."""

    chats_count: int = 0
    messages_count: int = 0
    assistant_count: int = 0
    memory_count: int = 0
    by_provider: dict = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════
# TTS
# ═══════════════════════════════════════════════════════════════════
class TTSRequest(BaseSchema):
    """Text-to-speech request."""

    text: str = Field(..., min_length=1, max_length=2000)
    voice: Optional[str] = Field(default=None, max_length=80)


class TTSVoicesOut(BaseSchema):
    """Available TTS voices."""

    azure_enabled: bool
    current: str
    saudi_male_voices: List[str]
    other_arabic: List[str]


# ═══════════════════════════════════════════════════════════════════
# Video
# ═══════════════════════════════════════════════════════════════════
class GenerateVideoRequest(BaseSchema):
    """Request to generate a video."""

    prompt: str = Field(..., min_length=1, max_length=2000)
    chat_id: str = Field(default="", max_length=100)
    user_id: str = Field(default="", max_length=64)


class VideoStatusRequest(BaseSchema):
    """Request to check video status."""

    operation: str = Field(..., min_length=1, max_length=500)


class VideoGenerateOut(BaseSchema):
    """Video generation response."""

    status: str
    operation: Optional[str] = None
    model: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════
# Health & Errors
# ═══════════════════════════════════════════════════════════════════
class HealthOut(BaseSchema):
    """Health/status response."""

    ai_name: str
    version: str
    environment: str
    database: str
    db_ok: bool
    redis_ok: bool
    providers: dict
    features: dict
    rate_limits: dict


class ErrorOut(BaseSchema):
    """Standard error response."""

    error: str
    code: str = "error"
    details: Optional[Any] = None

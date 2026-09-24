"""Abstract base class for AI providers."""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, List, Optional


class ProviderCapability(str, Enum):
    """Features a provider may or may not support."""

    TEXT = "text"
    STREAMING = "streaming"
    VISION = "vision"
    VIDEO = "video"


@dataclass(slots=True)
class ChatMessage:
    """A single message in a conversation history."""

    role: str  # "user" | "assistant" | "system"
    content: str

    def as_dict(self) -> dict:
        """Serialize to a plain dict."""
        return {"role": self.role, "content": self.content}


@dataclass(slots=True)
class AIResponse:
    """Normalized response from any AI provider."""

    text: str
    provider: str
    model: str
    latency_ms: int = 0
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    raw: Optional[dict] = field(default=None, repr=False)

    @property
    def source(self) -> str:
        """Human-readable source label."""
        return f"{self.provider}/{self.model}"


class AIProvider(abc.ABC):
    """Abstract AI provider."""

    name: str = "base"
    capabilities: frozenset[ProviderCapability] = frozenset()

    @abc.abstractmethod
    async def generate(
        self,
        history: List[ChatMessage],
        system_prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 4096,
    ) -> AIResponse:
        """Generate a text response synchronously (non-streaming)."""

    @abc.abstractmethod
    def supports(self, capability: ProviderCapability) -> bool:
        """Check whether a capability is supported."""

    # ─── Optional overrides ───
    async def stream(
        self,
        history: List[ChatMessage],
        system_prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream tokens. Default: fall back to full generate()."""
        response = await self.generate(
            history,
            system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        yield response.text

    async def vision(
        self,
        prompt: str,
        image_base64: str,
        mime_type: str = "image/jpeg",
        system_prompt: str = "",
    ) -> AIResponse:
        """Analyze an image. Providers without vision should raise."""
        raise NotImplementedError(f"{self.name} does not support vision")

    async def video(
        self,
        prompt: str,
    ) -> dict:
        """Start a video generation job. Providers without video should raise."""
        raise NotImplementedError(f"{self.name} does not support video")

    async def video_status(self, operation: str) -> dict:
        """Check status of a video generation job."""
        raise NotImplementedError(f"{self.name} does not support video")

    def supports(self, capability: ProviderCapability) -> bool:  # noqa: F811
        """Check whether a capability is supported."""
        return capability in self.capabilities

    async def close(self) -> None:
        """Optional cleanup."""
        return None

    # ─── Utilities ───
    @staticmethod
    def normalize_history(history: List[ChatMessage]) -> List[dict]:
        """Convert ChatMessage list to plain dicts."""
        return [m.as_dict() for m in history]

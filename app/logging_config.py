"""Structured logging configuration using structlog."""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.config import settings

_CONFIGURED = False


def configure_logging() -> None:
    """Configure structured logging once at startup."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    # Standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level.upper(),
    )

    # Shared processors for structlog
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.is_production:
        # JSON in production for log aggregation
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        # Human-readable in development
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Silence noisy loggers
    for noisy in ("urllib3", "httpx", "httpcore", "asyncio", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str | None = None) -> Any:
    """Return a structlog logger bound to a name."""
    configure_logging()
    return structlog.get_logger(name or "khallaqi")

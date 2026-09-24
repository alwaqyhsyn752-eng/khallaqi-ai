"""Middleware: request ID, security headers, exception handling."""
from __future__ import annotations

import time
import uuid
from typing import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.exceptions import KhallaqiError
from app.logging_config import get_logger

log = get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique request-id to every request and response."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = req_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(self)"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response


class TimingMiddleware(BaseHTTPMiddleware):
    """Measure and log request duration."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"
        log.debug(
            "http.request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            ms=round(elapsed_ms, 1),
        )
        return response


def register_exception_handler(app) -> None:
    """Register global exception handlers on the FastAPI app."""

    @app.exception_handler(KhallaqiError)
    async def _handle_khallaqi(request: Request, exc: KhallaqiError) -> JSONResponse:
        log.warning(
            "app_error",
            code=exc.error_code,
            message=exc.message,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict(),
        )

    @app.exception_handler(Exception)
    async def _handle_unknown(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_exception", path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": "حدث خطأ داخلي. الرجاء المحاولة لاحقاً.",
                "code": "internal_error",
            },
        )

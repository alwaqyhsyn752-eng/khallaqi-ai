"""Tests for system endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_liveness(client: AsyncClient) -> None:
    """Liveness probe should always return 200."""
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_status_returns_expected_shape(client: AsyncClient) -> None:
    """Status endpoint should return complete metadata."""
    r = await client.get("/api/v1/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ai_name"] == "الخلاقي"
    assert "version" in body
    assert "providers" in body
    assert "features" in body
    assert "rate_limits" in body
    assert body["db_ok"] is True


@pytest.mark.asyncio
async def test_root_serves_html(client: AsyncClient) -> None:
    """Root should return the HTML UI."""
    r = await client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_request_id_header_is_present(client: AsyncClient) -> None:
    """Every response should include an X-Request-ID."""
    r = await client.get("/api/v1/health")
    assert "x-request-id" in {k.lower() for k in r.headers}


@pytest.mark.asyncio
async def test_security_headers_present(client: AsyncClient) -> None:
    """Security headers should be added to responses."""
    r = await client.get("/api/v1/health")
    headers = {k.lower(): v for k, v in r.headers.items()}
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("x-frame-options") == "DENY"

"""Tests for search and export endpoints."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.services.ai.base import AIResponse


@pytest.mark.asyncio
async def test_search_finds_matching_messages(client: AsyncClient) -> None:
    """Searching should return matching chats."""
    r1 = await client.post("/api/v1/chats/new", json={"user_id": "searcher"})
    chat_id = r1.json()["chat_id"]

    fake_response = AIResponse(
        text="كود Python للترتيب",
        provider="gemini",
        model="gemini-2.0-flash",
    )
    with patch(
        "app.services.ai.router.AIRouter.generate",
        new=AsyncMock(return_value=fake_response),
    ):
        await client.post(
            "/api/v1/chat",
            json={
                "chat_id": chat_id,
                "user_id": "searcher",
                "message": "اكتب كود Python",
            },
        )

    r2 = await client.get(
        "/api/v1/search",
        headers={"X-User-ID": "searcher"},
        params={"q": "Python"},
    )
    assert r2.status_code == 200
    results = r2.json()["results"]
    assert len(results) >= 1
    assert results[0]["chat_id"] == chat_id


@pytest.mark.asyncio
async def test_search_no_results(client: AsyncClient) -> None:
    """Searching for a non-existent term returns empty."""
    r = await client.get(
        "/api/v1/search",
        headers={"X-User-ID": "nobody"},
        params={"q": "xyz_nonexistent_12345"},
    )
    assert r.status_code == 200
    assert r.json()["results"] == []


@pytest.mark.asyncio
async def test_export_json(client: AsyncClient) -> None:
    """Export as JSON should return valid payload."""
    r1 = await client.post("/api/v1/chats/new", json={"user_id": "exporter"})
    chat_id = r1.json()["chat_id"]

    r2 = await client.get(
        f"/api/v1/export/{chat_id}",
        headers={"X-User-ID": "exporter"},
        params={"format": "json"},
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["chat_id"] == chat_id
    assert "messages" in body


@pytest.mark.asyncio
async def test_export_markdown(client: AsyncClient) -> None:
    """Markdown export should set the right content type."""
    r1 = await client.post("/api/v1/chats/new", json={"user_id": "md_user"})
    chat_id = r1.json()["chat_id"]

    r2 = await client.get(
        f"/api/v1/export/{chat_id}",
        headers={"X-User-ID": "md_user"},
        params={"format": "md"},
    )
    assert r2.status_code == 200
    assert "text/markdown" in r2.headers["content-type"]
    assert "attachment" in r2.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_export_unauthorized(client: AsyncClient) -> None:
    """Non-owner cannot export."""
    r1 = await client.post("/api/v1/chats/new", json={"user_id": "owner2"})
    chat_id = r1.json()["chat_id"]

    r2 = await client.get(
        f"/api/v1/export/{chat_id}",
        headers={"X-User-ID": "intruder2"},
    )
    assert r2.status_code == 403

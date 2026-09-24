"""Tests for chat endpoints."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.services.ai.base import AIResponse


@pytest.mark.asyncio
async def test_create_chat(client: AsyncClient) -> None:
    """POST /chats/new should create a chat."""
    r = await client.post(
        "/api/v1/chats/new",
        json={"user_id": "test-user"},
    )
    assert r.status_code == 201
    body = r.json()
    assert "chat_id" in body
    assert body["title"] == "محادثة جديدة"


@pytest.mark.asyncio
async def test_list_chats_requires_user_header(client: AsyncClient) -> None:
    """GET /chats without X-User-ID should fail."""
    r = await client.get("/api/v1/chats", headers={"X-User-ID": ""})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_list_chats_empty(client: AsyncClient) -> None:
    """GET /chats returns empty list for new user."""
    r = await client.get("/api/v1/chats", headers={"X-User-ID": "new-user"})
    assert r.status_code == 200
    assert r.json() == {"chats": []}


@pytest.mark.asyncio
async def test_send_message_creates_chat(client: AsyncClient) -> None:
    """Sending a message should persist chat + reply."""
    # Create a chat
    r1 = await client.post("/api/v1/chats/new", json={"user_id": "u1"})
    chat_id = r1.json()["chat_id"]

    # Mock AI response
    fake_response = AIResponse(
        text="مرحباً بك!",
        provider="gemini",
        model="gemini-2.0-flash",
        latency_ms=100,
    )

    with patch(
        "app.services.ai.router.AIRouter.generate",
        new=AsyncMock(return_value=fake_response),
    ):
        r2 = await client.post(
            "/api/v1/chat",
            json={
                "chat_id": chat_id,
                "user_id": "u1",
                "message": "أهلاً",
            },
        )

    assert r2.status_code == 200
    body = r2.json()
    assert body["response"] == "مرحباً بك!"
    assert body["source"] == "gemini/gemini-2.0-flash"
    assert body["remaining_min"] >= 0
    assert body["remaining_hour"] >= 0


@pytest.mark.asyncio
async def test_unauthorized_chat_access(client: AsyncClient) -> None:
    """User cannot read a chat owned by someone else."""
    r1 = await client.post("/api/v1/chats/new", json={"user_id": "owner"})
    chat_id = r1.json()["chat_id"]

    r2 = await client.get(
        f"/api/v1/chats/{chat_id}",
        headers={"X-User-ID": "intruder"},
    )
    assert r2.status_code == 403


@pytest.mark.asyncio
async def test_delete_chat(client: AsyncClient) -> None:
    """Deleting a chat should succeed and remove it."""
    r1 = await client.post("/api/v1/chats/new", json={"user_id": "u2"})
    chat_id = r1.json()["chat_id"]

    r2 = await client.delete(
        f"/api/v1/chats/{chat_id}",
        json={"user_id": "u2"},
    )
    assert r2.status_code == 200

    # Confirm it's gone
    r3 = await client.get("/api/v1/chats", headers={"X-User-ID": "u2"})
    assert r3.json()["chats"] == []


@pytest.mark.asyncio
async def test_stream_endpoint_returns_sse(client: AsyncClient) -> None:
    """POST /chat/stream should return text/event-stream."""
    r1 = await client.post("/api/v1/chats/new", json={"user_id": "stream-user"})
    chat_id = r1.json()["chat_id"]

    async def fake_stream(*args, **kwargs):
        yield ("__provider__", "gemini")
        yield ("chunk", "Hello ")
        yield ("chunk", "World")

    with patch(
        "app.services.ai.router.AIRouter.stream",
        new=fake_stream,
    ):
        r2 = await client.post(
            "/api/v1/chat/stream",
            json={
                "chat_id": chat_id,
                "user_id": "stream-user",
                "message": "hi",
            },
        )

    assert r2.status_code == 200
    assert "text/event-stream" in r2.headers["content-type"]
    text = r2.text
    assert "Hello " in text
    assert "World" in text
    assert '"done": true' in text

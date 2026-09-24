"""Tests for memory endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_set_and_get_memory(client: AsyncClient) -> None:
    """Setting a memory entry should be retrievable."""
    r1 = await client.post(
        "/api/v1/memory",
        json={
            "user_id": "mem-user",
            "key": "language",
            "value": "ar",
            "category": "preference",
        },
    )
    assert r1.status_code == 201

    r2 = await client.get("/api/v1/memory", headers={"X-User-ID": "mem-user"})
    assert r2.status_code == 200
    memory = r2.json()["memory"]
    assert len(memory) == 1
    assert memory[0]["key"] == "language"
    assert memory[0]["value"] == "ar"


@pytest.mark.asyncio
async def test_update_memory_overwrites(client: AsyncClient) -> None:
    """Updating an existing key should overwrite it."""
    await client.post(
        "/api/v1/memory",
        json={"user_id": "u", "key": "skill", "value": "beginner"},
    )
    await client.post(
        "/api/v1/memory",
        json={"user_id": "u", "key": "skill", "value": "expert"},
    )
    r = await client.get("/api/v1/memory", headers={"X-User-ID": "u"})
    memory = r.json()["memory"]
    assert len(memory) == 1
    assert memory[0]["value"] == "expert"


@pytest.mark.asyncio
async def test_delete_single_memory(client: AsyncClient) -> None:
    """Deleting one key should leave others intact."""
    await client.post("/api/v1/memory", json={"user_id": "d", "key": "a", "value": "1"})
    await client.post("/api/v1/memory", json={"user_id": "d", "key": "b", "value": "2"})

    r1 = await client.delete(
        "/api/v1/memory",
        headers={"X-User-ID": "d"},
        params={"key": "a"},
    )
    assert r1.status_code == 200

    r2 = await client.get("/api/v1/memory", headers={"X-User-ID": "d"})
    memory = r2.json()["memory"]
    assert len(memory) == 1
    assert memory[0]["key"] == "b"


@pytest.mark.asyncio
async def test_delete_all_memory(client: AsyncClient) -> None:
    """Deleting without a key should wipe the whole memory."""
    for i in range(3):
        await client.post(
            "/api/v1/memory",
            json={"user_id": "wipe", "key": f"k{i}", "value": str(i)},
        )
    r1 = await client.delete("/api/v1/memory", headers={"X-User-ID": "wipe"})
    assert r1.status_code == 200
    assert r1.json()["deleted"] == 3

    r2 = await client.get("/api/v1/memory", headers={"X-User-ID": "wipe"})
    assert r2.json()["memory"] == []

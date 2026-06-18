"""Integration test for the health endpoint."""

import pytest
from httpx import AsyncClient


async def test_health_ok(async_client: AsyncClient) -> None:
    resp = await async_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


async def test_request_id_header(async_client: AsyncClient) -> None:
    resp = await async_client.get("/health")
    assert "x-request-id" in resp.headers
    assert len(resp.headers["x-request-id"]) == 36  # UUID length

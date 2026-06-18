"""Integration tests for metric endpoints."""

import pytest
from httpx import AsyncClient


async def test_review_load_404_before_sync(async_client: AsyncClient) -> None:
    resp = await async_client.get(
        "/metrics/review-load",
        params={"repo": "nobody/nowhere", "from": "2024-01-01", "to": "2024-06-30"},
    )
    assert resp.status_code == 404


async def test_cycle_time_404_before_sync(async_client: AsyncClient) -> None:
    resp = await async_client.get(
        "/metrics/cycle-time",
        params={"repo": "nobody/nowhere", "from": "2024-01-01", "to": "2024-06-30"},
    )
    assert resp.status_code == 404


async def test_review_load_missing_params(async_client: AsyncClient) -> None:
    resp = await async_client.get("/metrics/review-load")
    assert resp.status_code == 422

"""Shared fixtures for unit and integration tests."""

import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.config import Settings, get_settings
from app.db import build_session_factory, create_tables
from app.deps import get_app_settings, get_session
from app.main import create_app


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    return Settings(
        github_token="test_token",
        anthropic_api_key="test_key",
        database_url="sqlite+aiosqlite:///:memory:",
        log_level="WARNING",
        llm_enable_thinking=False,
    )


@pytest_asyncio.fixture
async def db_session(test_settings: Settings) -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    await create_tables(engine)
    factory = build_session_factory(engine)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def async_client(test_settings: Settings) -> AsyncGenerator[AsyncClient, None]:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_app_settings] = lambda: test_settings

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

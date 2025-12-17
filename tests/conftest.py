"""Pytest configuration and fixtures."""
import pytest
import asyncio
from typing import AsyncGenerator
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from apps.bot_service.clients.redis import RedisClient
from apps.bot_service.clients.database import DatabaseClient


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def redis_client() -> AsyncGenerator[RedisClient, None]:
    """Create Redis client for testing."""
    client = RedisClient("redis://localhost:6380/1")  # Use DB 1 for tests (external port)
    try:
        await client.connect()
        yield client
    finally:
        await client.disconnect()


@pytest.fixture
async def db_client() -> AsyncGenerator[DatabaseClient, None]:
    """Create database client for testing."""
    # Use test database
    client = DatabaseClient("postgresql+asyncpg://app:app@localhost:5432/bd_demo")
    try:
        await client.connect()
        yield client
    finally:
        await client.disconnect()


@pytest.fixture
async def clean_redis(redis_client: RedisClient):
    """Clean Redis before and after test."""
    # Clean before test
    if redis_client.redis:
        await redis_client.redis.flushdb()
    yield
    # Clean after test
    if redis_client.redis:
        await redis_client.redis.flushdb()


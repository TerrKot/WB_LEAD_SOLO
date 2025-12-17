"""Tests for database client."""
import pytest
from apps.bot_service.clients.database import DatabaseClient


@pytest.mark.asyncio
async def test_database_connection(db_client: DatabaseClient):
    """Test database connection."""
    assert db_client.engine is not None
    assert db_client.session_factory is not None


@pytest.mark.asyncio
async def test_database_session(db_client: DatabaseClient):
    """Test getting database session."""
    from sqlalchemy import text
    session = await db_client.get_session()
    async with session:
        result = await session.execute(text("SELECT 1 as test"))
        row = result.scalar()
        assert row == 1


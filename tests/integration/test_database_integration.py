"""Integration tests for database."""
import pytest
from apps.bot_service.clients.database import DatabaseClient


@pytest.mark.asyncio
async def test_database_full_workflow(db_client: DatabaseClient):
    """Test full database workflow."""
    # Test connection
    assert db_client.engine is not None
    assert db_client.session_factory is not None
    
    # Test session
    from sqlalchemy import text
    session = await db_client.get_session()
    async with session:
        # Test simple query
        result = await session.execute(text("SELECT 1 as test, 'bd_demo' as db_name"))
        row = result.first()
        assert row.test == 1
        assert row.db_name == "bd_demo"
        
        # Test database name
        result = await session.execute(text("SELECT current_database() as db_name"))
        row = result.first()
        assert row.db_name == "bd_demo"


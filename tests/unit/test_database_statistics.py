"""Tests for database statistics methods."""
import pytest
from sqlalchemy import text

from apps.bot_service.clients.database import DatabaseClient


@pytest.mark.asyncio
async def test_get_mau(db_client: DatabaseClient):
    """Test getting Monthly Active Users (MAU)."""
    # Create test data: user with calculation 15 days ago (within 30 days)
    user_id_1 = 1001
    user_id_2 = 1002
    
    # Save users
    await db_client.save_or_update_user(user_id_1, username="user1")
    await db_client.save_or_update_user(user_id_2, username="user2")
    
    # Create calculation 15 days ago
    calculation_id_1 = "test-mau-1"
    await db_client.save_calculation(
        calculation_id=calculation_id_1,
        user_id=user_id_1,
        article_id=12345,
        calculation_type="express",
        status="🟢"
    )
    
    # Manually set created_at to 15 days ago
    session = await db_client.get_session()
    try:
        update_query = text("""
            UPDATE calculations 
            SET created_at = NOW() - INTERVAL '15 days'
            WHERE calculation_id = :calc_id
        """)
        await session.execute(update_query, {"calc_id": calculation_id_1})
        await session.commit()
    finally:
        await session.close()
    
    # Get MAU
    mau = await db_client.get_mau()
    assert mau >= 1  # At least our test user
    
    # Cleanup
    session = await db_client.get_session()
    try:
        await session.execute(text("DELETE FROM calculations WHERE calculation_id = :calc_id"), {"calc_id": calculation_id_1})
        await session.execute(text("DELETE FROM users WHERE user_id IN (:uid1, :uid2)"), {"uid1": user_id_1, "uid2": user_id_2})
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_get_wau(db_client: DatabaseClient):
    """Test getting Weekly Active Users (WAU)."""
    user_id = 2001
    
    # Save user
    await db_client.save_or_update_user(user_id, username="wau_user")
    
    # Create calculation 3 days ago (within 7 days)
    calculation_id = "test-wau-1"
    await db_client.save_calculation(
        calculation_id=calculation_id,
        user_id=user_id,
        article_id=12345,
        calculation_type="express",
        status="🟡"
    )
    
    # Manually set created_at to 3 days ago
    session = await db_client.get_session()
    try:
        update_query = text("""
            UPDATE calculations 
            SET created_at = NOW() - INTERVAL '3 days'
            WHERE calculation_id = :calc_id
        """)
        await session.execute(update_query, {"calc_id": calculation_id})
        await session.commit()
    finally:
        await session.close()
    
    # Get WAU
    wau = await db_client.get_wau()
    assert wau >= 1  # At least our test user
    
    # Cleanup
    session = await db_client.get_session()
    try:
        await session.execute(text("DELETE FROM calculations WHERE calculation_id = :calc_id"), {"calc_id": calculation_id})
        await session.execute(text("DELETE FROM users WHERE user_id = :uid"), {"uid": user_id})
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_get_dau(db_client: DatabaseClient):
    """Test getting Daily Active Users (DAU)."""
    user_id = 3001
    
    # Save user
    await db_client.save_or_update_user(user_id, username="dau_user")
    
    # Create calculation 12 hours ago (within 24 hours)
    calculation_id = "test-dau-1"
    await db_client.save_calculation(
        calculation_id=calculation_id,
        user_id=user_id,
        article_id=12345,
        calculation_type="express",
        status="🟠"
    )
    
    # Manually set created_at to 12 hours ago
    session = await db_client.get_session()
    try:
        update_query = text("""
            UPDATE calculations 
            SET created_at = NOW() - INTERVAL '12 hours'
            WHERE calculation_id = :calc_id
        """)
        await session.execute(update_query, {"calc_id": calculation_id})
        await session.commit()
    finally:
        await session.close()
    
    # Get DAU
    dau = await db_client.get_dau()
    assert dau >= 1  # At least our test user
    
    # Cleanup
    session = await db_client.get_session()
    try:
        await session.execute(text("DELETE FROM calculations WHERE calculation_id = :calc_id"), {"calc_id": calculation_id})
        await session.execute(text("DELETE FROM users WHERE user_id = :uid"), {"uid": user_id})
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_get_new_users_24h(db_client: DatabaseClient):
    """Test getting new users in last 24 hours."""
    user_id = 4001
    
    # Save user (should be created now, within 24h)
    await db_client.save_or_update_user(user_id, username="new_user_24h")
    
    # Get new users count
    new_users = await db_client.get_new_users_24h()
    assert new_users >= 1  # At least our test user
    
    # Cleanup
    session = await db_client.get_session()
    try:
        await session.execute(text("DELETE FROM users WHERE user_id = :uid"), {"uid": user_id})
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_get_calculations_24h_by_status(db_client: DatabaseClient):
    """Test getting calculations by status in last 24 hours."""
    user_id = 5001
    
    # Save user
    await db_client.save_or_update_user(user_id, username="status_user")
    
    # Create calculations with different statuses
    statuses = ["🟢", "🟡", "🟠", "🔴"]
    calculation_ids = []
    
    for i, status in enumerate(statuses):
        calc_id = f"test-status-{i}"
        calculation_ids.append(calc_id)
        await db_client.save_calculation(
            calculation_id=calc_id,
            user_id=user_id,
            article_id=12345 + i,
            calculation_type="express",
            status=status
        )
    
    # Get calculations by status
    calculations_by_status = await db_client.get_calculations_24h_by_status()
    
    # Check that all statuses are present
    for status in statuses:
        assert status in calculations_by_status
        assert calculations_by_status[status] >= 1
    
    # Cleanup
    session = await db_client.get_session()
    try:
        for calc_id in calculation_ids:
            await session.execute(text("DELETE FROM calculations WHERE calculation_id = :calc_id"), {"calc_id": calc_id})
        await session.execute(text("DELETE FROM users WHERE user_id = :uid"), {"uid": user_id})
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_get_total_calculations_24h(db_client: DatabaseClient):
    """Test getting total calculations in last 24 hours."""
    user_id = 6001
    
    # Save user
    await db_client.save_or_update_user(user_id, username="total_user")
    
    # Create multiple calculations
    calculation_ids = []
    for i in range(3):
        calc_id = f"test-total-{i}"
        calculation_ids.append(calc_id)
        await db_client.save_calculation(
            calculation_id=calc_id,
            user_id=user_id,
            article_id=12345 + i,
            calculation_type="express",
            status="🟢"
        )
    
    # Get total calculations
    total = await db_client.get_total_calculations_24h()
    assert total >= 3  # At least our test calculations
    
    # Cleanup
    session = await db_client.get_session()
    try:
        for calc_id in calculation_ids:
            await session.execute(text("DELETE FROM calculations WHERE calculation_id = :calc_id"), {"calc_id": calc_id})
        await session.execute(text("DELETE FROM users WHERE user_id = :uid"), {"uid": user_id})
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_get_mau_excludes_old_calculations(db_client: DatabaseClient):
    """Test that MAU excludes calculations older than 30 days."""
    user_id = 7001
    
    # Save user
    await db_client.save_or_update_user(user_id, username="old_user")
    
    # Create calculation 35 days ago (outside 30 days window)
    calculation_id = "test-mau-old"
    await db_client.save_calculation(
        calculation_id=calculation_id,
        user_id=user_id,
        article_id=12345,
        calculation_type="express",
        status="🟢"
    )
    
    # Manually set created_at to 35 days ago
    session = await db_client.get_session()
    try:
        update_query = text("""
            UPDATE calculations 
            SET created_at = NOW() - INTERVAL '35 days'
            WHERE calculation_id = :calc_id
        """)
        await session.execute(update_query, {"calc_id": calculation_id})
        await session.commit()
    finally:
        await session.close()
    
    # Get MAU before cleanup (to check it doesn't include old calculation)
    mau_before = await db_client.get_mau()
    
    # Cleanup
    session = await db_client.get_session()
    try:
        await session.execute(text("DELETE FROM calculations WHERE calculation_id = :calc_id"), {"calc_id": calculation_id})
        await session.execute(text("DELETE FROM users WHERE user_id = :uid"), {"uid": user_id})
        await session.commit()
    finally:
        await session.close()
    
    # Get MAU after cleanup
    mau_after = await db_client.get_mau()
    
    # MAU should be the same (old calculation shouldn't be counted)
    assert mau_before == mau_after


@pytest.mark.asyncio
async def test_statistics_with_no_data(db_client: DatabaseClient):
    """Test statistics methods return 0 when there's no data."""
    # Use a user_id that definitely doesn't exist
    # First, check that methods don't crash with empty results
    
    # These should return 0 or empty dict, not crash
    mau = await db_client.get_mau()
    assert isinstance(mau, int)
    assert mau >= 0
    
    wau = await db_client.get_wau()
    assert isinstance(wau, int)
    assert wau >= 0
    
    dau = await db_client.get_dau()
    assert isinstance(dau, int)
    assert dau >= 0
    
    new_users = await db_client.get_new_users_24h()
    assert isinstance(new_users, int)
    assert new_users >= 0
    
    calculations_by_status = await db_client.get_calculations_24h_by_status()
    assert isinstance(calculations_by_status, dict)
    
    total = await db_client.get_total_calculations_24h()
    assert isinstance(total, int)
    assert total >= 0


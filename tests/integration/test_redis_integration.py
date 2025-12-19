"""Integration tests for Redis."""
import pytest
import asyncio
from apps.bot_service.clients.redis import RedisClient


@pytest.mark.asyncio
async def test_redis_full_workflow(redis_client: RedisClient, clean_redis):
    """Test full Redis workflow."""
    calculation_id = "integration-test-123"
    user_id = 99999
    data = {"article_id": 111222, "user_id": user_id}
    
    # Set status
    await redis_client.set_calculation_status(calculation_id, "pending")
    status = await redis_client.get_calculation_status(calculation_id)
    assert status == "pending"
    
    # Push to queue
    await redis_client.push_calculation(calculation_id, data)
    
    # Set user current calculation
    await redis_client.set_user_current_calculation(user_id, calculation_id)
    user_calc = await redis_client.get_user_current_calculation(user_id)
    assert user_calc == calculation_id
    
    # Update status
    await redis_client.set_calculation_status(calculation_id, "processing")
    status = await redis_client.get_calculation_status(calculation_id)
    assert status == "processing"
    
    # Set result
    result = {"status": "completed", "result": "success"}
    await redis_client.set_calculation_result(calculation_id, result)
    retrieved = await redis_client.get_calculation_result(calculation_id)
    assert retrieved == result
    
    # Final status
    await redis_client.set_calculation_status(calculation_id, "completed")
    status = await redis_client.get_calculation_status(calculation_id)
    assert status == "completed"




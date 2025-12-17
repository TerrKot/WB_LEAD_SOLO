"""Tests for Redis client."""
import pytest
import json
from apps.bot_service.clients.redis import RedisClient


@pytest.mark.asyncio
async def test_redis_connection(redis_client: RedisClient):
    """Test Redis connection."""
    assert redis_client.redis is not None
    result = await redis_client.redis.ping()
    assert result is True


@pytest.mark.asyncio
async def test_set_get_calculation_status(redis_client: RedisClient, clean_redis):
    """Test setting and getting calculation status."""
    calculation_id = "test-calculation-123"
    status = "pending"
    
    await redis_client.set_calculation_status(calculation_id, status)
    result = await redis_client.get_calculation_status(calculation_id)
    
    assert result == status


@pytest.mark.asyncio
async def test_push_get_calculation(redis_client: RedisClient, clean_redis):
    """Test pushing and getting calculation from queue."""
    calculation_id = "test-calculation-456"
    data = {"article_id": 123456, "user_id": 789}
    
    await redis_client.push_calculation(calculation_id, data)
    
    # Get from queue
    result = await redis_client.redis.brpop("calculation_queue", timeout=1)
    assert result is not None
    
    _, task_json = result
    task = json.loads(task_json)
    
    assert task["calculation_id"] == calculation_id
    assert task["data"] == data


@pytest.mark.asyncio
async def test_set_get_calculation_result(redis_client: RedisClient, clean_redis):
    """Test setting and getting calculation result."""
    calculation_id = "test-calculation-789"
    result = {"status": "completed", "result": "test"}
    
    await redis_client.set_calculation_result(calculation_id, result, ttl=60)
    retrieved = await redis_client.get_calculation_result(calculation_id)
    
    assert retrieved == result


@pytest.mark.asyncio
async def test_user_current_calculation(redis_client: RedisClient, clean_redis):
    """Test setting and getting user current calculation."""
    user_id = 12345
    calculation_id = "test-calculation-user"
    
    await redis_client.set_user_current_calculation(user_id, calculation_id)
    result = await redis_client.get_user_current_calculation(user_id)
    
    assert result == calculation_id


@pytest.mark.asyncio
async def test_user_agreement_accepted(redis_client: RedisClient, clean_redis):
    """Test setting and checking user agreement acceptance."""
    user_id = 12345
    
    # Initially not accepted
    result = await redis_client.is_user_agreement_accepted(user_id)
    assert result is False
    
    # Accept agreement
    await redis_client.set_user_agreement_accepted(user_id)
    
    # Check acceptance
    result = await redis_client.is_user_agreement_accepted(user_id)
    assert result is True


@pytest.mark.asyncio
async def test_user_agreement_ttl(redis_client: RedisClient, clean_redis):
    """Test that user agreement has TTL."""
    import asyncio
    user_id = 12345
    
    # Accept agreement with short TTL
    await redis_client.set_user_agreement_accepted(user_id, ttl=1)
    
    # Check acceptance
    result = await redis_client.is_user_agreement_accepted(user_id)
    assert result is True
    
    # Wait for TTL to expire
    await asyncio.sleep(2)
    
    # Check that agreement expired
    result = await redis_client.is_user_agreement_accepted(user_id)
    assert result is False

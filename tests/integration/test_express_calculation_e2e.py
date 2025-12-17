"""End-to-end integration tests for express calculation workflow."""
import pytest
import uuid
import json
from unittest.mock import AsyncMock, MagicMock, patch
from apps.bot_service.clients.redis import RedisClient
from apps.bot_service.workers.calculation_worker import CalculationWorker
from apps.bot_service.services.input_parser import InputParser


@pytest.mark.asyncio
async def test_express_calculation_e2e_workflow(redis_client: RedisClient, clean_redis):
    """Test full express calculation workflow from input to result."""
    # Setup
    calculation_id = str(uuid.uuid4())
    user_id = 12345
    article_id = 154345562
    
    # Mock product data
    mock_product_data = {
        "id": article_id,
        "name": "Тестовый товар",
        "price": 100000,  # 1000 RUB in kopecks
        "weight": 1.5,
        "volume": 0.015,
        "description": "Описание товара"
    }
    
    # Mock GPT service responses (async methods)
    with patch('apps.bot_service.workers.calculation_worker.GPTService.get_tn_ved_code', new_callable=AsyncMock) as mock_gpt_tnved:
        mock_gpt_tnved.return_value = {
            "tnved_code": "6402120000",
            "duty_type": "ad valorem",
            "duty_rate": 5.0,
            "vat_rate": 20.0
        }
        
        with patch('apps.bot_service.workers.calculation_worker.GPTService.check_orange_zone', new_callable=AsyncMock) as mock_gpt_orange:
            mock_gpt_orange.return_value = {"pass": 1, "reason": ""}
                
            # Initialize worker
            worker = CalculationWorker("redis://localhost:6380/1")
            await worker.connect()
            
            try:
                # Step 1: Set initial status
                await redis_client.set_calculation_status(calculation_id, "pending")
                await redis_client.set_user_current_calculation(user_id, calculation_id)
                
                # Step 2: Prepare calculation data
                calculation_data = {
                    "user_id": user_id,
                    "calculation_type": "express",
                    "input_data": {
                        "article_id": article_id,
                        "input_text": str(article_id)
                    }
                }
                
                # Step 3: Save product data (as JSON string, as worker expects)
                await redis_client.redis.setex(
                    f"calculation:{calculation_id}:product_data",
                    3600,
                    json.dumps(mock_product_data)
                )
                
                # Step 4: Process calculation
                await worker.process_calculation(calculation_id, calculation_data)
                
                # Step 5: Verify status
                status = await redis_client.get_calculation_status(calculation_id)
                assert status == "completed"
                
                # Step 6: Verify result
                result = await redis_client.get_calculation_result(calculation_id)
                assert result is not None
                assert "status" in result
                assert result["status"] in ["🟢", "🟡", "🟠", "🔴"]
                assert "product_data" in result
                assert result["product_data"]["id"] == article_id
                
            finally:
                await worker.disconnect()


@pytest.mark.asyncio
async def test_express_calculation_red_zone_block(redis_client: RedisClient, clean_redis):
    """Test express calculation with red zone block."""
    calculation_id = str(uuid.uuid4())
    user_id = 12345
    article_id = 154345562
    
    mock_product_data = {
        "id": article_id,
        "name": "Тестовый товар",
        "price": 100000,
        "weight": 1.5,
        "volume": 0.015,
        "description": "Описание товара"
    }
    
    with patch('apps.bot_service.workers.calculation_worker.GPTService.get_tn_ved_code', new_callable=AsyncMock) as mock_gpt_tnved:
        # Return code that should be in red zone (batteries example: 8506500000)
        mock_gpt_tnved.return_value = {
            "tnved_code": "8506500000",
            "duty_type": "ad valorem",
            "duty_rate": 5.0,
            "vat_rate": 20.0
        }
            
        worker = CalculationWorker("redis://localhost:6380/1")
        await worker.connect()
        
        try:
            await redis_client.set_calculation_status(calculation_id, "pending")
            
            calculation_data = {
                "user_id": user_id,
                "calculation_type": "express",
                "input_data": {
                    "article_id": article_id,
                    "input_text": str(article_id)
                }
            }
            
            # Save product data as JSON string
            await redis_client.redis.setex(
                f"calculation:{calculation_id}:product_data",
                3600,
                json.dumps(mock_product_data)
            )
            
            await worker.process_calculation(calculation_id, calculation_data)
            
            status = await redis_client.get_calculation_status(calculation_id)
            assert status == "completed"
            
            result = await redis_client.get_calculation_result(calculation_id)
            assert result is not None
            assert result["status"] == "🔴"
            
        finally:
            await worker.disconnect()


@pytest.mark.asyncio
async def test_input_parser_integration():
    """Test input parser with various formats."""
    # Test URL parsing
    article_id = InputParser.extract_article_from_url("https://www.wildberries.ru/catalog/154345562/detail.aspx")
    assert article_id == 154345562
    
    # Test plain number
    article_id = InputParser.extract_article_from_text("154345562")
    assert article_id == 154345562
    
    # Test number with text
    article_id = InputParser.extract_article_from_text("Артикул: 154345562")
    assert article_id == 154345562
    
    # Test invalid input
    article_id = InputParser.extract_article_from_text("invalid")
    assert article_id is None


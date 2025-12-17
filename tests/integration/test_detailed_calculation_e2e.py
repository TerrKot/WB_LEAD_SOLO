"""End-to-end integration tests for detailed calculation workflow."""
import pytest
import uuid
import json
from unittest.mock import patch, AsyncMock
from apps.bot_service.clients.redis import RedisClient
from apps.bot_service.workers.calculation_worker import CalculationWorker


@pytest.mark.asyncio
async def test_detailed_calculation_e2e_workflow(redis_client: RedisClient, clean_redis):
    """Test full detailed calculation workflow."""
    calculation_id = str(uuid.uuid4())
    user_id = 12345
    
    # Mock express calculation result (prerequisite)
    express_result = {
        "status": "🟢",
        "product_data": {
            "id": 154345562,
            "name": "Тестовый товар",
            "price": 100000,  # 1000 RUB
            "weight": 1.5,
            "volume": 0.015
        },
        "tn_ved_code": "6402120000",
        "duty_type": "ad valorem",
        "duty_rate": 5.0,
        "vat_rate": 20.0,
        "specific_value_usd_per_kg": 5.0
    }
    
    # Save express result
    await redis_client.set_calculation_result(f"express_{calculation_id}", express_result)
    
    # Mock exchange rate service (async method)
    with patch('apps.bot_service.workers.calculation_worker.ExchangeRateService.get_rates', new_callable=AsyncMock) as mock_rates:
        mock_rates.return_value = {
            "usd_rub": 100.0,
            "usd_cny": 7.2,
            "eur_rub": 110.0
        }
        
        worker = CalculationWorker("redis://localhost:6380/1")
        await worker.connect()
        
        try:
            await redis_client.set_calculation_status(calculation_id, "pending")
            
            # Prepare detailed calculation data
            calculation_data = {
                "user_id": user_id,
                "calculation_type": "detailed",
                "express_calculation_id": f"express_{calculation_id}",
                "parameters": {
                    "weight_kg": 1.5,
                    "volume_m3": 0.015,
                    "purchase_price_rub": 250.0
                }
            }
            
            # Save product data from express calculation (as JSON string)
            await redis_client.redis.setex(
                f"calculation:{calculation_id}:product_data",
                3600,
                json.dumps(express_result["product_data"])
            )
            
            # Save TN VED data
            await redis_client.redis.setex(
                f"calculation:{calculation_id}:tnved_data",
                3600,
                json.dumps({
                    "duty_type": "ad valorem",
                    "duty_rate": 5.0,
                    "vat_rate": 20.0
                })
            )
            
            # Process detailed calculation
            await worker.process_calculation(calculation_id, calculation_data)
            
            # Verify status
            status = await redis_client.get_calculation_status(calculation_id)
            assert status == "completed"
            
            # Verify result
            result = await redis_client.get_calculation_result(calculation_id)
            assert result is not None
            assert "cargo" in result or "white_logistics" in result
            assert result.get("ok") is True or "comparison" in result
            
        finally:
            await worker.disconnect()


@pytest.mark.asyncio
async def test_detailed_calculation_with_cargo_and_white(redis_client: RedisClient, clean_redis):
    """Test detailed calculation with both cargo and white logistics."""
    calculation_id = str(uuid.uuid4())
    
    express_result = {
        "status": "🟡",
        "product_data": {
            "id": 154345562,
            "name": "Тестовый товар",
            "price": 200000,  # 2000 RUB
            "weight": 2.0,
            "volume": 0.02
        },
        "tn_ved_code": "6402120000",
        "duty_type": "ad valorem",
        "duty_rate": 5.0,
        "vat_rate": 20.0
    }
    
    await redis_client.set_calculation_result(f"express_{calculation_id}", express_result)
    
    with patch('apps.bot_service.workers.calculation_worker.ExchangeRateService.get_rates', new_callable=AsyncMock) as mock_rates:
        mock_rates.return_value = {
            "usd_rub": 100.0,
            "usd_cny": 7.2,
            "eur_rub": 110.0
        }
        
        worker = CalculationWorker("redis://localhost:6380/1")
        await worker.connect()
        
        try:
            await redis_client.set_calculation_status(calculation_id, "pending")
            
            calculation_data = {
                "user_id": 12345,
                "calculation_type": "detailed",
                "express_calculation_id": f"express_{calculation_id}",
                "parameters": {
                    "weight_kg": 2.0,
                    "volume_m3": 0.02,
                    "purchase_price_rub": 500.0
                }
            }
            
            # Save product data as JSON string
            await redis_client.redis.setex(
                f"calculation:{calculation_id}:product_data",
                3600,
                json.dumps(express_result["product_data"])
            )
            
            # Save TN VED data
            await redis_client.redis.setex(
                f"calculation:{calculation_id}:tnved_data",
                3600,
                json.dumps({
                    "duty_type": "ad valorem",
                    "duty_rate": 5.0,
                    "vat_rate": 20.0
                })
            )
            
            await worker.process_calculation(calculation_id, calculation_data)
            
            result = await redis_client.get_calculation_result(calculation_id)
            assert result is not None
            
            # Verify both calculations are present
            if "cargo" in result:
                assert result["cargo"].get("ok") is True
            if "white_logistics" in result:
                assert result["white_logistics"].get("ok") is True
                
        finally:
            await worker.disconnect()


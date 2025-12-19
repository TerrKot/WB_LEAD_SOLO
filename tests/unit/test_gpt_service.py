"""Unit tests for GPT Service."""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import json
import aiohttp

from apps.bot_service.services.gpt_service import GPTService


class TestGPTService:
    """Test cases for GPTService."""

    @pytest.fixture
    def gpt_service(self):
        """Create GPTService instance with test config."""
        return GPTService(
            api_key="test-api-key",
            api_url="https://api.openai.com/v1/chat/completions",
            model="gpt-4o-mini"
        )

    @pytest.fixture
    def sample_gpt_response(self):
        """Sample GPT API response."""
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"weight": 1.5, "volume": 2.0}'
                    }
                }
            ]
        }

    @pytest.fixture
    def sample_gpt_response_with_markdown(self):
        """Sample GPT API response with markdown code blocks."""
        return {
            "choices": [
                {
                    "message": {
                        "content": '```json\n{"weight": 2.0, "volume": 3.5}\n```'
                    }
                }
            ]
        }

    @pytest.mark.asyncio
    async def test_get_weight_volume_success(self, gpt_service, sample_gpt_response):
        """Test successful weight/volume retrieval."""
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = sample_gpt_response
            
            result = await gpt_service.get_weight_volume("Тестовый товар")
            
            assert result is not None
            assert result["weight"] == 1.5
            assert result["volume"] == 2.0
            mock_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_weight_volume_with_markdown(self, gpt_service, sample_gpt_response_with_markdown):
        """Test weight/volume retrieval with markdown code blocks."""
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = sample_gpt_response_with_markdown
            
            result = await gpt_service.get_weight_volume("Тестовый товар")
            
            assert result is not None
            assert result["weight"] == 2.0
            assert result["volume"] == 3.5

    @pytest.mark.asyncio
    async def test_get_weight_volume_with_description(self, gpt_service, sample_gpt_response):
        """Test weight/volume retrieval with product description."""
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = sample_gpt_response
            
            result = await gpt_service.get_weight_volume(
                "Тестовый товар",
                "Описание товара"
            )
            
            assert result is not None
            assert result["weight"] == 1.5
            assert result["volume"] == 2.0

    @pytest.mark.asyncio
    async def test_get_weight_volume_api_error(self, gpt_service):
        """Test handling API error."""
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = None
            
            result = await gpt_service.get_weight_volume("Тестовый товар")
            
            assert result is None

    @pytest.mark.asyncio
    async def test_get_weight_volume_invalid_json(self, gpt_service):
        """Test handling invalid JSON response."""
        invalid_response = {
            "choices": [
                {
                    "message": {
                        "content": "Invalid JSON response"
                    }
                }
            ]
        }
        
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = invalid_response
            
            result = await gpt_service.get_weight_volume("Тестовый товар")
            
            assert result is None

    @pytest.mark.asyncio
    async def test_get_weight_volume_missing_fields(self, gpt_service):
        """Test handling response with missing fields."""
        incomplete_response = {
            "choices": [
                {
                    "message": {
                        "content": '{"weight": 1.5}'
                    }
                }
            ]
        }
        
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = incomplete_response
            
            result = await gpt_service.get_weight_volume("Тестовый товар")
            
            assert result is None

    @pytest.mark.asyncio
    async def test_get_weight_volume_invalid_values(self, gpt_service):
        """Test handling invalid (non-positive) values."""
        invalid_response = {
            "choices": [
                {
                    "message": {
                        "content": '{"weight": -1.0, "volume": 0}'
                    }
                }
            ]
        }
        
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = invalid_response
            
            result = await gpt_service.get_weight_volume("Тестовый товар")
            
            assert result is None

    @pytest.mark.asyncio
    async def test_call_gpt_api_success(self, gpt_service):
        """Test successful GPT API call."""
        mock_response_data = {
            "choices": [
                {
                    "message": {
                        "content": '{"weight": 1.5, "volume": 2.0}'
                    }
                }
            ]
        }
        
        # Create a proper async context manager for the response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_response_data)
        mock_response.text = AsyncMock(return_value="")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        
        # Create a proper async context manager for the post call
        mock_post_result = MagicMock()
        mock_post_result.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_result.__aexit__ = AsyncMock(return_value=None)
        
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        
        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await gpt_service._call_gpt_api("Test prompt")
            
            assert result is not None
            assert "choices" in result

    @pytest.mark.asyncio
    async def test_call_gpt_api_error_status(self, gpt_service):
        """Test handling API error status."""
        mock_response = AsyncMock()
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="Bad Request")
        
        mock_session = AsyncMock()
        mock_session.post = AsyncMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        
        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await gpt_service._call_gpt_api("Test prompt")
            
            assert result is None

    @pytest.mark.asyncio
    async def test_call_gpt_api_timeout(self, gpt_service):
        """Test handling timeout."""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session_class.side_effect = asyncio.TimeoutError()
            
            result = await gpt_service._call_gpt_api("Test prompt")
            
            assert result is None

    @pytest.mark.asyncio
    async def test_call_gpt_api_client_error(self, gpt_service):
        """Test handling client error."""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session_class.side_effect = aiohttp.ClientError("Connection error")
            
            result = await gpt_service._call_gpt_api("Test prompt")
            
            assert result is None

    def test_init_with_config(self):
        """Test initialization with config values."""
        # Mock config to have GPT_API_KEY
        with patch("apps.bot_service.services.gpt_service.config") as mock_config:
            mock_config.GPT_API_KEY = "test-key-from-config"
            mock_config.GPT_API_URL = "https://api.openai.com/v1/chat/completions"
            mock_config.GPT_MODEL = "gpt-4o-mini"
            
            service = GPTService()
            # Should use config values if not provided
            assert service.api_key == "test-key-from-config"
            assert service.api_url is not None
            assert service.model is not None

    def test_init_with_custom_values(self):
        """Test initialization with custom values."""
        service = GPTService(
            api_key="custom-key",
            api_url="custom-url",
            model="custom-model"
        )
        
        assert service.api_key == "custom-key"
        assert service.api_url == "custom-url"
        assert service.model == "custom-model"

    @pytest.fixture
    def sample_tn_ved_response(self):
        """Sample GPT API response for TN VED code (only code, no duties)."""
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"tn_ved_code": "4202120000"}'
                    }
                }
            ]
        }

    @pytest.fixture
    def sample_tn_ved_response_with_markdown(self):
        """Sample GPT API response with markdown code blocks for TN VED (only code)."""
        return {
            "choices": [
                {
                    "message": {
                        "content": '```json\n{"tn_ved_code": "4202120000"}\n```'
                    }
                }
            ]
        }
    
    @pytest.fixture
    def sample_duty_info(self):
        """Sample duty info from ifcg.ru parsing."""
        return {
            "duty_type": "ad_valorem",
            "duty_rate": 5.0,
            "vat_rate": 20.0
        }

    @pytest.mark.asyncio
    async def test_get_tn_ved_code_success(self, gpt_service, sample_tn_ved_response, sample_duty_info):
        """Test successful TN VED code retrieval."""
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call, \
             patch.object(gpt_service, "_parse_ifcg_duty", new_callable=AsyncMock) as mock_parse:
            mock_call.return_value = sample_tn_ved_response
            mock_parse.return_value = sample_duty_info
            
            result = await gpt_service.get_tn_ved_code({"name": "Рюкзак городской"})
            
            assert result is not None
            assert result["tn_ved_code"] == "4202120000"
            assert result["duty_type"] == "ad_valorem"
            assert result["duty_rate"] == 5.0
            assert result["vat_rate"] == 20.0
            mock_call.assert_called_once()
            mock_parse.assert_called_once_with("4202120000")

    @pytest.mark.asyncio
    async def test_get_tn_ved_code_with_markdown(self, gpt_service, sample_tn_ved_response_with_markdown, sample_duty_info):
        """Test TN VED code retrieval with markdown code blocks."""
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call, \
             patch.object(gpt_service, "_parse_ifcg_duty", new_callable=AsyncMock) as mock_parse:
            mock_call.return_value = sample_tn_ved_response_with_markdown
            mock_parse.return_value = sample_duty_info
            
            result = await gpt_service.get_tn_ved_code({"name": "Рюкзак городской"})
            
            assert result is not None
            assert result["tn_ved_code"] == "4202120000"
            assert result["duty_type"] == "ad_valorem"
            assert result["duty_rate"] == 5.0
            assert result["vat_rate"] == 20.0

    @pytest.mark.asyncio
    async def test_get_tn_ved_code_with_all_params(self, gpt_service, sample_tn_ved_response, sample_duty_info):
        """Test TN VED code retrieval with all optional parameters."""
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call, \
             patch.object(gpt_service, "_parse_ifcg_duty", new_callable=AsyncMock) as mock_parse:
            mock_call.return_value = sample_tn_ved_response
            mock_parse.return_value = sample_duty_info
            
            result = await gpt_service.get_tn_ved_code({
                "name": "Рюкзак",
                "description": "Городской рюкзак для ноутбука",
                "brand": "TestBrand",
                "weight": 1.5,
                "volume": 2
            })
            
            assert result is not None
            assert result["tn_ved_code"] == "4202120000"
            assert result["duty_type"] == "ad_valorem"
            assert result["duty_rate"] == 5.0
            assert result["vat_rate"] == 20.0
            # Может быть вызван 1 или 2 раза (второй раз для кандидатов при fallback)
            assert mock_call.call_count >= 1
            mock_parse.assert_called_once_with("4202120000")

    @pytest.mark.asyncio
    async def test_get_tn_ved_code_api_error(self, gpt_service):
        """Test handling API error for TN VED code."""
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = None
            
            result = await gpt_service.get_tn_ved_code({"name": "Тестовый товар"})
            
            assert result is None

    @pytest.mark.asyncio
    async def test_get_tn_ved_code_invalid_json(self, gpt_service):
        """Test handling invalid JSON response for TN VED code."""
        invalid_response = {
            "choices": [
                {
                    "message": {
                        "content": "Invalid JSON response"
                    }
                }
            ]
        }
        
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = invalid_response
            
            result = await gpt_service.get_tn_ved_code({"name": "Тестовый товар"})
            
            assert result is None

    @pytest.mark.asyncio
    async def test_get_tn_ved_code_missing_fields(self, gpt_service, sample_duty_info):
        """Test handling response with missing tn_ved_code field."""
        incomplete_response = {
            "choices": [
                {
                    "message": {
                        "content": '{"duty_type": "ad_valorem"}'
                    }
                }
            ]
        }
        
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = incomplete_response
            
            result = await gpt_service.get_tn_ved_code({"name": "Тестовый товар"})
            
            assert result is None

    @pytest.mark.asyncio
    async def test_get_tn_ved_code_invalid_code_format(self, gpt_service):
        """Test handling invalid TN VED code format (not 10 digits)."""
        invalid_response = {
            "choices": [
                {
                    "message": {
                        "content": '{"tn_ved_code": "42021", "duty_type": "ad_valorem", "duty_rate": 5.0, "vat_rate": 20.0}'
                    }
                }
            ]
        }
        
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = invalid_response
            
            result = await gpt_service.get_tn_ved_code({"name": "Тестовый товар"})
            
            assert result is None

    @pytest.mark.asyncio
    async def test_get_tn_ved_code_invalid_duty_type(self, gpt_service, sample_duty_info):
        """Test handling invalid section in code (validation happens before parsing)."""
        invalid_response = {
            "choices": [
                {
                    "message": {
                        "content": '{"tn_ved_code": "9900000000"}'  # Invalid section (99 > 97)
                    }
                }
            ]
        }
        
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = invalid_response
            
            result = await gpt_service.get_tn_ved_code({"name": "Тестовый товар"})
            
            assert result is None

    @pytest.mark.asyncio
    async def test_get_tn_ved_code_negative_rates(self, gpt_service, sample_duty_info):
        """Test handling invalid code format (not 10 digits)."""
        invalid_response = {
            "choices": [
                {
                    "message": {
                        "content": '{"tn_ved_code": "42021"}'  # Not 10 digits
                    }
                }
            ]
        }
        
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = invalid_response
            
            result = await gpt_service.get_tn_ved_code({"name": "Тестовый товар"})
            
            assert result is None

    @pytest.mark.asyncio
    async def test_get_tn_ved_code_exempt_duty(self, gpt_service):
        """Test handling exempt duty type (duty_rate = 0.0)."""
        exempt_response = {
            "choices": [
                {
                    "message": {
                        "content": '{"tn_ved_code": "4202120000"}'
                    }
                }
            ]
        }
        exempt_duty_info = {
            "duty_type": "exempt",
            "duty_rate": 0.0,
            "vat_rate": 20.0
        }
        
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call, \
             patch.object(gpt_service, "_parse_ifcg_duty", new_callable=AsyncMock) as mock_parse:
            mock_call.return_value = exempt_response
            mock_parse.return_value = exempt_duty_info
            
            result = await gpt_service.get_tn_ved_code({"name": "Тестовый товар"})
            
            assert result is not None
            assert result["duty_type"] == "exempt"
            assert result["duty_rate"] == 0.0
            assert result["vat_rate"] == 20.0

    @pytest.mark.asyncio
    async def test_get_tn_ved_code_combined_duty(self, gpt_service):
        """Test handling combined duty type."""
        combined_response = {
            "choices": [
                {
                    "message": {
                        "content": '{"tn_ved_code": "4202120000"}'
                    }
                }
            ]
        }
        combined_duty_info = {
            "duty_type": "combined",
            "duty_rate": 10.0,
            "vat_rate": 20.0
        }
        
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call, \
             patch.object(gpt_service, "_parse_ifcg_duty", new_callable=AsyncMock) as mock_parse:
            mock_call.return_value = combined_response
            mock_parse.return_value = combined_duty_info
            
            result = await gpt_service.get_tn_ved_code({"name": "Тестовый товар"})
            
            assert result is not None
            assert result["duty_type"] == "combined"
            assert result["duty_rate"] == 10.0
            assert result["vat_rate"] == 20.0

    @pytest.mark.asyncio
    async def test_check_orange_zone_pass_0_in_orange_zone(self, gpt_service):
        """Test orange zone check when product is in orange zone (pass = 0)."""
        orange_zone_response = {
            "choices": [
                {
                    "message": {
                        "content": '{"pass": 0, "reason": "🟠 Товар подлежит обязательной маркировке «Честный знак»"}'
                    }
                }
            ]
        }
        
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = orange_zone_response
            
            result = await gpt_service.check_orange_zone(
                product_name="Тестовый товар",
                tn_ved_code="6402120000",
                duty_type="ad_valorem"
            )
            
            assert result is not None
            assert result["pass"] == 0
            assert "reason" in result
            assert "🟠" in result["reason"] or "Честный знак" in result["reason"]

    @pytest.mark.asyncio
    async def test_check_orange_zone_pass_1_not_in_orange_zone(self, gpt_service):
        """Test orange zone check when product is not in orange zone (pass = 1)."""
        not_orange_zone_response = {
            "choices": [
                {
                    "message": {
                        "content": '{"pass": 1, "reason": "Товар не требует маркировки «Честный знак» и не имеет евроставки"}'
                    }
                }
            ]
        }
        
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = not_orange_zone_response
            
            result = await gpt_service.check_orange_zone(
                product_name="Тестовый товар",
                tn_ved_code="6402120000",
                duty_type="ad_valorem"
            )
            
            assert result is not None
            assert result["pass"] == 1
            assert "reason" in result

    @pytest.mark.asyncio
    async def test_check_orange_zone_with_euro_duty(self, gpt_service):
        """Test orange zone check when product has euro duty (specific or combined)."""
        orange_zone_response = {
            "choices": [
                {
                    "message": {
                        "content": '{"pass": 0, "reason": "🟠 Товар имеет евроставку (специфическую пошлину), что является признаком оранжевой зоны"}'
                    }
                }
            ]
        }
        
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = orange_zone_response
            
            result = await gpt_service.check_orange_zone(
                product_name="Тестовый товар",
                tn_ved_code="6402120000",
                duty_type="specific"
            )
            
            assert result is not None
            assert result["pass"] == 0
            assert "reason" in result

    @pytest.mark.asyncio
    async def test_check_orange_zone_with_combined_duty(self, gpt_service):
        """Test orange zone check when product has combined duty."""
        orange_zone_response = {
            "choices": [
                {
                    "message": {
                        "content": '{"pass": 0, "reason": "🟠 Товар имеет комбинированную пошлину, что является признаком оранжевой зоны"}'
                    }
                }
            ]
        }
        
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = orange_zone_response
            
            result = await gpt_service.check_orange_zone(
                product_name="Тестовый товар",
                tn_ved_code="6402120000",
                duty_type="combined"
            )
            
            assert result is not None
            assert result["pass"] == 0
            assert "reason" in result

    @pytest.mark.asyncio
    async def test_check_orange_zone_with_all_params(self, gpt_service):
        """Test orange zone check with all optional parameters."""
        not_orange_zone_response = {
            "choices": [
                {
                    "message": {
                        "content": '{"pass": 1, "reason": "Товар не требует маркировки"}'
                    }
                }
            ]
        }
        
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = not_orange_zone_response
            
            result = await gpt_service.check_orange_zone(
                product_name="Тестовый товар",
                tn_ved_code="6402120000",
                duty_type="ad_valorem",
                product_description="Описание товара",
                product_brand="Бренд"
            )
            
            assert result is not None
            assert result["pass"] == 1
            # Verify that GPT was called with context including description and brand
            assert mock_call.called

    @pytest.mark.asyncio
    async def test_check_orange_zone_api_error(self, gpt_service):
        """Test orange zone check when API returns error."""
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = None
            
            result = await gpt_service.check_orange_zone(
                product_name="Тестовый товар",
                tn_ved_code="6402120000",
                duty_type="ad_valorem"
            )
            
            assert result is None

    @pytest.mark.asyncio
    async def test_check_orange_zone_invalid_json(self, gpt_service):
        """Test orange zone check when GPT returns invalid JSON."""
        invalid_json_response = {
            "choices": [
                {
                    "message": {
                        "content": "Invalid JSON response"
                    }
                }
            ]
        }
        
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = invalid_json_response
            
            result = await gpt_service.check_orange_zone(
                product_name="Тестовый товар",
                tn_ved_code="6402120000",
                duty_type="ad_valorem"
            )
            
            assert result is None

    @pytest.mark.asyncio
    async def test_check_orange_zone_missing_fields(self, gpt_service):
        """Test orange zone check when response is missing required fields."""
        missing_fields_response = {
            "choices": [
                {
                    "message": {
                        "content": '{"pass": 0}'
                    }
                }
            ]
        }
        
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = missing_fields_response
            
            result = await gpt_service.check_orange_zone(
                product_name="Тестовый товар",
                tn_ved_code="6402120000",
                duty_type="ad_valorem"
            )
            
            assert result is None

    @pytest.mark.asyncio
    async def test_check_orange_zone_invalid_pass_value(self, gpt_service):
        """Test orange zone check when pass value is invalid."""
        invalid_pass_response = {
            "choices": [
                {
                    "message": {
                        "content": '{"pass": 2, "reason": "Invalid pass value"}'
                    }
                }
            ]
        }
        
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = invalid_pass_response
            
            result = await gpt_service.check_orange_zone(
                product_name="Тестовый товар",
                tn_ved_code="6402120000",
                duty_type="ad_valorem"
            )
            
            assert result is None

    @pytest.mark.asyncio
    async def test_check_orange_zone_with_markdown(self, gpt_service):
        """Test orange zone check when response contains markdown code blocks."""
        markdown_response = {
            "choices": [
                {
                    "message": {
                        "content": '```json\n{"pass": 1, "reason": "Товар не в оранжевой зоне"}\n```'
                    }
                }
            ]
        }
        
        with patch.object(gpt_service, "_call_gpt_api", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = markdown_response
            
            result = await gpt_service.check_orange_zone(
                product_name="Тестовый товар",
                tn_ved_code="6402120000",
                duty_type="ad_valorem"
            )
            
            assert result is not None
            assert result["pass"] == 1
            assert "reason" in result


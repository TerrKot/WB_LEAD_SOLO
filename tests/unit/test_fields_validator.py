"""Unit tests for Fields Validator."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from apps.bot_service.services.fields_validator import FieldsValidator, REQUIRED_FIELDS
from apps.bot_service.services.wb_parser import WBParserService


class TestFieldsValidator:
    """Test cases for FieldsValidator."""

    @pytest.fixture
    def wb_parser(self):
        """Create WBParserService instance."""
        return WBParserService()

    @pytest.fixture
    def sample_product_complete(self):
        """Sample product with all required fields."""
        return {
            "id": 154345562,
            "name": "Тестовый товар",
            "weight": 1.5,
            "volume": 2,
            "sizes": [
                {
                    "price": {
                        "product": 100000,  # 1000 rub in kopecks
                        "basic": 120000
                    }
                }
            ],
            "subjectId": 1,
            "subjectParentId": 1
        }

    @pytest.fixture
    def sample_product_missing_weight_volume(self):
        """Sample product missing weight and volume."""
        return {
            "id": 154345562,
            "name": "Тестовый товар",
            "weight": None,
            "volume": None,
            "sizes": [
                {
                    "price": {
                        "product": 100000,
                        "basic": 120000
                    }
                }
            ],
            "subjectId": 1,
            "subjectParentId": 1
        }

    @pytest.fixture
    def sample_product_missing_price(self):
        """Sample product missing price."""
        return {
            "id": 154345562,
            "name": "Тестовый товар",
            "weight": 1.5,
            "volume": 2,
            "sizes": [],
            "subjectId": 1,
            "subjectParentId": 1
        }

    @pytest.fixture
    def sample_product_missing_name(self):
        """Sample product missing name."""
        return {
            "id": 154345562,
            "name": "",
            "weight": 1.5,
            "volume": 2,
            "sizes": [
                {
                    "price": {
                        "product": 100000
                    }
                }
            ],
            "subjectId": 1,
            "subjectParentId": 1
        }

    @pytest.fixture
    def mock_gpt_service(self):
        """Create mock GPT service."""
        gpt_service = MagicMock()
        gpt_service.get_weight_volume = AsyncMock()
        return gpt_service

    @pytest.mark.asyncio
    async def test_validate_complete_product(self, sample_product_complete, mock_gpt_service):
        """Test validation of product with all required fields."""
        validator = FieldsValidator(gpt_service=mock_gpt_service)
        
        is_valid, missing_fields, product = await validator.validate_and_fill_fields(
            sample_product_complete
        )
        
        assert is_valid is True
        assert len(missing_fields) == 0
        assert product["id"] == 154345562
        # GPT should not be called for complete product
        mock_gpt_service.get_weight_volume.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_missing_weight_volume_gpt_success(
        self, sample_product_missing_weight_volume, mock_gpt_service
    ):
        """Test validation when weight/volume missing and GPT succeeds."""
        mock_gpt_service.get_weight_volume.return_value = {
            "weight": 2.0,
            "volume": 3.0
        }
        
        validator = FieldsValidator(gpt_service=mock_gpt_service)
        
        is_valid, missing_fields, product = await validator.validate_and_fill_fields(
            sample_product_missing_weight_volume
        )
        
        assert is_valid is True
        assert len(missing_fields) == 0
        assert product["weight"] == 2.0
        assert product["volume"] == 3  # Converted to int
        mock_gpt_service.get_weight_volume.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_missing_weight_volume_gpt_failed(
        self, sample_product_missing_weight_volume, mock_gpt_service
    ):
        """Test validation when weight/volume missing and GPT fails."""
        mock_gpt_service.get_weight_volume.return_value = None
        
        validator = FieldsValidator(gpt_service=mock_gpt_service)
        
        is_valid, missing_fields, product = await validator.validate_and_fill_fields(
            sample_product_missing_weight_volume
        )
        
        assert is_valid is False
        assert "weight" in missing_fields or "volume" in missing_fields
        mock_gpt_service.get_weight_volume.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_missing_weight_only(self, mock_gpt_service):
        """Test validation when only weight is missing."""
        product = {
            "id": 154345562,
            "name": "Тестовый товар",
            "weight": None,
            "volume": 2,
            "sizes": [
                {
                    "price": {
                        "product": 100000
                    }
                }
            ],
            "subjectId": 1,
            "subjectParentId": 1
        }
        
        mock_gpt_service.get_weight_volume.return_value = {
            "weight": 1.5,
            "volume": 2.0
        }
        
        validator = FieldsValidator(gpt_service=mock_gpt_service)
        
        is_valid, missing_fields, product_result = await validator.validate_and_fill_fields(product)
        
        assert is_valid is True
        assert len(missing_fields) == 0
        assert product_result["weight"] == 1.5
        assert product_result["volume"] == 2  # Original value preserved

    @pytest.mark.asyncio
    async def test_validate_missing_volume_only(self, mock_gpt_service):
        """Test validation when only volume is missing."""
        product = {
            "id": 154345562,
            "name": "Тестовый товар",
            "weight": 1.5,
            "volume": None,
            "sizes": [
                {
                    "price": {
                        "product": 100000
                    }
                }
            ],
            "subjectId": 1,
            "subjectParentId": 1
        }
        
        mock_gpt_service.get_weight_volume.return_value = {
            "weight": 1.5,
            "volume": 3.0
        }
        
        validator = FieldsValidator(gpt_service=mock_gpt_service)
        
        is_valid, missing_fields, product_result = await validator.validate_and_fill_fields(product)
        
        assert is_valid is True
        assert len(missing_fields) == 0
        assert product_result["weight"] == 1.5  # Original value preserved
        assert product_result["volume"] == 3  # Filled from GPT

    @pytest.mark.asyncio
    async def test_validate_missing_price(self, sample_product_missing_price, mock_gpt_service):
        """Test validation when price is missing."""
        validator = FieldsValidator(gpt_service=mock_gpt_service)
        
        is_valid, missing_fields, product = await validator.validate_and_fill_fields(
            sample_product_missing_price
        )
        
        assert is_valid is False
        assert "price" in missing_fields
        # GPT should not be called if price is missing
        mock_gpt_service.get_weight_volume.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_missing_name(self, sample_product_missing_name, mock_gpt_service):
        """Test validation when name is missing."""
        validator = FieldsValidator(gpt_service=mock_gpt_service)
        
        is_valid, missing_fields, product = await validator.validate_and_fill_fields(
            sample_product_missing_name
        )
        
        assert is_valid is False
        assert "name" in missing_fields
        # GPT should not be called if name is missing
        mock_gpt_service.get_weight_volume.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_multiple_missing_fields(self, mock_gpt_service):
        """Test validation when multiple fields are missing."""
        product = {
            "id": 154345562,
            "name": "",  # Missing
            "weight": None,  # Missing
            "volume": None,  # Missing
            "sizes": [],  # Missing price
            "subjectId": 1,
            "subjectParentId": 1
        }
        
        validator = FieldsValidator(gpt_service=mock_gpt_service)
        
        is_valid, missing_fields, product_result = await validator.validate_and_fill_fields(product)
        
        assert is_valid is False
        # Should have multiple missing fields
        assert len(missing_fields) > 1
        # GPT may be called even if name/price missing, but it will fail validation anyway
        # The important thing is that validation fails
        assert "price" in missing_fields or "name" in missing_fields

    def test_has_field_price(self, mock_gpt_service):
        """Test _has_field for price."""
        validator = FieldsValidator(gpt_service=mock_gpt_service)
        
        # Product with price
        product_with_price = {
            "sizes": [
                {
                    "price": {
                        "product": 100000
                    }
                }
            ]
        }
        assert validator._has_field(product_with_price, "price") is True
        
        # Product without price
        product_without_price = {
            "sizes": []
        }
        assert validator._has_field(product_without_price, "price") is False

    def test_has_field_name(self, mock_gpt_service):
        """Test _has_field for name."""
        validator = FieldsValidator(gpt_service=mock_gpt_service)
        
        # Product with name
        product_with_name = {"name": "Тестовый товар"}
        assert validator._has_field(product_with_name, "name") is True
        
        # Product without name
        product_without_name = {"name": ""}
        assert validator._has_field(product_without_name, "name") is False

    def test_has_field_weight(self, mock_gpt_service):
        """Test _has_field for weight."""
        validator = FieldsValidator(gpt_service=mock_gpt_service)
        
        # Product with weight
        product_with_weight = {"weight": 1.5}
        assert validator._has_field(product_with_weight, "weight") is True
        
        # Product without weight
        product_without_weight = {"weight": None}
        assert validator._has_field(product_without_weight, "weight") is False
        
        # Product with zero weight (invalid)
        product_zero_weight = {"weight": 0}
        assert validator._has_field(product_zero_weight, "weight") is False

    def test_has_field_volume(self, mock_gpt_service):
        """Test _has_field for volume."""
        validator = FieldsValidator(gpt_service=mock_gpt_service)
        
        # Product with volume
        product_with_volume = {"volume": 2}
        assert validator._has_field(product_with_volume, "volume") is True
        
        # Product without volume
        product_without_volume = {"volume": None}
        assert validator._has_field(product_without_volume, "volume") is False
        
        # Product with zero volume (invalid)
        product_zero_volume = {"volume": 0}
        assert validator._has_field(product_zero_volume, "volume") is False


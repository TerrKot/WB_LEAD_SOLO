"""Unit tests for Specific Value Calculator."""
import pytest

from apps.bot_service.services.specific_value_calculator import SpecificValueCalculator


class TestSpecificValueCalculator:
    """Test cases for SpecificValueCalculator."""

    @pytest.fixture
    def calculator(self):
        """Create SpecificValueCalculator instance with default exchange rate."""
        return SpecificValueCalculator(exchange_rate_usd_rub=100.0)

    @pytest.fixture
    def sample_product_data(self):
        """Sample product data from WB API."""
        return {
            "id": 154345562,
            "name": "Тестовый товар",
            "weight": 1.5,  # kg
            "sizes": [
                {
                    "price": {
                        "basic": 100000,  # 1000 RUB in kopecks
                        "product": 80000   # 800 RUB in kopecks (with discount)
                    }
                }
            ]
        }

    def test_calculate_basic(self, calculator):
        """Test basic calculation of specific value."""
        # Price: 1000 RUB = 10 USD (at 100 RUB/USD)
        # Weight: 1.5 kg
        # Specific value: 10 / 1.5 = 6.67 USD/kg
        result = calculator.calculate(
            product_price_kopecks=100000,
            product_weight_kg=1.5,
            quantity=1
        )
        
        assert result is not None
        assert result == pytest.approx(6.67, abs=0.01)

    def test_calculate_with_quantity(self, calculator):
        """Test calculation with quantity > 1."""
        # Price: 1000 RUB = 10 USD
        # Weight: 1.5 kg
        # Quantity: 2
        # Batch cost: 20 USD
        # Batch weight: 3.0 kg
        # Specific value: 20 / 3.0 = 6.67 USD/kg
        result = calculator.calculate(
            product_price_kopecks=100000,
            product_weight_kg=1.5,
            quantity=2
        )
        
        assert result is not None
        assert result == pytest.approx(6.67, abs=0.01)

    def test_calculate_high_value(self, calculator):
        """Test calculation for high-value product."""
        # Price: 50000 RUB = 500 USD
        # Weight: 2.0 kg
        # Specific value: 500 / 2.0 = 250 USD/kg
        result = calculator.calculate(
            product_price_kopecks=5000000,
            product_weight_kg=2.0,
            quantity=1
        )
        
        assert result is not None
        assert result == pytest.approx(250.0, abs=0.01)

    def test_calculate_low_value(self, calculator):
        """Test calculation for low-value product."""
        # Price: 100 RUB = 1 USD
        # Weight: 2.0 kg
        # Specific value: 1 / 2.0 = 0.5 USD/kg
        result = calculator.calculate(
            product_price_kopecks=10000,
            product_weight_kg=2.0,
            quantity=1
        )
        
        assert result is not None
        assert result == pytest.approx(0.5, abs=0.01)

    def test_calculate_invalid_weight(self, calculator):
        """Test calculation with invalid weight."""
        result = calculator.calculate(
            product_price_kopecks=100000,
            product_weight_kg=0,
            quantity=1
        )
        
        assert result is None

    def test_calculate_invalid_price(self, calculator):
        """Test calculation with invalid price."""
        result = calculator.calculate(
            product_price_kopecks=0,
            product_weight_kg=1.5,
            quantity=1
        )
        
        assert result is None

    def test_calculate_invalid_quantity(self, calculator):
        """Test calculation with invalid quantity."""
        result = calculator.calculate(
            product_price_kopecks=100000,
            product_weight_kg=1.5,
            quantity=0
        )
        
        assert result is None

    def test_calculate_from_product_data(self, calculator, sample_product_data):
        """Test calculation from product data dictionary."""
        # Price: 800 RUB (product price) = 8 USD
        # Weight: 1.5 kg
        # Specific value: 8 / 1.5 = 5.33 USD/kg
        result = calculator.calculate_from_product_data(
            product_data=sample_product_data,
            quantity=1
        )
        
        assert result is not None
        assert result == pytest.approx(5.33, abs=0.01)

    def test_calculate_from_product_data_missing_price(self, calculator, sample_product_data):
        """Test calculation with missing price."""
        sample_product_data["sizes"] = []
        result = calculator.calculate_from_product_data(
            product_data=sample_product_data,
            quantity=1
        )
        
        assert result is None

    def test_calculate_from_product_data_missing_weight(self, calculator, sample_product_data):
        """Test calculation with missing weight."""
        sample_product_data["weight"] = None
        result = calculator.calculate_from_product_data(
            product_data=sample_product_data,
            quantity=1
        )
        
        assert result is None

    def test_calculate_custom_exchange_rate(self):
        """Test calculation with custom exchange rate."""
        calculator = SpecificValueCalculator(exchange_rate_usd_rub=50.0)
        
        # Price: 1000 RUB = 20 USD (at 50 RUB/USD)
        # Weight: 1.5 kg
        # Specific value: 20 / 1.5 = 13.33 USD/kg
        result = calculator.calculate(
            product_price_kopecks=100000,
            product_weight_kg=1.5,
            quantity=1
        )
        
        assert result is not None
        assert result == pytest.approx(13.33, abs=0.01)


"""Unit tests for CargoCalculator."""
import pytest
from apps.bot_service.services.cargo_calculator import CargoCalculator


class TestCargoCalculator:
    """Test cases for CargoCalculator."""

    def test_init(self):
        """Test calculator initialization."""
        calculator = CargoCalculator()
        assert calculator.exchange_rate_usd_rub > 0
        assert calculator.exchange_rate_usd_cny > 0

    def test_calculate_per_m3_tariff(self):
        """Test calculation with per_m3 tariff (density < 100)."""
        calculator = CargoCalculator(exchange_rate_usd_rub=100.0, exchange_rate_usd_cny=7.2)
        
        input_data = {
            "weight_kg": 50.0,  # Low density
            "volume_m3": 1.0,
            "quantity_units": 10,
            "goods_value": {
                "amount": 1000.0,
                "currency": "USD"
            },
            "exchange_rates": {
                "usd_rub": 100.0,
                "usd_cny": 7.2
            }
        }
        
        result = calculator.calculate(input_data)
        
        assert result["ok"] is True
        assert result["errors"] == []
        assert result["cargo_params"]["tariff_type"] == "per_m3"
        assert result["cargo_params"]["tariff_value_usd"] == 500.0
        assert result["cargo_cost_usd"]["freight_usd"] == 500.0
        assert result["cargo_cost_usd"]["total_cargo_usd"] > 0

    def test_calculate_per_kg_tariff(self):
        """Test calculation with per_kg tariff (density >= 100)."""
        calculator = CargoCalculator(exchange_rate_usd_rub=100.0, exchange_rate_usd_cny=7.2)
        
        input_data = {
            "weight_kg": 150.0,  # High density
            "volume_m3": 1.0,
            "quantity_units": 10,
            "goods_value": {
                "amount": 1000.0,
                "currency": "USD"
            },
            "exchange_rates": {
                "usd_rub": 100.0,
                "usd_cny": 7.2
            }
        }
        
        result = calculator.calculate(input_data)
        
        assert result["ok"] is True
        assert result["errors"] == []
        assert result["cargo_params"]["tariff_type"] == "per_kg"
        assert result["cargo_params"]["tariff_value_usd"] > 0
        assert result["cargo_cost_usd"]["freight_usd"] > 0
        assert result["cargo_cost_usd"]["total_cargo_usd"] > 0

    def test_calculate_with_cny_currency(self):
        """Test calculation with CNY currency."""
        calculator = CargoCalculator(exchange_rate_usd_rub=100.0, exchange_rate_usd_cny=7.2)
        
        input_data = {
            "weight_kg": 100.0,
            "volume_m3": 1.0,
            "quantity_units": 10,
            "goods_value": {
                "amount": 7200.0,  # 1000 USD in CNY
                "currency": "CNY"
            },
            "exchange_rates": {
                "usd_rub": 100.0,
                "usd_cny": 7.2
            }
        }
        
        result = calculator.calculate(input_data)
        
        assert result["ok"] is True
        assert result["input_normalized"]["goods_value_usd"] == pytest.approx(1000.0, rel=0.01)
        assert result["input_normalized"]["goods_value_cny"] == pytest.approx(7200.0, rel=0.01)

    def test_calculate_with_rub_currency(self):
        """Test calculation with RUB currency."""
        calculator = CargoCalculator(exchange_rate_usd_rub=100.0, exchange_rate_usd_cny=7.2)
        
        input_data = {
            "weight_kg": 100.0,
            "volume_m3": 1.0,
            "quantity_units": 10,
            "goods_value": {
                "amount": 100000.0,  # 1000 USD in RUB
                "currency": "RUB"
            },
            "exchange_rates": {
                "usd_rub": 100.0,
                "usd_cny": 7.2
            }
        }
        
        result = calculator.calculate(input_data)
        
        assert result["ok"] is True
        assert result["input_normalized"]["goods_value_usd"] == pytest.approx(1000.0, rel=0.01)

    def test_calculate_insurance_rates(self):
        """Test insurance rate calculation based on specific value."""
        calculator = CargoCalculator(exchange_rate_usd_rub=100.0, exchange_rate_usd_cny=7.2)
        
        # Test low specific value (1%)
        input_data = {
            "weight_kg": 100.0,
            "volume_m3": 1.0,
            "quantity_units": 10,
            "goods_value": {
                "amount": 2000.0,  # 20 USD/kg
                "currency": "USD"
            },
            "exchange_rates": {
                "usd_rub": 100.0,
                "usd_cny": 7.2
            }
        }
        
        result = calculator.calculate(input_data)
        assert result["ok"] is True
        assert result["cargo_params"]["insurance_rate"] == 0.01
        
        # Test high specific value (10%)
        input_data["goods_value"]["amount"] = 25000.0  # 250 USD/kg
        result = calculator.calculate(input_data)
        assert result["ok"] is True
        assert result["cargo_params"]["insurance_rate"] == 0.10

    def test_calculate_buyer_commission_rates(self):
        """Test buyer commission rate calculation."""
        calculator = CargoCalculator(exchange_rate_usd_rub=100.0, exchange_rate_usd_cny=7.2)
        
        # Test low value (5%)
        input_data = {
            "weight_kg": 100.0,
            "volume_m3": 1.0,
            "quantity_units": 10,
            "goods_value": {
                "amount": 1000.0,
                "currency": "USD"
            },
            "goods_value_cny": 500.0,  # Low value in CNY
            "exchange_rates": {
                "usd_rub": 100.0,
                "usd_cny": 7.2
            }
        }
        
        result = calculator.calculate(input_data)
        assert result["ok"] is True
        assert result["cargo_params"]["buyer_commission_rate"] == 0.05
        
        # Test high value (1%)
        input_data["goods_value_cny"] = 60000.0
        result = calculator.calculate(input_data)
        assert result["ok"] is True
        assert result["cargo_params"]["buyer_commission_rate"] == 0.01

    def test_calculate_validation_errors(self):
        """Test validation error handling."""
        calculator = CargoCalculator()
        
        # Missing weight
        input_data = {
            "volume_m3": 1.0,
            "goods_value": {"amount": 1000.0, "currency": "USD"}
        }
        
        result = calculator.calculate(input_data)
        assert result["ok"] is False
        assert "weight_kg" in str(result["errors"])

    def test_calculate_tariff_rate_per_kg(self):
        """Test tariff rate per kg calculation for different densities."""
        calculator = CargoCalculator()
        
        # Test density 100-110
        rate = calculator._get_tariff_rate_per_kg(105.0)
        assert rate == 4.9
        
        # Test density 200-250
        rate = calculator._get_tariff_rate_per_kg(225.0)
        assert rate == 3.9
        
        # Test density > 1000
        rate = calculator._get_tariff_rate_per_kg(1500.0)
        assert rate == 3.1

    def test_calculate_cost_per_unit(self):
        """Test cost per unit calculation."""
        calculator = CargoCalculator(exchange_rate_usd_rub=100.0, exchange_rate_usd_cny=7.2)
        
        input_data = {
            "weight_kg": 100.0,
            "volume_m3": 1.0,
            "quantity_units": 10,
            "goods_value": {
                "amount": 1000.0,
                "currency": "USD"
            },
            "exchange_rates": {
                "usd_rub": 100.0,
                "usd_cny": 7.2
            }
        }
        
        result = calculator.calculate(input_data)
        
        assert result["ok"] is True
        assert result["cargo_cost_usd"]["cost_per_unit_usd"] is not None
        assert result["cargo_cost_rub"]["cost_per_unit_rub"] is not None
        assert result["cargo_cost_usd"]["cost_per_kg_usd"] is not None
        assert result["cargo_cost_rub"]["cost_per_kg_rub"] is not None


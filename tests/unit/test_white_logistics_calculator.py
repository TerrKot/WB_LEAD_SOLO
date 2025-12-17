"""Unit tests for WhiteLogisticsCalculator."""
import pytest
from apps.bot_service.services.white_logistics_calculator import WhiteLogisticsCalculator


class TestWhiteLogisticsCalculator:
    """Test cases for WhiteLogisticsCalculator."""

    def test_init(self):
        """Test calculator initialization."""
        calculator = WhiteLogisticsCalculator()
        assert calculator.base_price_usd > 0
        assert calculator.docs_rub > 0
        assert calculator.broker_rub > 0

    def test_calculate_basic(self):
        """Test basic white logistics calculation."""
        calculator = WhiteLogisticsCalculator(
            base_price_usd=1850.0,
            docs_rub=15000.0,
            broker_rub=25000.0,
            exchange_rate_usd_rub=100.0,
            exchange_rate_usd_cny=7.2,
            exchange_rate_eur_rub=110.0
        )
        
        input_data = {
            "weight_kg": 1000.0,
            "volume_m3": 4.6,
            "quantity_units": 100,
            "goods_value_cny": 72000.0,  # 10000 USD
            "tnved_data": {
                "duty_type": "ad valorem",
                "duty_rate": 5.0,  # 5%
                "vat_rate": 20.0  # 20%
            }
        }
        
        result = calculator.calculate(input_data)
        
        assert result["ok"] is True
        assert result["errors"] == []
        assert result["logistics_usd"] == 1850.0
        assert result["logistics_rub"] == 185000.0
        assert result["docs_rub"] == 15000.0
        assert result["broker_rub"] == 25000.0
        assert result["total_rub"] > 0
        assert result["cost_per_unit_rub"] > 0
        assert result["cost_per_kg_rub"] > 0

    def test_calculate_duty_by_weight(self):
        """Test duty calculation by weight."""
        calculator = WhiteLogisticsCalculator(
            exchange_rate_eur_rub=110.0
        )
        
        input_data = {
            "weight_kg": 1000.0,
            "volume_m3": 4.6,
            "quantity_units": 100,
            "goods_value_cny": 72000.0,
            "tnved_data": {
                "duty_type": "по весу",
                "duty_rate": 0.5,  # 0.5 EUR/kg
                "vat_rate": 20.0
            }
        }
        
        result = calculator.calculate(input_data)
        
        assert result["ok"] is True
        # Duty should be 1000 kg * 0.5 EUR/kg * 110 RUB/EUR = 55000 RUB
        assert result["duty_rub"] == pytest.approx(55000.0, rel=0.01)

    def test_calculate_duty_by_unit(self):
        """Test duty calculation by unit."""
        calculator = WhiteLogisticsCalculator(
            exchange_rate_eur_rub=110.0
        )
        
        input_data = {
            "weight_kg": 1000.0,
            "volume_m3": 4.6,
            "quantity_units": 100,
            "goods_value_cny": 72000.0,
            "tnved_data": {
                "duty_type": "по единице",
                "duty_rate": 2.0,  # 2 EUR/unit
                "vat_rate": 20.0
            }
        }
        
        result = calculator.calculate(input_data)
        
        assert result["ok"] is True
        # Duty should be 100 units * 2 EUR/unit * 110 RUB/EUR = 22000 RUB
        assert result["duty_rub"] == pytest.approx(22000.0, rel=0.01)

    def test_calculate_duty_ad_valorem(self):
        """Test ad valorem duty calculation."""
        calculator = WhiteLogisticsCalculator(
            exchange_rate_usd_rub=100.0,
            exchange_rate_usd_cny=7.2,
            exchange_rate_eur_rub=110.0
        )
        
        input_data = {
            "weight_kg": 1000.0,
            "volume_m3": 4.6,
            "quantity_units": 100,
            "goods_value_cny": 72000.0,  # 10000 USD
            "tnved_data": {
                "duty_type": "ad valorem",
                "duty_rate": 5.0,  # 5%
                "vat_rate": 20.0
            }
        }
        
        result = calculator.calculate(input_data)
        
        assert result["ok"] is True
        # Goods value in RUB: 10000 USD * 100 RUB/USD = 1000000 RUB
        # Duty: 1000000 RUB * 5% = 50000 RUB
        assert result["duty_rub"] == pytest.approx(50000.0, rel=0.01)

    def test_calculate_vat(self):
        """Test VAT calculation."""
        calculator = WhiteLogisticsCalculator(
            base_price_usd=1850.0,
            exchange_rate_usd_rub=100.0,
            exchange_rate_usd_cny=7.2,
            exchange_rate_eur_rub=110.0
        )
        
        input_data = {
            "weight_kg": 1000.0,
            "volume_m3": 4.6,
            "quantity_units": 100,
            "goods_value_cny": 72000.0,  # 10000 USD
            "tnved_data": {
                "duty_type": "ad valorem",
                "duty_rate": 5.0,
                "vat_rate": 20.0  # 20%
            }
        }
        
        result = calculator.calculate(input_data)
        
        assert result["ok"] is True
        # VAT base = goods_value_rub + 900 USD in RUB + duty_rub
        # goods_value_rub = 10000 USD * 100 = 1000000 RUB
        # 900 USD in RUB = 900 * 100 = 90000 RUB
        # duty_rub = 1000000 * 5% = 50000 RUB
        # VAT base = 1000000 + 90000 + 50000 = 1140000 RUB
        # VAT = 1140000 * 20% = 228000 RUB
        assert result["vat_rub"] > 0

    def test_calculate_validation_errors(self):
        """Test validation error handling."""
        calculator = WhiteLogisticsCalculator()
        
        # Missing weight
        input_data = {
            "volume_m3": 4.6,
            "goods_value_cny": 72000.0,
            "tnved_data": {"duty_type": "ad valorem", "duty_rate": 5.0, "vat_rate": 20.0}
        }
        
        result = calculator.calculate(input_data)
        assert result["ok"] is False
        assert "weight_kg" in str(result["errors"])

    def test_calculate_cost_per_unit_and_kg(self):
        """Test cost per unit and per kg calculation."""
        calculator = WhiteLogisticsCalculator()
        
        input_data = {
            "weight_kg": 1000.0,
            "volume_m3": 4.6,
            "quantity_units": 100,
            "goods_value_cny": 72000.0,
            "tnved_data": {
                "duty_type": "ad valorem",
                "duty_rate": 5.0,
                "vat_rate": 20.0
            }
        }
        
        result = calculator.calculate(input_data)
        
        assert result["ok"] is True
        assert result["cost_per_unit_rub"] > 0
        assert result["cost_per_kg_rub"] > 0
        # Cost per unit should be total / quantity
        assert result["cost_per_unit_rub"] == pytest.approx(
            result["total_rub"] / 100, rel=0.01
        )
        # Cost per kg should be total / weight
        assert result["cost_per_kg_rub"] == pytest.approx(
            result["total_rub"] / 1000, rel=0.01
        )


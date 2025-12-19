"""Unit tests for WhiteLogisticsCalculator."""
import pytest
from apps.bot_service.services.white_logistics_calculator import WhiteLogisticsCalculator


class TestWhiteLogisticsCalculator:
    """Test cases for WhiteLogisticsCalculator."""

    def test_init(self):
        """Test calculator initialization."""
        calculator = WhiteLogisticsCalculator()
        assert calculator.base_price_usd > 0
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
        # Dynamic delivery cost should be in 1800-1900 USD range
        assert 1800.0 <= result["logistics_usd"] <= 1900.0
        assert result["logistics_rub"] == pytest.approx(result["logistics_usd"] * 100.0, rel=0.01)
        assert result["broker_rub"] == 25000.0
        # Goods value in RUB: 10000 USD * 100 RUB/USD = 1000000 RUB
        # Customs fees for 1000000 RUB should be 4269.0 (between 450k and 1.2M)
        assert result["customs_fees_rub"] == 4269.0
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
        # Logistics in RUB: dynamic (1800-1900 USD) * 100 RUB/USD
        # Duty: (1000000 + logistics_rub/2) * 5%
        logistics_rub = result["logistics_rub"]
        expected_duty = (1000000.0 + logistics_rub / 2) * 0.05
        assert result["duty_rub"] == pytest.approx(expected_duty, rel=0.01)

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
        # VAT base = duty_rub + goods_value_rub + logistics_rub / 2
        # goods_value_rub = 10000 USD * 100 = 1000000 RUB
        # logistics_rub = dynamic (1800-1900 USD) * 100
        # VAT calculation should work correctly with dynamic logistics
        assert result["vat_rub"] > 0
        assert 1800.0 <= result["logistics_usd"] <= 1900.0

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

    def test_calculate_customs_fees(self):
        """Test customs fees calculation."""
        calculator = WhiteLogisticsCalculator(
            exchange_rate_usd_rub=100.0,
            exchange_rate_usd_cny=7.2
        )
        
        # Test different value ranges
        test_cases = [
            (100000.0, 1_067.0),  # <= 200k
            (300000.0, 2_134.0),  # <= 450k
            (800000.0, 4_269.0),  # <= 1.2M
            (2000000.0, 11_746.0),  # <= 2.7M
            (3500000.0, 16_524.0),  # <= 4.2M
            (5000000.0, 21_344.0),  # <= 5.5M
            (6500000.0, 27_540.0),  # <= 7M
            (8000000.0, 30_000.0),  # > 7M
        ]
        
        for goods_value_rub, expected_fees in test_cases:
            fees = calculator._calculate_customs_fees(goods_value_rub)
            assert fees == expected_fees, f"Failed for value {goods_value_rub}: expected {expected_fees}, got {fees}"

    def test_dynamic_delivery_deterministic(self):
        """Test that dynamic delivery cost is deterministic (same inputs = same output)."""
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
        
        # Calculate multiple times with same inputs
        result1 = calculator.calculate(input_data)
        result2 = calculator.calculate(input_data)
        result3 = calculator.calculate(input_data)
        
        # All results should be identical
        assert result1["logistics_usd"] == result2["logistics_usd"]
        assert result2["logistics_usd"] == result3["logistics_usd"]
        assert 1800.0 <= result1["logistics_usd"] <= 1900.0

    def test_dynamic_delivery_range(self):
        """Test that dynamic delivery cost is in correct range for different products."""
        calculator = WhiteLogisticsCalculator()
        
        test_cases = [
            {"weight_kg": 500.0, "volume_m3": 2.3, "goods_value_cny": 36000.0},
            {"weight_kg": 1000.0, "volume_m3": 4.6, "goods_value_cny": 72000.0},
            {"weight_kg": 2000.0, "volume_m3": 9.2, "goods_value_cny": 144000.0},
            {"weight_kg": 100.0, "volume_m3": 0.46, "goods_value_cny": 7200.0},
        ]
        
        for case in test_cases:
            input_data = {
                **case,
                "quantity_units": 100,
                "tnved_data": {
                    "duty_type": "ad valorem",
                    "duty_rate": 5.0,
                    "vat_rate": 20.0
                }
            }
            
            result = calculator.calculate(input_data)
            assert result["ok"] is True
            assert 1800.0 <= result["logistics_usd"] <= 1900.0, \
                f"Delivery cost {result['logistics_usd']} out of range for case {case}"


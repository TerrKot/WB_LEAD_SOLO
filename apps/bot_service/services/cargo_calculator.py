"""Service for calculating cargo costs according to Cargo.md rules."""
from typing import Dict, Any, Optional, List
import structlog

from apps.bot_service.config import config

logger = structlog.get_logger()


class CargoCalculator:
    """Service for calculating cargo costs according to Cargo.md rules."""

    def __init__(
        self,
        exchange_rate_usd_rub: Optional[float] = None,
        exchange_rate_usd_cny: Optional[float] = None
    ):
        """
        Initialize calculator.

        Args:
            exchange_rate_usd_rub: USD to RUB exchange rate (defaults to config value)
            exchange_rate_usd_cny: USD to CNY exchange rate (defaults to config value)
        """
        self.exchange_rate_usd_rub = exchange_rate_usd_rub or config.EXCHANGE_RATE_USD_RUB
        self.exchange_rate_usd_cny = exchange_rate_usd_cny or config.EXCHANGE_RATE_USD_CNY

    def calculate(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate cargo costs according to Cargo.md rules.

        Args:
            input_data: {
                "weight_kg": float,  # Total batch weight in kg (required)
                "volume_m3": float,  # Total batch volume in m³ (required)
                "quantity_units": int,  # Number of units (optional)
                "goods_value": {  # Product value
                    "amount": float,
                    "currency": "USD" | "CNY" | "RUB"
                },
                "goods_value_cny": float,  # Product value in CNY (optional, will be calculated)
                "exchange_rates": {  # Exchange rates (optional, will use config if not provided)
                    "usd_rub": float,
                    "usd_cny": float
                }
            }

        Returns:
            {
                "ok": bool,
                "errors": List[str],
                "input_normalized": Dict[str, Any],
                "cargo_params": Dict[str, Any],
                "cargo_cost_usd": Dict[str, Any],
                "cargo_cost_rub": Dict[str, Any],
                "summary_for_manager": Dict[str, str]
            }
        """
        errors: List[str] = []
        
        # Extract input data
        weight_kg = input_data.get("weight_kg")
        volume_m3 = input_data.get("volume_m3")
        quantity_units = input_data.get("quantity_units")
        goods_value = input_data.get("goods_value")
        goods_value_cny = input_data.get("goods_value_cny")
        exchange_rates = input_data.get("exchange_rates", {})
        
        # Get exchange rates
        usd_rub = exchange_rates.get("usd_rub", self.exchange_rate_usd_rub)
        usd_cny = exchange_rates.get("usd_cny", self.exchange_rate_usd_cny)
        
        # Validate required fields
        if weight_kg is None or weight_kg <= 0:
            errors.append("weight_kg is required and must be > 0")
        if volume_m3 is None or volume_m3 <= 0:
            errors.append("volume_m3 is required and must be > 0")
        if goods_value is None:
            errors.append("goods_value is required")
        
        if errors:
            return {
                "ok": False,
                "errors": errors,
                "input_normalized": {},
                "cargo_params": {},
                "cargo_cost_usd": {},
                "cargo_cost_rub": {},
                "summary_for_manager": {}
            }
        
        # Step 1: Normalize currencies (all internal calculations in USD)
        goods_value_amount = goods_value.get("amount")
        goods_value_currency = goods_value.get("currency", "USD").upper()
        
        if goods_value_currency == "USD":
            goods_value_usd = goods_value_amount
        elif goods_value_currency == "CNY":
            goods_value_usd = goods_value_amount / usd_cny
        elif goods_value_currency == "RUB":
            goods_value_usd = goods_value_amount / usd_rub
        else:
            errors.append(f"Unsupported currency: {goods_value_currency}")
            return {
                "ok": False,
                "errors": errors,
                "input_normalized": {},
                "cargo_params": {},
                "cargo_cost_usd": {},
                "cargo_cost_rub": {},
                "summary_for_manager": {}
            }
        
        # Calculate values in all currencies
        if goods_value_cny is None:
            goods_value_cny = goods_value_usd * usd_cny
        goods_value_rub = goods_value_usd * usd_rub
        
        # Step 2: Calculate density
        density_kg_m3 = weight_kg / volume_m3
        
        # Step 3: Determine tariff type and rate
        if density_kg_m3 < 100:
            tariff_type = "per_m3"
            tariff_value_usd = 500.0  # USD per m³
            freight_usd = volume_m3 * tariff_value_usd
        else:
            tariff_type = "per_kg"
            tariff_value_usd = self._get_tariff_rate_per_kg(density_kg_m3)
            freight_usd = weight_kg * tariff_value_usd
        
        # Step 4: Insurance by specific value
        specific_value_usd_per_kg = goods_value_usd / weight_kg
        insurance_rate = self._get_insurance_rate(specific_value_usd_per_kg)
        insurance_usd = goods_value_usd * insurance_rate
        
        # Step 5: Buyer commission (in CNY)
        buyer_commission_rate = self._get_buyer_commission_rate(goods_value_cny)
        buyer_commission_cny = goods_value_cny * buyer_commission_rate
        buyer_commission_usd = buyer_commission_cny / usd_cny
        
        # Step 6: Packaging cost
        # Packaging is always 120 USD
        packaging_usd = 120.0
        packaging_rub = packaging_usd * usd_rub
        
        # Step 7: Total cargo cost (including goods value and packaging)
        total_cargo_usd = freight_usd + insurance_usd + buyer_commission_usd + goods_value_usd + packaging_usd
        total_cargo_rub = total_cargo_usd * usd_rub
        
        # Calculate per unit and per kg costs
        cost_per_kg_usd = total_cargo_usd / weight_kg
        cost_per_kg_rub = total_cargo_rub / weight_kg
        
        cost_per_unit_usd = None
        cost_per_unit_rub = None
        if quantity_units and quantity_units > 0:
            cost_per_unit_usd = total_cargo_usd / quantity_units
            cost_per_unit_rub = total_cargo_rub / quantity_units
        
        # Round values
        freight_usd = round(freight_usd, 2)
        insurance_usd = round(insurance_usd, 2)
        buyer_commission_usd = round(buyer_commission_usd, 2)
        packaging_usd = round(packaging_usd, 2)
        total_cargo_usd = round(total_cargo_usd, 2)
        cost_per_kg_usd = round(cost_per_kg_usd, 2)
        if cost_per_unit_usd is not None:
            cost_per_unit_usd = round(cost_per_unit_usd, 2)
        
        freight_rub = round(freight_usd * usd_rub, 2)
        insurance_rub = round(insurance_usd * usd_rub, 2)
        buyer_commission_rub = round(buyer_commission_usd * usd_rub, 2)
        packaging_rub = round(packaging_rub, 2)
        total_cargo_rub = round(total_cargo_rub, 2)
        cost_per_kg_rub = round(cost_per_kg_rub, 2)
        if cost_per_unit_rub is not None:
            cost_per_unit_rub = round(cost_per_unit_rub, 2)
        
        # Build summary
        summary_short = (
            f"Итоговая стоимость карго: {total_cargo_usd:.2f} USD ({total_cargo_rub:.2f} ₽), "
            f"за кг: {cost_per_kg_usd:.2f} USD ({cost_per_kg_rub:.2f} ₽)"
        )
        if cost_per_unit_usd is not None:
            summary_short += f", за штуку: {cost_per_unit_usd:.2f} USD ({cost_per_unit_rub:.2f} ₽)"
        
        summary_details = (
            f"Плотность: {density_kg_m3:.1f} кг/м³, тариф: {tariff_type} "
            f"({tariff_value_usd:.2f} USD/{'м³' if tariff_type == 'per_m3' else 'кг'}), "
            f"страховка: {insurance_rate * 100:.0f}%, комиссия байера: {buyer_commission_rate * 100:.0f}%."
        )
        
        # Build normalized input
        input_normalized = {
            "weight_kg": weight_kg,
            "volume_m3": volume_m3,
            "quantity_units": quantity_units,
            "goods_value_usd": round(goods_value_usd, 2),
            "goods_value_cny": round(goods_value_cny, 2),
            "goods_value_rub": round(goods_value_rub, 2),
            "exchange_rates": {
                "usd_rub": usd_rub,
                "usd_cny": usd_cny
            }
        }
        # Copy additional fields
        for key, value in input_data.items():
            if key not in ["weight_kg", "volume_m3", "quantity_units", "goods_value", "goods_value_cny", "exchange_rates"]:
                input_normalized[key] = value
        
        logger.info(
            "cargo_calculation_completed",
            weight_kg=weight_kg,
            volume_m3=volume_m3,
            density_kg_m3=round(density_kg_m3, 2),
            tariff_type=tariff_type,
            total_cargo_usd=total_cargo_usd
        )
        
        return {
            "ok": True,
            "errors": [],
            "input_normalized": input_normalized,
            "cargo_params": {
                "density_kg_m3": round(density_kg_m3, 2),
                "tariff_type": tariff_type,
                "tariff_value_usd": round(tariff_value_usd, 2),
                "specific_value_usd_per_kg": round(specific_value_usd_per_kg, 2),
                "insurance_rate": round(insurance_rate, 4),
                "buyer_commission_rate": round(buyer_commission_rate, 4)
            },
            "cargo_cost_usd": {
                "freight_usd": freight_usd,
                "insurance_usd": insurance_usd,
                "buyer_commission_usd": buyer_commission_usd,
                "packaging_usd": packaging_usd,
                "goods_value_usd": round(goods_value_usd, 2),
                "total_cargo_usd": total_cargo_usd,
                "cost_per_kg_usd": cost_per_kg_usd,
                "cost_per_unit_usd": cost_per_unit_usd
            },
            "cargo_cost_rub": {
                "freight_rub": freight_rub,
                "insurance_rub": insurance_rub,
                "buyer_commission_rub": buyer_commission_rub,
                "packaging_rub": packaging_rub,
                "goods_value_rub": round(goods_value_rub, 2),
                "total_cargo_rub": total_cargo_rub,
                "cost_per_kg_rub": cost_per_kg_rub,
                "cost_per_unit_rub": cost_per_unit_rub
            },
            "summary_for_manager": {
                "short_text": summary_short,
                "details": summary_details
            }
        }

    def _get_tariff_rate_per_kg(self, density_kg_m3: float) -> float:
        """
        Get tariff rate per kg based on density.

        Args:
            density_kg_m3: Density in kg/m³

        Returns:
            Tariff rate in USD/kg
        """
        if density_kg_m3 < 100:
            return 500.0 / density_kg_m3  # Convert per_m3 to per_kg for consistency
        elif density_kg_m3 <= 110:
            return 4.9
        elif density_kg_m3 <= 120:
            return 4.8
        elif density_kg_m3 <= 130:
            return 4.7
        elif density_kg_m3 <= 140:
            return 4.6
        elif density_kg_m3 <= 150:
            return 4.5
        elif density_kg_m3 <= 160:
            return 4.4
        elif density_kg_m3 <= 170:
            return 4.3
        elif density_kg_m3 <= 180:
            return 4.2
        elif density_kg_m3 <= 190:
            return 4.1
        elif density_kg_m3 <= 200:
            return 4.0
        elif density_kg_m3 <= 250:
            return 3.9
        elif density_kg_m3 <= 300:
            return 3.8
        elif density_kg_m3 <= 350:
            return 3.7
        elif density_kg_m3 <= 400:
            return 3.6
        elif density_kg_m3 <= 500:
            return 3.5
        elif density_kg_m3 <= 600:
            return 3.4
        elif density_kg_m3 <= 800:
            return 3.3
        elif density_kg_m3 <= 1000:
            return 3.2
        else:  # > 1000
            return 3.1

    def _get_insurance_rate(self, specific_value_usd_per_kg: float) -> float:
        """
        Get insurance rate based on specific value.

        Args:
            specific_value_usd_per_kg: Specific value in USD/kg

        Returns:
            Insurance rate (0.01 to 0.10)
        """
        if specific_value_usd_per_kg <= 30:
            return 0.01  # 1%
        elif specific_value_usd_per_kg <= 50:
            return 0.02  # 2%
        elif specific_value_usd_per_kg <= 100:
            return 0.03  # 3%
        elif specific_value_usd_per_kg <= 200:
            return 0.05  # 5%
        else:  # > 200
            return 0.10  # 10%

    def _get_buyer_commission_rate(self, goods_value_cny: float) -> float:
        """
        Get buyer commission rate based on goods value in CNY.

        Args:
            goods_value_cny: Goods value in CNY

        Returns:
            Commission rate (0.01 to 0.05)
        """
        if goods_value_cny <= 1000:
            return 0.05  # 5%
        elif goods_value_cny <= 5000:
            return 0.04  # 4%
        elif goods_value_cny <= 10000:
            return 0.03  # 3%
        elif goods_value_cny <= 50000:
            return 0.02  # 2%
        else:  # > 50000
            return 0.01  # 1%


"""Service for detailed calculation (cargo vs white logistics)."""
from typing import Dict, Any, Optional, Tuple
import structlog

from apps.bot_service.services.cargo_calculator import CargoCalculator
from apps.bot_service.services.white_logistics_calculator import WhiteLogisticsCalculator
from apps.bot_service.config import config

logger = structlog.get_logger()


class DetailedCalculationService:
    """Service for detailed calculation (cargo vs white logistics)."""

    def __init__(
        self,
        exchange_rate_usd_rub: Optional[float] = None,
        exchange_rate_usd_cny: Optional[float] = None,
        exchange_rate_eur_rub: Optional[float] = None
    ):
        """
        Initialize service.

        Args:
            exchange_rate_usd_rub: USD to RUB exchange rate (defaults to config value)
            exchange_rate_usd_cny: USD to CNY exchange rate (defaults to config value)
            exchange_rate_eur_rub: EUR to RUB exchange rate (defaults to config value)
        """
        self.exchange_rate_usd_rub = exchange_rate_usd_rub or config.EXCHANGE_RATE_USD_RUB
        self.exchange_rate_usd_cny = exchange_rate_usd_cny or config.EXCHANGE_RATE_USD_CNY
        self.exchange_rate_eur_rub = exchange_rate_eur_rub or config.EXCHANGE_RATE_EUR_RUB
        
        self.cargo_calculator = CargoCalculator(
            exchange_rate_usd_rub=self.exchange_rate_usd_rub,
            exchange_rate_usd_cny=self.exchange_rate_usd_cny
        )
        self.white_logistics_calculator = WhiteLogisticsCalculator(
            exchange_rate_usd_rub=self.exchange_rate_usd_rub,
            exchange_rate_usd_cny=self.exchange_rate_usd_cny,
            exchange_rate_eur_rub=self.exchange_rate_eur_rub
        )

    def select_calculation_base(
        self,
        unit_weight_kg: float,
        unit_volume_m3: float
    ) -> Tuple[str, float, float, float, float, float, float]:
        """
        Select calculation base (1000 kg or 4.6 m³) and calculate actual quantities.
        
        The base weight should be close to 1000 kg (with tolerance due to integer quantity),
        and base volume should be close to 4.6 m³ (with tolerance due to integer quantity).

        Args:
            unit_weight_kg: Weight of one unit in kg
            unit_volume_m3: Volume of one unit in m³

        Returns:
            Tuple of (base_type, base_weight_kg, base_volume_m3, cargo_weight_kg, cargo_volume_m3, white_weight_kg, white_volume_m3)
            - base_type: "weight" or "volume"
            - base_weight_kg: Actual base weight (close to 1000 kg)
            - base_volume_m3: Actual base volume (close to 4.6 m³)
            - cargo_weight_kg: Weight with +15% adjustment for cargo
            - cargo_volume_m3: Volume with +15% adjustment for cargo
            - white_weight_kg: Weight with +5% adjustment for white logistics
            - white_volume_m3: Volume with +5% adjustment for white logistics
        """
        # Base values
        target_weight_kg = 1000.0
        target_volume_m3 = 4.6
        
        # Calculate how many units fit in each base (as integer)
        quantity_by_weight = int(target_weight_kg / unit_weight_kg) if unit_weight_kg > 0 else 0
        quantity_by_volume = int(target_volume_m3 / unit_volume_m3) if unit_volume_m3 > 0 else 0
        
        # Calculate actual weight and volume for each base (with integer quantities)
        actual_weight_for_weight_base = quantity_by_weight * unit_weight_kg
        actual_volume_for_weight_base = quantity_by_weight * unit_volume_m3
        
        actual_weight_for_volume_base = quantity_by_volume * unit_weight_kg
        actual_volume_for_volume_base = quantity_by_volume * unit_volume_m3
        
        # Select the base: compare which constraint is more limiting
        # The actual quantity must satisfy BOTH constraints (weight <= 1000 kg AND volume <= 4.6 m³)
        # So we take the minimum quantity
        quantity = min(quantity_by_weight, quantity_by_volume)
        
        # Recalculate actual weight and volume for the selected quantity
        selected_weight_kg = quantity * unit_weight_kg
        selected_volume_m3 = quantity * unit_volume_m3
        
        # Determine base type based on which constraint was more limiting
        if quantity_by_weight <= quantity_by_volume:
            # Weight constraint is more limiting
            base_type = "weight"
        else:
            # Volume constraint is more limiting
            base_type = "volume"
        
        # Apply adjustments
        # Cargo: +15%
        cargo_weight_kg = selected_weight_kg * 1.15
        cargo_volume_m3 = selected_volume_m3 * 1.15
        
        # White logistics: +5%
        white_weight_kg = selected_weight_kg * 1.05
        white_volume_m3 = selected_volume_m3 * 1.05
        
        logger.info(
            "calculation_base_selected",
            base_type=base_type,
            quantity=quantity,
            base_weight_kg=round(selected_weight_kg, 2),
            base_volume_m3=round(selected_volume_m3, 4),
            cargo_weight_kg=round(cargo_weight_kg, 2),
            cargo_volume_m3=round(cargo_volume_m3, 4),
            white_weight_kg=round(white_weight_kg, 2),
            white_volume_m3=round(white_volume_m3, 4)
        )
        
        return (
            base_type,
            selected_weight_kg,
            selected_volume_m3,
            cargo_weight_kg,
            cargo_volume_m3,
            white_weight_kg,
            white_volume_m3
        )

    def calculate_quantity(
        self,
        base_weight_kg: float,
        base_volume_m3: float,
        unit_weight_kg: float,
        unit_volume_m3: float
    ) -> int:
        """
        Calculate quantity of units in batch based on selected base.

        Args:
            base_weight_kg: Base weight for calculation
            base_volume_m3: Base volume for calculation
            unit_weight_kg: Weight of one unit in kg
            unit_volume_m3: Volume of one unit in m³

        Returns:
            Quantity of units
        """
        if unit_weight_kg <= 0 or unit_volume_m3 <= 0:
            return 0
        
        # Calculate quantity by weight and volume, take the minimum
        quantity_by_weight = int(base_weight_kg / unit_weight_kg)
        quantity_by_volume = int(base_volume_m3 / unit_volume_m3)
        
        # Take the minimum to ensure both weight and volume constraints are met
        quantity = min(quantity_by_weight, quantity_by_volume)
        
        logger.info(
            "quantity_calculated",
            base_weight_kg=base_weight_kg,
            base_volume_m3=base_volume_m3,
            unit_weight_kg=unit_weight_kg,
            unit_volume_m3=unit_volume_m3,
            quantity_by_weight=quantity_by_weight,
            quantity_by_volume=quantity_by_volume,
            quantity=quantity
        )
        
        return quantity

    def calculate_detailed(
        self,
        unit_weight_kg: float,
        unit_volume_m3: float,
        unit_price_rub: float,
        purchase_price_cny: float,
        tnved_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Perform detailed calculation (cargo vs white logistics).

        Args:
            unit_weight_kg: Weight of one unit in kg
            unit_volume_m3: Volume of one unit in m³
            unit_price_rub: Price of one unit in RUB (from WB)
            purchase_price_cny: Purchase price of one unit in CNY
            tnved_data: TN VED data with duty_type, duty_rate, vat_rate

        Returns:
            {
                "ok": bool,
                "errors": List[str],
                "base_info": Dict[str, Any],
                "quantity": int,
                "cargo": Dict[str, Any],
                "white_logistics": Dict[str, Any],
                "comparison": Dict[str, Any]
            }
        """
        errors = []
        
        # Validate inputs
        if unit_weight_kg <= 0:
            errors.append("unit_weight_kg must be > 0")
        if unit_volume_m3 <= 0:
            errors.append("unit_volume_m3 must be > 0")
        if unit_price_rub <= 0:
            errors.append("unit_price_rub must be > 0")
        if purchase_price_cny <= 0:
            errors.append("purchase_price_cny must be > 0")
        if not tnved_data:
            errors.append("tnved_data is required")
        
        if errors:
            return {
                "ok": False,
                "errors": errors,
                "base_info": {},
                "quantity": 0,
                "cargo": {},
                "white_logistics": {},
                "comparison": {}
            }
        
        # Step 1: Select calculation base and get quantity
        (
            base_type,
            base_weight_kg,
            base_volume_m3,
            cargo_weight_kg,
            cargo_volume_m3,
            white_weight_kg,
            white_volume_m3
        ) = self.select_calculation_base(unit_weight_kg, unit_volume_m3)
        
        # Step 2: Calculate quantity from base (already calculated in select_calculation_base)
        # Recalculate to ensure consistency
        if base_type == "weight":
            quantity = int(base_weight_kg / unit_weight_kg)
        else:  # volume
            quantity = int(base_volume_m3 / unit_volume_m3)
        
        if quantity <= 0:
            errors.append("Cannot calculate quantity: base constraints not met")
            return {
                "ok": False,
                "errors": errors,
                "base_info": {},
                "quantity": 0,
                "cargo": {},
                "white_logistics": {},
                "comparison": {}
            }
        
        # Step 3: Calculate batch values (use actual base values, not unit * quantity)
        batch_weight_kg = base_weight_kg  # Already calculated for integer quantity
        batch_volume_m3 = base_volume_m3  # Already calculated for integer quantity
        
        # Purchase price is already in CNY, so calculate batch price in CNY
        batch_purchase_price_cny = purchase_price_cny * quantity
        
        # Get exchange rates for each calculator
        # Cargo uses cargo rates (+4%), white logistics uses white rates (+2%)
        cargo_usd_rub = self.cargo_calculator.exchange_rate_usd_rub
        cargo_usd_cny = self.cargo_calculator.exchange_rate_usd_cny
        white_usd_rub = self.white_logistics_calculator.usd_rub
        white_usd_cny = self.white_logistics_calculator.usd_cny
        
        # For cargo calculation: convert from CNY using cargo rates
        batch_purchase_price_usd_cargo = batch_purchase_price_cny / cargo_usd_cny
        batch_purchase_price_rub_cargo = batch_purchase_price_usd_cargo * cargo_usd_rub
        
        # For white logistics calculation: convert from CNY using white rates
        batch_purchase_price_usd_white = batch_purchase_price_cny / white_usd_cny
        batch_purchase_price_rub_white = batch_purchase_price_usd_white * white_usd_rub
        
        # Step 4: Calculate cargo costs (with +15% adjustment)
        cargo_input = {
            "weight_kg": cargo_weight_kg,
            "volume_m3": cargo_volume_m3,
            "quantity_units": quantity,
            "goods_value": {
                "amount": batch_purchase_price_usd_cargo,
                "currency": "USD"
            },
            "goods_value_cny": batch_purchase_price_cny,
            "exchange_rates": {
                "usd_rub": cargo_usd_rub,
                "usd_cny": cargo_usd_cny
            }
        }
        
        cargo_result = self.cargo_calculator.calculate(cargo_input)
        
        # Step 5: Calculate white logistics costs (with +5% adjustment)
        white_input = {
            "weight_kg": white_weight_kg,
            "volume_m3": white_volume_m3,
            "quantity_units": quantity,
            "goods_value_cny": batch_purchase_price_cny,
            "tnved_data": tnved_data
        }
        
        white_result = self.white_logistics_calculator.calculate(white_input)
        
        # Step 6: Build comparison
        comparison = {}
        if cargo_result.get("ok") and white_result.get("ok"):
            cargo_total_rub = cargo_result["cargo_cost_rub"]["total_cargo_rub"]
            white_total_rub = white_result["total_rub"]
            difference_rub = white_total_rub - cargo_total_rub
            difference_percent = (difference_rub / cargo_total_rub * 100) if cargo_total_rub > 0 else 0
            
            comparison = {
                "cargo_total_rub": round(cargo_total_rub, 2),
                "white_total_rub": round(white_total_rub, 2),
                "difference_rub": round(difference_rub, 2),
                "difference_percent": round(difference_percent, 2),
                "cheaper_option": "cargo" if difference_rub > 0 else "white"
            }
        
        logger.info(
            "detailed_calculation_completed",
            quantity=quantity,
            base_type=base_type,
            cargo_ok=cargo_result.get("ok"),
            white_ok=white_result.get("ok")
        )
        
        return {
            "ok": cargo_result.get("ok") and white_result.get("ok"),
            "errors": cargo_result.get("errors", []) + white_result.get("errors", []),
            "base_info": {
                "base_type": base_type,
                "base_weight_kg": round(base_weight_kg, 2),
                "base_volume_m3": round(base_volume_m3, 4),
                "cargo_weight_kg": round(cargo_weight_kg, 2),
                "cargo_volume_m3": round(cargo_volume_m3, 4),
                "white_weight_kg": round(white_weight_kg, 2),
                "white_volume_m3": round(white_volume_m3, 4)
            },
            "quantity": quantity,
            "batch_info": {
                "batch_weight_kg": round(batch_weight_kg, 2),
                "batch_volume_m3": round(batch_volume_m3, 4),
                "batch_purchase_price_cny": round(batch_purchase_price_cny, 2),
                "batch_purchase_price_usd": round(batch_purchase_price_usd_cargo, 2),
                "batch_purchase_price_rub": round(batch_purchase_price_rub_cargo, 2)
            },
            "exchange_rates": {
                "cargo_usd_rub": round(cargo_usd_rub, 2),
                "cargo_usd_cny": round(cargo_usd_cny, 2),
                "white_usd_rub": round(white_usd_rub, 2),
                "white_usd_cny": round(white_usd_cny, 2)
            },
            "cargo": cargo_result,
            "white_logistics": white_result,
            "comparison": comparison
        }

    def calculate_purchase_price_cny(
        self,
        price_rub: float,
        unit_weight_kg: float,
        unit_volume_m3: float,
        usd_rub_rate: float,
        usd_cny_rate: float
    ) -> float:
        """
        Calculate purchase price in CNY using new formula:
        1. Budget CN = price_rub * 0.38
        2. Delivery CN = calculate by density (weight/volume)
        3. Raw purchase = Budget CN - Delivery CN
        4. Apply 8-28% constraint from price WB
        5. Convert to CNY

        Args:
            price_rub: WB price in RUB
            unit_weight_kg: Weight of one unit in kg
            unit_volume_m3: Volume of one unit in m³
            usd_rub_rate: USD to RUB exchange rate
            usd_cny_rate: USD to CNY exchange rate

        Returns:
            Purchase price in CNY
        """
        # Step 1: Calculate budget for China
        budget_cn_rub = price_rub * 0.38

        # Step 2: Calculate delivery from China for 1 unit
        if unit_volume_m3 <= 0:
            # If volume is 0 or negative, cannot calculate
            logger.warning(
                "purchase_price_calculation_zero_volume",
                price_rub=price_rub,
                unit_weight_kg=unit_weight_kg,
                unit_volume_m3=unit_volume_m3
            )
            # Fallback to old formula if volume is invalid
            rub_cny_rate = usd_rub_rate / usd_cny_rate if usd_cny_rate > 0 else 11.5
            return (price_rub / 4) / rub_cny_rate

        density_kg_m3 = unit_weight_kg / unit_volume_m3

        # Calculate delivery based on density
        if density_kg_m3 < 100:
            # By volume: 500 USD per m³
            delivery_cn_usd = unit_volume_m3 * 500.0
        else:
            # By weight: get tariff rate from table
            tariff_rate_usd_per_kg = self.cargo_calculator.get_tariff_rate_per_kg(density_kg_m3)
            delivery_cn_usd = unit_weight_kg * tariff_rate_usd_per_kg

        # Convert delivery to RUB
        delivery_cn_rub = delivery_cn_usd * usd_rub_rate

        # Step 3: Calculate raw purchase
        zakupka_raw_rub = budget_cn_rub - delivery_cn_rub

        # Step 4: Apply 8-28% constraint
        zakupka_min_rub = price_rub * 0.08  # Minimum 8%
        zakupka_max_rub = price_rub * 0.28   # Maximum 28%

        if zakupka_raw_rub < zakupka_min_rub:
            zakupka_final_rub = zakupka_min_rub
        elif zakupka_raw_rub > zakupka_max_rub:
            zakupka_final_rub = zakupka_max_rub
        else:
            zakupka_final_rub = zakupka_raw_rub

        # Step 5: Convert to CNY
        rub_cny_rate = usd_rub_rate / usd_cny_rate if usd_cny_rate > 0 else 11.5
        purchase_price_cny = zakupka_final_rub / rub_cny_rate

        logger.info(
            "purchase_price_calculated",
            price_rub=price_rub,
            budget_cn_rub=budget_cn_rub,
            delivery_cn_rub=delivery_cn_rub,
            zakupka_raw_rub=zakupka_raw_rub,
            zakupka_final_rub=zakupka_final_rub,
            purchase_price_cny=purchase_price_cny,
            density_kg_m3=density_kg_m3
        )

        return purchase_price_cny


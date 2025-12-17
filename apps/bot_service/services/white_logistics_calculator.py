"""Service for calculating white logistics costs."""
from typing import Dict, Any, Optional
import structlog

from apps.bot_service.config import config

logger = structlog.get_logger()


class WhiteLogisticsCalculator:
    """Service for calculating white logistics costs."""

    def __init__(
        self,
        base_price_usd: Optional[float] = None,
        docs_rub: Optional[float] = None,
        broker_rub: Optional[float] = None,
        exchange_rate_usd_rub: Optional[float] = None,
        exchange_rate_usd_cny: Optional[float] = None,
        exchange_rate_eur_rub: Optional[float] = None
    ):
        """
        Initialize calculator.

        Args:
            base_price_usd: Base logistics price in USD (defaults to config value)
            docs_rub: Documents cost in RUB (defaults to config value)
            broker_rub: Broker cost in RUB (defaults to config value)
            exchange_rate_usd_rub: USD to RUB exchange rate (defaults to config value)
            exchange_rate_usd_cny: USD to CNY exchange rate (defaults to config value)
            exchange_rate_eur_rub: EUR to RUB exchange rate (defaults to config value)
        """
        self.base_price_usd = base_price_usd or config.WHITE_LOGISTICS_BASE_PRICE_USD
        self.docs_rub = docs_rub or config.WHITE_LOGISTICS_DOCS_RUB
        self.broker_rub = broker_rub or config.WHITE_LOGISTICS_BROKER_RUB
        self.usd_rub = exchange_rate_usd_rub or config.EXCHANGE_RATE_USD_RUB
        self.usd_cny = exchange_rate_usd_cny or config.EXCHANGE_RATE_USD_CNY
        self.eur_rub = exchange_rate_eur_rub or config.EXCHANGE_RATE_EUR_RUB

    def calculate(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate white logistics costs.

        Args:
            input_data: {
                "weight_kg": float,  # Total batch weight in kg
                "volume_m3": float,  # Total batch volume in m³
                "quantity_units": int,  # Number of units
                "goods_value_cny": float,  # Product value in CNY (required)
                "tnved_data": {  # TN VED data
                    "duty_type": str,  # "по весу" | "по единице" | "по паре" | "ad valorem" | etc.
                    "duty_rate": float,  # Duty rate (in EUR/unit or percentage)
                    "vat_rate": float  # VAT rate (percentage, e.g. 20 for 20%)
                }
            }

        Returns:
            {
                "ok": bool,
                "errors": List[str],
                "logistics_usd": float,
                "logistics_rub": float,
                "goods_value_cny": float,
                "goods_value_usd": float,
                "goods_value_rub": float,
                "docs_rub": float,
                "broker_rub": float,
                "duty_rub": float,
                "vat_rub": float,
                "total_rub": float,
                "cost_per_unit_rub": float,
                "cost_per_kg_rub": float
            }
        """
        errors = []
        
        # Extract input data
        weight_kg = input_data.get("weight_kg")
        volume_m3 = input_data.get("volume_m3")
        quantity_units = input_data.get("quantity_units", 1)
        goods_value_cny = input_data.get("goods_value_cny")
        tnved_data = input_data.get("tnved_data")
        
        # Validate required fields
        if weight_kg is None or weight_kg <= 0:
            errors.append("weight_kg is required and must be > 0")
        if volume_m3 is None or volume_m3 <= 0:
            errors.append("volume_m3 is required and must be > 0")
        if goods_value_cny is None or goods_value_cny <= 0:
            errors.append("goods_value_cny is required and must be > 0")
        if not tnved_data:
            errors.append("tnved_data is required")
        
        if errors:
            return {
                "ok": False,
                "errors": errors,
                "logistics_usd": 0.0,
                "logistics_rub": 0.0,
                "goods_value_cny": 0.0,
                "goods_value_usd": 0.0,
                "goods_value_rub": 0.0,
                "docs_rub": 0.0,
                "broker_rub": 0.0,
                "duty_rub": 0.0,
                "vat_rub": 0.0,
                "total_rub": 0.0,
                "cost_per_unit_rub": 0.0,
                "cost_per_kg_rub": 0.0
            }
        
        # Base logistics (in USD)
        # Logistics price: 1850 USD, converted to RUB using exchange rate
        # Exchange rate in config should be CB rate + 2% (e.g., if CB = 98, then rate = 98 * 1.02 = 99.96)
        logistics_usd = self.base_price_usd
        logistics_rub = logistics_usd * self.usd_rub
        
        # Goods value
        goods_value_usd = goods_value_cny / self.usd_cny
        goods_value_rub = goods_value_usd * self.usd_rub
        
        # Documents and broker (in RUB)
        docs_broker_rub = self.docs_rub + self.broker_rub
        
        # Duty calculation
        duty_rub = self._calculate_duty(input_data, tnved_data)
        
        # VAT calculation
        vat_rub = self._calculate_vat(goods_value_usd, duty_rub, tnved_data)
        
        # Total cost
        total_rub = (
            logistics_rub +
            goods_value_rub +
            docs_broker_rub +
            duty_rub +
            vat_rub
        )
        
        # Per unit and per kg costs
        cost_per_unit_rub = total_rub / quantity_units if quantity_units > 0 else total_rub
        cost_per_kg_rub = total_rub / weight_kg
        
        logger.info(
            "white_logistics_calculation_completed",
            weight_kg=weight_kg,
            volume_m3=volume_m3,
            quantity_units=quantity_units,
            total_rub=round(total_rub, 2)
        )
        
        return {
            "ok": True,
            "errors": [],
            "logistics_usd": round(logistics_usd, 2),
            "logistics_rub": round(logistics_rub, 2),
            "goods_value_cny": round(goods_value_cny, 2),
            "goods_value_usd": round(goods_value_usd, 2),
            "goods_value_rub": round(goods_value_rub, 2),
            "docs_rub": round(self.docs_rub, 2),
            "broker_rub": round(self.broker_rub, 2),
            "duty_rub": round(duty_rub, 2),
            "vat_rub": round(vat_rub, 2),
            "total_rub": round(total_rub, 2),
            "cost_per_unit_rub": round(cost_per_unit_rub, 2),
            "cost_per_kg_rub": round(cost_per_kg_rub, 2)
        }

    def _calculate_duty(self, input_data: Dict[str, Any], tnved_data: Dict[str, Any]) -> float:
        """
        Calculate duty based on TN VED data.
        
        Each duty type has its own formula:
        - ad_valorem: duty = goods_value_rub * (duty_rate / 100)
        - по весу: duty = weight_kg * duty_rate * eur_rub
        - по единице: duty = quantity_units * duty_rate * eur_rub
        - по паре: duty = quantity_units * duty_rate * eur_rub

        Args:
            input_data: Input data with weight_kg, volume_m3, quantity_units, goods_value_cny
            tnved_data: TN VED data with duty_type and duty_rate

        Returns:
            Duty in RUB
        """
        duty_type = str(tnved_data.get("duty_type", "")).strip().lower()
        duty_rate = tnved_data.get("duty_rate", 0.0)
        
        if not duty_rate or duty_rate <= 0:
            return 0.0
        
        # Convert duty_rate to float if it's a string
        if isinstance(duty_rate, str):
            duty_rate = float(duty_rate.replace("%", "").replace(",", ".").strip())
        
        # Formula 1: Ad valorem (percentage) - duty_rate is percentage (e.g., 20 for 20%)
        if duty_type == "ad_valorem" or "ad valorem" in duty_type:
            goods_value_cny = input_data.get("goods_value_cny", 0)
            goods_value_usd = goods_value_cny / self.usd_cny
            goods_value_rub = goods_value_usd * self.usd_rub
            duty_percentage = duty_rate / 100.0  # Convert percentage to decimal
            duty_rub = goods_value_rub * duty_percentage
            
            logger.info(
                "duty_calculated_ad_valorem",
                duty_type=duty_type,
                duty_rate=duty_rate,
                goods_value_rub=round(goods_value_rub, 2),
                duty_rub=round(duty_rub, 2)
            )
            return duty_rub
        
        # Formula 2: По весу (EUR/кг) - duty_rate is EUR per kg
        elif duty_type == "по весу":
            weight_kg = input_data.get("weight_kg", 0)
            duty_rub = weight_kg * duty_rate * self.eur_rub
            
            logger.info(
                "duty_calculated_by_weight",
                duty_type=duty_type,
                duty_rate=duty_rate,
                weight_kg=weight_kg,
                eur_rub=self.eur_rub,
                duty_rub=round(duty_rub, 2)
            )
            return duty_rub
        
        # Formula 3: По единице (EUR/шт) - duty_rate is EUR per unit
        elif duty_type == "по единице":
            quantity_units = input_data.get("quantity_units", 1)
            duty_rub = quantity_units * duty_rate * self.eur_rub
            
            logger.info(
                "duty_calculated_by_unit",
                duty_type=duty_type,
                duty_rate=duty_rate,
                quantity_units=quantity_units,
                eur_rub=self.eur_rub,
                duty_rub=round(duty_rub, 2)
            )
            return duty_rub
        
        # Formula 4: По паре (EUR/пар) - duty_rate is EUR per pair
        elif duty_type == "по паре":
            quantity_units = input_data.get("quantity_units", 1)
            duty_rub = quantity_units * duty_rate * self.eur_rub
            
            logger.info(
                "duty_calculated_by_pair",
                duty_type=duty_type,
                duty_rate=duty_rate,
                quantity_units=quantity_units,
                eur_rub=self.eur_rub,
                duty_rub=round(duty_rub, 2)
            )
            return duty_rub
        
        # Unknown duty type - log error and return 0
        else:
            logger.error(
                "unknown_duty_type",
                duty_type=duty_type,
                duty_rate=duty_rate,
                message=f"Unknown duty type '{duty_type}', cannot calculate duty"
            )
            return 0.0

    def _calculate_vat(self, goods_value_usd: float, duty_rub: float, tnved_data: Dict[str, Any]) -> float:
        """
        Calculate VAT.

        VAT = (goods_value_rub + 900 USD in RUB + duty_rub) * vat_rate

        Args:
            goods_value_usd: Goods value in USD
            duty_rub: Duty in RUB
            tnved_data: TN VED data with vat_rate

        Returns:
            VAT in RUB
        """
        vat_rate_percentage = tnved_data.get("vat_rate", 20)  # Default 20%
        vat_rate = vat_rate_percentage / 100.0  # Convert to decimal
        
        goods_value_rub = goods_value_usd * self.usd_rub
        base_for_vat = goods_value_rub + (900 * self.usd_rub) + duty_rub  # 900 USD = fixed logistics cost for VAT
        
        return base_for_vat * vat_rate


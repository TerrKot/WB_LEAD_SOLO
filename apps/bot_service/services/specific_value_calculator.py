"""Service for calculating specific value (USD/kg) of a product."""
from typing import Dict, Any, Optional
import structlog

from apps.bot_service.config import config

logger = structlog.get_logger()


class SpecificValueCalculator:
    """Service for calculating specific value (USD/kg) of a product."""

    def __init__(self, exchange_rate_usd_rub: Optional[float] = None):
        """
        Initialize calculator.

        Args:
            exchange_rate_usd_rub: USD to RUB exchange rate (defaults to config value)
        """
        self.exchange_rate_usd_rub = exchange_rate_usd_rub or config.EXCHANGE_RATE_USD_RUB

    def calculate(
        self,
        product_price_kopecks: int,
        product_weight_kg: float,
        quantity: int = 1
    ) -> Optional[float]:
        """
        Calculate specific value (USD/kg) = (batch cost in USD) / (batch weight in kg).

        Args:
            product_price_kopecks: Product price in kopecks (from WB API)
            product_weight_kg: Product weight in kg
            quantity: Quantity of items in batch (default: 1)

        Returns:
            Specific value in USD/kg or None if calculation is not possible
        """
        if product_weight_kg is None or product_weight_kg <= 0:
            logger.warning(
                "specific_value_calculation_failed",
                reason="invalid_weight",
                weight=product_weight_kg
            )
            return None

        if product_price_kopecks is None or product_price_kopecks <= 0:
            logger.warning(
                "specific_value_calculation_failed",
                reason="invalid_price",
                price=product_price_kopecks
            )
            return None

        if quantity <= 0:
            logger.warning(
                "specific_value_calculation_failed",
                reason="invalid_quantity",
                quantity=quantity
            )
            return None

        # Convert price from kopecks to RUB
        price_rub = product_price_kopecks / 100.0

        # Calculate batch cost in RUB
        batch_cost_rub = price_rub * quantity

        # Convert to USD
        batch_cost_usd = batch_cost_rub / self.exchange_rate_usd_rub

        # Calculate batch weight in kg
        batch_weight_kg = product_weight_kg * quantity

        # Calculate specific value (USD/kg)
        specific_value_usd_per_kg = batch_cost_usd / batch_weight_kg

        logger.info(
            "specific_value_calculated",
            price_kopecks=product_price_kopecks,
            weight_kg=product_weight_kg,
            quantity=quantity,
            batch_cost_usd=round(batch_cost_usd, 2),
            batch_weight_kg=round(batch_weight_kg, 2),
            specific_value_usd_per_kg=round(specific_value_usd_per_kg, 2)
        )

        return round(specific_value_usd_per_kg, 2)

    def calculate_from_product_data(
        self,
        product_data: Dict[str, Any],
        quantity: int = 1
    ) -> Optional[float]:
        """
        Calculate specific value from product data dictionary.

        Args:
            product_data: Product data dictionary (from WB parser)
            quantity: Quantity of items in batch (default: 1)

        Returns:
            Specific value in USD/kg or None if calculation is not possible
        """
        # Extract price from product data
        # Price is in kopecks, stored in sizes[0].price.product or sizes[0].price.basic
        price_kopecks = None
        sizes = product_data.get('sizes', [])
        if sizes and isinstance(sizes[0], dict):
            price_info = sizes[0].get('price', {})
            if isinstance(price_info, dict):
                price_kopecks = price_info.get('product') or price_info.get('basic')
                if price_kopecks is not None:
                    price_kopecks = int(price_kopecks)

        # Extract weight from product data
        weight_kg = product_data.get('weight')
        if weight_kg is not None:
            try:
                weight_kg = float(weight_kg)
            except (ValueError, TypeError):
                weight_kg = None

        if price_kopecks is None or weight_kg is None:
            logger.warning(
                "specific_value_calculation_failed",
                reason="missing_data",
                has_price=price_kopecks is not None,
                has_weight=weight_kg is not None
            )
            return None

        return self.calculate(price_kopecks, weight_kg, quantity)


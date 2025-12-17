"""Required fields validator for product data."""
from typing import Dict, Any, List, Tuple, Optional
import structlog

from apps.bot_service.services.gpt_service import GPTService
from apps.bot_service.services.wb_parser import WBParserService

logger = structlog.get_logger()

# Required fields for express calculation
REQUIRED_FIELDS = ['price', 'name', 'weight', 'volume']


class FieldsValidator:
    """Validator for required product fields."""

    def __init__(self, gpt_service: Optional[GPTService] = None):
        """
        Initialize Fields Validator.

        Args:
            gpt_service: GPT Service instance (creates new if None)
        """
        self.gpt_service = gpt_service or GPTService()
        self.wb_parser = WBParserService()

    async def validate_and_fill_fields(
        self, product: Dict[str, Any]
    ) -> Tuple[bool, List[str], Dict[str, Any]]:
        """
        Validate required fields and fill missing weight/volume via GPT if needed.

        Args:
            product: Normalized product data from WB API

        Returns:
            (is_valid, missing_fields, product_with_filled_fields)
            - is_valid: True if all required fields are present
            - missing_fields: List of field names that are still missing
            - product_with_filled_fields: Product dict with filled weight/volume if GPT succeeded
        """
        # Create a copy to avoid modifying original
        product_copy = dict(product)
        missing_fields = []

        # Check required fields
        for field in REQUIRED_FIELDS:
            if not self._has_field(product_copy, field):
                missing_fields.append(field)

        # If weight or volume are missing, try to get them from GPT
        if 'weight' in missing_fields or 'volume' in missing_fields:
            logger.info(
                "fields_missing_weight_volume",
                missing_fields=missing_fields,
                product_id=product_copy.get('id')
            )

            # Get product name for GPT
            product_name = self.wb_parser.get_product_name(product_copy) or "Товар"
            product_description = self.wb_parser.get_product_description(product_copy)

            # Request weight/volume from GPT
            gpt_result = await self.gpt_service.get_weight_volume(
                product_name, product_description
            )

            if gpt_result:
                # Fill missing fields from GPT response
                if 'weight' in missing_fields and 'weight' in gpt_result:
                    product_copy['weight'] = gpt_result['weight']
                    missing_fields.remove('weight')
                    logger.info(
                        "field_filled_from_gpt",
                        field="weight",
                        value=gpt_result['weight'],
                        product_id=product_copy.get('id')
                    )

                if 'volume' in missing_fields and 'volume' in gpt_result:
                    # Convert liters to the format expected by WB API (if needed)
                    # WB API uses volume in liters as integer, but we'll store as float
                    # and convert when needed
                    product_copy['volume'] = int(gpt_result['volume']) if gpt_result['volume'] > 0 else None
                    if product_copy['volume']:
                        missing_fields.remove('volume')
                        logger.info(
                            "field_filled_from_gpt",
                            field="volume",
                            value=product_copy['volume'],
                            product_id=product_copy.get('id')
                        )
            else:
                logger.warning(
                    "gpt_weight_volume_failed",
                    product_id=product_copy.get('id'),
                    product_name=product_name
                )

        # Check if all required fields are now present
        is_valid = len(missing_fields) == 0

        if is_valid:
            logger.info(
                "fields_validation_success",
                product_id=product_copy.get('id')
            )
        else:
            logger.warning(
                "fields_validation_failed",
                product_id=product_copy.get('id'),
                missing_fields=missing_fields
            )

        return is_valid, missing_fields, product_copy

    def _has_field(self, product: Dict[str, Any], field: str) -> bool:
        """
        Check if product has a valid value for the field.

        Args:
            product: Product data
            field: Field name to check

        Returns:
            True if field exists and has valid value
        """
        if field == 'price':
            # Price is in sizes[].price.product or sizes[].price.basic
            price = self.wb_parser.get_product_price(product)
            return price is not None and price > 0

        elif field == 'name':
            # Name should be non-empty string
            name = self.wb_parser.get_product_name(product)
            return name is not None and len(name.strip()) > 0

        elif field == 'weight':
            # Weight should be positive number
            weight = self.wb_parser.get_product_weight(product)
            return weight is not None and weight > 0

        elif field == 'volume':
            # Volume should be positive integer
            volume = self.wb_parser.get_product_volume(product)
            return volume is not None and volume > 0

        else:
            # Unknown field, check if exists and not None/empty
            value = product.get(field)
            if value is None:
                return False
            if isinstance(value, str):
                return len(value.strip()) > 0
            if isinstance(value, (list, dict)):
                return len(value) > 0
            return True


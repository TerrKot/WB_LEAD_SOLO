"""Calculation worker for processing calculation queue."""
import asyncio
import sys
import json
import signal
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import redis.asyncio as redis
import structlog
import logging

from apps.bot_service.config import config
from apps.bot_service.clients.database import DatabaseClient
from apps.bot_service.services.fields_validator import FieldsValidator
from apps.bot_service.services.gpt_service import GPTService
from apps.bot_service.services.wb_parser import WBParserService
from apps.bot_service.services.tn_ved_red_zone_checker import TNVEDRedZoneChecker
from apps.bot_service.services.specific_value_calculator import SpecificValueCalculator
from apps.bot_service.services.express_assessment_generator import ExpressAssessmentGenerator
from apps.bot_service.services.detailed_calculation_service import DetailedCalculationService
from apps.bot_service.services.exchange_rate_service import ExchangeRateService
from apps.bot_service.utils.error_handler import ErrorHandler
from apps.bot_service.utils.logger_utils import log_event

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=False,
)

logger = structlog.get_logger()


class CalculationWorker:
    """Worker for processing calculation queue."""

    def __init__(self, redis_url: str, database_url: str = None):
        """
        Initialize worker.

        Args:
            redis_url: Redis connection URL
            database_url: PostgreSQL connection URL (optional)
        """
        self.redis_url = redis_url
        self.database_url = database_url
        self.redis: redis.Redis = None
        self.db_client: DatabaseClient = None
        self.fields_validator = FieldsValidator()
        self.gpt_service = GPTService()
        self.wb_parser = WBParserService()
        self.red_zone_checker = TNVEDRedZoneChecker()
        self.specific_value_calculator = SpecificValueCalculator()
        self.express_assessment_generator = ExpressAssessmentGenerator()
        # Exchange rate service for fetching current rates from CBR API
        self.exchange_rate_service = ExchangeRateService()
        
        # Detailed calculation service will use rates from exchange_rate_service
        self.detailed_calculation_service = DetailedCalculationService()

    async def connect(self):
        """Connect to Redis and database."""
        self.redis = redis.from_url(self.redis_url, decode_responses=True)
        await self.redis.ping()
        logger.info("worker_redis_connected", redis_url=self.redis_url)
        
        # Connect to database if URL provided
        if self.database_url:
            try:
                self.db_client = DatabaseClient(self.database_url)
                await self.db_client.connect()
                logger.info("worker_database_connected")
            except Exception as e:
                logger.warning("worker_database_connection_failed", error=str(e))
                # Continue without database
                self.db_client = None

    async def disconnect(self):
        """Disconnect from Redis and database."""
        if self.redis:
            await self.redis.close()
            logger.info("worker_redis_disconnected")
        
        if self.db_client:
            try:
                await self.db_client.disconnect()
                logger.info("worker_database_disconnected")
            except Exception as e:
                logger.warning("worker_database_disconnect_error", error=str(e))

    async def process_calculation(self, calculation_id: str, data: dict):
        """
        Process calculation task.

        Args:
            calculation_id: Unique calculation ID
            data: Calculation data
        """
        logger.info("calculation_processing_started", calculation_id=calculation_id)
        
        # Update status to processing
        await self.redis.set(f"calculation:{calculation_id}:status", "processing")
        
        # Check calculation type
        calculation_type = data.get("calculation_type", "express")
        
        if calculation_type == "detailed":
            await self._process_detailed_calculation(calculation_id, data)
            return
        
        # Express calculation (default)
        await self._process_express_calculation(calculation_id, data)
    
    async def _process_express_calculation(self, calculation_id: str, data: dict):
        """Process express calculation."""
        try:
            # Get product data from Redis
            product_data_json = await self.redis.get(f"calculation:{calculation_id}:product_data")
            if not product_data_json:
                raise ValueError(f"Product data not found for calculation {calculation_id}")
            
            product_data = json.loads(product_data_json)
            
            # Validate and fill required fields
            is_valid, missing_fields, product_with_filled_fields = (
                await self.fields_validator.validate_and_fill_fields(product_data)
            )
            
            # Save updated product data back to Redis
            await self.redis.setex(
                f"calculation:{calculation_id}:product_data",
                3600,  # 1 hour TTL
                json.dumps(product_with_filled_fields)
            )
            
            if not is_valid:
                # Fields validation failed
                user_id = data.get("user_id")
                error_message = ErrorHandler.get_user_message_for_calculation_error("fields_validation")
                result = {
                    "status": "failed",
                    "calculation_id": calculation_id,
                    "user_id": user_id,
                    "error": "required_fields_missing",
                    "missing_fields": missing_fields,
                    "message": error_message
                }
                
                await self.redis.setex(
                    f"calculation:{calculation_id}:result",
                    86400,  # 24 hours TTL
                    json.dumps(result)
                )
                await self.redis.set(f"calculation:{calculation_id}:status", "failed")
                
                log_event(
                    "calculation_fields_validation_failed",
                    calculation_id=calculation_id,
                    user_id=user_id,
                    level="warning",
                    missing_fields=missing_fields
                )
                return
            
            # Fields validation successful - continue with TN VED selection
            logger.info(
                "calculation_tn_ved_selection_started",
                calculation_id=calculation_id
            )
            
            # Extract product fields for logging and later use
            product_name = self.wb_parser.get_product_name(product_with_filled_fields) or "Товар"
            product_description = self.wb_parser.get_product_description(product_with_filled_fields)
            product_brand = product_with_filled_fields.get('brand') or None
            product_weight = self.wb_parser.get_product_weight(product_with_filled_fields)
            # Volume is NOT taken from WB API v4 - only from Basket API (card_data)
            product_volume = None
            
            # Fetch card data and category data for enhanced TN VED selection
            article_id = product_with_filled_fields.get('id')
            card_data = None
            category_data = None
            
            if article_id:
                try:
                    # Fetch card data from basket API
                    card_data = await self.wb_parser.fetch_product_card_data(article_id)
                    
                    if card_data:
                        # Extract subject_id from card data for category API
                        subject_id = card_data.get("data", {}).get("subject_id")
                        
                        # Fetch category data
                        category_data = await self.wb_parser.fetch_product_category_data(article_id, subject_id)
                        
                        # Always use package weight and dimensions from card_data (Basket API)
                        # This is the primary source for weight/volume, not WB API v4
                        package_weight = self.wb_parser.get_package_weight(card_data)
                        package_volume = self.wb_parser.calculate_package_volume(card_data)
                        
                        # Update product data with package weight from card_data
                        if package_weight:
                            product_with_filled_fields['weight'] = package_weight
                            product_weight = package_weight
                            logger.info(
                                "package_weight_used_from_card",
                                calculation_id=calculation_id,
                                weight_kg=package_weight
                            )
                        elif not product_weight:
                            # If weight not in card_data, keep from WB API v4 (fallback)
                            logger.warning(
                                "package_weight_not_found_in_card",
                                calculation_id=calculation_id
                            )
                        
                        # Always use volume from card_data (Basket API) - primary source
                        if package_volume:
                            # Convert liters to deciliters (WB API format: volume in 0.1 dm³ units)
                            product_with_filled_fields['volume'] = int(package_volume * 10)
                            product_volume = package_volume
                            logger.info(
                                "package_volume_used_from_card",
                                calculation_id=calculation_id,
                                volume_liters=package_volume
                            )
                        else:
                            logger.warning(
                                "package_volume_not_found_in_card",
                                calculation_id=calculation_id,
                                article_id=article_id
                            )
                        
                        # Save card data to Redis for later use
                        await self.redis.setex(
                            f"calculation:{calculation_id}:card_data",
                            3600,  # 1 hour TTL
                            json.dumps(card_data)
                        )
                        
                        if category_data:
                            await self.redis.setex(
                                f"calculation:{calculation_id}:category_data",
                                3600,  # 1 hour TTL
                                json.dumps(category_data)
                            )
                    else:
                        logger.warning(
                            "card_data_not_available",
                            calculation_id=calculation_id,
                            article_id=article_id
                        )
                except Exception as e:
                    logger.warning(
                        "card_data_fetch_error",
                        calculation_id=calculation_id,
                        article_id=article_id,
                        error=str(e),
                        error_class=type(e).__name__
                    )
                    # Continue without card_data - will use fallback approach
            
            # If volume is still not set (card_data unavailable or volume not found in card_data),
            # try to get it from GPT (fallback)
            if not product_volume:
                logger.info(
                    "volume_not_found_trying_gpt_fallback",
                    calculation_id=calculation_id,
                    product_name=product_name
                )
                gpt_result = await self.gpt_service.get_weight_volume(
                    product_name, product_description
                )
                if gpt_result and 'volume' in gpt_result:
                    product_volume = gpt_result['volume']
                    # Convert liters to deciliters (WB API format: volume in 0.1 dm³ units)
                    product_with_filled_fields['volume'] = int(product_volume * 10)
                    logger.info(
                        "volume_filled_from_gpt_fallback",
                        calculation_id=calculation_id,
                        volume_liters=product_volume
                    )
                else:
                    logger.warning(
                        "volume_not_found_even_with_gpt_fallback",
                        calculation_id=calculation_id
                    )
            
            # Первый уровень проверки: проверка запрещенных категорий по смыслу
            logger.info(
                "calculation_forbidden_categories_check_started",
                calculation_id=calculation_id,
                product_name=product_name
            )
            
            forbidden_check = await self.gpt_service.check_forbidden_categories(
                product_name=product_name,
                product_description=product_description
            )
            
            if forbidden_check.get("is_forbidden", False):
                # Товар относится к запрещенной категории - сразу выдаем красную зону
                user_id = data.get("user_id")
                category = forbidden_check.get("category", "запрещенная категория")
                reason = forbidden_check.get("reason", f"Товар относится к категории: {category}")
                
                # Генерируем детальное сообщение для красной зоны с учетом категории
                formatted_message = await self.gpt_service.format_forbidden_category_message(
                    product_name=product_name,
                    category=category,
                    product_weight_kg=product_weight,
                    product_volume_liters=product_volume
                )
                
                # Если GPT не смог сгенерировать сообщение, используем базовый шаблон
                if not formatted_message:
                    base_message = self.express_assessment_generator.generate_template(
                        status="🔴",
                        product_name=product_name,
                        tn_ved_code=None,  # Код ТН ВЭД еще не определен
                        red_zone_reason=reason
                    )
                    final_message = base_message
                else:
                    final_message = formatted_message
                
                result = {
                    "status": "blocked",
                    "calculation_id": calculation_id,
                    "user_id": user_id,
                    "fields_validated": True,
                    "tn_ved_selected": False,  # Код ТН ВЭД не был подобран
                    "forbidden_category": category,
                    "forbidden_reason": reason,
                    "red_zone_decision": "BLOCK",
                    "red_zone_reason": reason,
                    "message": final_message
                }
                
                await self.redis.setex(
                    f"calculation:{calculation_id}:result",
                    86400,  # 24 hours TTL
                    json.dumps(result)
                )
                await self.redis.set(f"calculation:{calculation_id}:status", "blocked")
                
                # Сохраняем в базу данных
                if self.db_client:
                    try:
                        article_id = product_with_filled_fields.get('id') or product_with_filled_fields.get('nm_id') or data.get('article_id')
                        if article_id:
                            await self.db_client.save_calculation(
                                calculation_id=calculation_id,
                                user_id=user_id,
                                article_id=article_id,
                                calculation_type="express",
                                status="🔴",
                                tn_ved_code=None,
                                express_result=result
                            )
                    except Exception as e:
                        logger.warning("calculation_db_save_failed", calculation_id=calculation_id, error=str(e))
                
                logger.info(
                    "calculation_forbidden_category_blocked",
                    calculation_id=calculation_id,
                    category=category,
                    reason=reason
                )
                return
            
            # Request TN VED code from GPT using card_data if available, otherwise use product_data
            tn_ved_data = await self.gpt_service.get_tn_ved_code(
                product_data=product_with_filled_fields,
                card_data=card_data,
                category_data=category_data
            )
            
            if not tn_ved_data:
                # TN VED selection failed
                user_id = data.get("user_id")
                error_message = ErrorHandler.get_user_message_for_calculation_error("tn_ved_selection")
                result = {
                    "status": "failed",
                    "calculation_id": calculation_id,
                    "user_id": user_id,
                    "error": "tn_ved_selection_failed",
                    "message": error_message
                }
                
                await self.redis.setex(
                    f"calculation:{calculation_id}:result",
                    86400,  # 24 hours TTL
                    json.dumps(result)
                )
                await self.redis.set(f"calculation:{calculation_id}:status", "failed")
                
                log_event(
                    "calculation_tn_ved_selection_failed",
                    calculation_id=calculation_id,
                    user_id=user_id,
                    level="warning",
                    product_name=product_name[:100]  # Truncate for logging
                )
                return
            
            # Save TN VED data to Redis
            logger.info(
                "saving_tn_ved_data_to_redis",
                calculation_id=calculation_id,
                tn_ved_code=tn_ved_data.get("tn_ved_code"),
                has_duty_minimum="duty_minimum" in tn_ved_data,
                duty_minimum=tn_ved_data.get("duty_minimum"),
                tn_ved_data_keys=list(tn_ved_data.keys())
            )
            await self.redis.setex(
                f"calculation:{calculation_id}:tn_ved_data",
                3600,  # 1 hour TTL
                json.dumps(tn_ved_data)
            )
            
            # Update product data with TN VED code
            product_with_filled_fields['tn_ved_code'] = tn_ved_data['tn_ved_code']
            product_with_filled_fields['duty_type'] = tn_ved_data['duty_type']
            product_with_filled_fields['duty_rate'] = tn_ved_data['duty_rate']
            product_with_filled_fields['vat_rate'] = tn_ved_data['vat_rate']
            
            # Save updated product data back to Redis
            await self.redis.setex(
                f"calculation:{calculation_id}:product_data",
                3600,  # 1 hour TTL
                json.dumps(product_with_filled_fields)
            )
            
            # Check red zone
            logger.info(
                "calculation_red_zone_check_started",
                calculation_id=calculation_id,
                tn_ved_code=tn_ved_data['tn_ved_code']
            )
            
            decision, reason = self.red_zone_checker.check_code(tn_ved_data['tn_ved_code'])
            
            if decision == "BLOCK":
                # Code is in red zone - block and terminate express calculation
                # Get user_id from calculation data
                user_id = data.get("user_id")
                
                # Generate base message template
                base_message = self.express_assessment_generator.generate_template(
                    status="🔴",
                    product_name=product_name,
                    tn_ved_code=tn_ved_data['tn_ved_code'],
                    red_zone_reason=reason
                )
                
                # Format message with GPT for better readability
                formatted_message = await self.gpt_service.format_express_result_message(
                    base_message=base_message,
                    status="🔴",
                    product_name=product_name,
                    tn_ved_code=tn_ved_data['tn_ved_code'],
                    red_zone_reason=reason,
                    product_weight_kg=product_weight,
                    product_volume_liters=product_volume
                )
                
                # Use formatted message if available, otherwise fallback to base
                final_message = formatted_message if formatted_message else base_message
                
                result = {
                    "status": "blocked",
                    "calculation_id": calculation_id,
                    "user_id": user_id,
                    "fields_validated": True,
                    "tn_ved_selected": True,
                    "tn_ved_code": tn_ved_data['tn_ved_code'],
                    "red_zone_decision": "BLOCK",
                    "red_zone_reason": reason,
                    "message": final_message
                }
                
                await self.redis.setex(
                    f"calculation:{calculation_id}:result",
                    86400,  # 24 hours TTL
                    json.dumps(result)
                )
                await self.redis.set(f"calculation:{calculation_id}:status", "blocked")
                
                # Save to database
                if self.db_client:
                    try:
                        article_id = product_with_filled_fields.get('id') or product_with_filled_fields.get('nm_id') or data.get('article_id')
                        if article_id:
                            await self.db_client.save_calculation(
                                calculation_id=calculation_id,
                                user_id=user_id,
                                article_id=article_id,
                                calculation_type="express",
                                status="🔴",
                                tn_ved_code=tn_ved_data['tn_ved_code'],
                                express_result=result
                            )
                    except Exception as e:
                        logger.warning("calculation_db_save_failed", calculation_id=calculation_id, error=str(e))
                
                logger.info(
                    "calculation_red_zone_blocked",
                    calculation_id=calculation_id,
                    tn_ved_code=tn_ved_data['tn_ved_code'],
                    reason=reason
                )
                return
            
            # Check orange zone (only if not blocked by red zone)
            logger.info(
                "calculation_orange_zone_check_started",
                calculation_id=calculation_id,
                tn_ved_code=tn_ved_data['tn_ved_code'],
                duty_type=tn_ved_data['duty_type']
            )
            
            orange_zone_result = await self.gpt_service.check_orange_zone(
                product_name=product_name,
                tn_ved_code=tn_ved_data['tn_ved_code'],
                duty_type=tn_ved_data['duty_type'],
                product_description=product_description,
                product_brand=product_brand
            )
            
            if not orange_zone_result:
                # Orange zone check failed - treat as error
                user_id = data.get("user_id")
                error_message = ErrorHandler.get_user_message_for_calculation_error("orange_zone_check")
                result = {
                    "status": "failed",
                    "calculation_id": calculation_id,
                    "user_id": user_id,
                    "error": "orange_zone_check_failed",
                    "message": error_message
                }
                
                await self.redis.setex(
                    f"calculation:{calculation_id}:result",
                    86400,  # 24 hours TTL
                    json.dumps(result)
                )
                await self.redis.set(f"calculation:{calculation_id}:status", "failed")
                
                log_event(
                    "calculation_orange_zone_check_failed",
                    calculation_id=calculation_id,
                    user_id=user_id,
                    level="warning",
                    tn_ved_code=tn_ved_data['tn_ved_code']
                )
                return
            
            # Check if product is in orange zone (pass = 0)
            if orange_zone_result["pass"] == 0:
                # Product is in orange zone - terminate express calculation
                user_id = data.get("user_id")
                
                # Generate express assessment message for orange zone
                assessment_result = self.express_assessment_generator.generate_result_dict(
                    status="🟠",
                    product_data=product_with_filled_fields,
                    tn_ved_code=tn_ved_data['tn_ved_code'],
                    orange_zone_reason=orange_zone_result["reason"]
                )
                
                # Format message with GPT for better readability
                formatted_message = await self.gpt_service.format_express_result_message(
                    base_message=assessment_result["message"],
                    status="🟠",
                    product_name=product_name,
                    tn_ved_code=tn_ved_data['tn_ved_code'],
                    orange_zone_reason=orange_zone_result["reason"],
                    product_weight_kg=product_weight,
                    product_volume_liters=product_volume
                )
                
                # Use formatted message if available, otherwise fallback to base
                final_message = formatted_message if formatted_message else assessment_result["message"]
                
                result = {
                    "status": "🟠",
                    "calculation_id": calculation_id,
                    "user_id": user_id,
                    "fields_validated": True,
                    "tn_ved_selected": True,
                    "tn_ved_code": tn_ved_data['tn_ved_code'],
                    "duty_type": tn_ved_data['duty_type'],
                    "duty_rate": tn_ved_data['duty_rate'],
                    "vat_rate": tn_ved_data['vat_rate'],
                    "duty_minimum": tn_ved_data.get('duty_minimum'),  # Приписка о минимальной пошлине
                    "red_zone_decision": decision,
                    "orange_zone_pass": 0,
                    "orange_zone_reason": orange_zone_result["reason"],
                    "product_data": product_with_filled_fields,
                    "message": final_message
                }
                
                await self.redis.setex(
                    f"calculation:{calculation_id}:result",
                    86400,  # 24 hours TTL
                    json.dumps(result)
                )
                # Save status as "orange_zone" for Redis, but result contains "🟠" status
                await self.redis.set(f"calculation:{calculation_id}:status", "orange_zone")
                
                # Save to database
                if self.db_client:
                    try:
                        article_id = product_with_filled_fields.get('id') or product_with_filled_fields.get('nm_id') or data.get('article_id')
                        if article_id:
                            await self.db_client.save_calculation(
                                calculation_id=calculation_id,
                                user_id=user_id,
                                article_id=article_id,
                                calculation_type="express",
                                status="🟠",
                                tn_ved_code=tn_ved_data['tn_ved_code'],
                                express_result=result
                            )
                    except Exception as e:
                        logger.warning("calculation_db_save_failed", calculation_id=calculation_id, error=str(e))
                
                logger.info(
                    "calculation_orange_zone_blocked",
                    calculation_id=calculation_id,
                    tn_ved_code=tn_ved_data['tn_ved_code'],
                    reason=orange_zone_result["reason"]
                )
                return
            
            # Continue with express assessment (specific value calculation and classification)
            logger.info(
                "calculation_express_assessment_started",
                calculation_id=calculation_id
            )
            
            # Get current exchange rates for express calculation
            # Use cargo rates (+4%) for consistency with detailed calculation
            cargo_rates = await self.exchange_rate_service.get_rates_for_cargo()
            # Update specific value calculator with current cargo rate
            self.specific_value_calculator.exchange_rate_usd_rub = cargo_rates["usd_rub"]
            
            # Calculate specific value (USD/kg)
            specific_value_usd_per_kg = self.specific_value_calculator.calculate_from_product_data(
                product_with_filled_fields,
                quantity=1  # For express assessment, we use single item
            )
            
            if specific_value_usd_per_kg is None:
                # Specific value calculation failed
                user_id = data.get("user_id")
                error_message = ErrorHandler.get_user_message_for_calculation_error("specific_value_calculation")
                result = {
                    "status": "failed",
                    "calculation_id": calculation_id,
                    "user_id": user_id,
                    "error": "specific_value_calculation_failed",
                    "message": error_message
                }
                
                await self.redis.setex(
                    f"calculation:{calculation_id}:result",
                    86400,  # 24 hours TTL
                    json.dumps(result)
                )
                await self.redis.set(f"calculation:{calculation_id}:status", "failed")
                
                log_event(
                    "calculation_specific_value_failed",
                    calculation_id=calculation_id,
                    user_id=user_id,
                    level="warning"
                )
                return
            
            # Classify by specific value (🟢 or 🟡)
            assessment_status = self.express_assessment_generator.classify_by_specific_value(
                specific_value_usd_per_kg
            )
            
            # Generate express assessment result
            user_id = data.get("user_id")
            assessment_result = self.express_assessment_generator.generate_result_dict(
                status=assessment_status,
                specific_value_usd_per_kg=specific_value_usd_per_kg,
                product_data=product_with_filled_fields,
                tn_ved_code=tn_ved_data['tn_ved_code']
            )
            
            # Format message with GPT for better readability
            formatted_message = await self.gpt_service.format_express_result_message(
                base_message=assessment_result["message"],
                status=assessment_status,
                product_name=product_name,
                tn_ved_code=tn_ved_data['tn_ved_code'],
                specific_value_usd_per_kg=specific_value_usd_per_kg,
                product_weight_kg=product_weight,
                product_volume_liters=product_volume
            )
            
            # Use formatted message if available, otherwise fallback to base
            final_message = formatted_message if formatted_message else assessment_result["message"]
            
            # Build final result
            result = {
                "status": assessment_status,
                "calculation_id": calculation_id,
                "user_id": user_id,
                "fields_validated": True,
                "tn_ved_selected": True,
                "tn_ved_code": tn_ved_data['tn_ved_code'],
                "duty_type": tn_ved_data['duty_type'],
                "duty_rate": tn_ved_data['duty_rate'],
                "vat_rate": tn_ved_data['vat_rate'],
                "duty_minimum": tn_ved_data.get('duty_minimum'),  # Приписка о минимальной пошлине
                "red_zone_decision": decision,
                "orange_zone_pass": orange_zone_result["pass"],
                "specific_value_usd_per_kg": specific_value_usd_per_kg,
                "assessment_status": assessment_status,
                "product_data": product_with_filled_fields,
                "message": final_message
            }
            
            await self.redis.setex(
                f"calculation:{calculation_id}:result",
                86400,  # 24 hours TTL
                json.dumps(result)
            )
            
            # Set status based on assessment
            # For 🟢 and 🟡, we use "completed" status, but result contains assessment_status
            await self.redis.set(f"calculation:{calculation_id}:status", "completed")
            
            # Save to database
            if self.db_client:
                try:
                    article_id = product_with_filled_fields.get('nm_id') or data.get('article_id')
                    if article_id:
                        await self.db_client.save_calculation(
                            calculation_id=calculation_id,
                            user_id=user_id,
                            article_id=article_id,
                            calculation_type="express",
                            status=assessment_status,
                            tn_ved_code=tn_ved_data['tn_ved_code'],
                            express_result=result
                        )
                except Exception as e:
                    logger.warning("calculation_db_save_failed", calculation_id=calculation_id, error=str(e))
            
            logger.info(
                "calculation_express_assessment_completed",
                calculation_id=calculation_id,
                fields_validated=True,
                tn_ved_code=tn_ved_data['tn_ved_code'],
                red_zone_decision=decision,
                orange_zone_pass=orange_zone_result["pass"],
                specific_value_usd_per_kg=specific_value_usd_per_kg,
                assessment_status=assessment_status
            )
        except Exception as e:
            user_id = data.get("user_id")
            await self.redis.set(f"calculation:{calculation_id}:status", "failed")
            error_message = ErrorHandler.get_user_message_for_calculation_error("unknown", str(e)[:200])
            result = {
                "status": "failed",
                "calculation_id": calculation_id,
                "user_id": user_id,
                "error": "unknown_error",
                "message": error_message
            }
            try:
                await self.redis.setex(
                    f"calculation:{calculation_id}:result",
                    86400,
                    json.dumps(result)
                )
            except Exception:
                pass  # If Redis fails, at least we logged the error
            
            log_event(
                "calculation_express_processing_failed",
                calculation_id=calculation_id,
                user_id=user_id,
                level="error",
                error=str(e)[:200],
                error_class=type(e).__name__
            )
            raise
    
    async def _process_detailed_calculation(self, calculation_id: str, data: dict):
        """Process detailed calculation."""
        try:
            # Get product data from Redis
            product_data_json = await self.redis.get(f"calculation:{calculation_id}:product_data")
            if not product_data_json:
                raise ValueError(f"Product data not found for calculation {calculation_id}")
            
            product_data = json.loads(product_data_json)
            
            # Extract parameters
            unit_weight_kg = data.get("unit_weight_kg")
            unit_volume_m3 = data.get("unit_volume_m3")
            purchase_price_cny = data.get("purchase_price_cny")
            tnved_data = data.get("tnved_data")
            
            if not unit_weight_kg or not unit_volume_m3 or not purchase_price_cny or not tnved_data:
                raise ValueError("Missing required parameters for detailed calculation")
            
            # Get unit price from product data
            wb_parser = WBParserService()
            product_price = wb_parser.get_product_price(product_data)
            unit_price_rub = product_price / 100.0 if product_price else 0
            
            # Get current exchange rates from CBR API
            # White logistics: CB rate + 2%
            white_rates = await self.exchange_rate_service.get_rates_for_white()
            # Cargo: CB rate + 4%
            cargo_rates = await self.exchange_rate_service.get_rates_for_cargo()
            
            logger.info(
                "exchange_rates_used",
                white_usd_rub=white_rates["usd_rub"],
                white_usd_cny=white_rates["usd_cny"],
                white_eur_rub=white_rates["eur_rub"],
                cargo_usd_rub=cargo_rates["usd_rub"],
                cargo_usd_cny=cargo_rates["usd_cny"]
            )
            
            # Create detailed calculation service with current exchange rates
            # Note: DetailedCalculationService will use different rates for cargo and white logistics
            # We pass white logistics rates as default, but cargo rates will be passed separately
            detailed_calc_service = DetailedCalculationService(
                exchange_rate_usd_rub=white_rates["usd_rub"],  # Default for white logistics
                exchange_rate_usd_cny=white_rates["usd_cny"],
                exchange_rate_eur_rub=white_rates["eur_rub"]
            )
            
            # Update cargo calculator with cargo rates (+4%)
            detailed_calc_service.cargo_calculator.exchange_rate_usd_rub = cargo_rates["usd_rub"]
            detailed_calc_service.cargo_calculator.exchange_rate_usd_cny = cargo_rates["usd_cny"]
            
            # Update white logistics calculator with white rates (+2%)
            detailed_calc_service.white_logistics_calculator.usd_rub = white_rates["usd_rub"]
            detailed_calc_service.white_logistics_calculator.usd_cny = white_rates["usd_cny"]
            detailed_calc_service.white_logistics_calculator.eur_rub = white_rates["eur_rub"]
            
            # Prepare TN VED data for calculation service
            tnved_calc_data = {
                "duty_type": tnved_data.get("duty_type"),
                "duty_rate": tnved_data.get("duty_rate"),
                "vat_rate": tnved_data.get("vat_rate"),
                "duty_minimum": tnved_data.get("duty_minimum")  # Приписка о минимальной пошлине
            }
            
            # Perform detailed calculation with current exchange rates
            detailed_result = detailed_calc_service.calculate_detailed(
                unit_weight_kg=unit_weight_kg,
                unit_volume_m3=unit_volume_m3,
                unit_price_rub=unit_price_rub,
                purchase_price_cny=purchase_price_cny,
                tnved_data=tnved_calc_data
            )
            
            if not detailed_result.get("ok"):
                # Calculation failed
                user_id = data.get("user_id")
                error_message = ErrorHandler.get_user_message_for_calculation_error("detailed_calculation")
                result = {
                    "status": "failed",
                    "calculation_id": calculation_id,
                    "user_id": user_id,
                    "error": "detailed_calculation_failed",
                    "errors": detailed_result.get("errors", []),
                    "message": error_message
                }
                
                await self.redis.setex(
                    f"calculation:{calculation_id}:result",
                    86400,  # 24 hours TTL
                    json.dumps(result)
                )
                await self.redis.set(f"calculation:{calculation_id}:status", "failed")
                
                log_event(
                    "detailed_calculation_failed",
                    calculation_id=calculation_id,
                    user_id=user_id,
                    level="warning",
                    errors_count=len(detailed_result.get("errors", []))
                )
                return
            
            # Get TN VED data for formatting
            tnved_data = data.get("tnved_data", {})
            
            logger.info(
                "tnved_data_for_formatting",
                calculation_id=calculation_id,
                tnved_data_keys=list(tnved_data.keys()),
                has_duty_minimum="duty_minimum" in tnved_data,
                duty_minimum=tnved_data.get("duty_minimum"),
                duty_type=tnved_data.get("duty_type"),
                duty_rate=tnved_data.get("duty_rate")
            )
            
            # Format result message
            formatted_message = self._format_detailed_result(detailed_result, product_data, tnved_data)
            
            # Build final result
            user_id = data.get("user_id")
            result = {
                "status": "completed",
                "calculation_id": calculation_id,
                "user_id": user_id,
                "calculation_type": "detailed",
                "detailed_result": detailed_result,
                "message": formatted_message
            }
            
            await self.redis.setex(
                f"calculation:{calculation_id}:result",
                86400,  # 24 hours TTL
                json.dumps(result)
            )
            await self.redis.set(f"calculation:{calculation_id}:status", "completed")
            
            # Save to database (update existing express calculation with detailed result)
            if self.db_client:
                try:
                    article_id = product_data.get('id') or product_data.get('nm_id') or data.get('article_id')
                    if article_id:
                        # Get TN VED code from tnved_data
                        tnved_data = data.get("tnved_data", {})
                        tn_ved_code = tnved_data.get("tn_ved_code")
                        
                        # Get original calculation_id if this is a detailed calculation continuation
                        original_calculation_id = data.get("original_calculation_id")
                        # Use original_calculation_id if available, otherwise use current calculation_id
                        db_calculation_id = original_calculation_id if original_calculation_id else calculation_id
                        
                        await self.db_client.save_calculation(
                            calculation_id=db_calculation_id,
                            user_id=user_id,
                            article_id=article_id,
                            calculation_type="detailed",  # Update type to detailed
                            status="completed",
                            tn_ved_code=tn_ved_code,
                            detailed_result=result  # Add detailed result to existing calculation
                        )
                except Exception as e:
                    logger.warning("calculation_db_save_failed", calculation_id=calculation_id, error=str(e))
            
            logger.info(
                "detailed_calculation_completed",
                calculation_id=calculation_id,
                quantity=detailed_result.get("quantity", 0),
                cargo_total=detailed_result.get("cargo", {}).get("cargo_cost_rub", {}).get("total_cargo_rub", 0),
                white_total=detailed_result.get("white_logistics", {}).get("total_rub", 0)
            )
        except Exception as e:
            user_id = data.get("user_id")
            await self.redis.set(f"calculation:{calculation_id}:status", "failed")
            error_message = ErrorHandler.get_user_message_for_calculation_error("unknown", str(e)[:200])
            result = {
                "status": "failed",
                "calculation_id": calculation_id,
                "user_id": user_id,
                "error": "unknown_error",
                "message": error_message
            }
            try:
                await self.redis.setex(
                    f"calculation:{calculation_id}:result",
                    86400,
                    json.dumps(result)
                )
            except Exception:
                pass  # If Redis fails, at least we logged the error
            
            log_event(
                "detailed_calculation_processing_failed",
                calculation_id=calculation_id,
                user_id=user_id,
                level="error",
                error=str(e)[:200],
                error_class=type(e).__name__
            )
            raise
    
    def _format_detailed_result(self, detailed_result: dict, product_data: dict, tnved_data: dict = None) -> str:
        """Format detailed calculation result for user message."""
        wb_parser = WBParserService()
        product_name = wb_parser.get_product_name(product_data) or "Товар"
        
        base_info = detailed_result.get("base_info", {})
        quantity = detailed_result.get("quantity", 0)
        batch_info = detailed_result.get("batch_info", {})
        cargo = detailed_result.get("cargo", {})
        white = detailed_result.get("white_logistics", {})
        comparison = detailed_result.get("comparison", {})
        exchange_rates = detailed_result.get("exchange_rates", {})
        
        # Build message
        message_parts = [
            f"💰 <b>Подробный расчёт: {product_name}</b>\n",
            f"📦 <b>Количество в партии:</b> {quantity} шт.\n"
        ]
        
        # Cargo section
        if cargo.get("ok"):
            cargo_cost_usd = cargo.get("cargo_cost_usd", {})
            cargo_cost_rub = cargo.get("cargo_cost_rub", {})
            cargo_input_normalized = cargo.get("input_normalized", {})
            cargo_usd_rub = exchange_rates.get("cargo_usd_rub", 0)
            cargo_usd_cny = exchange_rates.get("cargo_usd_cny", 0)
            cargo_weight_kg = base_info.get("cargo_weight_kg", 0)
            cargo_volume_m3 = base_info.get("cargo_volume_m3", 0)
            
            # Calculate density (weight/volume)
            density_kg_m3 = cargo_weight_kg / cargo_volume_m3 if cargo_volume_m3 > 0 else 0
            
            # Calculate RUB/CNY rate
            cargo_rub_cny = cargo_usd_rub / cargo_usd_cny if cargo_usd_cny > 0 else 0
            
            # Get goods_value_rub (already calculated with cargo_usd_rub +4%)
            goods_value_rub = cargo_cost_rub.get('goods_value_rub', 0)
            
            # Get goods_value_cny from input_normalized (already calculated correctly in cargo_calculator)
            # This value is calculated as goods_value_usd * cargo_usd_cny, which is correct
            goods_value_cny = cargo_input_normalized.get("goods_value_cny", 0)
            if goods_value_cny == 0:
                # Fallback: calculate from USD if not available
                goods_value_usd = cargo_cost_usd.get('goods_value_usd', 0)
                goods_value_cny = goods_value_usd * cargo_usd_cny if cargo_usd_cny > 0 else 0
            
            # Calculate buyer commission in CNY from USD
            buyer_commission_usd = cargo_cost_usd.get('buyer_commission_usd', 0)
            buyer_commission_cny = buyer_commission_usd * cargo_usd_cny if cargo_usd_cny > 0 else 0
            
            message_parts.extend([
                f"🚚 <b>Карго</b>\n",
                f"(Срок доставки авто 35-50 дней)\n",
                f"-Вес: {cargo_weight_kg:.2f} кг",
                f"-Объём: {cargo_volume_m3:.2f} м³",
                f"-Плотность товара: {density_kg_m3:.2f} кг/м³",
                f"-Курсы: {cargo_usd_rub:.2f} RUB/USD {cargo_rub_cny:.1f} RUB/CNY",
                f"",
                f"Пояснение: Вес с учетом упаковки",
                f"<b>Затраты:</b>",
                f"Доставка: {cargo_cost_usd.get('freight_usd', 0):.2f} USD ({cargo_cost_rub.get('freight_rub', 0):.2f} RUB)",
                f"Страховка: {cargo_cost_usd.get('insurance_usd', 0):.2f} USD ({cargo_cost_rub.get('insurance_rub', 0):.2f} RUB)",
                f"Комиссия байера: {buyer_commission_cny:.0f} CNY ({cargo_cost_rub.get('buyer_commission_rub', 0):.2f} RUB)",
                f"Упаковка: {cargo_cost_usd.get('packaging_usd', 0):.2f} USD ({cargo_cost_rub.get('packaging_rub', 0):.2f} RUB)",
                f"Товар: {goods_value_cny:.0f} CNY ({goods_value_rub:.2f} RUB)",
                f"",
                f"<b>Итого:</b>",
                f"Всего: {cargo_cost_usd.get('total_cargo_usd', 0):.2f} USD ({cargo_cost_rub.get('total_cargo_rub', 0):.2f} RUB)",
                f"За кг: {cargo_cost_usd.get('cost_per_kg_usd', 0):.2f} USD/кг ({cargo_cost_rub.get('cost_per_kg_rub', 0):.2f} RUB/кг)",
                f"За штуку: {cargo_cost_usd.get('cost_per_unit_usd', 0):.2f} USD/шт ({cargo_cost_rub.get('cost_per_unit_rub', 0):.2f} RUB/шт)\n"
            ])
        
        # White logistics section
        if white.get("ok"):
            white_usd_rub = exchange_rates.get("white_usd_rub", 0)
            white_usd_cny = exchange_rates.get("white_usd_cny", 0)
            white_weight_kg = base_info.get("white_weight_kg", 0)
            white_volume_m3 = base_info.get("white_volume_m3", 0)
            
            # Calculate RUB/CNY rate
            white_rub_cny = white_usd_rub / white_usd_cny if white_usd_cny > 0 else 0
            
            # Convert logistics to USD
            logistics_usd = white.get('logistics_usd', 0)
            goods_value_usd = white.get('goods_value_usd', 0)
            total_rub = white.get('total_rub', 0)
            total_usd = total_rub / white_usd_rub if white_usd_rub > 0 else 0
            
            # Get TN VED data for display
            tn_ved_code = ""
            duty_rate_display = ""
            vat_rate_display = ""
            duty_minimum_display = ""
            if tnved_data:
                tn_ved_code = tnved_data.get("tn_ved_code", "")
                duty_type = tnved_data.get("duty_type", "")
                duty_rate = tnved_data.get("duty_rate", 0)
                vat_rate = tnved_data.get("vat_rate", 0)
                duty_minimum = tnved_data.get("duty_minimum")
                
                logger.info(
                    "formatting_tnved_data",
                    tn_ved_code=tn_ved_code,
                    duty_type=duty_type,
                    duty_rate=duty_rate,
                    has_duty_minimum=bool(duty_minimum),
                    duty_minimum=duty_minimum,
                    tnved_data_keys=list(tnved_data.keys())
                )
                
                if duty_rate:
                    # Format duty rate based on duty type
                    if duty_type and ("ad_valorem" in str(duty_type).lower() or "%" in str(duty_type)):
                        duty_rate_display = f"{duty_rate:.0f}%"
                    elif duty_type and "по весу" in str(duty_type):
                        duty_rate_display = f"{duty_rate:.2f} EUR/кг"
                    elif duty_type and "по паре" in str(duty_type):
                        duty_rate_display = f"{duty_rate:.2f} EUR/пар"
                    elif duty_type and "по единице" in str(duty_type):
                        duty_rate_display = f"{duty_rate:.2f} EUR/шт"
                    else:
                        # Default to percentage if type unknown
                        duty_rate_display = f"{duty_rate:.0f}%"
                
                # Добавляем приписку о минимальной пошлине, если она есть
                if duty_minimum and isinstance(duty_minimum, dict):
                    minimum_value = duty_minimum.get("value", 0)
                    minimum_unit = duty_minimum.get("unit", "EUR/кг")
                    duty_minimum_display = f", но не менее {minimum_value:.2f} {minimum_unit}"
                    logger.info(
                        "duty_minimum_display_formatted",
                        duty_minimum=duty_minimum,
                        duty_minimum_display=duty_minimum_display
                    )
                elif duty_minimum:
                    logger.warning(
                        "duty_minimum_not_dict",
                        duty_minimum=duty_minimum,
                        duty_minimum_type=type(duty_minimum).__name__
                    )
                
                if vat_rate:
                    vat_rate_display = f"{vat_rate:.0f}%"
            
            message_parts.extend([
                f"📋 <b>Белая логистика</b>\n",
                f"(срок доставки авто 20-30 дней)\n",
                f"-Вес: {white_weight_kg:.2f} кг",
                f"-Объём: {white_volume_m3:.2f} м³",
                f"-Курс: {white_usd_rub:.2f} RUB/USD {white_rub_cny:.0f}RUB/CNY",
            ])
            
            # Add TN VED code line if available
            if tn_ved_code:
                # Remove spaces and dashes from TN VED code for URL
                tn_ved_code_clean = str(tn_ved_code).replace(" ", "").replace("-", "")
                alta_url = f"https://www.alta.ru/tnved/code/{tn_ved_code_clean}/"
                tn_ved_line = f"код ТНВЭД: {tn_ved_code} <a href=\"{alta_url}\">🔗</a>"
                
                logger.info(
                    "formatting_tnved_line",
                    duty_rate_display=duty_rate_display,
                    duty_minimum_display=duty_minimum_display,
                    vat_rate_display=vat_rate_display,
                    has_duty_minimum=bool(duty_minimum),
                    duty_minimum=duty_minimum
                )
                
                if duty_rate_display and vat_rate_display:
                    tn_ved_line += f" ({duty_rate_display}{duty_minimum_display} пошлина, {vat_rate_display} НДС)"
                elif duty_rate_display:
                    tn_ved_line += f" ({duty_rate_display}{duty_minimum_display} пошлина)"
                elif vat_rate_display:
                    tn_ved_line += f" ({vat_rate_display} НДС)"
                
                logger.info("tnved_line_formatted", tn_ved_line=tn_ved_line)
                message_parts.append(tn_ved_line)
            
            message_parts.extend([
                f"",
                f"<b>Затраты:</b>",
                f"Логистика: {logistics_usd:.2f} USD ({white.get('logistics_rub', 0):.2f} RUB)",
                f"Товар: {goods_value_usd:.2f} USD ({white.get('goods_value_rub', 0):.2f} RUB)",
                f"Брокер: {white.get('broker_rub', 0):.2f} RUB",
                f"Пошлина: {white.get('duty_rub', 0):.2f} RUB{f' ({duty_rate_display}{duty_minimum_display})' if duty_rate_display else ''}",
                f"Таможенные сборы: {white.get('customs_fees_rub', 0):.2f} RUB",
                f"НДС: {white.get('vat_rub', 0):.2f} RUB{f' ({vat_rate_display})' if vat_rate_display else ''}",
                f"",
                f"<b>Итого:</b>",
                f"Всего: {total_usd:.2f} USD ({total_rub:.2f} RUB)",
                f"За кг: {white.get('cost_per_kg_rub', 0):.2f} RUB/кг",
                f"За штуку: {white.get('cost_per_unit_rub', 0):.2f} RUB/шт"
            ])
        
        # Comparison
        if comparison:
            cheaper = comparison.get("cheaper_option", "cargo")
            difference = comparison.get("difference_rub", 0)
            difference_percent = comparison.get("difference_percent", 0)
            
            if cheaper == "cargo":
                message_parts.append(
                    f"\n✅ <b>Карго дешевле на {abs(difference):.2f} ₽ ({abs(difference_percent):.2f}%)</b>"
                )
            else:
                message_parts.append(
                    f"\n✅ <b>Белая логистика дешевле на {abs(difference):.2f} ₽ ({abs(difference_percent):.2f}%)</b>"
                )
        
        return "\n".join(message_parts)

    async def run(self):
        """Run worker loop."""
        await self.connect()
        
        logger.info("worker_started")
        
        # Setup signal handlers for graceful shutdown
        shutdown_event = asyncio.Event()
        
        def signal_handler(sig, frame):
            logger.info("shutdown_signal_received", signal=sig)
            shutdown_event.set()
        
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        try:
            while not shutdown_event.is_set():
                # Blocking pop from queue (timeout 5 seconds)
                result = await self.redis.brpop("calculation_queue", timeout=5)
                
                if result:
                    _, task_json = result
                    task = json.loads(task_json)
                    calculation_id = task.get("calculation_id")
                    data = task.get("data", {})
                    
                    try:
                        await self.process_calculation(calculation_id, data)
                    except Exception as e:
                        logger.error("worker_task_error", calculation_id=calculation_id, error=str(e))
                else:
                    # No tasks, continue loop
                    await asyncio.sleep(0.1)
        except KeyboardInterrupt:
            logger.info("worker_stopping")
        finally:
            logger.info("worker_cleanup_started")
            await self.disconnect()
            logger.info("worker_stopped")


async def main():
    """Main function."""
    worker = CalculationWorker(config.REDIS_URL, config.DATABASE_URL)
    try:
        await worker.run()
    except KeyboardInterrupt:
        logger.info("worker_interrupted")
        sys.exit(0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("worker_interrupted")
        sys.exit(0)


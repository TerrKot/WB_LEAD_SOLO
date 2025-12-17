"""Start command handler."""
import uuid
import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from typing import Annotated
from aiogram import Bot
import structlog

from apps.bot_service.clients.redis import RedisClient
from apps.bot_service.clients.database import DatabaseClient
from apps.bot_service.services.input_parser import InputParser
from apps.bot_service.services.wb_parser import WBParserService
from apps.bot_service.services.exchange_rate_service import ExchangeRateService
from apps.bot_service.utils.error_handler import ErrorHandler
from apps.bot_service.utils.logger_utils import log_event

logger = structlog.get_logger()

router = Router()

# Store redis_client, db_client and bot globally for handlers (will be set in main.py)
_redis_client: RedisClient = None
_db_client: DatabaseClient = None
_bot: Bot = None

def set_redis_client(client: RedisClient):
    """Set Redis client for handlers."""
    global _redis_client
    _redis_client = client

def get_redis_client() -> RedisClient:
    """Get Redis client for handlers."""
    return _redis_client

def set_db_client(client: DatabaseClient):
    """Set Database client for handlers."""
    global _db_client
    _db_client = client

def get_db_client() -> DatabaseClient:
    """Get Database client for handlers."""
    return _db_client

def set_bot(bot: Bot):
    """Set Bot instance for handlers."""
    global _bot
    _bot = bot

def get_bot() -> Bot:
    """Get Bot instance for handlers."""
    return _bot

# FSM States
class ExpressCalculationStates(StatesGroup):
    """FSM states for express calculation."""
    waiting_for_article = State()


class DetailedCalculationStates(StatesGroup):
    """FSM states for detailed calculation."""
    waiting_for_weight = State()
    waiting_for_volume = State()
    waiting_for_purchase_price = State()


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Get main persistent keyboard with 'Новый запрос' button."""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Новый запрос")]
        ],
        resize_keyboard=True,
        persistent=True
    )
    return keyboard


async def handle_start_logic(message: Message, state: FSMContext):
    """Common logic for /start and /newrequest commands."""
    user_id = message.from_user.id
    from_user = message.from_user
    
    # Get redis_client and db_client
    redis_client: RedisClient = get_redis_client()
    db_client: DatabaseClient = get_db_client()
    
    if not redis_client:
        logger.error("redis_client_not_available", user_id=user_id)
        await message.answer("Ошибка: сервис временно недоступен. Попробуйте позже.")
        return
    
    # Save or update user data in database
    if db_client:
        try:
            await db_client.save_or_update_user(
                user_id=user_id,
                username=from_user.username,
                first_name=from_user.first_name,
                last_name=from_user.last_name,
                language_code=from_user.language_code
            )
        except Exception as e:
            logger.warning("user_save_failed", user_id=user_id, error=str(e))
            # Continue even if user save fails
    
    # Check if user already accepted agreement
    agreement_accepted = await redis_client.is_user_agreement_accepted(user_id)
    
    if agreement_accepted:
        # User already accepted, start express calculation
        await start_express_calculation(message, redis_client, user_id, state)
        return
    
    # Show agreement
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Принимаю",
                callback_data="agreement_accepted"
            ),
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data="agreement_rejected"
            )
        ]
    ])
    
    text = """Пользовательское соглашение

Согласие на обработку персональных данных

Для использования бота необходимо принять пользовательское соглашение и дать согласие на обработку персональных данных."""
    
    await message.answer(text, reply_markup=keyboard)
    logger.info("start_command", user_id=user_id)


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Handle /start command - show user agreement or start express calculation."""
    await handle_start_logic(message, state)


@router.message(Command("newrequest"))
async def cmd_newrequest(message: Message, state: FSMContext):
    """Handle /newrequest command - duplicate of /start."""
    await handle_start_logic(message, state)
    logger.info("newrequest_command", user_id=message.from_user.id)


async def start_express_calculation(message: Message, redis_client: RedisClient, user_id: int, state: FSMContext):
    """Start express calculation after agreement acceptance."""
    # Generate calculation_id
    calculation_id = str(uuid.uuid4())
    
    # Save calculation status
    await redis_client.set_calculation_status(calculation_id, "pending")
    
    # Set current calculation for user
    await redis_client.set_user_current_calculation(user_id, calculation_id)
    
    # Set FSM state
    await state.set_state(ExpressCalculationStates.waiting_for_article)
    await state.update_data(calculation_id=calculation_id)
    
    # Request article input (keyboard removed - using bot menu instead)
    await message.answer("Введите артикул WB или ссылку на карточку товара:")
    
    logger.info(
        "express_calculation_started",
        user_id=user_id,
        calculation_id=calculation_id
    )


@router.callback_query(F.data == "agreement_accepted")
async def handle_agreement_accepted(callback: CallbackQuery, state: FSMContext):
    """Handle agreement acceptance - save status and start express calculation."""
    user_id = callback.from_user.id
    
    # Get redis_client from bot data
    redis_client: RedisClient = get_redis_client()
    
    if not redis_client:
        log_event("redis_unavailable", user_id=user_id, level="error")
        error_message = ErrorHandler.get_user_message_for_redis_error("unavailable")
        await callback.answer(error_message, show_alert=True)
        return
    
    # Save agreement acceptance
    await redis_client.set_user_agreement_accepted(user_id)
    
    # Save agreement acceptance to database
    db_client: DatabaseClient = get_db_client()
    if db_client:
        try:
            from datetime import datetime
            from_user = callback.from_user
            await db_client.save_or_update_user(
                user_id=user_id,
                username=from_user.username,
                first_name=from_user.first_name,
                last_name=from_user.last_name,
                language_code=from_user.language_code,
                agreement_accepted=datetime.utcnow()
            )
        except Exception as e:
            logger.warning("user_agreement_save_failed", user_id=user_id, error=str(e))
    
    await callback.answer("Соглашение принято")
    
    # Start express calculation
    await start_express_calculation(callback.message, redis_client, user_id, state)
    
    logger.info("agreement_accepted", user_id=user_id)


@router.callback_query(F.data == "agreement_rejected")
async def handle_agreement_rejected(callback: CallbackQuery):
    """Handle agreement rejection."""
    user_id = callback.from_user.id
    
    await callback.answer("Соглашение отклонено")
    await callback.message.answer("Для использования бота необходимо принять пользовательское соглашение.")
    
    logger.info("agreement_rejected", user_id=user_id)


@router.message(ExpressCalculationStates.waiting_for_article)
async def handle_article_input(message: Message, state: FSMContext):
    """Handle article ID or URL input from user."""
    user_id = message.from_user.id
    text = message.text or ""
    
    logger.info(
        "article_input_received",
        user_id=user_id,
        text=text[:100],  # Log first 100 chars only
        text_length=len(text)
    )
    
    # Get redis_client from bot data
    redis_client: RedisClient = get_redis_client()
    
    if not redis_client:
        log_event("redis_unavailable", user_id=user_id, level="error")
        error_message = ErrorHandler.get_user_message_for_redis_error("unavailable")
        await message.answer(error_message)
        return
    
    # Get calculation_id from state
    current_state = await state.get_state()
    state_data = await state.get_data()
    calculation_id = state_data.get("calculation_id")
    
    logger.info(
        "fsm_state_check",
        user_id=user_id,
        current_state=str(current_state),
        state_data=state_data,
        calculation_id=calculation_id
    )
    
    if not calculation_id:
        logger.error("calculation_id_not_found", user_id=user_id, state_data=state_data, current_state=str(current_state))
        # Try to get from Redis as fallback
        calculation_id = await redis_client.get_user_current_calculation(user_id)
        if calculation_id:
            logger.info("calculation_id_recovered_from_redis", user_id=user_id, calculation_id=calculation_id)
            await state.update_data(calculation_id=calculation_id)
        else:
            await message.answer(
                "Ошибка: сессия истекла. Начните заново с /start или используйте команду /newrequest из меню бота."
            )
            await state.clear()
            return
    
    # Check if input is a URL and detect marketplace type
    input_parser = InputParser()
    
    # Check marketplace type if it's a URL
    if text.strip().startswith("http://") or text.strip().startswith("https://"):
        marketplace_type = input_parser.detect_marketplace_type(text.strip())
        
        if marketplace_type == 'ozon':
            await message.answer(
                "⚠️ Данный функционал ещё в разработке.\n\n"
                "Пожалуйста, отправьте ссылку на товар с Wildberries."
            )
            logger.info("ozon_link_rejected", user_id=user_id, calculation_id=calculation_id)
            return
        
        if marketplace_type == 'yandex':
            await message.answer(
                "⚠️ Данный функционал ещё в разработке.\n\n"
                "Пожалуйста, отправьте ссылку на товар с Wildberries."
            )
            logger.info("yandex_link_rejected", user_id=user_id, calculation_id=calculation_id)
            return
        
        # If it's a URL but not Wildberries and not detected as Ozon/Yandex, still try to process
        # (might be a different WB domain or format)
        if marketplace_type != 'wildberries' and marketplace_type is not None:
            await message.answer(
                "⚠️ Данный функционал ещё в разработке.\n\n"
                "Пожалуйста, отправьте ссылку на товар с Wildberries."
            )
            logger.info("unknown_marketplace_link_rejected", user_id=user_id, marketplace_type=marketplace_type, calculation_id=calculation_id)
            return
    
    # Extract article ID from input
    article_id = input_parser.extract_article_from_text(text)
    
    if not article_id:
        await message.answer(
            "❌ Не удалось извлечь артикул из введённых данных.\n\n"
            "Пожалуйста, введите:\n"
            "• Артикул WB (например: 154345562)\n"
            "• Или ссылку на карточку товара (например: https://www.wildberries.ru/catalog/154345562/detail.aspx)"
        )
        logger.warning("article_extraction_failed", user_id=user_id, text_length=len(text))
        return
    
    logger.info("article_extracted", user_id=user_id, article_id=article_id, calculation_id=calculation_id)
    
    # Send first status message (product info) - without keyboard as it will be edited
    product_info_message = await message.answer("🔍 Получаю данные о товаре...")
    product_info_message_id = product_info_message.message_id
    
    wb_parser = WBParserService()
    
    try:
        product_data = await wb_parser.get_product_by_article(article_id)
    except Exception as e:
        error_type = ErrorHandler.classify_wb_error(e)
        log_event(
            "wb_api_error",
            calculation_id=calculation_id,
            user_id=user_id,
            level="error",
            article_id=article_id,
            error_type=error_type,
            error=str(e)[:200]
        )
        # Edit product info message with user-friendly error
        error_message = ErrorHandler.get_user_message_for_wb_error(error_type, article_id)
        await message.bot.edit_message_text(
            chat_id=user_id,
            message_id=product_info_message_id,
            text=error_message
        )
        return
    
    if not product_data:
        # Edit product info message with not found
        error_message = ErrorHandler.get_user_message_for_wb_error("not_found", article_id)
        await message.bot.edit_message_text(
            chat_id=user_id,
            message_id=product_info_message_id,
            text=error_message
        )
        log_event(
            "product_not_found",
            calculation_id=calculation_id,
            user_id=user_id,
            level="warning",
            article_id=article_id
        )
        return
    
    # Edit product info message with found product data
    product_name = wb_parser.get_product_name(product_data) or "Не указано"
    product_price = wb_parser.get_product_price(product_data)
    price_rub = f"{product_price / 100:.2f} ₽" if product_price else "Не указана"
    
    await message.bot.edit_message_text(
        chat_id=user_id,
        message_id=product_info_message_id,
        text=f"✅ Товар найден!\n\n"
             f"📦 Название: {product_name}\n"
             f"💰 Цена: {price_rub}\n"
             f"🔢 Артикул: {article_id}"
    )
    
    # Save product data to calculation
    calculation_data = {
        "user_id": user_id,
        "calculation_type": "express",
        "calculation_id": calculation_id,
        "article_id": article_id,
        "product_data": product_data,
        "input_data": {
            "article_id": article_id,
            "input_text": text
        }
    }
    
    # Update calculation data in Redis
    await redis_client.set_calculation_status(calculation_id, "processing")
    
    # Save product data temporarily (will be used by worker)
    await redis_client.set_calculation_product_data(calculation_id, product_data, ttl=3600)
    
    # Push to calculation queue for further processing
    await redis_client.push_calculation(calculation_id, calculation_data)
    
    # Clear FSM state
    await state.clear()
    
    # Send second status message (calculation status) - without keyboard as it will be edited
    calculation_status_message = await message.answer("⏳ Начинаю экспресс-расчёт...")
    calculation_status_message_id = calculation_status_message.message_id
    
    # Save calculation status message ID to Redis for later editing
    await redis_client.redis.setex(
        f"calculation:{calculation_id}:status_message_id",
        3600,  # 1 hour TTL
        str(calculation_status_message_id)
    )
    
    logger.info(
        "product_parsed",
        user_id=user_id,
        article_id=article_id,
        calculation_id=calculation_id,
        product_name=product_name
    )
    
    # Start background task to check for results
    bot = get_bot()
    if bot:
        asyncio.create_task(_poll_calculation_result(bot, redis_client, calculation_id, user_id, calculation_status_message_id))


@router.message(F.text == "Новый запрос")
async def handle_new_request_button(message: Message, state: FSMContext):
    """Handle 'Новый запрос' button click - same as /newrequest command."""
    await handle_start_logic(message, state)
    logger.info("new_request_button_clicked", user_id=message.from_user.id)


@router.message()
async def handle_unknown_message(message: Message, state: FSMContext):
    """Handle messages that don't match any specific handler."""
    user_id = message.from_user.id
    text = message.text or ""
    current_state = await state.get_state()
    
    logger.warning(
        "unknown_message",
        user_id=user_id,
        text=text[:100],
        text_length=len(text),
        current_state=current_state
    )
    
    # If user is in waiting_for_article state but handler didn't trigger, try to process
    if current_state == ExpressCalculationStates.waiting_for_article.state:
        logger.info("retrying_article_input", user_id=user_id)
        await handle_article_input(message, state)
        return
    
    # If user is in detailed calculation states, try to process
    if current_state == DetailedCalculationStates.waiting_for_weight.state:
        logger.info("retrying_weight_input", user_id=user_id)
        await handle_weight_input(message, state)
        return
    
    if current_state == DetailedCalculationStates.waiting_for_volume.state:
        logger.info("retrying_volume_input", user_id=user_id)
        await handle_volume_input(message, state)
        return
    
    if current_state == DetailedCalculationStates.waiting_for_purchase_price.state:
        logger.info("retrying_purchase_price_input", user_id=user_id)
        await handle_purchase_price_input(message, state)
        return
    
    # Otherwise, suggest to start
    await message.answer(
        "Для начала работы отправьте команду /start или используйте команду /newrequest из меню бота."
    )


async def _poll_calculation_result(bot: Bot, redis_client: RedisClient, calculation_id: str, user_id: int, status_message_id: int, max_attempts: int = 60, interval: float = 2.0):
    """
    Poll for calculation result and notify user by deleting status message and sending new one with keyboard.

    Args:
        bot: Telegram Bot instance
        redis_client: Redis client
        calculation_id: Calculation ID
        user_id: Telegram user ID
        status_message_id: Message ID to delete
        max_attempts: Maximum number of polling attempts
        interval: Interval between checks in seconds
    """
    from apps.bot_service.services.result_notifier import ResultNotifier
    
    notifier = ResultNotifier(bot, redis_client)
    
    for attempt in range(max_attempts):
        try:
            result_sent = await notifier.check_and_notify(calculation_id, user_id, status_message_id)
            if result_sent:
                logger.info(
                    "calculation_result_sent",
                    calculation_id=calculation_id,
                    user_id=user_id,
                    attempt=attempt + 1
                )
                return
            
            await asyncio.sleep(interval)
        except Exception as e:
            logger.error(
                "result_polling_error",
                calculation_id=calculation_id,
                user_id=user_id,
                attempt=attempt + 1,
                error=str(e)
            )
            await asyncio.sleep(interval)
    
    logger.warning(
        "result_polling_timeout",
        calculation_id=calculation_id,
        user_id=user_id,
        max_attempts=max_attempts
    )


@router.callback_query(F.data.startswith("detailed_calculation:"))
async def handle_detailed_calculation(callback: CallbackQuery, state: FSMContext):
    """Handle detailed calculation button click - show parameters screen."""
    user_id = callback.from_user.id
    
    # Extract calculation_id from callback data
    calculation_id = callback.data.split(":", 1)[1]
    
    # Get redis_client
    redis_client: RedisClient = get_redis_client()
    
    if not redis_client:
        logger.error("redis_client_not_available", user_id=user_id)
        await callback.answer("Ошибка: сервис временно недоступен.", show_alert=True)
        return
    
    # Get calculation result
    result = await redis_client.get_calculation_result(calculation_id)
    
    if not result:
        logger.error("calculation_result_not_found", user_id=user_id, calculation_id=calculation_id)
        await callback.answer("Ошибка: данные расчёта не найдены.", show_alert=True)
        return
    
    # Get product data from result or Redis
    product_data = result.get("product_data")
    if not product_data:
        # Try to get from Redis (for orange zone, product_data might not be in result)
        product_data = await redis_client.get_calculation_product_data(calculation_id)
        if not product_data:
            logger.error("product_data_not_found", user_id=user_id, calculation_id=calculation_id)
            await callback.answer("Ошибка: данные товара не найдены.", show_alert=True)
            return
    
    # Get article_id from product_data (id field in normalized product_data)
    article_id = product_data.get("id") or product_data.get("nmId")
    
    # If still not found, try to get from raw product_data in Redis
    if not article_id:
        product_data_raw = await redis_client.get_calculation_product_data(calculation_id)
        if product_data_raw:
            article_id = product_data_raw.get("id") or product_data_raw.get("nmId")
    
    # Extract product information
    wb_parser = WBParserService()
    product_name = wb_parser.get_product_name(product_data) or "Не указано"
    product_price = wb_parser.get_product_price(product_data)
    price_rub = product_price / 100 if product_price else 0
    
    # Get exchange rates to calculate purchase price in CNY
    # Purchase price in CNY = (Price WB / 4) / RUB/CNY rate
    exchange_rate_service = ExchangeRateService()
    cb_rates = await exchange_rate_service._get_cb_rates()
    rub_cny_rate = cb_rates["usd_rub"] / cb_rates["usd_cny"] if cb_rates["usd_cny"] > 0 else 11.5
    purchase_price_cny = (price_rub / 4) / rub_cny_rate  # Расчётная закупочная цена в CNY = (цена WB / 4) / курс RUB/CNY
    
    weight = wb_parser.get_product_weight(product_data) or 0
    volume_liters = wb_parser.get_product_volume(product_data) or 0
    
    # Convert volume from liters to m³ (1 liter = 0.001 m³)
    volume_m3 = volume_liters * 0.001 if volume_liters else 0
    
    # Build parameters message
    message_text = (
        f"📊 <b>Параметры для подробного расчёта</b>\n\n"
        f"📦 <b>Товар:</b> {product_name}\n"
        f"🔢 <b>Артикул WB:</b> {article_id or 'N/A'}\n"
        f"💰 <b>Цена WB:</b> {price_rub:.2f} ₽\n"
        f"💵 <b>Расчётная закупочная цена:</b> {purchase_price_cny:.2f} CNY\n"
        f"⚖️ <b>Вес единицы:</b> {weight:.3f} кг\n"
        f"📏 <b>Объём единицы:</b> {volume_m3:.4f} м³ ({volume_liters:.2f} л)\n"
    )
    
    # Create keyboard with action buttons
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Рассчитать с указанными параметрами",
                callback_data=f"calculate_detailed:{calculation_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="Указать точный вес",
                callback_data=f"adjust_weight:{calculation_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="Указать точный объем",
                callback_data=f"adjust_volume:{calculation_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="Указать закупочную стоимость",
                callback_data=f"adjust_purchase_price:{calculation_id}"
            )
        ]
    ])
    
    # Save current parameters to state for later use
    await state.update_data(
        calculation_id=calculation_id,
        current_weight=weight,
        current_volume=volume_m3,
        current_purchase_price_cny=purchase_price_cny,
        article_id=article_id
    )
    
    # Send new message instead of editing (to preserve express calculation result)
    await callback.message.answer(
        text=message_text,
        parse_mode="HTML",
        reply_markup=keyboard
    )
    
    await callback.answer()
    
    logger.info(
        "detailed_calculation_screen_shown",
        user_id=user_id,
        calculation_id=calculation_id
    )


@router.callback_query(F.data.startswith("adjust_weight:"))
async def handle_adjust_weight(callback: CallbackQuery, state: FSMContext):
    """Handle weight adjustment button - request new weight value."""
    user_id = callback.from_user.id
    calculation_id = callback.data.split(":", 1)[1]
    
    await state.set_state(DetailedCalculationStates.waiting_for_weight)
    await state.update_data(calculation_id=calculation_id)
    
    await callback.message.answer(
        "⚖️ Введите новый вес единицы товара в килограммах (например: 0.5):"
    )
    await callback.answer()
    
    logger.info("weight_adjustment_requested", user_id=user_id, calculation_id=calculation_id)


@router.callback_query(F.data.startswith("adjust_volume:"))
async def handle_adjust_volume(callback: CallbackQuery, state: FSMContext):
    """Handle volume adjustment button - request new volume value."""
    user_id = callback.from_user.id
    calculation_id = callback.data.split(":", 1)[1]
    
    await state.set_state(DetailedCalculationStates.waiting_for_volume)
    await state.update_data(calculation_id=calculation_id)
    
    await callback.message.answer(
        "📏 Введите новый объём единицы товара в литрах (например: 2.5):"
    )
    await callback.answer()
    
    logger.info("volume_adjustment_requested", user_id=user_id, calculation_id=calculation_id)


@router.callback_query(F.data.startswith("adjust_purchase_price:"))
async def handle_adjust_purchase_price(callback: CallbackQuery, state: FSMContext):
    """Handle purchase price adjustment button - request new price value."""
    user_id = callback.from_user.id
    calculation_id = callback.data.split(":", 1)[1]
    
    await state.set_state(DetailedCalculationStates.waiting_for_purchase_price)
    await state.update_data(calculation_id=calculation_id)
    
    await callback.message.answer(
        "💵 Введите новую закупочную цену в юанях CNY (например: 250.50):"
    )
    await callback.answer()
    
    logger.info("purchase_price_adjustment_requested", user_id=user_id, calculation_id=calculation_id)


@router.message(DetailedCalculationStates.waiting_for_weight)
async def handle_weight_input(message: Message, state: FSMContext):
    """Handle weight input from user."""
    user_id = message.from_user.id
    text = message.text or ""
    
    try:
        weight = float(text.replace(",", "."))
        if weight <= 0:
            await message.answer("❌ Вес должен быть положительным числом. Попробуйте снова:")
            return
        
        state_data = await state.get_data()
        calculation_id = state_data.get("calculation_id")
        
        # Update weight in state
        await state.update_data(current_weight=weight)
        
        # Show updated parameters screen
        await show_parameters_screen(message, state, calculation_id, weight_adjusted=weight)
        
        logger.info("weight_adjusted", user_id=user_id, calculation_id=calculation_id, weight=weight)
        
    except ValueError:
        await message.answer("❌ Неверный формат. Введите число (например: 0.5):")


@router.message(DetailedCalculationStates.waiting_for_volume)
async def handle_volume_input(message: Message, state: FSMContext):
    """Handle volume input from user."""
    user_id = message.from_user.id
    text = message.text or ""
    
    try:
        volume_liters = float(text.replace(",", "."))
        if volume_liters <= 0:
            await message.answer("❌ Объём должен быть положительным числом. Попробуйте снова:")
            return
        
        volume_m3 = volume_liters * 0.001  # Convert to m³
        
        state_data = await state.get_data()
        calculation_id = state_data.get("calculation_id")
        
        # Update volume in state
        await state.update_data(current_volume=volume_m3)
        
        # Show updated parameters screen
        await show_parameters_screen(message, state, calculation_id, volume_adjusted=volume_m3)
        
        logger.info("volume_adjusted", user_id=user_id, calculation_id=calculation_id, volume_m3=volume_m3)
        
    except ValueError:
        await message.answer("❌ Неверный формат. Введите число (например: 2.5):")


@router.message(DetailedCalculationStates.waiting_for_purchase_price)
async def handle_purchase_price_input(message: Message, state: FSMContext):
    """Handle purchase price input from user (in CNY)."""
    user_id = message.from_user.id
    text = message.text or ""
    
    try:
        purchase_price_cny = float(text.replace(",", "."))
        if purchase_price_cny <= 0:
            await message.answer("❌ Цена должна быть положительным числом. Попробуйте снова:")
            return
        
        state_data = await state.get_data()
        calculation_id = state_data.get("calculation_id")
        
        # Update purchase price in state (in CNY)
        await state.update_data(current_purchase_price_cny=purchase_price_cny)
        
        # Show updated parameters screen
        await show_parameters_screen(message, state, calculation_id, purchase_price_adjusted_cny=purchase_price_cny)
        
        logger.info("purchase_price_adjusted", user_id=user_id, calculation_id=calculation_id, purchase_price_cny=purchase_price_cny)
        
    except ValueError:
        await message.answer("❌ Неверный формат. Введите число (например: 250.50):")


@router.callback_query(F.data.startswith("calculate_detailed:"))
async def handle_calculate_detailed(callback: CallbackQuery, state: FSMContext):
    """Handle detailed calculation button - start detailed calculation."""
    user_id = callback.from_user.id
    original_calculation_id = callback.data.split(":", 1)[1]
    
    # Get redis_client
    redis_client: RedisClient = get_redis_client()
    
    if not redis_client:
        logger.error("redis_client_not_available", user_id=user_id)
        await callback.answer("Ошибка: сервис временно недоступен.", show_alert=True)
        return
    
    # Get parameters from state
    state_data = await state.get_data()
    weight = state_data.get("current_weight")
    volume_m3 = state_data.get("current_volume")  # Already in m³ from state
    purchase_price_cny = state_data.get("current_purchase_price_cny")
    
    if not weight or not volume_m3 or not purchase_price_cny:
        await callback.answer("Ошибка: не все параметры указаны.", show_alert=True)
        return
    
    # Get original calculation result to get product data and TN VED
    original_result = await redis_client.get_calculation_result(original_calculation_id)
    if not original_result:
        await callback.answer("Ошибка: данные исходного расчёта не найдены.", show_alert=True)
        return
    
    # Get product data and TN VED data
    product_data = original_result.get("product_data")
    if not product_data:
        await callback.answer("Ошибка: данные товара не найдены.", show_alert=True)
        return
    
    # Get TN VED data
    tn_ved_code = original_result.get("tn_ved_code")
    duty_type = original_result.get("duty_type")
    duty_rate = original_result.get("duty_rate")
    vat_rate = original_result.get("vat_rate")
    
    if not tn_ved_code or not duty_type or duty_rate is None or vat_rate is None:
        await callback.answer("Ошибка: данные ТН ВЭД не найдены.", show_alert=True)
        return
    
    # Use the same calculation_id for detailed calculation (it's a continuation of express)
    detailed_calculation_id = original_calculation_id
    
    # Save product data for detailed calculation (update existing)
    await redis_client.set_calculation_product_data(detailed_calculation_id, product_data)
    
    # Save detailed calculation parameters
    detailed_calculation_data = {
        "user_id": user_id,
        "calculation_type": "detailed",
        "original_calculation_id": original_calculation_id,
        "unit_weight_kg": weight,
        "unit_volume_m3": volume_m3,  # Already in m³
        "purchase_price_cny": purchase_price_cny,
        "tnved_data": {
            "tn_ved_code": tn_ved_code,
            "duty_type": duty_type,
            "duty_rate": duty_rate,
            "vat_rate": vat_rate
        }
    }
    
    # Clear notification_sent flag to allow new result notification
    notification_sent_key = f"calculation:{detailed_calculation_id}:notification_sent"
    await redis_client.redis.delete(notification_sent_key)
    
    # Push detailed calculation to queue
    await redis_client.push_calculation(detailed_calculation_id, detailed_calculation_data)
    
    # Set status to pending
    await redis_client.set_calculation_status(detailed_calculation_id, "pending")
    
    # Set user's current calculation
    await redis_client.set_user_current_calculation(user_id, detailed_calculation_id)
    
    # Send status message
    status_message = await callback.message.answer("⏳ Запущен подробный расчёт...")
    status_message_id = status_message.message_id
    
    await callback.answer("Подробный расчёт запущен")
    
    logger.info(
        "detailed_calculation_started",
        user_id=user_id,
        original_calculation_id=original_calculation_id,
        detailed_calculation_id=detailed_calculation_id,
        weight=weight,
        volume_m3=volume_m3,
        purchase_price_cny=purchase_price_cny
    )
    
    # Poll for result
    bot = get_bot()
    await _poll_calculation_result(
        bot, redis_client, detailed_calculation_id, user_id, status_message_id
    )


async def show_parameters_screen(
    message: Message,
    state: FSMContext,
    calculation_id: str,
    weight_adjusted: float = None,
    volume_adjusted: float = None,
    purchase_price_adjusted_cny: float = None
):
    """Show parameters screen with updated values."""
    redis_client: RedisClient = get_redis_client()
    
    if not redis_client:
        await message.answer("Ошибка: сервис временно недоступен.")
        return
    
    # Get calculation result
    result = await redis_client.get_calculation_result(calculation_id)
    if not result:
        await message.answer("Ошибка: данные расчёта не найдены.")
        return
    
    # Get product data
    product_data = result.get("product_data")
    if not product_data:
        await message.answer("Ошибка: данные товара не найдены.")
        return
    
    # Get current state data
    state_data = await state.get_data()
    
    # Extract product information
    wb_parser = WBParserService()
    product_name = wb_parser.get_product_name(product_data) or "Не указано"
    product_price = wb_parser.get_product_price(product_data)
    price_rub = product_price / 100 if product_price else 0
    
    # Use adjusted values or defaults
    weight = weight_adjusted if weight_adjusted is not None else state_data.get("current_weight")
    if weight is None:
        weight = wb_parser.get_product_weight(product_data) or 0
    
    volume_m3 = volume_adjusted if volume_adjusted is not None else state_data.get("current_volume")
    if volume_m3 is None:
        volume_liters = wb_parser.get_product_volume(product_data) or 0
        volume_m3 = volume_liters * 0.001
    else:
        volume_liters = volume_m3 * 1000  # Convert back to liters for display
    
    purchase_price_cny = purchase_price_adjusted_cny if purchase_price_adjusted_cny is not None else state_data.get("current_purchase_price_cny")
    if purchase_price_cny is None:
        # Calculate purchase price in CNY: (Price WB / 4) / RUB/CNY rate
        exchange_rate_service = ExchangeRateService()
        cb_rates = await exchange_rate_service._get_cb_rates()
        rub_cny_rate = cb_rates["usd_rub"] / cb_rates["usd_cny"] if cb_rates["usd_cny"] > 0 else 11.5
        purchase_price_cny = (price_rub / 4) / rub_cny_rate
    
    article_id = product_data.get("id") or product_data.get("nmId") or state_data.get("article_id")
    
    # Build parameters message
    message_text = (
        f"📊 <b>Параметры для подробного расчёта</b>\n\n"
        f"📦 <b>Товар:</b> {product_name}\n"
        f"🔢 <b>Артикул WB:</b> {article_id or 'N/A'}\n"
        f"💰 <b>Цена WB:</b> {price_rub:.2f} ₽\n"
        f"💵 <b>Расчётная закупочная цена:</b> {purchase_price_cny:.2f} CNY\n"
        f"⚖️ <b>Вес единицы:</b> {weight:.3f} кг\n"
        f"📏 <b>Объём единицы:</b> {volume_m3:.4f} м³ ({volume_liters:.1f} л)\n"
    )
    
    # Create keyboard with action buttons
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Рассчитать с указанными параметрами",
                callback_data=f"calculate_detailed:{calculation_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="Указать точный вес",
                callback_data=f"adjust_weight:{calculation_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="Указать точный объем",
                callback_data=f"adjust_volume:{calculation_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="Указать закупочную стоимость",
                callback_data=f"adjust_purchase_price:{calculation_id}"
            )
        ]
    ])
    
    # Update state with current values
    await state.update_data(
        calculation_id=calculation_id,
        current_weight=weight,
        current_volume=volume_m3,
        current_purchase_price_cny=purchase_price_cny,
        article_id=article_id
    )
    
    await message.answer(
        text=message_text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


"""Start command handler."""
import uuid
import asyncio
import json
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from typing import Annotated
from aiogram import Bot
import structlog

from apps.bot_service.clients.redis import RedisClient
from apps.bot_service.clients.database import DatabaseClient, User
from apps.bot_service.services.input_parser import InputParser
from apps.bot_service.services.wb_parser import WBParserService
from apps.bot_service.services.exchange_rate_service import ExchangeRateService
from apps.bot_service.services.detailed_calculation_service import DetailedCalculationService
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
            [KeyboardButton(text="🔄 Новый запрос")]
        ],
        resize_keyboard=True,
        persistent=True
    )
    return keyboard


# Статусы для ротации во время получения данных о товаре
PRODUCT_FETCH_STATUSES = [
    "🔍 Получаю данные о товаре...",
    "📡 Запрашиваю информацию с Wildberries...",
    "🔎 Ищу товар по артикулу...",
    "📦 Загружаю характеристики товара...",
    "🌐 Подключаюсь к API Wildberries...",
    "📊 Обрабатываю данные о товаре...",
    "🔍 Анализирую карточку товара...",
    "⏳ Получаю информацию о товаре..."
]

# Статусы для ротации во время экспресс-расчёта
CALCULATION_STATUSES = [
    "⏳ Начинаю экспресс-расчёт...",
    "🔢 Проверяю обязательные поля...",
    "🤖 Подбираю код ТН ВЭД...",
    "🔍 Проверяю красную зону ТН ВЭД...",
    "🟠 Анализирую оранжевую зону...",
    "💰 Рассчитываю удельную ценность...",
    "📊 Формирую экспресс-оценку...",
    "⚙️ Обрабатываю данные расчёта...",
    "🔬 Проверяю характеристики товара...",
    "📈 Вычисляю параметры логистики..."
]

# Статусы для ротации во время подробного расчёта
DETAILED_CALCULATION_STATUSES = [
    "⏳ Запущен подробный расчёт...",
    "📊 Рассчитываю стоимость карго...",
    "🚚 Вычисляю стоимость белой логистики...",
    "💱 Получаю актуальные курсы валют...",
    "📦 Рассчитываю количество товара...",
    "💰 Вычисляю пошлины и НДС...",
    "📈 Сравниваю варианты доставки...",
    "🔢 Обрабатываю параметры расчёта...",
    "⚙️ Формирую детальный отчёт...",
    "📋 Подготавливаю результаты..."
]


async def rotate_status_messages(
    bot: Bot,
    chat_id: int,
    message_id: int,
    statuses: list[str],
    stop_event: asyncio.Event,
    interval: float = 5.0,
    calculation_id: str = None,
    redis_client: RedisClient = None
):
    """
    Ротация статусных сообщений каждые N секунд.
    
    Args:
        bot: Telegram Bot instance
        chat_id: Chat ID
        message_id: Message ID to edit
        statuses: List of status messages to rotate
        stop_event: Event to stop rotation
        interval: Interval between status changes in seconds
        calculation_id: Calculation ID for Redis stop flag check (optional)
        redis_client: Redis client for stop flag check (optional)
    """
    status_index = 1  # Начинаем со второго статуса, первый уже показан
    max_attempts = 200  # Максимум 200 обновлений (1000 секунд = ~16 минут при 5 сек)
    
    while not stop_event.is_set() and status_index < max_attempts:
        try:
            # Проверяем флаг остановки в Redis, если передан calculation_id
            if calculation_id and redis_client:
                rotation_stop_key = f"calculation:{calculation_id}:rotation_stop_event"
                stop_flag = await redis_client.redis.get(rotation_stop_key)
                if stop_flag == b"stop":
                    break
            
            # Ждём interval секунд или пока не будет установлен stop_event
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
                break  # Если событие установлено, выходим
            except asyncio.TimeoutError:
                # Таймаут прошёл, обновляем статус
                pass
            
            # Проверяем ещё раз после ожидания
            if stop_event.is_set():
                break
            
            if calculation_id and redis_client:
                rotation_stop_key = f"calculation:{calculation_id}:rotation_stop_event"
                stop_flag = await redis_client.redis.get(rotation_stop_key)
                if stop_flag == b"stop":
                    break
            
            # Обновляем статус
            current_status = statuses[status_index % len(statuses)]
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=current_status
                )
                status_index += 1
            except Exception as edit_error:
                # Если сообщение уже удалено или не найдено, прекращаем ротацию
                error_msg = str(edit_error)
                if "message to edit not found" in error_msg.lower() or "message not found" in error_msg.lower():
                    logger.debug(
                        "status_rotation_stopped_message_deleted",
                        chat_id=chat_id,
                        message_id=message_id,
                        calculation_id=calculation_id
                    )
                    break
                else:
                    # Другие ошибки - логируем и продолжаем
                    logger.warning(
                        "status_rotation_error",
                        chat_id=chat_id,
                        message_id=message_id,
                        error=error_msg,
                        calculation_id=calculation_id
                    )
                    # Продолжаем ротацию, но увеличиваем индекс
                    status_index += 1
                
        except Exception as e:
            # Если произошла критическая ошибка, прекращаем ротацию
            logger.warning(
                "status_rotation_critical_error",
                chat_id=chat_id,
                message_id=message_id,
                error=str(e),
                calculation_id=calculation_id
            )
            break


async def handle_start_logic(message: Message, state: FSMContext, is_new_request: bool = False):
    """Common logic for /start and /newrequest commands."""
    user_id = message.from_user.id
    from_user = message.from_user
    
    # Get redis_client and db_client
    redis_client: RedisClient = get_redis_client()
    db_client: DatabaseClient = get_db_client()
    
    if not redis_client:
        logger.error("redis_client_not_available", user_id=user_id)
        await message.answer(
            "Ошибка: сервис временно недоступен. Попробуйте позже.",
            reply_markup=get_main_keyboard()
        )
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
        await start_express_calculation(message, redis_client, user_id, state, is_new_request=is_new_request)
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
    
    text = """Пользовательское соглашение и обработка данных

Используя этого бота, вы соглашаетесь с тем, что:

Бот обрабатывает данные, которые вы добровольно отправляете в чат:
– ссылку или артикул товара на Wildberries,
– описание товара, цену, вес и другие параметры,
– технические данные Telegram (ID, username, время запросов).

Эти данные используются только для:
– анализа карточки товара,
– подбора примерного кода ТН ВЭД,
– сравнения ориентировочной стоимости доставки по белой схеме и карго,
– формирования кратких рекомендаций по ВЭД.

Данные могут храниться на серверах и сервисах, которые используются для работы бота (в т.ч. облачные провайдеры и сервисы ИИ).
Оператор принимает разумные меры для защиты данных, но не может гарантировать абсолютную безопасность.

Все расчёты и рекомендации носят ориентировочный характер и не являются офертой.
Итоговые решения по схеме поставки, коду ТН ВЭД, документам и экономике вы принимаете самостоятельно, после консультации с менеджером/специалистом по ВЭД.

Если вы не согласны с обработкой данных, просто не используйте бота и не отправляйте ему информацию."""
    
    await message.answer(text, reply_markup=keyboard)
    logger.info("start_command", user_id=user_id)


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Handle /start command - show user agreement or start express calculation."""
    await handle_start_logic(message, state)


@router.message(Command("newrequest"))
async def cmd_newrequest(message: Message, state: FSMContext):
    """Handle /newrequest command - duplicate of /start."""
    await handle_start_logic(message, state, is_new_request=True)
    logger.info("newrequest_command", user_id=message.from_user.id)


async def start_express_calculation(message: Message, redis_client: RedisClient, user_id: int, state: FSMContext, is_new_request: bool = False):
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
    
    # Request article input without keyboard
    if is_new_request:
        welcome_text = """Для нового запроса отправьте, пожалуйста:

🔗 ссылку на товар на Wildberries

или

#️⃣ артикул товара на WB

⏱️ Обработка одного запроса занимает до 2 минут."""
    else:
        welcome_text = """Здравствуйте, я бесплатный бот! 👋



Я анализирую карточку Wildberries, подбираю примерный код ТН ВЭД, сравниваю стоимость доставки по белой и карго, выдаю краткий вывод по товару для входа в ВЭД.

- На обработку запроса уходит до 2 минут.

- Все расчёты являются ориентировочными и не являются офертой.

🔗 Просто отправьте ссылку на товар или артикул WB"""
    
    await message.answer(welcome_text)
    
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
    
    # Edit message to remove keyboard and show acceptance confirmation
    try:
        await callback.message.edit_text(
            "✅ Соглашение принято!\n\nТеперь вы можете использовать бота для расчётов.",
            reply_markup=None
        )
    except Exception as e:
        logger.warning("failed_to_edit_agreement_message", user_id=user_id, error=str(e))
        # If edit fails, try to delete the message
        try:
            await callback.message.delete()
        except Exception as delete_error:
            logger.warning("failed_to_delete_agreement_message", user_id=user_id, error=str(delete_error))
    
    # Show notification
    await callback.answer("✅ Соглашение принято!", show_alert=False)
    
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
    
    # Check if user clicked "Новый запрос" button - redirect to new request handler
    if text.strip() in ("Новый запрос", "🔄 Новый запрос"):
        logger.info("new_request_button_clicked_from_article_input", user_id=user_id)
        await handle_start_logic(message, state)
        return
    
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
        await message.answer(
            error_message,
            reply_markup=get_main_keyboard()
        )
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
            "• Или ссылку на карточку товара (например: https://www.wildberries.ru/catalog/154345562/detail.aspx)",
            disable_web_page_preview=True,
            reply_markup=get_main_keyboard()
        )
        logger.warning("article_extraction_failed", user_id=user_id, text_length=len(text))
        return
    
    logger.info("article_extracted", user_id=user_id, article_id=article_id, calculation_id=calculation_id)
    
    # Send first status message (product info) - without keyboard as it will be edited
    product_info_message = await message.answer("🔍 Получаю данные о товаре...")
    product_info_message_id = product_info_message.message_id
    
    # Запускаем ротацию статусов для получения данных о товаре
    product_fetch_stop_event = asyncio.Event()
    bot = get_bot()
    product_fetch_task = asyncio.create_task(
        rotate_status_messages(
            bot=bot,
            chat_id=user_id,
            message_id=product_info_message_id,
            statuses=PRODUCT_FETCH_STATUSES,
            stop_event=product_fetch_stop_event,
            interval=5.0,
            calculation_id=None,
            redis_client=None
        )
    )
    
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
        # Останавливаем ротацию статусов
        product_fetch_stop_event.set()
        try:
            await product_fetch_task
        except Exception:
            pass
        
        # Edit product info message with user-friendly error
        error_message = ErrorHandler.get_user_message_for_wb_error(error_type, article_id)
        await message.bot.edit_message_text(
            chat_id=user_id,
            message_id=product_info_message_id,
            text=error_message
        )
        # Clear FSM state to allow new request
        await state.clear()
        # Send reply keyboard for new request
        await message.answer(
            "💡 Используйте кнопку ниже для нового запроса",
            reply_markup=get_main_keyboard()
        )
        return
    
    if not product_data:
        # Останавливаем ротацию статусов
        product_fetch_stop_event.set()
        try:
            await product_fetch_task
        except Exception:
            pass
        
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
        # Clear FSM state to allow new request
        await state.clear()
        # Send reply keyboard for new request
        await message.answer(
            "💡 Используйте кнопку ниже для нового запроса",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Останавливаем ротацию статусов получения товара
    product_fetch_stop_event.set()
    try:
        await product_fetch_task
    except Exception:
        pass
    
    # Edit product info message with found product data
    product_name = wb_parser.get_product_name(product_data) or "Не указано"
    product_price = wb_parser.get_product_price(product_data)
    price_rub = f"{product_price / 100:.2f} ₽" if product_price else "Не указана"
    
    # Fetch card_data and category_data for additional info (габариты, категория, подкатегория)
    card_data = None
    category_data = None
    
    try:
        # Fetch card data from basket API
        logger.info(
            "fetching_card_data_for_product_info",
            calculation_id=calculation_id,
            article_id=article_id
        )
        card_data = await wb_parser.fetch_product_card_data(article_id)
        
        logger.info(
            "card_data_fetched",
            calculation_id=calculation_id,
            article_id=article_id,
            has_card_data=card_data is not None,
            card_data_keys=list(card_data.keys()) if card_data else []
        )
        
        if card_data:
            # Extract subject_id from card data for category API
            # Try different possible locations for subject_id
            subject_id = None
            if "data" in card_data and isinstance(card_data["data"], dict):
                subject_id = card_data["data"].get("subject_id")
            elif "subject_id" in card_data:
                subject_id = card_data.get("subject_id")
            
            logger.info(
                "subject_id_extracted",
                calculation_id=calculation_id,
                article_id=article_id,
                subject_id=subject_id
            )
            
            # Fetch category data
            if subject_id:
                category_data = await wb_parser.fetch_product_category_data(article_id, subject_id)
            else:
                # Try without subject_id
                category_data = await wb_parser.fetch_product_category_data(article_id, None)
            
            logger.info(
                "category_data_fetched",
                calculation_id=calculation_id,
                article_id=article_id,
                has_category_data=category_data is not None,
                category_data=category_data
            )
    except Exception as e:
        logger.warning(
            "card_category_data_fetch_error_in_handler",
            calculation_id=calculation_id,
            article_id=article_id,
            error=str(e),
            error_class=type(e).__name__
        )
        # Continue without card_data/category_data - will show basic info only
    
    # Get review rating and feedbacks count
    review_rating = wb_parser.get_product_review_rating(product_data)
    feedbacks_count = wb_parser.get_product_feedbacks(product_data)
    
    # Build message text
    message_lines = [
        "✅ Товар найден!\n",
        f"Название: {product_name}",
        f"Цена: {price_rub}",
        f"Артикул: {article_id}"
    ]
    
    # Add review rating and feedbacks if available
    if review_rating is not None:
        message_lines.append(f"⭐ Рейтинг: {review_rating:.1f}")
    if feedbacks_count is not None:
        message_lines.append(f"💬 Отзывов: {feedbacks_count}")
    
    # Add category and subcategory if available
    # Show category even if only type_name or only category_name is available
    if category_data:
        type_name = category_data.get("type_name")
        category_name = category_data.get("category_name")
        logger.info(
            "adding_category_info",
            calculation_id=calculation_id,
            type_name=type_name,
            category_name=category_name,
            category_data=category_data
        )
        if type_name:
            message_lines.append(f"Категория: {type_name}")
        if category_name:
            message_lines.append(f"Подкатегория: {category_name}")
    else:
        logger.warning(
            "category_data_not_available",
            calculation_id=calculation_id,
            article_id=article_id
        )
    
    # Add package dimensions if available
    if card_data:
        # Log full card_data structure for debugging (first level only)
        logger.info(
            "card_data_structure_for_dimensions",
            calculation_id=calculation_id,
            article_id=article_id,
            card_data_keys=list(card_data.keys())[:30] if card_data else [],
            has_options="options" in card_data,
            has_data="data" in card_data,
            data_type=type(card_data.get("data")).__name__ if "data" in card_data else "None",
            data_keys=list(card_data.get("data", {}).keys())[:30] if isinstance(card_data.get("data"), dict) else []
        )
        
        # If data section exists, log its options
        if "data" in card_data and isinstance(card_data.get("data"), dict):
            data_section = card_data["data"]
            if "options" in data_section:
                options_list = data_section.get("options", [])
                if isinstance(options_list, list):
                    option_names = [opt.get("name", "") if isinstance(opt, dict) else str(opt) for opt in options_list[:20]]
                    logger.info(
                        "options_found_in_data_section",
                        calculation_id=calculation_id,
                        article_id=article_id,
                        options_count=len(options_list),
                        option_names=option_names
                    )
        
        dimensions = wb_parser.get_package_dimensions(card_data)
        
        logger.info(
            "package_dimensions_extracted",
            calculation_id=calculation_id,
            article_id=article_id,
            dimensions=dimensions,
            has_dimensions=dimensions is not None
        )
        if dimensions:
            length = dimensions.get("length")
            width = dimensions.get("width")
            height = dimensions.get("height")
            if length and width and height:
                message_lines.append(f"Габариты: {length}×{width}×{height} см")
        else:
            logger.warning(
                "dimensions_not_found_in_card_data",
                calculation_id=calculation_id,
                article_id=article_id,
                card_data_keys=list(card_data.keys())[:30] if card_data else [],
                card_data_data_keys=list(card_data.get("data", {}).keys())[:30] if isinstance(card_data.get("data"), dict) else []
            )
    else:
        logger.warning(
            "card_data_not_available",
            calculation_id=calculation_id,
            article_id=article_id
        )
    
    await message.bot.edit_message_text(
        chat_id=user_id,
        message_id=product_info_message_id,
        text="\n".join(message_lines)
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
    
    # Save card_data and category_data to Redis if available (to avoid duplicate requests in worker)
    if card_data:
        await redis_client.redis.setex(
            f"calculation:{calculation_id}:card_data",
            3600,  # 1 hour TTL
            json.dumps(card_data)
        )
    
    if category_data:
        await redis_client.redis.setex(
            f"calculation:{calculation_id}:category_data",
            3600,  # 1 hour TTL
            json.dumps(category_data)
        )
    
    # Push to calculation queue for further processing
    await redis_client.push_calculation(calculation_id, calculation_data)
    
    # Clear FSM state
    await state.clear()
    
    # Send second status message (calculation status) - without keyboard as it will be edited
    calculation_status_message = await message.answer("⏳ Начинаю экспресс-расчёт...")
    calculation_status_message_id = calculation_status_message.message_id
    
    # Запускаем ротацию статусов для экспресс-расчёта
    calculation_stop_event = asyncio.Event()
    calculation_rotation_task = asyncio.create_task(
        rotate_status_messages(
            bot=bot,
            chat_id=user_id,
            message_id=calculation_status_message_id,
            statuses=CALCULATION_STATUSES,
            stop_event=calculation_stop_event,
            interval=5.0,
            calculation_id=calculation_id,
            redis_client=redis_client
        )
    )
    
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


@router.message(F.text.in_(["Новый запрос", "🔄 Новый запрос"]))
async def handle_new_request_button(message: Message, state: FSMContext):
    """Handle 'Новый запрос' button click - same as /newrequest command."""
    await handle_start_logic(message, state, is_new_request=True)
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
        "Для начала работы отправьте команду /start или используйте команду /newrequest из меню бота.",
        reply_markup=get_main_keyboard()
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


@router.callback_query(F.data == "new_request")
async def handle_new_request_callback(callback: CallbackQuery, state: FSMContext):
    """Handle 'Новый запрос' inline button click - same as /newrequest command."""
    await callback.answer()
    user_id = callback.from_user.id
    
    # Get redis_client
    redis_client: RedisClient = get_redis_client()
    if not redis_client:
        logger.error("redis_client_not_available", user_id=user_id)
        await callback.message.answer(
            "Ошибка: сервис временно недоступен. Попробуйте позже.",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Check if user already accepted agreement (in Redis)
    agreement_accepted = await redis_client.is_user_agreement_accepted(user_id)
    
    # If not in Redis, check database
    if not agreement_accepted:
        db_client: DatabaseClient = get_db_client()
        if db_client:
            try:
                from sqlalchemy import select
                session = await db_client.get_session()
                try:
                    result = await session.execute(
                        select(User).where(User.user_id == user_id)
                    )
                    user = result.scalar_one_or_none()
                    if user and user.agreement_accepted:
                        # User accepted agreement in DB, restore it in Redis
                        await redis_client.set_user_agreement_accepted(user_id)
                        agreement_accepted = True
                        logger.info("agreement_restored_from_db", user_id=user_id)
                finally:
                    await session.close()
            except Exception as e:
                logger.warning("db_agreement_check_failed", user_id=user_id, error=str(e))
    
    # If user has agreement accepted, start express calculation directly
    if agreement_accepted:
        await start_express_calculation(callback.message, redis_client, user_id, state, is_new_request=True)
    else:
        # If no agreement found, use standard start logic
        if not hasattr(callback.message, 'text'):
            callback.message.text = "/start"
        await handle_start_logic(callback.message, state)
    
    logger.info("new_request_callback_clicked", user_id=user_id, agreement_accepted=agreement_accepted)


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
    
    # Remove keyboard from express calculation result message
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logger.warning("failed_to_remove_detailed_calculation_button", user_id=user_id, error=str(e))
    
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
            await callback.message.answer(
                "Ошибка: данные товара не найдены.",
                reply_markup=get_main_keyboard()
            )
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
    
    weight = wb_parser.get_product_weight(product_data) or 0
    
    # Volume priority: 1) Basket API (card_data), 2) WB API v4 (product_data), 3) GPT fallback
    # Try to get card_data from Redis first
    card_data_json = await redis_client.redis.get(f"calculation:{calculation_id}:card_data")
    volume_liters = 0
    
    # Priority 1: Try Basket API (card_data)
    if card_data_json:
        try:
            card_data = json.loads(card_data_json)
            package_volume = wb_parser.calculate_package_volume(card_data)
            if package_volume and package_volume > 0:
                volume_liters = package_volume
                logger.info(
                    "volume_from_card_data",
                    calculation_id=calculation_id,
                    volume_liters=volume_liters
                )
        except Exception as e:
            logger.warning(
                "failed_to_get_volume_from_card_data",
                calculation_id=calculation_id,
                error=str(e)
            )
    
    # Priority 2: Fallback to WB API v4 (product_data) if Basket API didn't provide volume
    if not volume_liters or volume_liters == 0:
        volume_from_product = wb_parser.get_product_volume(product_data)
        if volume_from_product and volume_from_product > 0:
            volume_liters = volume_from_product
            logger.info(
                "volume_from_wb_api_v4_fallback",
                calculation_id=calculation_id,
                volume_liters=volume_liters
            )
    
    # Priority 3: If still no volume, try GPT (but this is async, so we'll skip for now in handler)
    # Volume will be requested via GPT in calculation_worker if needed
    
    # Convert volume from liters to m³ (1 liter = 0.001 m³)
    volume_m3 = volume_liters * 0.001 if volume_liters else 0
    
    # Calculate purchase price in CNY using new formula
    exchange_rate_service = ExchangeRateService()
    cb_rates = await exchange_rate_service._get_cb_rates()
    usd_rub_rate = cb_rates["usd_rub"]
    usd_cny_rate = cb_rates["usd_cny"]
    
    # Use new calculation method with 0.38 coefficient and 8-28% constraint
    detailed_calc_service = DetailedCalculationService(
        exchange_rate_usd_rub=usd_rub_rate,
        exchange_rate_usd_cny=usd_cny_rate
    )
    
    if weight > 0 and volume_m3 > 0:
        purchase_price_cny = detailed_calc_service.calculate_purchase_price_cny(
            price_rub=price_rub,
            unit_weight_kg=weight,
            unit_volume_m3=volume_m3,
            usd_rub_rate=usd_rub_rate,
            usd_cny_rate=usd_cny_rate
        )
    else:
        # Fallback to old formula if weight or volume is missing
        rub_cny_rate = usd_rub_rate / usd_cny_rate if usd_cny_rate > 0 else 11.5
        purchase_price_cny = (price_rub / 4) / rub_cny_rate
    
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
    
    # Send new message instead of editing (to preserve express calculation result)
    new_message = await callback.message.answer(
        text=message_text,
        parse_mode="HTML",
        reply_markup=keyboard
    )
    
    # Save current parameters to state for later use, including message_id
    await state.update_data(
        calculation_id=calculation_id,
        current_weight=weight,
        current_volume=volume_m3,
        current_purchase_price_cny=purchase_price_cny,
        article_id=article_id,
        parameters_message_id=new_message.message_id
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
        await callback.message.answer(
            "Ошибка: данные товара не найдены.",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Get TN VED data
    tn_ved_code = original_result.get("tn_ved_code")
    duty_type = original_result.get("duty_type")
    duty_rate = original_result.get("duty_rate")
    vat_rate = original_result.get("vat_rate")
    duty_minimum = original_result.get("duty_minimum")  # Приписка о минимальной пошлине
    
    # Validate TN VED data: code must exist, duty info must be present
    # 0% duty rate is valid - it means the code exists and has zero duty
    if not tn_ved_code or not duty_type or duty_rate is None or vat_rate is None:
        await callback.answer("Ошибка: данные ТН ВЭД не найдены.", show_alert=True)
        return
    
    # Use the same calculation_id for detailed calculation (it's a continuation of express)
    detailed_calculation_id = original_calculation_id
    
    # Delete old express calculation result to prevent it from being sent instead of detailed result
    old_result_key = f"calculation:{detailed_calculation_id}:result"
    await redis_client.redis.delete(old_result_key)
    
    # Clear notification_sent flag to allow new result notification
    notification_sent_key = f"calculation:{detailed_calculation_id}:notification_sent"
    await redis_client.redis.delete(notification_sent_key)
    
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
            "vat_rate": vat_rate,
            "duty_minimum": duty_minimum  # Приписка о минимальной пошлине
        }
    }
    
    # Push detailed calculation to queue
    await redis_client.push_calculation(detailed_calculation_id, detailed_calculation_data)
    
    # Set status to pending
    await redis_client.set_calculation_status(detailed_calculation_id, "pending")
    
    # Set user's current calculation
    await redis_client.set_user_current_calculation(user_id, detailed_calculation_id)
    
    # Remove keyboard from parameters message
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logger.warning("failed_to_remove_parameters_keyboard", user_id=user_id, error=str(e))
    
    # Send status message
    status_message = await callback.message.answer("⏳ Запущен подробный расчёт...")
    status_message_id = status_message.message_id
    
    # Запускаем ротацию статусов для подробного расчёта
    detailed_calculation_stop_event = asyncio.Event()
    bot = get_bot()
    detailed_calculation_rotation_task = asyncio.create_task(
        rotate_status_messages(
            bot=bot,
            chat_id=user_id,
            message_id=status_message_id,
            statuses=DETAILED_CALCULATION_STATUSES,
            stop_event=detailed_calculation_stop_event,
            interval=5.0,
            calculation_id=detailed_calculation_id,
            redis_client=redis_client
        )
    )
    
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
        await message.answer(
            "Ошибка: данные товара не найдены.",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Get current state data
    state_data = await state.get_data()
    
    # Delete previous parameters message if exists
    previous_params_message_id = state_data.get("parameters_message_id")
    if previous_params_message_id:
        try:
            await message.bot.delete_message(
                chat_id=message.chat.id,
                message_id=previous_params_message_id
            )
        except Exception as e:
            logger.warning("failed_to_delete_previous_parameters_message", user_id=message.from_user.id, error=str(e))
    
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
        # Volume priority: 1) Basket API (card_data), 2) WB API v4 (product_data)
        # Try to get card_data from Redis first
        card_data_json = await redis_client.redis.get(f"calculation:{calculation_id}:card_data")
        volume_liters = 0
        
        # Priority 1: Try Basket API (card_data)
        if card_data_json:
            try:
                card_data = json.loads(card_data_json)
                package_volume = wb_parser.calculate_package_volume(card_data)
                if package_volume and package_volume > 0:
                    volume_liters = package_volume
                    logger.info(
                        "volume_from_card_data_in_show_parameters",
                        calculation_id=calculation_id,
                        volume_liters=volume_liters
                    )
            except Exception as e:
                logger.warning(
                    "failed_to_get_volume_from_card_data_in_show_parameters",
                    calculation_id=calculation_id,
                    error=str(e)
                )
        
        # Priority 2: Fallback to WB API v4 (product_data) if Basket API didn't provide volume
        if not volume_liters or volume_liters == 0:
            volume_from_product = wb_parser.get_product_volume(product_data)
            if volume_from_product and volume_from_product > 0:
                volume_liters = volume_from_product
                logger.info(
                    "volume_from_wb_api_v4_fallback_in_show_parameters",
                    calculation_id=calculation_id,
                    volume_liters=volume_liters
                )
        
        volume_m3 = volume_liters * 0.001
    else:
        volume_liters = volume_m3 * 1000  # Convert back to liters for display
    
    purchase_price_cny = purchase_price_adjusted_cny if purchase_price_adjusted_cny is not None else state_data.get("current_purchase_price_cny")
    if purchase_price_cny is None:
        # Calculate purchase price in CNY using new formula
        exchange_rate_service = ExchangeRateService()
        cb_rates = await exchange_rate_service._get_cb_rates()
        usd_rub_rate = cb_rates["usd_rub"]
        usd_cny_rate = cb_rates["usd_cny"]
        
        # Use new calculation method with 0.38 coefficient and 8-28% constraint
        detailed_calc_service = DetailedCalculationService(
            exchange_rate_usd_rub=usd_rub_rate,
            exchange_rate_usd_cny=usd_cny_rate
        )
        
        if weight > 0 and volume_m3 > 0:
            purchase_price_cny = detailed_calc_service.calculate_purchase_price_cny(
                price_rub=price_rub,
                unit_weight_kg=weight,
                unit_volume_m3=volume_m3,
                usd_rub_rate=usd_rub_rate,
                usd_cny_rate=usd_cny_rate
            )
        else:
            # Fallback to old formula if weight or volume is missing
            rub_cny_rate = usd_rub_rate / usd_cny_rate if usd_cny_rate > 0 else 11.5
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
    
    # Send new parameters message
    new_message = await message.answer(
        text=message_text,
        parse_mode="HTML",
        reply_markup=keyboard
    )
    
    # Update state with current values and save new message_id
    await state.update_data(
        calculation_id=calculation_id,
        current_weight=weight,
        current_volume=volume_m3,
        current_purchase_price_cny=purchase_price_cny,
        article_id=article_id,
        parameters_message_id=new_message.message_id
    )


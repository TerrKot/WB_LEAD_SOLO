"""Service for notifying users about calculation results."""
import asyncio
import json
import re
from typing import Optional, Dict, Any
import structlog

from apps.bot_service.clients.redis import RedisClient
from apps.bot_service.clients.database import DatabaseClient
from apps.bot_service.config import config
from aiogram import Bot
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

logger = structlog.get_logger()


def clean_html_for_telegram(text: str) -> str:
    """
    Clean HTML text to be compatible with Telegram HTML parse mode.
    
    Telegram HTML supports only: <b>, <strong>, <i>, <em>, <u>, <ins>, <s>, <strike>, <del>,
    <span>, <tg-spoiler>, <a>, <code>, <pre>.
    
    Replaces unsupported tags like <br>, <ul>, <li>, <ol>, <div>, <p> with appropriate text formatting.
    
    Args:
        text: HTML text to clean
        
    Returns:
        Cleaned HTML text compatible with Telegram
    """
    if not text:
        return text
    
    # Replace <br>, <br/>, <br /> with newlines
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    
    # Convert <li> items to bullet points (•)
    # First, replace <li> with newline + bullet, then remove <ul>/<ol> tags
    text = re.sub(r'<li[^>]*>', '\n• ', text, flags=re.IGNORECASE)
    text = re.sub(r'</li>', '', text, flags=re.IGNORECASE)
    
    # Remove list container tags but keep content
    text = re.sub(r'</?ul[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</?ol[^>]*>', '\n', text, flags=re.IGNORECASE)
    
    # Remove other unsupported block-level tags but keep their content
    # Note: <span> is supported by Telegram, so we don't remove it
    # Remove opening and closing tags for: div, p, h1-h6, etc.
    unsupported_tags = ['div', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'section', 'article', 'header', 'footer', 'nav']
    for tag in unsupported_tags:
        # Remove opening tags
        text = re.sub(rf'<{tag}[^>]*>', '', text, flags=re.IGNORECASE)
        # Remove closing tags
        text = re.sub(rf'</{tag}>', '', text, flags=re.IGNORECASE)
    
    # Clean up multiple consecutive newlines (more than 2)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Strip leading/trailing whitespace
    text = text.strip()
    
    return text


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


async def send_notification(bot: Bot, username: Optional[str], status: str, article_id: int):
    """
    Send notification to notification group in format: @username | Статус: 🟢 | WB: артикул
    
    Args:
        bot: Telegram Bot instance
        username: Telegram username (without @)
        status: Status emoji (🟢, 🟡, 🟠, 🔴, ⚪️)
        article_id: WB article ID
    """
    if not config.NOTIFICATION_CHAT_ID:
        logger.debug("notification_skipped_no_chat_id", article_id=article_id, status=status)
        return
    
    try:
        # Format username
        username_str = f"@{username}" if username else "без username"
        
        # Format notification message
        notification_text = f"{username_str} | Статус: {status} | WB: {article_id}"
        
        logger.info(
            "notification_sending",
            username=username,
            status=status,
            article_id=article_id,
            chat_id=config.NOTIFICATION_CHAT_ID,
            message_text=notification_text
        )
        
        await bot.send_message(
            chat_id=config.NOTIFICATION_CHAT_ID,
            text=notification_text
        )
        
        logger.info(
            "notification_sent",
            username=username,
            status=status,
            article_id=article_id
        )
    except Exception as e:
        logger.error(
            "notification_send_failed",
            username=username,
            status=status,
            article_id=article_id,
            chat_id=config.NOTIFICATION_CHAT_ID,
            error=str(e),
            error_class=type(e).__name__
        )


class ResultNotifier:
    """Service for checking calculation results and notifying users."""

    def __init__(self, bot: Bot, redis_client: RedisClient, db_client: DatabaseClient = None):
        """
        Initialize result notifier.

        Args:
            bot: Telegram Bot instance
            redis_client: Redis client
            db_client: Database client (optional, for getting username)
        """
        self.bot = bot
        self.redis = redis_client
        self.db_client = db_client
    
    async def _get_username(self, user_id: int) -> Optional[str]:
        """Get username from database or return None."""
        if not self.db_client:
            return None
        
        try:
            from sqlalchemy import select
            from apps.bot_service.clients.database import User
            
            session = await self.db_client.get_session()
            try:
                result = await session.execute(
                    select(User).where(User.user_id == user_id)
                )
                user = result.scalar_one_or_none()
                return user.username if user else None
            finally:
                await session.close()
        except Exception as e:
            logger.warning("username_fetch_failed", user_id=user_id, error=str(e))
            return None
    
    async def _get_article_id_from_result(self, result: Dict[str, Any]) -> Optional[int]:
        """Extract article_id from result. Priority: direct article_id > input_data > product_data."""
        # First, try to get article_id directly from result (added in worker from user request)
        article_id = result.get("article_id")
        if article_id:
            logger.debug("article_id_found_directly", article_id=article_id)
            return article_id
        
        # Second, try to get from input_data (from user request)
        input_data = result.get("input_data")
        if input_data:
            article_id = input_data.get("article_id")
            if article_id:
                logger.debug("article_id_found_in_input_data", article_id=article_id)
                return article_id
        
        # Third, try to get from product_data (fallback from WB API)
        product_data = result.get("product_data")
        if product_data:
            # Try nm_id first (more common in WB API v4), then id
            article_id = product_data.get("nm_id") or product_data.get("id")
            if article_id:
                logger.debug("article_id_found_in_product_data", article_id=article_id, has_nm_id="nm_id" in product_data, has_id="id" in product_data)
                return article_id
        
        # Last resort: try to get from calculation data in Redis
        calculation_id = result.get("calculation_id")
        if calculation_id:
            try:
                # Try to get article_id from calculation data stored in Redis
                calculation_data_json = await self.redis.redis.get(f"calculation:{calculation_id}:data")
                if calculation_data_json:
                    import json
                    calculation_data = json.loads(calculation_data_json)
                    article_id = calculation_data.get("article_id")
                    if article_id:
                        logger.debug("article_id_found_in_calculation_data", article_id=article_id, calculation_id=calculation_id)
                        return article_id
            except Exception as e:
                logger.debug("article_id_fallback_failed", calculation_id=calculation_id, error=str(e))
        
        logger.warning(
            "article_id_not_found",
            calculation_id=calculation_id,
            has_product_data=bool(product_data),
            product_data_keys=list(product_data.keys()) if product_data else [],
            has_input_data=bool(input_data),
            result_keys=list(result.keys())
        )
        return None

    async def check_and_notify(self, calculation_id: str, user_id: int, status_message_id: int) -> bool:
        """
        Check calculation result and notify user if ready by deleting status message and sending new one with keyboard.

        Args:
            calculation_id: Calculation ID
            user_id: Telegram user ID
            status_message_id: Message ID to delete

        Returns:
            True if result was found and sent, False otherwise
        """
        try:
            # Early check: if notification was already sent, don't process again
            notification_sent_key = f"calculation:{calculation_id}:notification_sent"
            notification_sent = await self.redis.redis.get(notification_sent_key)
            if notification_sent:
                # Result was already sent, don't send again
                return True
            
            # Get calculation status
            status = await self.redis.get_calculation_status(calculation_id)
            
            # Don't send results if calculation is in progress (pending or processing)
            # This prevents sending old express results when detailed calculation is starting
            if status in ("pending", "processing"):
                return False
            
            if status in ("blocked", "completed", "failed", "orange_zone"):
                # Get result
                result = await self.redis.get_calculation_result(calculation_id)
                
                if result:
                    # Try to atomically set notification flag (SETNX with TTL)
                    # This ensures only one process can send the notification
                    set_result = await self.redis.redis.set(
                        notification_sent_key,
                        "1",
                        ex=86400,  # 24 hours TTL
                        nx=True  # Only set if not exists (atomic operation)
                    )
                    
                    if not set_result:
                        # Another process already set the flag, don't send
                        return True
                    
                    # We successfully set the flag, so we can send the message
                    await self._send_result_message(user_id, status_message_id, result)
                    return True
            
            # Also check for assessment statuses (🟢/🟡/🟠/🔴)
            result = await self.redis.get_calculation_result(calculation_id)
            if result:
                calculation_type = result.get("calculation_type")
                assessment_status = result.get("status")
                # Get current status to check if we're waiting for a new calculation
                current_status = await self.redis.get_calculation_status(calculation_id)
                
                # Only send express calculation results if:
                # 1. This is not a detailed calculation result
                # 2. Current status is not "pending" (if pending, we're waiting for new result)
                # 3. Result has assessment status
                should_send = (
                    calculation_type != "detailed" and
                    current_status != "pending" and
                    assessment_status in ("🟢", "🟡", "🟠", "🔴")
                )
                
                if should_send:
                    # Try to atomically set notification flag (SETNX with TTL)
                    # This ensures only one process can send the notification
                    set_result = await self.redis.redis.set(
                        notification_sent_key,
                        "1",
                        ex=86400,  # 24 hours TTL
                        nx=True  # Only set if not exists (atomic operation)
                    )
                    
                    if not set_result:
                        # Another process already set the flag, don't send
                        return True
                    
                    # We successfully set the flag, so we can send the message
                    await self._send_result_message(user_id, status_message_id, result)
                    return True
            
            return False
        except Exception as e:
            logger.error(
                "result_check_error",
                calculation_id=calculation_id,
                user_id=user_id,
                error=str(e)
            )
            return False

    async def _send_result_message(self, user_id: int, status_message_id: int, result: Dict[str, Any]):
        """
        Delete status message and send new message with calculation result and keyboard.

        Args:
            user_id: Telegram user ID
            status_message_id: Message ID to delete
            result: Calculation result
        """
        status = result.get("status")
        calculation_id = result.get("calculation_id")
        
        # Останавливаем ротацию статусов, если она запущена
        if calculation_id:
            rotation_stop_key = f"calculation:{calculation_id}:rotation_stop_event"
            await self.redis.redis.setex(rotation_stop_key, 60, "stop")  # Устанавливаем флаг остановки
        
        # Check if this is a detailed calculation result
        calculation_type = result.get("calculation_type")
        
        # Delete intermediate status message
        try:
            await self.bot.delete_message(chat_id=user_id, message_id=status_message_id)
        except Exception as e:
            # If delete fails (e.g., message was already deleted), log and continue
            logger.warning(
                "status_message_delete_failed",
                error=str(e),
                user_id=user_id,
                message_id=status_message_id,
                calculation_id=result.get("calculation_id")
            )
        
        # Get main keyboard with "Новый запрос" button
        main_keyboard = get_main_keyboard()
        
        if calculation_type == "detailed":
            # Detailed calculation result
            message_text = result.get("message", "✅ Подробный расчёт завершён")
            message_text = clean_html_for_telegram(message_text)
            
            # Ensure message is not empty
            if not message_text or not message_text.strip():
                message_text = "✅ Подробный расчёт завершён"
            
            # Create inline keyboard with button to another bot
            detailed_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Сделать расчет точнее",
                        url="https://t.me/Voronoi_access_bot?start=WB"
                    )
                ]
            ])
            
            await self.bot.send_message(
                chat_id=user_id,
                text=message_text,
                parse_mode="HTML",
                reply_markup=detailed_keyboard,
                disable_web_page_preview=True
            )
            
            logger.info(
                "detailed_calculation_notification_sent",
                user_id=user_id,
                calculation_id=result.get("calculation_id")
            )
        
        elif status == "blocked":
            # Red zone blocked - use formatted message from result if available
            message_text = result.get("message")
            if not message_text:
                # Fallback to template if message not in result
                tn_ved_code = result.get("tn_ved_code", "N/A")
                reason = result.get("red_zone_reason") or result.get("forbidden_reason") or "Товар попадает в красную зону"
                forbidden_category = result.get("forbidden_category", "")
                
                if forbidden_category:
                    message_text = (
                        f"🔴 <b>Белая доставка — только после подготовки / смены продукта, с текущей категорией товара белая схема не рекомендована.</b>\n\n"
                        f"Категория товара: <b>{forbidden_category}</b>\n"
                        f"Причина: {reason}\n\n"
                        f"Товар не может быть доставлен белой логистикой.\n\n"
                        f"💡 Используйте кнопку ниже для нового запроса"
                    )
                else:
                    message_text = (
                        f"🔴 <b>Белая доставка — только после подготовки / смены продукта, с текущей категорией товара белая схема не рекомендована.</b>\n\n"
                        f"Код ТН ВЭД: <code>{tn_ved_code}</code>\n"
                        f"Причина: {reason}\n\n"
                        f"Товар не может быть доставлен белой логистикой.\n\n"
                        f"💡 Используйте кнопку ниже для нового запроса"
                    )
            
            # Clean HTML to remove unsupported tags like <br>
            message_text = clean_html_for_telegram(message_text)
            
            # Ensure message is not empty after cleaning
            if not message_text or not message_text.strip():
                # Fallback to default message if cleaning resulted in empty text
                forbidden_category = result.get("forbidden_category", "")
                reason = result.get("forbidden_reason") or result.get("red_zone_reason") or "Товар попадает в запрещенную категорию"
                if forbidden_category:
                    message_text = (
                        f"🔴 <b>Белая доставка — только после подготовки / смены продукта</b>\n\n"
                        f"Товар относится к категории: <b>{forbidden_category}</b>\n"
                        f"{reason}\n\n"
                        f"Товар не может быть доставлен белой логистикой.\n\n"
                        f"💡 Используйте кнопку ниже для нового запроса"
                    )
                else:
                    message_text = (
                        f"🔴 <b>Белая доставка — только после подготовки / смены продукта</b>\n\n"
                        f"{reason}\n\n"
                        f"Товар не может быть доставлен белой логистикой.\n\n"
                        f"💡 Используйте кнопку ниже для нового запроса"
                    )
                message_text = clean_html_for_telegram(message_text)
            
            await self.bot.send_message(
                chat_id=user_id,
                text=message_text,
                parse_mode="HTML",
                reply_markup=main_keyboard
            )
            
            logger.info(
                "red_zone_notification_sent",
                user_id=user_id,
                calculation_id=result.get("calculation_id"),
                tn_ved_code=result.get("tn_ved_code", "N/A")
            )
            
            # Send notification about express calculation result
            article_id = await self._get_article_id_from_result(result)
            if article_id:
                username = await self._get_username(user_id)
                try:
                    await send_notification(self.bot, username, "🔴", article_id)
                except Exception as e:
                    logger.warning("notification_send_failed_on_result", user_id=user_id, article_id=article_id, error=str(e))
            else:
                logger.warning(
                    "notification_skipped_no_article_id",
                    user_id=user_id,
                    calculation_id=result.get("calculation_id"),
                    result_keys=list(result.keys()) if result else [],
                    has_product_data=bool(result.get("product_data")) if result else False
                )
        
        elif status == "orange_zone" or status == "🟠":
            # Orange zone blocked
            message_text = result.get("message", "🟠 Экспресс-расчёт завершён")
            message_text = clean_html_for_telegram(message_text)
            
            # Add button for detailed calculation
            inline_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📊 Подробный расчёт",
                        callback_data=f"detailed_calculation:{result.get('calculation_id')}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔄 Новый запрос",
                        callback_data="new_request"
                    )
                ]
            ])
            
            # Send message with inline keyboard
            await self.bot.send_message(
                chat_id=user_id,
                text=message_text,
                parse_mode="HTML",
                reply_markup=inline_keyboard
            )
            # Send reply keyboard in a separate minimal message to ensure it's always visible
            await self.bot.send_message(
                chat_id=user_id,
                text="\u200B",  # Zero-width space (invisible)
                reply_markup=main_keyboard
            )
            
            logger.info(
                "orange_zone_notification_sent",
                user_id=user_id,
                calculation_id=result.get("calculation_id")
            )
            
            # Send notification about express calculation result
            article_id = await self._get_article_id_from_result(result)
            if article_id:
                username = await self._get_username(user_id)
                try:
                    await send_notification(self.bot, username, "🟠", article_id)
                except Exception as e:
                    logger.warning("notification_send_failed_on_result", user_id=user_id, article_id=article_id, error=str(e))
            else:
                logger.warning(
                    "notification_skipped_no_article_id",
                    user_id=user_id,
                    calculation_id=result.get("calculation_id"),
                    result_keys=list(result.keys()) if result else [],
                    has_product_data=bool(result.get("product_data")) if result else False
                )
        
        elif (status == "completed" or status in ("🟢", "🟡")) and calculation_type != "detailed":
            # Express assessment completed (🟢 or 🟡) - but not detailed calculation
            message_text = result.get("message", "✅ Расчёт завершён")
            message_text = clean_html_for_telegram(message_text)
            
            # For 🟢 and 🟡, we need to add buttons for detailed calculation
            inline_keyboard = None
            if status in ("🟢", "🟡"):
                inline_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="📊 Подробный расчёт",
                            callback_data=f"detailed_calculation:{result.get('calculation_id')}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="🔄 Новый запрос",
                            callback_data="new_request"
                        )
                    ]
                ])
            
            # Send message with inline keyboard (if available) and reply keyboard
            # In Telegram, you can't have both in one message, so we'll send reply keyboard separately
            if inline_keyboard:
                # Send main message with inline keyboard
                await self.bot.send_message(
                    chat_id=user_id,
                    text=message_text,
                    parse_mode="HTML",
                    reply_markup=inline_keyboard
                )
                # Send reply keyboard in a separate minimal message to ensure it's always visible
                await self.bot.send_message(
                    chat_id=user_id,
                    text="\u200B",  # Zero-width space (invisible)
                    reply_markup=main_keyboard
                )
            else:
                # No inline buttons, just send with reply keyboard
                await self.bot.send_message(
                    chat_id=user_id,
                    text=message_text,
                    parse_mode="HTML",
                    reply_markup=main_keyboard
                )
            
            logger.info(
                "calculation_completed_notification_sent",
                user_id=user_id,
                calculation_id=result.get("calculation_id"),
                assessment_status=status
            )
            
            # Send notification about express calculation result
            article_id = await self._get_article_id_from_result(result)
            if article_id:
                username = await self._get_username(user_id)
                # Use assessment_status if available, otherwise use status
                notification_status = result.get("assessment_status") or status
                try:
                    await send_notification(self.bot, username, notification_status, article_id)
                except Exception as e:
                    logger.warning("notification_send_failed_on_result", user_id=user_id, article_id=article_id, error=str(e))
            else:
                logger.warning(
                    "notification_skipped_no_article_id",
                    user_id=user_id,
                    calculation_id=result.get("calculation_id"),
                    result_keys=list(result.keys()) if result else [],
                    has_product_data=bool(result.get("product_data")) if result else False
                )
        
        elif status == "failed":
            # Calculation failed - show white status instead of error
            message_text = "⚪️ Нужно больше данных — данная категория пока не включена в наш реестр и не может быть отработана, доджитесь ближайшего обновления."
            
            await self.bot.send_message(
                chat_id=user_id,
                text=message_text,
                reply_markup=main_keyboard
            )
            
            logger.info(
                "calculation_failed_notification_sent",
                user_id=user_id,
                calculation_id=result.get("calculation_id")
            )
            
            # Send notification about express calculation result
            article_id = await self._get_article_id_from_result(result)
            if article_id:
                username = await self._get_username(user_id)
                try:
                    await send_notification(self.bot, username, "⚪️", article_id)
                except Exception as e:
                    logger.warning("notification_send_failed_on_result", user_id=user_id, article_id=article_id, error=str(e))
            else:
                logger.warning(
                    "notification_skipped_no_article_id",
                    user_id=user_id,
                    calculation_id=result.get("calculation_id"),
                    result_keys=list(result.keys()) if result else [],
                    has_product_data=bool(result.get("product_data")) if result else False
                )

    async def start_polling(self, check_interval: float = 2.0):
        """
        Start polling for calculation results.

        Args:
            check_interval: Interval between checks in seconds
        """
        logger.info("result_notifier_started", check_interval=check_interval)
        
        while True:
            try:
                # Get all pending calculations
                # This is a simplified approach - in production, use Redis pub/sub or similar
                await asyncio.sleep(check_interval)
                
                # Note: This is a basic implementation
                # For production, consider using Redis pub/sub or a dedicated queue
                # for result notifications
                
            except asyncio.CancelledError:
                logger.info("result_notifier_stopped")
                break
            except Exception as e:
                logger.error("result_notifier_error", error=str(e))
                await asyncio.sleep(check_interval)


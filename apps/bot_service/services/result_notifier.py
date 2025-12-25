"""Service for notifying users about calculation results."""
import asyncio
import json
import re
from typing import Optional, Dict, Any
import structlog

from apps.bot_service.clients.redis import RedisClient
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


class ResultNotifier:
    """Service for checking calculation results and notifying users."""

    def __init__(self, bot: Bot, redis_client: RedisClient):
        """
        Initialize result notifier.

        Args:
            bot: Telegram Bot instance
            redis_client: Redis client
        """
        self.bot = bot
        self.redis = redis_client

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
                        url="https://t.me/Voronoi_info_bot"
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
                reason = result.get("red_zone_reason", "Товар попадает в красную зону")
                message_text = (
                    f"🔴 <b>Белая доставка — только после подготовки / смены продукта, с текущей категорией товара белая схема не рекомендована.</b>\n\n"
                    f"Код ТН ВЭД: <code>{tn_ved_code}</code>\n"
                    f"Причина: {reason}\n\n"
                    f"Товар не может быть доставлен белой логистикой.\n\n"
                    f"💡 Используйте кнопку ниже для нового запроса"
                )
            
            # Clean HTML to remove unsupported tags like <br>
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


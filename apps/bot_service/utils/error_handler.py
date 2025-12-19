"""Error handling utilities for user-friendly error messages."""
from typing import Optional, Dict, Any
import structlog

logger = structlog.get_logger()


class ErrorHandler:
    """Utility class for handling errors and generating user-friendly messages."""

    @staticmethod
    def get_user_message_for_gpt_error(error_type: str, error_details: Optional[str] = None) -> str:
        """
        Get user-friendly message for GPT API errors.

        Args:
            error_type: Type of error (timeout, connection, api_error, etc.)
            error_details: Optional error details

        Returns:
            User-friendly error message
        """
        # Все ошибки подбора кода ТН ВЭД возвращают белый статус
        if error_details:
            logger.warning("gpt_error_details", error_type=error_type, details=error_details[:200])
        
        return "⚪️ Нужно больше данных — данная категория пока не включена в наш реестр и не может быть отработана, доджитесь ближайшего обновления."

    @staticmethod
    def get_user_message_for_wb_error(error_type: str, article_id: Optional[int] = None) -> str:
        """
        Get user-friendly message for WB API errors.

        Args:
            error_type: Type of error (not_found, timeout, connection, api_error, etc.)
            article_id: Optional article ID

        Returns:
            User-friendly error message
        """
        # Все ошибки парсинга данных возвращают белый статус
        return "⚪️ Нужно больше данных — данная категория пока не включена в наш реестр и не может быть отработана, доджитесь ближайшего обновления."

    @staticmethod
    def get_user_message_for_redis_error(error_type: str) -> str:
        """
        Get user-friendly message for Redis errors.

        Args:
            error_type: Type of error (connection, timeout, unavailable, etc.)

        Returns:
            User-friendly error message
        """
        messages = {
            "connection": "🔌 Ошибка подключения к сервису. Попробуйте позже.",
            "timeout": "⏱️ Превышено время ожидания ответа от сервиса. Попробуйте позже.",
            "unavailable": "🚫 Сервис временно недоступен. Попробуйте позже.",
            "data_not_found": "❌ Данные расчёта не найдены. Начните заново с /start",
            "unknown": "❌ Произошла ошибка при обработке запроса. Попробуйте позже."
        }
        
        return messages.get(error_type, messages["unknown"])

    @staticmethod
    def get_user_message_for_calculation_error(error_type: str, error_details: Optional[str] = None) -> str:
        """
        Get user-friendly message for calculation errors.

        Args:
            error_type: Type of error (fields_validation, tn_ved_selection, orange_zone_check, etc.)
            error_details: Optional error details

        Returns:
            User-friendly error message
        """
        # Все ошибки расчёта возвращают белый статус
        if error_details:
            logger.warning("calculation_error_details", error_type=error_type, details=error_details[:200])
        
        return "⚪️ Нужно больше данных — данная категория пока не включена в наш реестр и не может быть отработана, доджитесь ближайшего обновления."

    @staticmethod
    def classify_gpt_error(exception: Exception) -> str:
        """
        Classify GPT API error type.

        Args:
            exception: Exception object

        Returns:
            Error type string
        """
        error_str = str(exception).lower()
        error_type = type(exception).__name__
        
        if "timeout" in error_str or error_type == "TimeoutError":
            return "timeout"
        elif "connection" in error_str or "connect" in error_str:
            return "connection"
        elif "rate limit" in error_str or "429" in error_str:
            return "rate_limit"
        elif "api" in error_str or "400" in error_str or "401" in error_str or "403" in error_str or "500" in error_str:
            return "api_error"
        elif "json" in error_str or "parse" in error_str:
            return "invalid_response"
        else:
            return "unknown"

    @staticmethod
    def classify_wb_error(exception: Exception, status_code: Optional[int] = None) -> str:
        """
        Classify WB API error type.

        Args:
            exception: Exception object
            status_code: Optional HTTP status code

        Returns:
            Error type string
        """
        error_str = str(exception).lower()
        error_type = type(exception).__name__
        
        if status_code == 404:
            return "not_found"
        elif "timeout" in error_str or error_type == "TimeoutError":
            return "timeout"
        elif "connection" in error_str or "connect" in error_str:
            return "connection"
        elif status_code and status_code >= 500:
            return "api_error"
        elif status_code and status_code >= 400:
            return "api_error"
        elif "json" in error_str or "parse" in error_str:
            return "invalid_response"
        else:
            return "unknown"

    @staticmethod
    def classify_redis_error(exception: Exception) -> str:
        """
        Classify Redis error type.

        Args:
            exception: Exception object

        Returns:
            Error type string
        """
        error_str = str(exception).lower()
        error_type = type(exception).__name__
        
        if "connection" in error_str or "connect" in error_str:
            return "connection"
        elif "timeout" in error_str or error_type == "TimeoutError":
            return "timeout"
        elif "unavailable" in error_str or "not available" in error_str:
            return "unavailable"
        else:
            return "unknown"


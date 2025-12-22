"""Logging utilities with required fields and PII protection."""
import structlog
from typing import Optional, Dict, Any
import uuid

logger = structlog.get_logger()


def get_logger_with_context(
    calculation_id: Optional[str] = None,
    user_id: Optional[int] = None,
    event_type: Optional[str] = None
) -> structlog.BoundLogger:
    """
    Get logger with required context fields.

    Args:
        calculation_id: Calculation ID (required for calculation-related events)
        user_id: User ID (required for user-related events)
        event_type: Event type (required for all events)

    Returns:
        Bound logger with context
    """
    context: Dict[str, Any] = {}
    
    if event_type:
        context["event_type"] = event_type
    else:
        context["event_type"] = "unknown"
    
    if calculation_id:
        context["calculation_id"] = calculation_id
    
    if user_id:
        context["user_id"] = user_id
    
    # Generate event_id for tracking
    context["event_id"] = str(uuid.uuid4())
    
    return logger.bind(**context)


def sanitize_for_logging(data: Any, max_length: int = 200) -> Any:
    """
    Sanitize data for logging (remove PII, truncate long strings).

    Args:
        data: Data to sanitize
        max_length: Maximum length for strings

    Returns:
        Sanitized data
    """
    if isinstance(data, str):
        # Truncate long strings
        if len(data) > max_length:
            return data[:max_length] + "..."
        return data
    elif isinstance(data, dict):
        # Recursively sanitize dict values
        sanitized = {}
        for key, value in data.items():
            # Skip PII fields
            if key.lower() in ["phone", "email", "address", "full_name", "name", "description"]:
                # Log length instead of content
                if isinstance(value, str):
                    sanitized[key] = f"<{len(value)} chars>"
                else:
                    sanitized[key] = "<redacted>"
            else:
                sanitized[key] = sanitize_for_logging(value, max_length)
        return sanitized
    elif isinstance(data, list):
        # Sanitize list items
        return [sanitize_for_logging(item, max_length) for item in data]
    else:
        return data


def log_event(
    event_type: str,
    calculation_id: Optional[str] = None,
    user_id: Optional[int] = None,
    level: str = "info",
    **kwargs
):
    """
    Log event with required fields.

    Args:
        event_type: Event type (required)
        calculation_id: Calculation ID (optional)
        user_id: User ID (optional)
        level: Log level (info, warning, error, debug)
        **kwargs: Additional log fields
    """
    log = get_logger_with_context(
        calculation_id=calculation_id,
        user_id=user_id,
        event_type=event_type
    )
    
    # Sanitize kwargs to remove PII
    sanitized_kwargs = sanitize_for_logging(kwargs)
    
    # Log with appropriate level
    log_method = getattr(log, level.lower(), log.info)
    log_method(event_type, **sanitized_kwargs)





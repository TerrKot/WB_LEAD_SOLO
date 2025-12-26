"""Configuration module for bot service."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)


class Config:
    """Application configuration."""

    # Telegram Bot
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

    # GPT API
    GPT_API_KEY: str = os.getenv("GPT_API_KEY", "")
    GPT_API_URL: str = os.getenv("GPT_API_URL", "https://api.openai.com/v1/chat/completions")
    GPT_MODEL: str = os.getenv("GPT_MODEL", "gpt-4o")
    GPT_MODEL_FOR_CODE: str = os.getenv("GPT_MODEL_FOR_CODE", "gpt-5-mini")
    GPT_MODEL_FOR_CODE_WITH_SEARCH: str = os.getenv("GPT_MODEL_FOR_CODE_WITH_SEARCH", "gpt-4o-search-preview")

    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379/0")

    # PostgreSQL
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://app:app@postgres:5432/app"
    )

    # Exchange Rates
    EXCHANGE_RATE_USD_RUB: float = float(os.getenv("EXCHANGE_RATE_USD_RUB", "100.0"))
    EXCHANGE_RATE_USD_CNY: float = float(os.getenv("EXCHANGE_RATE_USD_CNY", "7.2"))
    EXCHANGE_RATE_EUR_RUB: float = float(os.getenv("EXCHANGE_RATE_EUR_RUB", "110.0"))

    # White Logistics
    WHITE_LOGISTICS_BASE_PRICE_USD: float = float(os.getenv("WHITE_LOGISTICS_BASE_PRICE_USD", "1850"))
    WHITE_LOGISTICS_DOCS_RUB: float = float(os.getenv("WHITE_LOGISTICS_DOCS_RUB", "15000"))
    WHITE_LOGISTICS_BROKER_RUB: float = float(os.getenv("WHITE_LOGISTICS_BROKER_RUB", "25000"))

    # Service
    SERVICE_PORT: int = int(os.getenv("SERVICE_PORT", "8444"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


config = Config()

# Validate required config only when actually needed (not on import)
# This allows tests to run without setting BOT_TOKEN
def validate_config():
    """Validate required configuration."""
    if not config.BOT_TOKEN:
        raise ValueError("BOT_TOKEN is required. Set it in .env file or environment variables.")


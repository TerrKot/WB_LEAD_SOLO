"""Tests for configuration."""
import os
import pytest
from unittest.mock import patch

# Set BOT_TOKEN before importing config to avoid validation error
if "BOT_TOKEN" not in os.environ:
    os.environ["BOT_TOKEN"] = "test_token_for_tests"

from apps.bot_service.config import Config, config


def test_config_required_bot_token():
    """Test that BOT_TOKEN is required."""
    # Save original token and config value
    original_token = os.environ.get("BOT_TOKEN")
    from apps.bot_service.config import config, validate_config
    original_config_token = config.BOT_TOKEN
    
    try:
        # Remove token from environment and config
        if "BOT_TOKEN" in os.environ:
            del os.environ["BOT_TOKEN"]
        config.BOT_TOKEN = ""
        
        # Call validate_config which should raise ValueError
        with pytest.raises(ValueError, match="BOT_TOKEN is required"):
            validate_config()
    finally:
        # Restore original token
        if original_token:
            os.environ["BOT_TOKEN"] = original_token
        elif "BOT_TOKEN" in os.environ:
            del os.environ["BOT_TOKEN"]
        config.BOT_TOKEN = original_config_token


def test_config_default_values():
    """Test default configuration values."""
    with patch.dict(os.environ, {"BOT_TOKEN": "test_token"}):
        config = Config()
        assert config.GPT_API_URL == "https://api.openai.com/v1/chat/completions"
        assert config.GPT_MODEL == "gpt-4o"
        assert config.SERVICE_PORT == 8443
        assert config.LOG_LEVEL == "INFO"
        assert config.EXCHANGE_RATE_USD_RUB == 100.0
        assert config.EXCHANGE_RATE_USD_CNY == 7.2


def test_config_env_override():
    """Test environment variable override."""
    original_env = dict(os.environ)
    try:
        os.environ.update({
            "BOT_TOKEN": "test_token",
            "SERVICE_PORT": "9000",
            "LOG_LEVEL": "DEBUG",
            "EXCHANGE_RATE_USD_RUB": "150.5"
        })
        
        # Reload config module
        import importlib
        import apps.bot_service.config
        importlib.reload(apps.bot_service.config)
        test_config = apps.bot_service.config.config
        
        assert test_config.SERVICE_PORT == 9000
        assert test_config.LOG_LEVEL == "DEBUG"
        assert test_config.EXCHANGE_RATE_USD_RUB == 150.5
    finally:
        os.environ.clear()
        os.environ.update(original_env)
        # Reload config module back
        import importlib
        import apps.bot_service.config
        importlib.reload(apps.bot_service.config)


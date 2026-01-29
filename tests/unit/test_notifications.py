"""Unit tests for notification functionality."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram import Bot

from apps.bot_service.services.result_notifier import send_notification, ResultNotifier
from apps.bot_service.clients.redis import RedisClient
from apps.bot_service.clients.database import DatabaseClient


class TestSendNotification:
    """Test cases for send_notification function."""

    @pytest.fixture
    def mock_bot(self):
        """Create mock bot."""
        bot = MagicMock(spec=Bot)
        bot.send_message = AsyncMock()
        return bot

    @pytest.mark.asyncio
    async def test_send_notification_with_username(self, mock_bot):
        """Test sending notification with username."""
        with patch('apps.bot_service.services.result_notifier.config') as mock_config:
            mock_config.NOTIFICATION_CHAT_ID = "-1001234567890"
            
            await send_notification(mock_bot, "testuser", "🟢", 154345562)
            
            mock_bot.send_message.assert_called_once_with(
                chat_id="-1001234567890",
                text="@testuser | Статус: 🟢 | WB: 154345562"
            )

    @pytest.mark.asyncio
    async def test_send_notification_without_username(self, mock_bot):
        """Test sending notification without username."""
        with patch('apps.bot_service.services.result_notifier.config') as mock_config:
            mock_config.NOTIFICATION_CHAT_ID = "-1001234567890"
            
            await send_notification(mock_bot, None, "🟡", 154345562)
            
            mock_bot.send_message.assert_called_once_with(
                chat_id="-1001234567890",
                text="без username | Статус: 🟡 | WB: 154345562"
            )

    @pytest.mark.asyncio
    async def test_send_notification_no_chat_id(self, mock_bot):
        """Test that notification is not sent when NOTIFICATION_CHAT_ID is not set."""
        with patch('apps.bot_service.services.result_notifier.config') as mock_config:
            mock_config.NOTIFICATION_CHAT_ID = ""
            
            await send_notification(mock_bot, "testuser", "🟢", 154345562)
            
            mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_notification_all_statuses(self, mock_bot):
        """Test sending notifications for all statuses."""
        with patch('apps.bot_service.services.result_notifier.config') as mock_config:
            mock_config.NOTIFICATION_CHAT_ID = "-1001234567890"
            
            statuses = ["🟢", "🟡", "🟠", "🔴", "⚪️"]
            
            for status in statuses:
                await send_notification(mock_bot, "testuser", status, 154345562)
            
            assert mock_bot.send_message.call_count == len(statuses)
            
            # Check last call
            last_call = mock_bot.send_message.call_args_list[-1]
            assert last_call[1]["text"] == "@testuser | Статус: ⚪️ | WB: 154345562"


class TestResultNotifierNotifications:
    """Test cases for ResultNotifier notification methods."""

    @pytest.fixture
    def mock_bot(self):
        """Create mock bot."""
        bot = MagicMock(spec=Bot)
        bot.send_message = AsyncMock()
        return bot

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        redis = MagicMock(spec=RedisClient)
        redis.redis = MagicMock()
        redis.get_calculation_status = AsyncMock(return_value="completed")
        redis.get_calculation_result = AsyncMock()
        return redis

    @pytest.fixture
    def mock_db(self):
        """Create mock database client."""
        db = MagicMock(spec=DatabaseClient)
        return db

    @pytest.fixture
    def notifier(self, mock_bot, mock_redis, mock_db):
        """Create ResultNotifier instance."""
        return ResultNotifier(mock_bot, mock_redis, mock_db)

    @pytest.mark.asyncio
    async def test_get_article_id_from_product_data(self, notifier):
        """Test extracting article_id from product_data."""
        result = {
            "product_data": {
                "nm_id": 154345562
            }
        }
        
        article_id = await notifier._get_article_id_from_result(result)
        assert article_id == 154345562

    @pytest.mark.asyncio
    async def test_get_article_id_from_input_data(self, notifier):
        """Test extracting article_id from input_data."""
        result = {
            "input_data": {
                "article_id": 154345562
            }
        }
        
        article_id = await notifier._get_article_id_from_result(result)
        assert article_id == 154345562

    @pytest.mark.asyncio
    async def test_get_article_id_priority(self, notifier):
        """Test that product_data has priority over input_data."""
        result = {
            "product_data": {
                "nm_id": 154345562
            },
            "input_data": {
                "article_id": 999999999
            }
        }
        
        article_id = await notifier._get_article_id_from_result(result)
        assert article_id == 154345562

    @pytest.mark.asyncio
    async def test_get_username_from_telegram_api(self, notifier):
        """Test getting username from Telegram API first."""
        mock_chat = MagicMock()
        mock_chat.username = "telegram_user"
        mock_chat.first_name = "Test"
        mock_chat.last_name = "User"
        notifier.bot.get_chat = AsyncMock(return_value=mock_chat)
        
        username = await notifier._get_username(12345)
        
        assert username == "telegram_user"
        notifier.bot.get_chat.assert_called_once_with(12345)

    @pytest.mark.asyncio
    async def test_get_username_from_db_fallback(self, notifier, mock_db):
        """Test fallback to database when Telegram API fails."""
        from sqlalchemy import select
        from apps.bot_service.clients.database import User
        
        # Telegram API fails
        notifier.bot.get_chat = AsyncMock(side_effect=Exception("API error"))
        
        # Database returns username
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_user = MagicMock()
        mock_user.username = "db_user"
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_user)
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.close = AsyncMock()
        mock_db.get_session = AsyncMock(return_value=mock_session)
        
        username = await notifier._get_username(12345)
        
        assert username == "db_user"
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_username_from_db_when_no_username_in_telegram(self, notifier, mock_db):
        """Test fallback to database when Telegram API returns no username."""
        from sqlalchemy import select
        from apps.bot_service.clients.database import User
        
        # Telegram API returns chat without username
        mock_chat = MagicMock()
        mock_chat.username = None
        notifier.bot.get_chat = AsyncMock(return_value=mock_chat)
        
        # Database returns username
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_user = MagicMock()
        mock_user.username = "db_user"
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_user)
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.close = AsyncMock()
        mock_db.get_session = AsyncMock(return_value=mock_session)
        
        username = await notifier._get_username(12345)
        
        assert username == "db_user"
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_username_not_found(self, notifier, mock_db):
        """Test getting username when not found in Telegram API or database."""
        # Telegram API returns chat without username
        mock_chat = MagicMock()
        mock_chat.username = None
        notifier.bot.get_chat = AsyncMock(return_value=mock_chat)
        
        # Database returns None
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.close = AsyncMock()
        mock_db.get_session = AsyncMock(return_value=mock_session)
        
        username = await notifier._get_username(12345)
        
        assert username is None
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_username_no_db_client(self, mock_bot, mock_redis):
        """Test getting username when db_client is None."""
        notifier = ResultNotifier(mock_bot, mock_redis, None)
        
        # Telegram API returns chat without username
        mock_chat = MagicMock()
        mock_chat.username = None
        notifier.bot.get_chat = AsyncMock(return_value=mock_chat)
        
        username = await notifier._get_username(12345)
        
        assert username is None

    @pytest.mark.asyncio
    async def test_get_username_telegram_api_error_no_db(self, mock_bot, mock_redis):
        """Test getting username when Telegram API fails and no db_client."""
        notifier = ResultNotifier(mock_bot, mock_redis, None)
        
        # Telegram API fails
        notifier.bot.get_chat = AsyncMock(side_effect=Exception("API error"))
        
        username = await notifier._get_username(12345)
        
        assert username is None







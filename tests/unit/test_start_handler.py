"""Tests for start handler."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import Message, User, Chat, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram import Bot

from apps.bot_service.handlers.start import (
    cmd_start,
    handle_agreement_accepted,
    handle_agreement_rejected,
    start_express_calculation,
    set_redis_client,
    update_user_from_telegram,
    set_db_client,
    set_bot
)
from apps.bot_service.clients.redis import RedisClient
from apps.bot_service.clients.database import DatabaseClient


@pytest.fixture
def mock_user():
    """Create mock user."""
    user = User(
        id=12345,
        is_bot=False,
        first_name="Test",
        username="testuser"
    )
    return user


@pytest.fixture
def mock_chat():
    """Create mock chat."""
    return Chat(id=12345, type="private")


@pytest.fixture
def mock_message(mock_user, mock_chat):
    """Create mock message."""
    message = MagicMock(spec=Message)
    message.from_user = mock_user
    message.chat = mock_chat
    message.answer = AsyncMock()
    message.bot = MagicMock()
    return message


@pytest.fixture
def mock_callback_query(mock_user, mock_chat):
    """Create mock callback query."""
    callback = MagicMock(spec=CallbackQuery)
    callback.from_user = mock_user
    callback.answer = AsyncMock()
    callback.message = MagicMock(spec=Message)
    callback.message.answer = AsyncMock()
    callback.message.chat = mock_chat
    callback.bot = MagicMock()
    return callback


@pytest.fixture
def mock_redis_client():
    """Create mock Redis client."""
    client = MagicMock(spec=RedisClient)
    client.is_user_agreement_accepted = AsyncMock(return_value=False)
    client.set_user_agreement_accepted = AsyncMock()
    client.set_calculation_status = AsyncMock()
    client.set_user_current_calculation = AsyncMock()
    client.push_calculation = AsyncMock()
    return client


@pytest.fixture
def mock_state():
    """Create mock FSM state."""
    return MagicMock(spec=FSMContext)


@pytest.mark.asyncio
async def test_cmd_start_new_user(mock_message, mock_redis_client, mock_state):
    """Test /start command for new user (agreement not accepted)."""
    # Setup
    mock_redis_client.is_user_agreement_accepted.return_value = False
    set_redis_client(mock_redis_client)
    
    # Execute
    await cmd_start(mock_message, mock_state)
    
    # Verify
    mock_redis_client.is_user_agreement_accepted.assert_called_once_with(12345)
    mock_message.answer.assert_called_once()
    call_args = mock_message.answer.call_args
    assert "Пользовательское соглашение" in call_args[0][0]
    assert call_args[1]["reply_markup"] is not None


@pytest.mark.asyncio
async def test_cmd_start_existing_user(mock_message, mock_redis_client, mock_state):
    """Test /start command for user who already accepted agreement."""
    # Setup
    mock_redis_client.is_user_agreement_accepted.return_value = True
    set_redis_client(mock_redis_client)
    mock_state.set_state = AsyncMock()
    mock_state.update_data = AsyncMock()
    
    # Execute
    await cmd_start(mock_message, mock_state)
    
    # Verify
    mock_redis_client.is_user_agreement_accepted.assert_called_once_with(12345)
    # Should start express calculation instead of showing agreement
    mock_redis_client.set_calculation_status.assert_called_once()
    mock_redis_client.set_user_current_calculation.assert_called_once()
    # push_calculation is not called here, it's called later in handle_article_input
    mock_state.set_state.assert_called_once()
    mock_state.update_data.assert_called_once()
    mock_message.answer.assert_called_once()
    assert "артикул WB" in mock_message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_agreement_accepted(mock_callback_query, mock_redis_client, mock_state):
    """Test agreement acceptance handler."""
    # Setup
    set_redis_client(mock_redis_client)
    mock_state.set_state = AsyncMock()
    mock_state.update_data = AsyncMock()
    
    # Execute
    await handle_agreement_accepted(mock_callback_query, mock_state)
    
    # Verify
    mock_redis_client.set_user_agreement_accepted.assert_called_once_with(12345)
    mock_callback_query.answer.assert_called_once_with("Соглашение принято")
    mock_redis_client.set_calculation_status.assert_called_once()
    mock_redis_client.set_user_current_calculation.assert_called_once()
    # push_calculation is not called here, it's called later in handle_article_input
    mock_state.set_state.assert_called_once()
    mock_state.update_data.assert_called_once()
    mock_callback_query.message.answer.assert_called_once()
    assert "артикул WB" in mock_callback_query.message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_agreement_rejected(mock_callback_query):
    """Test agreement rejection handler."""
    # Execute
    await handle_agreement_rejected(mock_callback_query)
    
    # Verify
    mock_callback_query.answer.assert_called_once_with("Соглашение отклонено")
    mock_callback_query.message.answer.assert_called_once()
    assert "необходимо принять" in mock_callback_query.message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_start_express_calculation(mock_message, mock_redis_client, mock_state):
    """Test starting express calculation."""
    user_id = 12345
    mock_state.set_state = AsyncMock()
    mock_state.update_data = AsyncMock()
    
    # Execute
    await start_express_calculation(mock_message, mock_redis_client, user_id, mock_state)
    
    # Verify
    mock_redis_client.set_calculation_status.assert_called_once()
    call_args = mock_redis_client.set_calculation_status.call_args
    assert call_args[0][1] == "pending"
    
    mock_redis_client.set_user_current_calculation.assert_called_once()
    call_args = mock_redis_client.set_user_current_calculation.call_args
    assert call_args[0][0] == user_id
    
    # push_calculation is not called here, it's called later in handle_article_input
    mock_state.set_state.assert_called_once()
    mock_state.update_data.assert_called_once()
    
    mock_message.answer.assert_called_once()
    assert "артикул WB" in mock_message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_cmd_start_redis_unavailable(mock_message, mock_state):
    """Test /start command when Redis is unavailable."""
    # Setup
    set_redis_client(None)
    
    # Execute
    await cmd_start(mock_message, mock_state)
    
    # Verify
    mock_message.answer.assert_called_once()
    assert "недоступен" in mock_message.answer.call_args[0][0].lower()


class TestUpdateUserFromTelegram:
    """Test cases for update_user_from_telegram function."""

    @pytest.fixture
    def mock_bot(self):
        """Create mock bot."""
        bot = MagicMock(spec=Bot)
        bot.get_chat = AsyncMock()
        return bot

    @pytest.fixture
    def mock_db_client(self):
        """Create mock database client."""
        db = MagicMock(spec=DatabaseClient)
        db.save_or_update_user = AsyncMock()
        return db

    @pytest.fixture
    def mock_user(self):
        """Create mock user."""
        user = MagicMock()
        user.id = 12345
        user.username = "testuser"
        user.first_name = "Test"
        user.last_name = "User"
        user.language_code = "ru"
        return user

    @pytest.mark.asyncio
    async def test_update_user_from_telegram_success(self, mock_bot, mock_db_client, mock_user):
        """Test updating user from Telegram API successfully."""
        # Setup
        mock_chat = MagicMock()
        mock_chat.username = "telegram_user"
        mock_chat.first_name = "Telegram"
        mock_chat.last_name = "User"
        mock_bot.get_chat = AsyncMock(return_value=mock_chat)
        set_bot(mock_bot)
        set_db_client(mock_db_client)
        
        # Execute
        with patch('apps.bot_service.handlers.start.logger'):
            await update_user_from_telegram(12345, mock_user)
        
        # Verify
        mock_bot.get_chat.assert_called_once_with(12345)
        mock_db_client.save_or_update_user.assert_called_once_with(
            user_id=12345,
            username="telegram_user",
            first_name="Telegram",
            last_name="User",
            language_code=None
        )

    @pytest.mark.asyncio
    async def test_update_user_from_telegram_api_fallback(self, mock_bot, mock_db_client, mock_user):
        """Test fallback to from_user when Telegram API fails."""
        # Setup
        mock_bot.get_chat = AsyncMock(side_effect=Exception("API error"))
        set_bot(mock_bot)
        set_db_client(mock_db_client)
        
        # Execute
        with patch('apps.bot_service.handlers.start.logger'):
            await update_user_from_telegram(12345, mock_user)
        
        # Verify
        mock_bot.get_chat.assert_called_once_with(12345)
        mock_db_client.save_or_update_user.assert_called_once_with(
            user_id=12345,
            username="testuser",
            first_name="Test",
            last_name="User",
            language_code="ru"
        )

    @pytest.mark.asyncio
    async def test_update_user_from_telegram_no_db_client(self, mock_bot, mock_user):
        """Test updating user when db_client is None."""
        # Setup
        mock_chat = MagicMock()
        mock_chat.username = "telegram_user"
        mock_bot.get_chat = AsyncMock(return_value=mock_chat)
        set_bot(mock_bot)
        set_db_client(None)
        
        # Execute - should not raise exception
        with patch('apps.bot_service.handlers.start.logger'):
            await update_user_from_telegram(12345, mock_user)
        
        # Verify - get_chat should not be called when db_client is None
        mock_bot.get_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_user_from_telegram_no_bot(self, mock_db_client, mock_user):
        """Test updating user when bot is None."""
        # Setup
        set_bot(None)
        set_db_client(mock_db_client)
        
        # Execute - should not raise exception
        with patch('apps.bot_service.handlers.start.logger'):
            await update_user_from_telegram(12345, mock_user)
        
        # Verify - save_or_update_user should not be called
        mock_db_client.save_or_update_user.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_user_from_telegram_no_username_in_telegram(self, mock_bot, mock_db_client, mock_user):
        """Test updating user when Telegram API returns no username."""
        # Setup
        mock_chat = MagicMock()
        mock_chat.username = None
        mock_chat.first_name = "Telegram"
        mock_chat.last_name = "User"
        mock_bot.get_chat = AsyncMock(return_value=mock_chat)
        set_bot(mock_bot)
        set_db_client(mock_db_client)
        
        # Execute
        with patch('apps.bot_service.handlers.start.logger'):
            await update_user_from_telegram(12345, mock_user)
        
        # Verify - should use from_user.username as fallback
        mock_bot.get_chat.assert_called_once_with(12345)
        mock_db_client.save_or_update_user.assert_called_once_with(
            user_id=12345,
            username=None,  # From Telegram API (None), not from_user
            first_name="Telegram",
            last_name="User",
            language_code=None
        )


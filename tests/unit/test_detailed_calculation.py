"""Tests for detailed calculation handlers."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import Message, User, Chat, CallbackQuery
from aiogram.fsm.context import FSMContext

from apps.bot_service.handlers.start import (
    handle_detailed_calculation,
    handle_adjust_weight,
    handle_adjust_volume,
    handle_adjust_purchase_price,
    handle_weight_input,
    handle_volume_input,
    handle_purchase_price_input,
    handle_calculate_detailed,
    DetailedCalculationStates,
    set_redis_client,
    set_bot
)
from apps.bot_service.clients.redis import RedisClient


@pytest.fixture
def mock_user():
    """Create mock user."""
    return User(
        id=12345,
        is_bot=False,
        first_name="Test",
        username="testuser"
    )


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
    message.text = "0.5"
    return message


@pytest.fixture
def mock_callback_query(mock_user, mock_chat):
    """Create mock callback query."""
    callback = MagicMock(spec=CallbackQuery)
    callback.from_user = mock_user
    callback.answer = AsyncMock()
    callback.message = MagicMock(spec=Message)
    callback.message.answer = AsyncMock()
    callback.message.edit_text = AsyncMock()
    callback.message.chat = mock_chat
    callback.data = "detailed_calculation:test-calculation-id"
    return callback


@pytest.fixture
def mock_redis_client():
    """Create mock Redis client."""
    client = MagicMock(spec=RedisClient)
    client.get_calculation_result = AsyncMock(return_value={
        "status": "🟢",
        "calculation_id": "test-calculation-id",
        "product_data": {
            "id": 123456,
            "name": "Test Product",
            "weight": 0.5,
            "volume": 2,
            "sizes": [{
                "price": {
                    "product": 10000  # 100 rubles in kopecks
                }
            }]
        }
    })
    client.get_calculation_product_data = AsyncMock(return_value={
        "id": 123456,
        "name": "Test Product"
    })
    return client


@pytest.fixture
def mock_state():
    """Create mock FSM state."""
    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.get_data = AsyncMock(return_value={
        "calculation_id": "test-calculation-id",
        "current_weight": 0.5,
        "current_volume": 0.002,
        "current_purchase_price": 25.0
    })
    return state


@pytest.mark.asyncio
async def test_handle_detailed_calculation_success(mock_callback_query, mock_redis_client, mock_state):
    """Test successful detailed calculation screen display."""
    # Setup
    set_redis_client(mock_redis_client)
    
    # Execute
    await handle_detailed_calculation(mock_callback_query, mock_state)
    
    # Verify
    mock_redis_client.get_calculation_result.assert_called_once_with("test-calculation-id")
    # Now we send new message instead of editing
    mock_callback_query.message.answer.assert_called_once()
    call_args = mock_callback_query.message.answer.call_args
    assert "Параметры для подробного расчёта" in call_args[1]["text"]
    assert call_args[1]["reply_markup"] is not None
    mock_callback_query.answer.assert_called_once()


@pytest.mark.asyncio
async def test_handle_detailed_calculation_no_result(mock_callback_query, mock_redis_client, mock_state):
    """Test detailed calculation when result not found."""
    # Setup
    mock_redis_client.get_calculation_result.return_value = None
    set_redis_client(mock_redis_client)
    
    # Execute
    await handle_detailed_calculation(mock_callback_query, mock_state)
    
    # Verify
    mock_callback_query.answer.assert_called_once()
    call_args = mock_callback_query.answer.call_args
    assert "Ошибка" in call_args[0][0]
    assert call_args[1]["show_alert"] is True


@pytest.mark.asyncio
async def test_handle_adjust_weight(mock_callback_query, mock_state):
    """Test weight adjustment handler."""
    # Setup
    mock_callback_query.data = "adjust_weight:test-calculation-id"
    
    # Execute
    await handle_adjust_weight(mock_callback_query, mock_state)
    
    # Verify
    mock_state.set_state.assert_called_once_with(DetailedCalculationStates.waiting_for_weight)
    mock_state.update_data.assert_called_once()
    mock_callback_query.message.answer.assert_called_once()
    assert "вес" in mock_callback_query.message.answer.call_args[0][0].lower()
    mock_callback_query.answer.assert_called_once()


@pytest.mark.asyncio
async def test_handle_adjust_volume(mock_callback_query, mock_state):
    """Test volume adjustment handler."""
    # Setup
    mock_callback_query.data = "adjust_volume:test-calculation-id"
    
    # Execute
    await handle_adjust_volume(mock_callback_query, mock_state)
    
    # Verify
    mock_state.set_state.assert_called_once_with(DetailedCalculationStates.waiting_for_volume)
    mock_state.update_data.assert_called_once()
    mock_callback_query.message.answer.assert_called_once()
    assert "объём" in mock_callback_query.message.answer.call_args[0][0].lower()
    mock_callback_query.answer.assert_called_once()


@pytest.mark.asyncio
async def test_handle_adjust_purchase_price(mock_callback_query, mock_state):
    """Test purchase price adjustment handler."""
    # Setup
    mock_callback_query.data = "adjust_purchase_price:test-calculation-id"
    
    # Execute
    await handle_adjust_purchase_price(mock_callback_query, mock_state)
    
    # Verify
    mock_state.set_state.assert_called_once_with(DetailedCalculationStates.waiting_for_purchase_price)
    mock_state.update_data.assert_called_once()
    mock_callback_query.message.answer.assert_called_once()
    answer_text = mock_callback_query.message.answer.call_args[0][0].lower()
    assert "закупочную цену" in answer_text or "закупочная цена" in answer_text
    mock_callback_query.answer.assert_called_once()


@pytest.mark.asyncio
async def test_handle_weight_input_valid(mock_message, mock_state):
    """Test valid weight input."""
    # Setup
    mock_message.text = "0.75"
    
    # Mock show_parameters_screen
    with patch('apps.bot_service.handlers.start.show_parameters_screen', new_callable=AsyncMock) as mock_show:
        # Execute
        await handle_weight_input(mock_message, mock_state)
        
        # Verify
        mock_state.update_data.assert_called()
        mock_show.assert_called_once()
        call_args = mock_show.call_args
        assert call_args[1]["weight_adjusted"] == 0.75


@pytest.mark.asyncio
async def test_handle_weight_input_invalid(mock_message, mock_state):
    """Test invalid weight input."""
    # Setup
    mock_message.text = "invalid"
    
    # Execute
    await handle_weight_input(mock_message, mock_state)
    
    # Verify
    mock_message.answer.assert_called_once()
    assert "Неверный формат" in mock_message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_weight_input_negative(mock_message, mock_state):
    """Test negative weight input."""
    # Setup
    mock_message.text = "-0.5"
    
    # Execute
    await handle_weight_input(mock_message, mock_state)
    
    # Verify
    mock_message.answer.assert_called_once()
    assert "положительным" in mock_message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_volume_input_valid(mock_message, mock_state):
    """Test valid volume input."""
    # Setup
    mock_message.text = "3.5"
    
    # Mock show_parameters_screen
    with patch('apps.bot_service.handlers.start.show_parameters_screen', new_callable=AsyncMock) as mock_show:
        # Execute
        await handle_volume_input(mock_message, mock_state)
        
        # Verify
        mock_state.update_data.assert_called()
        mock_show.assert_called_once()
        call_args = mock_show.call_args
        # Volume should be converted to m³ (3.5 liters = 0.0035 m³)
        assert abs(call_args[1]["volume_adjusted"] - 0.0035) < 0.0001


@pytest.mark.asyncio
async def test_handle_volume_input_invalid(mock_message, mock_state):
    """Test invalid volume input."""
    # Setup
    mock_message.text = "invalid"
    
    # Execute
    await handle_volume_input(mock_message, mock_state)
    
    # Verify
    mock_message.answer.assert_called_once()
    assert "Неверный формат" in mock_message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_purchase_price_input_valid(mock_message, mock_state):
    """Test valid purchase price input."""
    # Setup
    mock_message.text = "250.50"
    
    # Mock show_parameters_screen
    with patch('apps.bot_service.handlers.start.show_parameters_screen', new_callable=AsyncMock) as mock_show:
        # Execute
        await handle_purchase_price_input(mock_message, mock_state)
        
        # Verify
        mock_state.update_data.assert_called()
        mock_show.assert_called_once()
        call_args = mock_show.call_args
        assert call_args[1]["purchase_price_adjusted"] == 250.50


@pytest.mark.asyncio
async def test_handle_purchase_price_input_invalid(mock_message, mock_state):
    """Test invalid purchase price input."""
    # Setup
    mock_message.text = "invalid"
    
    # Execute
    await handle_purchase_price_input(mock_message, mock_state)
    
    # Verify
    mock_message.answer.assert_called_once()
    assert "Неверный формат" in mock_message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_calculate_detailed(mock_callback_query, mock_state, monkeypatch):
    """Test detailed calculation button handler."""
    from unittest.mock import AsyncMock, MagicMock
    from apps.bot_service.clients.redis import RedisClient
    
    # Setup mocks
    mock_callback_query.data = "calculate_detailed:test-calculation-id"
    mock_callback_query.message.answer = AsyncMock(return_value=MagicMock(message_id=1))
    
    mock_state.get_data = AsyncMock(return_value={
        "current_weight": 1.0,
        "current_volume": 0.01,
        "current_purchase_price": 250.0
    })
    
    # Mock Redis client
    mock_redis = AsyncMock(spec=RedisClient)
    mock_redis.get_calculation_result = AsyncMock(return_value={
        "product_data": {"id": 123, "name": "Test Product"},
        "tn_ved_code": "1234567890",
        "duty_type": "ad valorem",
        "duty_rate": 5.0,
        "vat_rate": 20.0
    })
    mock_redis.set_calculation_product_data = AsyncMock()
    mock_redis.push_calculation = AsyncMock()
    mock_redis.set_calculation_status = AsyncMock()
    mock_redis.set_user_current_calculation = AsyncMock()
    
    # Mock get_redis_client
    def mock_get_redis():
        return mock_redis
    
    monkeypatch.setattr("apps.bot_service.handlers.start.get_redis_client", mock_get_redis)
    
    # Mock get_bot and _poll_calculation_result
    mock_bot = MagicMock()
    monkeypatch.setattr("apps.bot_service.handlers.start.get_bot", lambda: mock_bot)
    monkeypatch.setattr("apps.bot_service.handlers.start._poll_calculation_result", AsyncMock())
    
    # Execute
    await handle_calculate_detailed(mock_callback_query, mock_state)
    
    # Verify
    mock_callback_query.answer.assert_called_once()
    call_args = mock_callback_query.answer.call_args
    assert "запущен" in call_args[0][0].lower() or "расчёт" in call_args[0][0].lower()
    mock_state.get_data.assert_called_once()
    mock_redis.get_calculation_result.assert_called_once()


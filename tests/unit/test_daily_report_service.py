"""Unit tests for daily report service."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
import pytz
from aiogram import Bot

from apps.bot_service.services.daily_report_service import DailyReportService
from apps.bot_service.clients.database import DatabaseClient


@pytest.fixture
def mock_bot():
    """Create mock bot."""
    bot = MagicMock(spec=Bot)
    bot.send_message = AsyncMock()
    return bot


@pytest.fixture
def mock_db_client():
    """Create mock database client."""
    db = MagicMock(spec=DatabaseClient)
    db.get_mau = AsyncMock(return_value=12400)
    db.get_wau = AsyncMock(return_value=1023)
    db.get_dau = AsyncMock(return_value=102)
    db.get_new_users_24h = AsyncMock(return_value=230)
    db.get_total_calculations_24h = AsyncMock(return_value=1230000)
    db.get_calculations_24h_by_status = AsyncMock(return_value={
        "🟢": 2245,
        "🟡": 2524,
        "🟠": 11231,
        "🔴": 1234
    })
    return db


@pytest.fixture
def report_service(mock_bot, mock_db_client):
    """Create DailyReportService instance."""
    return DailyReportService(mock_bot, mock_db_client)


@pytest.mark.asyncio
async def test_generate_report_success(report_service, mock_db_client):
    """Test successful report generation."""
    report_text = await report_service.generate_report()
    
    # Check that all statistics methods were called
    mock_db_client.get_mau.assert_called_once()
    mock_db_client.get_wau.assert_called_once()
    mock_db_client.get_dau.assert_called_once()
    mock_db_client.get_new_users_24h.assert_called_once()
    mock_db_client.get_total_calculations_24h.assert_called_once()
    mock_db_client.get_calculations_24h_by_status.assert_called_once()
    
    # Check report format
    assert "WB бот отчет:" in report_text
    assert "-MAU: 12400" in report_text
    assert "-WAU: 1023" in report_text
    assert "-DAU: 102" in report_text
    assert "-Новых юзеров (24ч): 230" in report_text
    assert "-Кол-во расчетов (24ч): 1230000" in report_text
    assert "🟢2245" in report_text
    assert "🟡2524" in report_text
    assert "🟠11231" in report_text
    assert "🔴1234" in report_text
    
    # Check date format (DD.MM.YYYY)
    lines = report_text.split("\n")
    first_line = lines[0]
    assert "WB бот отчет:" in first_line
    date_part = first_line.split(" WB бот отчет:")[0]
    # Date should be in format DD.MM.YYYY
    assert len(date_part.split(".")) == 3


@pytest.mark.asyncio
async def test_generate_report_with_empty_statuses(report_service, mock_db_client):
    """Test report generation when there are no calculations with emoji statuses."""
    mock_db_client.get_calculations_24h_by_status.return_value = {
        "pending": 100,
        "processing": 50
    }
    mock_db_client.get_total_calculations_24h.return_value = 150
    
    report_text = await report_service.generate_report()
    
    # Should not crash and should show total without status breakdown
    assert "-Кол-во расчетов (24ч): 150" in report_text
    # Should not have status emojis
    assert "🟢" not in report_text
    assert "🟡" not in report_text
    assert "🟠" not in report_text
    assert "🔴" not in report_text


@pytest.mark.asyncio
async def test_generate_report_with_partial_statuses(report_service, mock_db_client):
    """Test report generation with only some statuses present."""
    mock_db_client.get_calculations_24h_by_status.return_value = {
        "🟢": 100,
        "🔴": 50
    }
    mock_db_client.get_total_calculations_24h.return_value = 150
    
    report_text = await report_service.generate_report()
    
    # Should show only present statuses
    assert "🟢100" in report_text
    assert "🔴50" in report_text
    assert "🟡" not in report_text
    assert "🟠" not in report_text


@pytest.mark.asyncio
async def test_generate_report_with_zero_calculations(report_service, mock_db_client):
    """Test report generation when there are no calculations."""
    mock_db_client.get_total_calculations_24h.return_value = 0
    mock_db_client.get_calculations_24h_by_status.return_value = {}
    
    report_text = await report_service.generate_report()
    
    # Should show zero calculations
    assert "-Кол-во расчетов (24ч): 0" in report_text
    # Should not have status breakdown
    assert "(" not in report_text or ")" not in report_text or "🟢" not in report_text


@pytest.mark.asyncio
async def test_generate_report_date_format(report_service):
    """Test that report uses Moscow timezone and correct date format."""
    with patch('apps.bot_service.services.daily_report_service.datetime') as mock_datetime:
        moscow_tz = pytz.timezone('Europe/Moscow')
        test_date = datetime(2025, 12, 24, 12, 0, 0, tzinfo=moscow_tz)
        mock_datetime.now.return_value = test_date
        
        report_text = await report_service.generate_report()
        
        # Check date format
        assert "24.12.2025 WB бот отчет:" in report_text


@pytest.mark.asyncio
async def test_generate_report_exception_handling(report_service, mock_db_client):
    """Test that exceptions during report generation are handled."""
    mock_db_client.get_mau.side_effect = Exception("Database error")
    
    with pytest.raises(Exception):
        await report_service.generate_report()


@pytest.mark.asyncio
async def test_send_report_success(report_service, mock_bot, mock_db_client):
    """Test successful report sending."""
    chat_id = "-1001234567890"
    
    success = await report_service.send_report(chat_id)
    
    assert success is True
    mock_bot.send_message.assert_called_once()
    call_args = mock_bot.send_message.call_args
    assert call_args[1]["chat_id"] == chat_id
    assert "WB бот отчет:" in call_args[1]["text"]


@pytest.mark.asyncio
async def test_send_report_failure(report_service, mock_bot, mock_db_client):
    """Test report sending failure handling."""
    chat_id = "-1001234567890"
    mock_bot.send_message.side_effect = Exception("Telegram API error")
    
    success = await report_service.send_report(chat_id)
    
    assert success is False
    mock_bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_send_report_generation_error(report_service, mock_bot, mock_db_client):
    """Test that generation errors are propagated."""
    chat_id = "-1001234567890"
    mock_db_client.get_mau.side_effect = Exception("Database error")
    
    success = await report_service.send_report(chat_id)
    
    assert success is False
    # send_message should not be called if generation fails
    mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_report_format_matches_template(report_service):
    """Test that report format matches the expected template."""
    report_text = await report_service.generate_report()
    
    lines = report_text.strip().split("\n")
    
    # Check structure
    assert len(lines) >= 5  # Date line + 5 metric lines
    assert "WB бот отчет:" in lines[0]
    assert any("-MAU:" in line for line in lines)
    assert any("-WAU:" in line for line in lines)
    assert any("-DAU:" in line for line in lines)
    assert any("-Новых юзеров (24ч):" in line for line in lines)
    assert any("-Кол-во расчетов (24ч):" in line for line in lines)


@pytest.mark.asyncio
async def test_report_status_order(report_service, mock_db_client):
    """Test that statuses appear in correct order (🟢🟡🟠🔴)."""
    mock_db_client.get_calculations_24h_by_status.return_value = {
        "🟠": 100,
        "🟢": 50,
        "🔴": 25,
        "🟡": 75
    }
    
    report_text = await report_service.generate_report()
    
    # Find the status line
    status_line = None
    for line in report_text.split("\n"):
        if "Кол-во расчетов" in line:
            status_line = line
            break
    
    assert status_line is not None
    
    # Check order: 🟢 should come before 🟡, 🟡 before 🟠, 🟠 before 🔴
    green_pos = status_line.find("🟢")
    yellow_pos = status_line.find("🟡")
    orange_pos = status_line.find("🟠")
    red_pos = status_line.find("🔴")
    
    assert green_pos < yellow_pos
    assert yellow_pos < orange_pos
    assert orange_pos < red_pos


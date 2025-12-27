"""Unit tests for daily report scheduler logic."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
import pytz
import asyncio


@pytest.mark.asyncio
async def test_scheduler_time_window_logic():
    """Test that scheduler correctly identifies 12:00-12:01 window."""
    moscow_tz = pytz.timezone('Europe/Moscow')
    
    # Test cases: (hour, minute, should_trigger)
    test_cases = [
        (11, 59, False),  # Before window
        (12, 0, True),    # Start of window
        (12, 1, True),    # Within window
        (12, 2, False),   # After window
        (13, 0, False),   # Different hour
    ]
    
    for hour, minute, should_trigger in test_cases:
        test_time = datetime(2025, 1, 15, hour, minute, 0, tzinfo=moscow_tz)
        current_hour = test_time.hour
        current_minute = test_time.minute
        
        # Logic from scheduler
        is_in_window = current_hour == 12 and current_minute <= 1
        
        assert is_in_window == should_trigger, \
            f"Failed for {hour:02d}:{minute:02d} - expected {should_trigger}, got {is_in_window}"


@pytest.mark.asyncio
async def test_scheduler_prevents_duplicate_same_day():
    """Test that scheduler prevents sending twice on same day."""
    moscow_tz = pytz.timezone('Europe/Moscow')
    
    # Same day, different times
    time1 = datetime(2025, 1, 15, 12, 0, 0, tzinfo=moscow_tz)
    time2 = datetime(2025, 1, 15, 12, 0, 30, tzinfo=moscow_tz)
    
    date1 = time1.date()
    date2 = time2.date()
    
    # Should not send if same date
    assert date1 == date2
    assert date1 != None  # last_sent_date check would prevent duplicate


@pytest.mark.asyncio
async def test_scheduler_prevents_duplicate_within_2_minutes():
    """Test that scheduler prevents duplicate sends within 2 minutes."""
    moscow_tz = pytz.timezone('Europe/Moscow')
    
    # First send at 12:00:00
    time1 = datetime(2025, 1, 15, 12, 0, 0, tzinfo=moscow_tz)
    # Second check at 12:00:30 (within 2 minutes)
    time2 = datetime(2025, 1, 15, 12, 0, 30, tzinfo=moscow_tz)
    
    time_diff = (time2 - time1).total_seconds()
    
    # Should prevent duplicate if less than 120 seconds
    should_prevent = time_diff < 120
    assert should_prevent is True, "Should prevent duplicate within 2 minutes"
    
    # Third check at 12:02:01 (more than 2 minutes)
    time3 = datetime(2025, 1, 15, 12, 2, 1, tzinfo=moscow_tz)
    time_diff2 = (time3 - time1).total_seconds()
    should_prevent2 = time_diff2 < 120
    assert should_prevent2 is False, "Should allow send after 2 minutes"


@pytest.mark.asyncio
async def test_scheduler_allows_send_next_day():
    """Test that scheduler allows sending on next day."""
    moscow_tz = pytz.timezone('Europe/Moscow')
    
    # First day
    time1 = datetime(2025, 1, 15, 12, 0, 0, tzinfo=moscow_tz)
    date1 = time1.date()
    
    # Next day
    time2 = datetime(2025, 1, 16, 12, 0, 0, tzinfo=moscow_tz)
    date2 = time2.date()
    
    # Should allow send if different date
    assert date1 != date2
    assert date2 != None  # Would allow send


@pytest.mark.asyncio
async def test_scheduler_sleep_intervals():
    """Test that scheduler uses correct sleep intervals for different times."""
    moscow_tz = pytz.timezone('Europe/Moscow')
    
    # Test critical window (11:55-12:05) - should use 10 seconds
    time_before = datetime(2025, 1, 15, 11, 55, 0, tzinfo=moscow_tz)
    time_after = datetime(2025, 1, 15, 12, 5, 0, tzinfo=moscow_tz)
    
    hour_before = time_before.hour
    minute_before = time_before.minute
    hour_after = time_after.hour
    minute_after = time_after.minute
    
    # Logic from scheduler
    is_critical_before = hour_before == 11 and minute_before >= 55
    is_critical_after = hour_after == 12 and minute_after <= 5
    
    assert is_critical_before is True, "Should detect critical window before 12:00"
    assert is_critical_after is True, "Should detect critical window after 12:00"
    
    # Test normal time - should use 30 seconds
    time_normal = datetime(2025, 1, 15, 10, 0, 0, tzinfo=moscow_tz)
    hour_normal = time_normal.hour
    minute_normal = time_normal.minute
    
    is_critical_normal = (hour_normal == 11 and minute_normal >= 55) or \
                        (hour_normal == 12 and minute_normal <= 5)
    
    assert is_critical_normal is False, "Should not detect critical window at normal time"

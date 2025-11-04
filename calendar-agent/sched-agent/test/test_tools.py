"""
Direct unit tests for tools.py functions
Tests calendar operations implementation without FastAPI layer
NOW INCLUDES PAST DATE VALIDATION TESTS
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import (
    format_datetime,
    validate_future_datetime,
    check_conflicts,
    create_event_impl,
    search_events_impl,
    update_event_impl,
    delete_event_impl,
    list_calendars_impl,
    create_calendar_impl,
    handle_user_confirmation,
    find_calendar_id_by_name,
)


# ============================================================
# TEST DATETIME FORMATTING
# ============================================================

class TestDateTimeFormatting:
    """Test datetime formatting and parsing"""
    
    def test_format_basic_datetime(self):
        """Test basic datetime formatting"""
        result = format_datetime("2025-11-15 10:00")
        assert result is not None
        assert "2025-11-15" in result
        assert "10:00" in result
        assert "+08:00" in result  # Asia/Manila timezone
    
    def test_format_12_hour_am(self):
        """Test 12 AM format"""
        result = format_datetime("2025-11-15 12:00 AM")
        assert result is not None
        assert "2025-11-15" in result
    
    def test_format_12_hour_pm(self):
        """Test 12 PM format"""
        result = format_datetime("2025-11-15 2:30 PM")
        assert result is not None
        assert "2025-11-15" in result
    
    @patch('tools.datetime')
    def test_format_today(self, mock_dt):
        """Test 'today' relative date"""
        tz = pytz.timezone("Asia/Manila")
        fixed_now = datetime(2025, 11, 15, 10, 0, 0, tzinfo=tz)
        mock_dt.now.return_value = fixed_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        
        result = format_datetime("today at 2pm")
        assert result is not None
    
    @patch('tools.datetime')
    def test_format_tomorrow(self, mock_dt):
        """Test 'tomorrow' relative date"""
        tz = pytz.timezone("Asia/Manila")
        fixed_now = datetime(2025, 11, 15, 10, 0, 0, tzinfo=tz)
        mock_dt.now.return_value = fixed_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        
        result = format_datetime("tomorrow at 10am")
        assert result is not None
    
    def test_format_invalid_datetime(self):
        """Test invalid datetime returns None"""
        result = format_datetime("not a valid date")
        assert result is None
    
    def test_format_empty_string(self):
        """Test empty string returns None"""
        result = format_datetime("")
        assert result is None


# ============================================================
# TEST PAST DATE VALIDATION (NEW)
# ============================================================

class TestPastDateValidation:
    """Test validation of future/past datetimes"""
    
    def test_validate_future_date_valid(self):
        """Test validation passes for future dates"""
        result = validate_future_datetime("2025-11-15 10:00")
        
        assert result["valid"] is True
        assert result["error"] is None
        assert result["parsed_datetime"] is not None
    
    def test_validate_past_date_invalid(self):
        """Test validation fails for past dates"""
        # Use a date that's definitely in the past
        result = validate_future_datetime("2024-01-01 10:00")
        
        assert result["valid"] is False
        assert "past" in result["error"].lower()
    
    def test_validate_yesterday_invalid(self):
        """Test validation fails for yesterday's date"""
        tz = pytz.timezone("Asia/Manila")
        yesterday = (datetime.now(tz) - timedelta(days=1)).strftime("%Y-%m-%d 10:00")
        
        result = validate_future_datetime(yesterday)
        
        assert result["valid"] is False
        assert "past" in result["error"].lower()
    
    def test_validate_tomorrow_valid(self):
        """Test 'tomorrow' is always valid"""
        result = validate_future_datetime("tomorrow at 10am")
        
        assert result["valid"] is True
    
    def test_validate_invalid_format(self):
        """Test validation handles invalid date formats"""
        result = validate_future_datetime("not a valid date")
        
        assert result["valid"] is False
        assert "Invalid date format" in result["error"]


# ============================================================
# TEST CONFLICT CHECKING
# ============================================================

class TestConflictChecking:
    """Test event conflict detection"""
    
    @patch('tools.get_calendar_service')
    def test_check_conflicts_found(self, mock_service):
        """Test conflict detection when conflicts exist"""
        mock_event = {
            "id": "conflict123",
            "summary": "Existing Meeting"
        }
        mock_service().events().list().execute.return_value = {
            "items": [mock_event]
        }
        
        conflicts = check_conflicts(
            "2025-11-15 10:00",
            "2025-11-15 11:00"
        )
        
        assert len(conflicts) == 1
        assert conflicts[0]["id"] == "conflict123"
    
    @patch('tools.get_calendar_service')
    def test_check_conflicts_none(self, mock_service):
        """Test conflict detection when no conflicts"""
        mock_service().events().list().execute.return_value = {
            "items": []
        }
        
        conflicts = check_conflicts(
            "2025-11-15 10:00",
            "2025-11-15 11:00"
        )
        
        assert len(conflicts) == 0
    
    @patch('tools.get_calendar_service')
    def test_check_conflicts_api_error(self, mock_service):
        """Test conflict checking handles API errors"""
        mock_service().events().list().execute.side_effect = Exception("API Error")
        
        conflicts = check_conflicts(
            "2025-11-15 10:00",
            "2025-11-15 11:00"
        )
        
        assert conflicts == []


# ============================================================
# TEST CREATE EVENT (WITH PAST DATE VALIDATION)
# ============================================================

class TestCreateEvent:
    """Test event creation implementation with date validation"""
    
    @patch('tools.get_calendar_service')
    @patch('tools.check_conflicts')
    def test_create_event_success(self, mock_conflicts, mock_service):
        """Test successful event creation"""
        mock_conflicts.return_value = []
        mock_service().events().insert().execute.return_value = {
            "id": "new_event_123",
            "summary": "New Meeting",
            "htmlLink": "https://calendar.google.com/event?eid=123"
        }
        
        # Use a date far in the future to ensure it passes validation
        result = create_event_impl(
            summary="New Meeting",
            start="2026-11-15 10:00",
            end="2026-11-15 11:00",
            emails=["test@example.com"]
        )
        
        assert result["success"] is True
        assert result["event_id"] == "new_event_123"
        assert "event_url" in result
    
    def test_create_event_past_start_date(self):
        """Test event creation fails with past start date"""
        result = create_event_impl(
            summary="Past Meeting",
            start="2020-01-01 10:00",
            end="2020-01-01 11:00",
            emails=[]
        )
        
        assert result["success"] is False
        assert result["error_type"] == "past_date"
        assert "past" in result["error"].lower()
    
    def test_create_event_end_before_start(self):
        """Test event creation fails when end is before start"""
        result = create_event_impl(
            summary="Invalid Time Range",
            start="2026-11-15 11:00",
            end="2026-11-15 10:00",
            emails=[]
        )
        
        assert result["success"] is False
        assert result["error_type"] == "invalid_time_range"
        assert "End time must be after start time" in result["error"]
    
    @patch('tools.get_calendar_service')
    @patch('tools.check_conflicts')
    def test_create_event_with_meet_link(self, mock_conflicts, mock_service):
        """Test creating event with Google Meet link"""
        mock_conflicts.return_value = []
        mock_service().events().insert().execute.return_value = {
            "id": "meet_event_123",
            "summary": "Video Meeting",
            "htmlLink": "https://calendar.google.com/event?eid=123",
            "conferenceData": {
                "entryPoints": [{"uri": "https://meet.google.com/abc-defg-hij"}]
            }
        }
        
        # Use future date
        result = create_event_impl(
            summary="Video Meeting",
            start="2026-11-15 10:00",
            end="2026-11-15 11:00",
            emails=[],
            add_meet_link=True
        )
        
        assert result["success"] is True
        assert result["meet_link"] == "https://meet.google.com/abc-defg-hij"
    
    @patch('tools.check_conflicts')
    def test_create_event_conflict_detected(self, mock_conflicts):
        """Test event creation with conflict"""
        mock_conflicts.return_value = [{
            "id": "conflict_id",
            "summary": "Existing Event"
        }]
        
        # Use future date
        result = create_event_impl(
            summary="New Meeting",
            start="2026-11-15 10:00",
            end="2026-11-15 11:00",
            emails=[]
        )
        
        assert result["success"] is False
        assert result["error_type"] == "conflict"
        assert result["conflict_id"] == "conflict_id"
    
    def test_create_event_invalid_datetime(self):
        """Test event creation with invalid datetime"""
        result = create_event_impl(
            summary="Invalid Event",
            start="invalid date",
            end="invalid date",
            emails=[]
        )
        
        assert result["success"] is False
        assert "error_type" in result


# ============================================================
# TEST SEARCH EVENTS
# ============================================================

class TestSearchEvents:
    """Test event searching"""
    
    @patch('tools.get_calendar_service')
    def test_search_events_found(self, mock_service):
        """Test searching events returns results"""
        mock_events = [
            {
                "id": "event1",
                "summary": "Meeting 1",
                "start": {"dateTime": "2025-11-15T10:00:00+08:00"},
                "end": {"dateTime": "2025-11-15T11:00:00+08:00"},
                "attendees": [{"email": "test@example.com"}]
            }
        ]
        mock_service().events().list().execute.return_value = {
            "items": mock_events
        }
        
        result = search_events_impl(max_results=5)
        
        assert result["success"] is True
        assert result["count"] == 1
        assert len(result["events"]) == 1
        assert result["events"][0]["event_id"] == "event1"
    
    @patch('tools.get_calendar_service')
    def test_search_events_empty(self, mock_service):
        """Test searching when no events found"""
        mock_service().events().list().execute.return_value = {
            "items": []
        }
        
        result = search_events_impl()
        
        assert result["success"] is True
        assert result["count"] == 0
        assert len(result["events"]) == 0


# ============================================================
# TEST UPDATE EVENT (WITH PAST DATE VALIDATION)
# ============================================================

class TestUpdateEvent:
    """Test event updating with date validation"""
    
    @patch('tools.get_calendar_service')
    def test_update_event_title(self, mock_service):
        """Test updating event title"""
        mock_service().events().get().execute.return_value = {
            "id": "event123",
            "summary": "Old Title",
            "start": {"dateTime": "2025-11-15T10:00:00+08:00"},
            "end": {"dateTime": "2025-11-15T11:00:00+08:00"}
        }
        mock_service().events().update().execute.return_value = {
            "id": "event123",
            "summary": "New Title",
            "htmlLink": "https://calendar.google.com/event?eid=123"
        }
        
        result = update_event_impl(
            event_id="event123",
            new_summary="New Title"
        )
        
        assert result["success"] is True
        assert "title" in str(result["changes"])
    
    @patch('tools.get_calendar_service')
    def test_update_event_time_future(self, mock_service):
        """Test updating event to future time"""
        mock_service().events().get().execute.return_value = {
            "id": "event123",
            "summary": "Meeting",
            "start": {"dateTime": "2025-11-15T10:00:00+08:00"},
            "end": {"dateTime": "2025-11-15T11:00:00+08:00"}
        }
        mock_service().events().update().execute.return_value = {
            "id": "event123",
            "htmlLink": "https://calendar.google.com/event?eid=123"
        }
        
        result = update_event_impl(
            event_id="event123",
            new_start="2025-11-15 14:00"
        )
        
        assert result["success"] is True
        assert "start time" in str(result["changes"])
    
    @patch('tools.get_calendar_service')
    def test_update_event_to_past_date(self, mock_service):
        """Test updating event to past date fails"""
        mock_service().events().get().execute.return_value = {
            "id": "event123",
            "summary": "Meeting",
            "start": {"dateTime": "2025-11-15T10:00:00+08:00"},
            "end": {"dateTime": "2025-11-15T11:00:00+08:00"}
        }
        
        result = update_event_impl(
            event_id="event123",
            new_start="2024-01-01 10:00"
        )
        
        assert result["success"] is False
        assert result["error_type"] == "past_date"
        assert "past" in result["error"].lower()


# ============================================================
# TEST DELETE EVENT
# ============================================================

class TestDeleteEvent:
    """Test event deletion"""
    
    @patch('tools.get_calendar_service')
    def test_delete_event_requires_confirmation(self, mock_service):
        """Test delete requires confirmation"""
        mock_service().events().get().execute.return_value = {
            "id": "event123",
            "summary": "Meeting to Delete",
            "start": {"dateTime": "2025-11-15T10:00:00+08:00"},
            "attendees": []
        }
        
        result = delete_event_impl(
            event_id="event123",
            skip_confirmation=False
        )
        
        assert result["success"] is False
        assert result["requires_confirmation"] is True
        assert "confirmation_prompt" in result
    
    @patch('tools.get_calendar_service')
    def test_delete_event_confirmed(self, mock_service):
        """Test confirmed deletion"""
        mock_service().events().get().execute.return_value = {
            "id": "event123",
            "summary": "Meeting to Delete",
            "start": {"dateTime": "2025-11-15T10:00:00+08:00"},
            "attendees": []
        }
        mock_service().events().delete().execute.return_value = None
        
        result = delete_event_impl(
            event_id="event123",
            skip_confirmation=True
        )
        
        assert result["success"] is True
        assert result["deleted"] is True


# ============================================================
# TEST CALENDAR MANAGEMENT
# ============================================================

class TestCalendarManagement:
    """Test calendar list and creation"""
    
    @patch('tools.get_calendar_service')
    def test_list_calendars(self, mock_service):
        """Test listing calendars"""
        mock_service().calendarList().list().execute.return_value = {
            "items": [
                {"id": "cal1", "summary": "Work", "primary": True},
                {"id": "cal2", "summary": "Personal", "primary": False}
            ]
        }
        
        result = list_calendars_impl()
        
        assert result["success"] is True
        assert len(result["calendars"]) == 2
    
    @patch('tools.get_calendar_service')
    def test_create_calendar(self, mock_service):
        """Test creating calendar"""
        mock_service().calendars().insert().execute.return_value = {
            "id": "new_cal_123",
            "summary": "New Calendar"
        }
        
        result = create_calendar_impl(
            calendar_name="New Calendar",
            description="Test calendar"
        )
        
        assert result["success"] is True
    
    @patch('tools.get_calendar_service')
    def test_find_calendar_by_name(self, mock_service):
        """Test finding calendar by name"""
        mock_service().calendarList().list().execute.return_value = {
            "items": [
                {"id": "work_cal", "summary": "Work Calendar"}
            ]
        }
        
        result = find_calendar_id_by_name("Work Calendar")
        assert result == "work_cal"


# ============================================================
# TEST CONFLICT RESOLUTION
# ============================================================

class TestConflictResolution:
    """Test conflict resolution workflow"""
    
    @patch('tools.get_calendar_service')
    @patch('tools.create_event_impl')
    def test_handle_user_confirmation(self, mock_create, mock_service):
        """Test resolving conflict by moving event"""
        mock_service().events().get().execute.return_value = {
            "id": "conflict_id",
            "summary": "Existing Event",
            "start": {"dateTime": "2025-11-15T10:00:00+08:00"},
            "end": {"dateTime": "2025-11-15T11:00:00+08:00"}
        }
        mock_service().events().update().execute.return_value = {}
        mock_create.return_value = {
            "success": True,
            "event_id": "new_event_id",
            "message": "Created successfully"
        }
        
        new_event = {
            "summary": "New Meeting",
            "start": "2025-11-15 10:00",
            "end": "2025-11-15 11:00",
            "emails": []
        }
        
        result = handle_user_confirmation("conflict_id", new_event)
        
        assert result["success"] is True
        assert "event_id" in result


# ============================================================
# INTEGRATION TESTS FOR EDGE CASES
# ============================================================

class TestEdgeCases:
    """Test edge cases and special scenarios"""
    
    def test_future_date_validation(self):
        """Test validation for dates in the future"""
        # Use a date far in the future
        result = validate_future_datetime("2026-12-31 10:00")
        assert result["valid"] is True
    
    def test_past_date_validation(self):
        """Test validation for dates in the past"""
        # Use a date definitely in the past
        result = validate_future_datetime("2020-01-01 10:00")
        assert result["valid"] is False
        assert "past" in result["error"].lower()


# ============================================================
# RUN TESTS
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
"""
Unit Tests for Calendar Agent API
Tests all calendar operations with mocked Google Calendar API
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import json

# Add parent directory to path to import from api.py and tools.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi.testclient import TestClient


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def mock_calendar_service():
    """Mock Google Calendar service"""
    with patch('tools.get_calendar_service') as mock_service:
        service = MagicMock()
        mock_service.return_value = service
        yield service


@pytest.fixture
def client():
    """Create FastAPI test client"""
    # Import here to avoid issues with mocking
    from api import app
    return TestClient(app)


@pytest.fixture
def sample_event():
    """Sample event data for testing"""
    return {
        "id": "test_event_123",
        "summary": "Test Meeting",
        "start": {"dateTime": "2025-11-15T10:00:00+08:00", "timeZone": "Asia/Manila"},
        "end": {"dateTime": "2025-11-15T11:00:00+08:00", "timeZone": "Asia/Manila"},
        "location": "Conference Room A",
        "description": "Test meeting description",
        "attendees": [
            {"email": "attendee1@example.com"},
            {"email": "attendee2@example.com"}
        ],
        "htmlLink": "https://calendar.google.com/event?eid=test123"
    }


@pytest.fixture
def sample_calendar():
    """Sample calendar data"""
    return {
        "id": "test_calendar_id",
        "summary": "Test Calendar",
        "primary": False,
        "timeZone": "Asia/Manila"
    }


# ============================================================
# TEST HEALTH & ROOT ENDPOINTS
# ============================================================

def test_health_check(client):
    """Test health check endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "calendar-agent"
    assert "available_tools" in data


def test_root_endpoint(client):
    """Test root endpoint returns tool descriptions"""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "Calendar Agent API"
    assert "available_tools" in data
    assert "list_events" in data["available_tools"]
    assert "create_event" in data["available_tools"]


# ============================================================
# TEST LIST EVENTS
# ============================================================

def test_list_events_success(client, mock_calendar_service, sample_event):
    """Test listing events successfully"""
    # Mock the events list API call
    mock_calendar_service.events().list().execute.return_value = {
        "items": [sample_event]
    }
    
    response = client.post("/execute_task", json={
        "tool": "list_events",
        "inputs": {
            "max_results": 10
        }
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["count"] == 1
    assert len(data["events"]) == 1
    assert data["events"][0]["summary"] == "Test Meeting"
    assert "event_id" in data["events"][0]


def test_list_events_empty(client, mock_calendar_service):
    """Test listing events when calendar is empty"""
    mock_calendar_service.events().list().execute.return_value = {
        "items": []
    }
    
    response = client.post("/execute_task", json={
        "tool": "list_events",
        "inputs": {}
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["count"] == 0
    assert len(data["events"]) == 0


def test_list_events_with_calendar_name(client, mock_calendar_service, sample_event):
    """Test listing events from specific calendar"""
    # Mock calendar search
    mock_calendar_service.calendarList().list().execute.return_value = {
        "items": [{"id": "work_calendar_id", "summary": "Work Calendar"}]
    }
    
    mock_calendar_service.events().list().execute.return_value = {
        "items": [sample_event]
    }
    
    response = client.post("/execute_task", json={
        "tool": "list_events",
        "inputs": {
            "calendar_name": "Work Calendar",
            "max_results": 5
        }
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# ============================================================
# TEST CREATE EVENT
# ============================================================

def test_create_event_success(client, mock_calendar_service, sample_event):
    """Test creating event successfully"""
    mock_calendar_service.events().list().execute.return_value = {
        "items": []  # No conflicts
    }
    mock_calendar_service.events().insert().execute.return_value = sample_event
    
    response = client.post("/execute_task", json={
        "tool": "create_event",
        "inputs": {
            "summary": "Test Meeting",
            "start_time": "2025-11-15 10:00",
            "end_time": "2025-11-15 11:00",
            "attendees": ["attendee1@example.com"],
            "location": "Conference Room A"
        }
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "event_id" in data
    assert data["event_id"] == "test_event_123"
    assert "event_url" in data


def test_create_event_auto_end_time(client, mock_calendar_service, sample_event):
    """Test creating event with auto-calculated end time"""
    mock_calendar_service.events().list().execute.return_value = {"items": []}
    mock_calendar_service.events().insert().execute.return_value = sample_event
    
    response = client.post("/execute_task", json={
        "tool": "create_event",
        "inputs": {
            "summary": "Quick Meeting",
            "start_time": "2025-11-15 10:00"
            # No end_time - should auto-calculate
        }
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "event_id" in data


def test_create_event_with_meet_link(client, mock_calendar_service):
    """Test creating event with Google Meet link"""
    event_with_meet = {
        "id": "test_event_123",
        "summary": "Meeting with Google Meet",
        "start": {"dateTime": "2025-11-15T10:00:00+08:00"},
        "end": {"dateTime": "2025-11-15T11:00:00+08:00"},
        "htmlLink": "https://calendar.google.com/event?eid=test123",
        "conferenceData": {
            "entryPoints": [{"uri": "https://meet.google.com/abc-defg-hij"}]
        }
    }
    
    mock_calendar_service.events().list().execute.return_value = {"items": []}
    mock_calendar_service.events().insert().execute.return_value = event_with_meet
    
    response = client.post("/execute_task", json={
        "tool": "create_event",
        "inputs": {
            "summary": "Meeting with Google Meet",
            "start_time": "2025-11-15 10:00",
            "end_time": "2025-11-15 11:00",
            "add_meet_link": True
        }
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["meet_link"] == "https://meet.google.com/abc-defg-hij"


def test_create_event_missing_summary(client):
    """Test creating event without summary (should fail)"""
    response = client.post("/execute_task", json={
        "tool": "create_event",
        "inputs": {
            "start_time": "2025-11-15 10:00"
        }
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "summary" in data["error"].lower()


def test_create_event_conflict(client, mock_calendar_service, sample_event):
    """Test creating event with scheduling conflict"""
    # Mock conflict detection
    mock_calendar_service.events().list().execute.return_value = {
        "items": [sample_event]  # Existing conflicting event
    }
    
    response = client.post("/execute_task", json={
        "tool": "create_event",
        "inputs": {
            "summary": "New Meeting",
            "start_time": "2025-11-15 10:00",
            "end_time": "2025-11-15 11:00"
        }
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["status"] == "conflict"
    assert "conflict_id" in data
    assert data["conflict_title"] == "Test Meeting"


# ============================================================
# TEST UPDATE EVENT
# ============================================================

def test_update_event_success(client, mock_calendar_service, sample_event):
    """Test updating event successfully"""
    mock_calendar_service.events().get().execute.return_value = sample_event
    
    updated_event = sample_event.copy()
    updated_event["summary"] = "Updated Meeting"
    mock_calendar_service.events().update().execute.return_value = updated_event
    
    response = client.post("/execute_task", json={
        "tool": "update_event",
        "inputs": {
            "event_id": "test_event_123",
            "new_summary": "Updated Meeting",
            "new_location": "New Conference Room"
        }
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["event_id"] == "test_event_123"
    assert len(data["changes"]) > 0


def test_update_event_time(client, mock_calendar_service, sample_event):
    """Test updating event time"""
    mock_calendar_service.events().get().execute.return_value = sample_event
    mock_calendar_service.events().update().execute.return_value = sample_event
    
    response = client.post("/execute_task", json={
        "tool": "update_event",
        "inputs": {
            "event_id": "test_event_123",
            "new_start": "2025-11-15 14:00",
            "new_end": "2025-11-15 15:00"
        }
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "start time" in str(data["changes"])


def test_update_event_missing_id(client):
    """Test updating event without event_id"""
    response = client.post("/execute_task", json={
        "tool": "update_event",
        "inputs": {
            "new_summary": "Updated Meeting"
        }
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "event_id" in data["error"].lower()


# ============================================================
# TEST DELETE EVENT
# ============================================================

def test_delete_event_requires_confirmation(client, mock_calendar_service, sample_event):
    """Test that delete event requires confirmation first"""
    mock_calendar_service.events().get().execute.return_value = sample_event
    
    response = client.post("/execute_task", json={
        "tool": "delete_event",
        "inputs": {
            "event_id": "test_event_123"
        }
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["requires_confirmation"] is True
    assert "confirmation_prompt" in data
    assert data["event_title"] == "Test Meeting"


def test_delete_event_with_confirmation(client, mock_calendar_service, sample_event):
    """Test deleting event with confirmation"""
    mock_calendar_service.events().get().execute.return_value = sample_event
    mock_calendar_service.events().delete().execute.return_value = None
    
    response = client.post("/execute_task", json={
        "tool": "delete_event",
        "inputs": {
            "event_id": "test_event_123",
            "confirmed": True
        }
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["deleted"] is True


def test_confirm_delete_event(client, mock_calendar_service, sample_event):
    """Test confirm_delete_event tool"""
    mock_calendar_service.events().get().execute.return_value = sample_event
    mock_calendar_service.events().delete().execute.return_value = None
    
    response = client.post("/execute_task", json={
        "tool": "confirm_delete_event",
        "inputs": {
            "event_id": "test_event_123"
        }
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["deleted"] is True


# ============================================================
# TEST CALENDAR MANAGEMENT
# ============================================================

def test_list_calendars(client, mock_calendar_service, sample_calendar):
    """Test listing calendars"""
    mock_calendar_service.calendarList().list().execute.return_value = {
        "items": [sample_calendar]
    }
    
    response = client.post("/execute_task", json={
        "tool": "list_calendars",
        "inputs": {}
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


def test_create_calendar(client, mock_calendar_service):
    """Test creating a new calendar"""
    mock_calendar_service.calendars().insert().execute.return_value = {
        "id": "new_calendar_id",
        "summary": "New Work Calendar"
    }
    
    response = client.post("/execute_task", json={
        "tool": "create_calendar",
        "inputs": {
            "calendar_name": "New Work Calendar",
            "description": "Calendar for work events"
        }
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# ============================================================
# TEST ERROR HANDLING
# ============================================================

def test_unknown_tool(client):
    """Test calling unknown tool"""
    response = client.post("/execute_task", json={
        "tool": "nonexistent_tool",
        "inputs": {}
    })
    
    assert response.status_code == 400
    assert "Unknown tool" in response.json()["detail"]


def test_api_error_handling(client, mock_calendar_service):
    """Test handling Google API errors"""
    mock_calendar_service.events().list().execute.side_effect = Exception("API Error")
    
    response = client.post("/execute_task", json={
        "tool": "list_events",
        "inputs": {}
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "error" in data


# ============================================================
# TEST TIME FORMAT PARSING
# ============================================================

@pytest.mark.parametrize("time_input,expected_valid", [
    ("2025-11-15 10:00", True),
    ("2025-11-15 12:00 AM", True),
    ("2025-11-15 2:30 PM", True),
    ("tomorrow at 2pm", True),
    ("today at 10:00", True),
    ("invalid time", False),
])
def test_time_format_parsing(time_input, expected_valid):
    """Test various time format inputs"""
    from tools import format_datetime
    result = format_datetime(time_input)
    if expected_valid:
        assert result is not None
    else:
        assert result is None


# ============================================================
# TEST HELPER FUNCTIONS
# ============================================================

def test_resolve_calendar_id_primary(mock_calendar_service):
    """Test resolving primary calendar"""
    from api import resolve_calendar_id
    result = resolve_calendar_id("primary")
    assert result == "primary"


def test_resolve_calendar_id_by_name(mock_calendar_service):
    """Test resolving calendar by name"""
    mock_calendar_service.calendarList().list().execute.return_value = {
        "items": [{"id": "work_cal_id", "summary": "Work Calendar"}]
    }
    
    from api import resolve_calendar_id
    result = resolve_calendar_id("Work Calendar")
    assert result == "work_cal_id"


def test_auto_calculate_end_time():
    """Test auto-calculating end time"""
    from api import auto_calculate_end_time
    
    start_time = "2025-11-15 10:00"
    end_time = auto_calculate_end_time(start_time, duration_hours=1.0)
    
    assert end_time is not None
    assert "11:00" in end_time  # Should be 1 hour later


# ============================================================
# RUN TESTS
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
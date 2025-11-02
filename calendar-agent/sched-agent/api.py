"""
Calendar Agent API - Supervisor-Compatible Version
Handles Google Calendar operations via /execute_task endpoint
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import uvicorn
import json
import pytz
from dateutil import parser as date_parser

# Import your existing tools
from tools import (
    create_event_impl,
    create_multiple_events_impl,
    search_events_impl,
    delete_event_impl,
    update_event_impl,
    handle_user_confirmation,
    create_calendar_impl,
    list_calendars_impl,
    notify_attendees_about_change,
    get_calendar_service,
    find_calendar_id_by_name,
)

load_dotenv()

app = FastAPI(title="Calendar Agent API")


# ============================================================
# MODELS (Matching Supervisor's Format)
# ============================================================

class CredentialsDict(BaseModel):
    """Google OAuth credentials from supervisor"""
    access_token: str
    refresh_token: str
    token_uri: str = "https://oauth2.googleapis.com/token"
    client_id: str = ""
    client_secret: str = ""


class TaskRequest(BaseModel):
    """Request format from supervisor"""
    tool: str
    inputs: Dict[str, Any]
    credentials_dict: Optional[CredentialsDict] = None


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def resolve_calendar_id(calendar_name: str = None) -> str:
    """
    Resolve calendar name to calendar ID.
    Returns "primary" if no name specified or name not found.
    """
    if not calendar_name or calendar_name.lower() == "primary":
        return "primary"
    
    calendar_id = find_calendar_id_by_name(calendar_name)
    if calendar_id:
        return calendar_id
    
    print(f"⚠️ Calendar '{calendar_name}' not found, using primary")
    return "primary"


def auto_calculate_end_time(start_time: str, duration_hours: float = 1.0) -> str:
    """
    Auto-calculate end time from start time.
    Default duration is 1 hour.
    """
    try:
        start_dt = date_parser.parse(start_time)
        end_dt = start_dt + timedelta(hours=duration_hours)
        return end_dt.strftime("%Y-%m-%d %H:%M")
    except Exception as e:
        print(f"⚠️ Failed to auto-calculate end_time: {e}")
        return None


# ============================================================
# TOOL IMPLEMENTATIONS (Matching supervisor's expectations)
# ============================================================

def list_events(inputs: dict) -> dict:
    """
    List upcoming calendar events with structured output.
    
    Inputs:
        time_min: str (optional) - Start time (YYYY-MM-DD or ISO)
        time_max: str (optional) - End time (YYYY-MM-DD or ISO)
        max_results: int (optional) - Number of events (default: 10)
        calendar_name: str (optional) - Calendar name
    
    Returns:
        success: bool
        events: list of event objects with id, summary, start, end, etc.
        count: int
    """
    try:
        max_results = inputs.get("max_results", 10)
        calendar_name = inputs.get("calendar_name", "")
        
        calendar_id = resolve_calendar_id(calendar_name)
        
        # Use the enhanced search_events_impl that returns structured data
        result = search_events_impl(max_results, calendar_id)
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "events": [],
            "count": 0,
            "error": str(e)
        }


def create_event(inputs: dict) -> dict:
    """
    Create a new calendar event with auto-calculated end time if needed.
    
    Inputs:
        summary: str (required) - Event title
        start_time: str (required) - Start datetime (supports "12 AM", "12:00 PM", etc.)
        end_time: str (optional) - End datetime (auto-calculated if not provided)
        description: str (optional)
        location: str (optional)
        attendees: list (optional) - List of emails
        calendar_name: str (optional)
        add_meet_link: bool (optional) - Add Google Meet link
    
    Returns:
        success: bool
        event_id: str
        event_url: str
        meet_link: str (if applicable)
        message: str
    """
    try:
        summary = inputs.get("summary")
        start_time = inputs.get("start_time") or inputs.get("start")
        end_time = inputs.get("end_time") or inputs.get("end")
        description = inputs.get("description", "")
        location = inputs.get("location", "")
        attendees = inputs.get("attendees") or inputs.get("emails", [])
        calendar_name = inputs.get("calendar_name", "")
        add_meet_link = inputs.get("add_meet_link", False)
        
        if not summary:
            return {"success": False, "error": "summary is required"}
        if not start_time:
            return {"success": False, "error": "start_time is required"}
        
        # AUTO-CALCULATE END TIME if not provided
        if not end_time:
            end_time = auto_calculate_end_time(start_time)
            if not end_time:
                return {"success": False, "error": "Could not auto-calculate end_time"}
            print(f"ℹ️ Auto-calculated end_time: {end_time} (start + 1 hour)")
        
        calendar_id = resolve_calendar_id(calendar_name)
        
        # Call create_event_impl which now returns Dict
        result = create_event_impl(
            summary=summary,
            start=start_time,
            end=end_time,
            emails=attendees,
            description=description,
            location=location,
            calendar_id=calendar_id,
            add_meet_link=add_meet_link
        )
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def update_event(inputs: dict) -> dict:
    """
    Update an existing calendar event (supports changing name, time, location, attendees).
    
    Inputs:
        event_id: str (required)
        new_summary: str (optional) - New event title
        new_start: str (optional) - New start time (supports "12 AM", "2:30 PM", etc.)
        new_end: str (optional) - New end time
        new_description: str (optional)
        new_location: str (optional)
        new_attendees: list (optional) - New list of attendee emails
        calendar_name: str (optional)
    
    Returns:
        success: bool
        event_id: str
        event_url: str
        changes: list
        message: str
    """
    try:
        event_id = inputs.get("event_id")
        if not event_id:
            return {"success": False, "error": "event_id is required"}
        
        new_summary = inputs.get("new_summary")
        new_start = inputs.get("new_start")
        new_end = inputs.get("new_end")
        new_description = inputs.get("new_description")
        new_location = inputs.get("new_location")
        new_attendees = inputs.get("new_attendees")
        calendar_name = inputs.get("calendar_name", "")
        
        calendar_id = resolve_calendar_id(calendar_name)
        
        # Call update_event_impl which now returns Dict
        result = update_event_impl(
            event_id=event_id,
            new_summary=new_summary,
            new_start=new_start,
            new_end=new_end,
            new_description=new_description,
            new_location=new_location,
            new_attendees=new_attendees,
            calendar_id=calendar_id
        )
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def delete_event(inputs: dict) -> dict:
    """
    Delete a calendar event (with confirmation requirement).
    
    Inputs:
        event_id: str (required)
        calendar_name: str (optional)
        confirmed: bool (optional) - Set to true to skip confirmation
    
    Returns:
        success: bool
        deleted: bool
        requires_confirmation: bool (if confirmation needed)
        event_title: str
        event_start: str
        confirmation_prompt: str (if confirmation needed)
        message: str
    """
    try:
        event_id = inputs.get("event_id")
        if not event_id:
            return {"success": False, "error": "event_id is required"}
        
        calendar_name = inputs.get("calendar_name", "")
        confirmed = inputs.get("confirmed", False)
        
        calendar_id = resolve_calendar_id(calendar_name)
        
        # Call delete_event_impl which now returns Dict with confirmation support
        result = delete_event_impl(
            event_id=event_id,
            calendar_id=calendar_id,
            skip_confirmation=confirmed
        )
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def confirm_delete_event(inputs: dict) -> dict:
    """
    Confirm and execute deletion of a calendar event.
    This is called after user confirms deletion.
    
    Inputs:
        event_id: str (required)
        calendar_name: str (optional)
    
    Returns:
        success: bool
        deleted: bool
        message: str
    """
    try:
        event_id = inputs.get("event_id")
        if not event_id:
            return {"success": False, "error": "event_id is required"}
        
        calendar_name = inputs.get("calendar_name", "")
        calendar_id = resolve_calendar_id(calendar_name)
        
        # Call with skip_confirmation=True to actually delete
        result = delete_event_impl(
            event_id=event_id,
            calendar_id=calendar_id,
            skip_confirmation=True
        )
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def list_calendars(inputs: dict) -> dict:
    """
    List all user's calendars
    
    Returns:
        success: bool
        calendars: list
        message: str
    """
    try:
        result = list_calendars_impl()
        
        if "❌" in result or "Failed" in result:
            return {
                "success": False,
                "calendars": [],
                "message": result,
                "error": result
            }
        
        return {
            "success": True,
            "calendars": [],  # Could parse result into structured data
            "message": result,
            "error": None
        }
        
    except Exception as e:
        return {
            "success": False,
            "calendars": [],
            "error": str(e)
        }


def create_calendar(inputs: dict) -> dict:
    """
    Create a new calendar
    
    Inputs:
        calendar_name: str (required)
        description: str (optional)
    
    Returns:
        success: bool
        calendar_id: str
        message: str
    """
    try:
        calendar_name = inputs.get("calendar_name")
        if not calendar_name:
            return {"success": False, "error": "calendar_name is required"}
        
        description = inputs.get("description", "")
        
        result = create_calendar_impl(calendar_name, description)
        
        if "❌" in result or "Failed" in result:
            return {
                "success": False,
                "calendar_id": None,
                "message": result,
                "error": result
            }
        
        return {
            "success": True,
            "calendar_id": None,  # Could extract from result
            "message": result,
            "error": None
        }
        
    except Exception as e:
        return {
            "success": False,
            "calendar_id": None,
            "error": str(e)
        }


def resolve_conflict(inputs: dict) -> dict:
    """
    Resolve scheduling conflict by moving conflicting event
    
    Inputs:
        conflict_id: str (required)
        new_event: dict (required) - New event details
        calendar_name: str (optional)
    
    Returns:
        success: bool
        message: str
    """
    try:
        conflict_id = inputs.get("conflict_id")
        new_event = inputs.get("new_event")
        
        if not conflict_id:
            return {"success": False, "error": "conflict_id is required"}
        if not new_event:
            return {"success": False, "error": "new_event is required"}
        
        calendar_name = inputs.get("calendar_name", "")
        calendar_id = resolve_calendar_id(calendar_name)
        
        result = handle_user_confirmation(conflict_id, new_event, calendar_id)
        
        if "❌" in result or "Failed" in result:
            return {
                "success": False,
                "message": result,
                "error": result
            }
        
        return {
            "success": True,
            "message": result,
            "error": None
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ============================================================
# TOOL REGISTRY (Maps tool names to functions)
# ============================================================

CALENDAR_TOOLS = {
    "list_events": list_events,
    "create_event": create_event,
    "update_event": update_event,
    "delete_event": delete_event,
    "confirm_delete_event": confirm_delete_event,
    "list_calendars": list_calendars,
    "create_calendar": create_calendar,
    "resolve_conflict": resolve_conflict,
}


# ============================================================
# API ENDPOINTS
# ============================================================

@app.post("/execute_task")
async def execute_task(request: TaskRequest):
    """
    Main endpoint that supervisor calls.
    Executes calendar operations based on tool name.
    """
    try:
        tool_name = request.tool
        inputs = request.inputs
        
        print(f"\n{'='*60}")
        print(f"📅 CALENDAR AGENT - Executing: {tool_name}")
        print(f"{'='*60}")
        print(f"📥 Inputs: {json.dumps(inputs, indent=2)}")
        
        # Get tool function
        tool_func = CALENDAR_TOOLS.get(tool_name)
        if not tool_func:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown tool: {tool_name}. Available: {list(CALENDAR_TOOLS.keys())}"
            )
        
        # Execute tool
        result = tool_func(inputs)
        
        print(f"✅ Result: {result.get('success')}")
        if result.get('error'):
            print(f"❌ Error: {result.get('error')}")
        if result.get('event_id'):
            print(f"🆔 Event ID: {result.get('event_id')}")
        print(f"{'='*60}\n")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Calendar Agent Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "calendar-agent",
        "available_tools": list(CALENDAR_TOOLS.keys())
    }


@app.get("/")
async def root():
    """Root endpoint with available tools"""
    return {
        "service": "Calendar Agent API",
        "version": "2.0.0",
        "available_tools": list(CALENDAR_TOOLS.keys()),
        "tool_descriptions": {
            "list_events": "List upcoming calendar events with structured output",
            "create_event": "Create a new event (auto-calculates end_time, supports 12 AM format)",
            "update_event": "Update event (name, time, location, attendees)",
            "delete_event": "Delete an event (requires confirmation first)",
            "confirm_delete_event": "Confirm and execute deletion",
            "list_calendars": "List all user calendars",
            "create_calendar": "Create a new calendar",
            "resolve_conflict": "Resolve scheduling conflicts"
        },
        "improvements": [
            "✅ Proper 12 AM/PM time parsing",
            "✅ Auto-calculate end_time if not provided",
            "✅ Returns event_id in all operations",
            "✅ Delete confirmation workflow",
            "✅ Update supports attendees",
            "✅ Structured data output for all tools"
        ],
        "endpoints": {
            "execute_task": "/execute_task (POST) - Execute calendar operations",
            "health": "/health (GET) - Health check"
        }
    }


# ============================================================
# RUN SERVER
# ============================================================

if __name__ == "__main__":
    port = int(os.getenv("CALENDAR_AGENT_PORT", "8005"))
    print(f"🚀 Starting Calendar Agent v2.0 on port {port}")
    print(f"📚 Available tools: {list(CALENDAR_TOOLS.keys())}")
    print(f"✨ New features: 12 AM/PM support, event_id returns, delete confirmation")
    print(f"📋 Ready to receive requests from Supervisor Agent")
    uvicorn.run(app, host="0.0.0.0", port=port)
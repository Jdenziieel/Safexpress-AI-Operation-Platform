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

from tools import (
    create_event_impl,
    create_multiple_events_impl,
    search_events_impl,
    find_event_by_name,
    delete_event_impl,
    update_event_impl,
    handle_user_confirmation,
    create_calendar_impl,
    rename_calendar_impl,
    list_calendars_impl,
    notify_attendees_about_change,
    get_calendar_service,
    find_calendar_id_by_name,
    _resolve_relative_date,
)

load_dotenv()

app = FastAPI(title="Calendar Agent API")


# ============================================================
# MODELS
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

def sanitize_inputs(inputs: dict) -> dict:
    """
    Clean up inputs from the supervisor before dispatching to tool functions.

    - Strips whitespace from all string values.
    - Drops keys whose string value is empty (so `if not value` checks work
      reliably — supervisors often send {"event_id": ""} instead of omitting
      the key entirely).
    - Normalises common field aliases (e.g. "name" -> "event_name").
    """
    cleaned = {}
    for k, v in inputs.items():
        if isinstance(v, str):
            v = v.strip()
            if v:  # only keep non-empty strings
                cleaned[k] = v
        else:
            cleaned[k] = v

    # Alias: some supervisors send "name" instead of "event_name"
    if "name" in cleaned and "event_name" not in cleaned:
        cleaned["event_name"] = cleaned.pop("name")

    return cleaned


def resolve_calendar_id(calendar_name: str = None,
                         credentials_dict: dict = None) -> str:
    """Resolve calendar name to ID. Returns 'primary' if not found."""
    if not calendar_name or calendar_name.lower() == "primary":
        return "primary"

    calendar_id = find_calendar_id_by_name(calendar_name, credentials_dict)
    if calendar_id:
        return calendar_id

    print(f"Warning: Calendar '{calendar_name}' not found, using primary")
    return "primary"


def auto_calculate_end_time(start_time: str, duration_hours: float = 1.0) -> Optional[str]:
    """
    Auto-calculate end time from start time. Default duration is 1 hour.

    Handles bare time strings like '6 PM' or '14:00' by anchoring them to
    today's date (Asia/Manila) before parsing, so dateutil never falls back
    to the year-1900 default.
    """
    try:
        tz = pytz.timezone("Asia/Manila")
        now = datetime.now(tz)

        resolved = _resolve_relative_date(start_time)
        start_dt = date_parser.parse(resolved)

        # Final safety net: if year is still 1900, anchor to today
        if start_dt.year == 1900:
            start_dt = start_dt.replace(year=now.year, month=now.month, day=now.day)

        end_dt = start_dt + timedelta(hours=duration_hours)
        return end_dt.strftime("%Y-%m-%d %H:%M")
    except Exception as e:
        print(f"Warning: Failed to auto-calculate end_time: {e}")
        return None


def _resolve_event_id(inputs: dict, calendar_id: str,
                      credentials_dict: dict) -> tuple:
    """
    Return (event_id, error_dict_or_None).

    Resolution order:
      1. inputs["event_id"]  - use directly if present and non-empty
      2. inputs["event_name"] / inputs["summary"] - substring search
      3. Neither supplied - fetch upcoming events and return them as a
         helpful prompt so the supervisor/user can pick one.
    """
    event_id = inputs.get("event_id")
    if event_id:
        return event_id, None

    # Try name-based lookup
    event_name = inputs.get("event_name") or inputs.get("summary")
    if event_name:
        lookup = find_event_by_name(event_name, calendar_id, credentials_dict)

        if not lookup["found"]:
            return None, {
                "success": False,
                "error": f"No upcoming event found matching '{event_name}'. Use list_events to verify the name."
            }

        if not lookup["exact"]:
            match_list = "\n".join(
                f"- {e['summary']} on {e['start_formatted']} (ID: {e['event_id']})"
                for e in lookup["matches"]
            )
            return None, {
                "success": False,
                "requires_event_id": True,
                "matches": lookup["matches"],
                "error": (
                    f"Multiple events match '{event_name}'. "
                    f"Please re-send with the correct event_id:\n{match_list}"
                )
            }

        resolved_id = lookup["matches"][0]["event_id"]
        print(f"Info: Resolved '{event_name}' -> event_id: {resolved_id}")
        return resolved_id, None

    # Nothing supplied at all - list upcoming events so supervisor can choose
    print("Warning: No event_id or event_name provided - fetching upcoming events for reference")
    upcoming = search_events_impl(max_results=10, calendar_id=calendar_id,
                                  credentials_dict=credentials_dict)
    events = upcoming.get("events", [])

    if not events:
        return None, {
            "success": False,
            "error": "No event_id or event_name provided, and no upcoming events were found."
        }

    event_list = "\n".join(
        f"- {e['summary']} on {e['start_formatted']} (ID: {e['event_id']})"
        for e in events
    )
    return None, {
        "success": False,
        "requires_event_id": True,
        "upcoming_events": events,
        "error": (
            "No event_id or event_name was provided. "
            "Here are your upcoming events - re-send the request with the correct "
            "event_id or event_name:\n" + event_list
        )
    }


# ============================================================
# TOOL IMPLEMENTATIONS
# ============================================================

def list_events(inputs: dict, credentials_dict: dict = None) -> dict:
    try:
        max_results = inputs.get("max_results", 10)
        calendar_name = inputs.get("calendar_name", "")
        time_min = inputs.get("time_min")
        time_max = inputs.get("time_max")
        calendar_id = resolve_calendar_id(calendar_name, credentials_dict)
        return search_events_impl(
            max_results, calendar_id, credentials_dict,
            time_min=time_min, time_max=time_max,
        )
    except Exception as e:
        return {"success": False, "events": [], "count": 0, "error": str(e)}


def create_event(inputs: dict, credentials_dict: dict = None) -> dict:
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

        # Auto-calculate end time when it is not provided
        if not end_time:
            end_time = auto_calculate_end_time(start_time)
            if not end_time:
                return {"success": False, "error": "Could not auto-calculate end_time from the given start_time"}
            print(f"Info: Auto-calculated end_time: {end_time} (start + 1 hour)")

        calendar_id = resolve_calendar_id(calendar_name, credentials_dict)

        return create_event_impl(
            summary=summary,
            start=start_time,
            end=end_time,
            emails=attendees,
            description=description,
            location=location,
            calendar_id=calendar_id,
            add_meet_link=add_meet_link,
            credentials_dict=credentials_dict,
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_event(inputs: dict, credentials_dict: dict = None) -> dict:
    try:
        calendar_id = resolve_calendar_id(inputs.get("calendar_name", ""), credentials_dict)

        event_id, err = _resolve_event_id(inputs, calendar_id, credentials_dict)
        if err:
            return err

        # Bare-name aliases for the `new_*` mutation args. The canonical args
        # use a `new_` prefix to distinguish from create_event's read-side
        # names, but the planner sometimes borrows create_event's naming
        # (especially when the user says "update the description" and the
        # word "description" flows straight into inputs). Without these
        # aliases the unknown keys are silently dropped and the event
        # updates with zero changes — a silent failure that looks successful
        # (see execution_logs/CM/DEMO8.3.log). Canonical `new_*` names still
        # win when both are present.
        def _pick(*keys):
            for k in keys:
                v = inputs.get(k)
                if v is None:
                    continue
                if isinstance(v, (str, list, dict, tuple)) and not v:
                    continue
                return v
            return None

        return update_event_impl(
            event_id=event_id,
            new_summary=_pick("new_summary", "summary"),
            new_start=_pick("new_start", "start_time", "start"),
            new_end=_pick("new_end", "end_time", "end"),
            new_description=_pick("new_description", "description"),
            new_location=_pick("new_location", "location"),
            new_attendees=_pick("new_attendees", "attendees", "emails"),
            calendar_id=calendar_id,
            credentials_dict=credentials_dict,
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_event(inputs: dict, credentials_dict: dict = None) -> dict:
    """
    Delete an event.

    Accepts any of:
      - event_id   - used directly
      - event_name / summary - auto-resolved via name search
      - neither    - returns the upcoming event list so the caller can pick one

    Requires user confirmation unless inputs["confirmed"] == True.
    """
    try:
        calendar_id = resolve_calendar_id(inputs.get("calendar_name", ""), credentials_dict)

        event_id, err = _resolve_event_id(inputs, calendar_id, credentials_dict)
        if err:
            return err

        return delete_event_impl(
            event_id=event_id,
            calendar_id=calendar_id,
            skip_confirmation=inputs.get("confirmed", False),
            credentials_dict=credentials_dict,
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def confirm_delete_event(inputs: dict, credentials_dict: dict = None) -> dict:
    """
    Confirm and execute a previously requested deletion.
    Accepts event_id directly, or resolves by event_name/summary.
    """
    try:
        calendar_id = resolve_calendar_id(inputs.get("calendar_name", ""), credentials_dict)

        event_id, err = _resolve_event_id(inputs, calendar_id, credentials_dict)
        if err:
            return err

        return delete_event_impl(
            event_id=event_id,
            calendar_id=calendar_id,
            skip_confirmation=True,
            credentials_dict=credentials_dict,
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_calendars(inputs: dict, credentials_dict: dict = None) -> dict:
    try:
        return list_calendars_impl(credentials_dict)
    except Exception as e:
        return {"success": False, "calendars": [], "error": str(e)}


def create_calendar(inputs: dict, credentials_dict: dict = None) -> dict:
    try:
        calendar_name = inputs.get("calendar_name")
        if not calendar_name:
            return {"success": False, "error": "calendar_name is required"}

        return create_calendar_impl(
            calendar_name,
            inputs.get("description", ""),
            credentials_dict,
        )
    except Exception as e:
        return {"success": False, "calendar_id": None, "error": str(e)}


def rename_calendar(inputs: dict, credentials_dict: dict = None) -> dict:
    """Rename an existing Google Calendar."""
    try:
        calendar_name = inputs.get("calendar_name")
        new_calendar_name = inputs.get("new_calendar_name")

        if not calendar_name:
            return {"success": False, "error": "calendar_name (current name) is required"}
        if not new_calendar_name:
            return {"success": False, "error": "new_calendar_name is required"}

        calendar_id = find_calendar_id_by_name(calendar_name, credentials_dict)
        if not calendar_id:
            return {
                "success": False,
                "error": f"Calendar '{calendar_name}' not found. Use list_calendars to see available calendars."
            }

        return rename_calendar_impl(calendar_id, new_calendar_name, credentials_dict)
    except Exception as e:
        return {"success": False, "error": str(e)}


def resolve_conflict(inputs: dict, credentials_dict: dict = None) -> dict:
    try:
        conflict_id = inputs.get("conflict_id")
        new_event = inputs.get("new_event")

        if not conflict_id:
            return {"success": False, "error": "conflict_id is required"}
        if not new_event:
            return {"success": False, "error": "new_event is required"}

        calendar_id = resolve_calendar_id(inputs.get("calendar_name", ""), credentials_dict)

        return handle_user_confirmation(
            conflict_id, new_event, calendar_id, credentials_dict
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# TOOL REGISTRY
# ============================================================

CALENDAR_TOOLS = {
    "list_events": list_events,
    "create_event": create_event,
    "update_event": update_event,
    "delete_event": delete_event,
    "confirm_delete_event": confirm_delete_event,
    "list_calendars": list_calendars,
    "create_calendar": create_calendar,
    "rename_calendar": rename_calendar,
    "resolve_conflict": resolve_conflict,
}


# ============================================================
# API ENDPOINTS
# ============================================================

@app.post("/execute_task")
async def execute_task(request: TaskRequest):
    """Main endpoint that supervisor calls."""
    try:
        tool_name = request.tool
        # Sanitize BEFORE dispatch - strips empty strings like {"event_id": ""}
        # so downstream `if not value` checks work correctly.
        inputs = sanitize_inputs(request.inputs)

        print(f"\n{'='*60}")
        print(f"CALENDAR AGENT - Executing: {tool_name}")
        print(f"{'='*60}")
        print(f"Inputs (sanitized): {json.dumps(inputs, indent=2)}")

        tool_func = CALENDAR_TOOLS.get(tool_name)
        if not tool_func:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown tool: {tool_name}. Available: {list(CALENDAR_TOOLS.keys())}"
            )

        creds = request.credentials_dict.dict() if request.credentials_dict else None
        result = tool_func(inputs, credentials_dict=creds)

        print(f"Result success: {result.get('success')}")
        if result.get('error'):
            print(f"Error: {result.get('error')}")
        if result.get('event_id'):
            print(f"Event ID: {result.get('event_id')}")

        print(f"\nComplete Result:")
        print(json.dumps(result, indent=2, default=str))
        print(f"{'='*60}\n")

        return result

    except HTTPException:
        raise
    except Exception as e:
        print(f"Calendar Agent Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "calendar-agent",
        "available_tools": list(CALENDAR_TOOLS.keys())
    }


@app.get("/")
async def root():
    return {
        "service": "Calendar Agent API",
        "version": "2.3.0",
        "available_tools": list(CALENDAR_TOOLS.keys()),
        "tool_descriptions": {
            "list_events": "List upcoming calendar events with structured output",
            "create_event": "Create a new event (auto-calculates end_time if omitted; handles bare times like '6 PM')",
            "update_event": "Update event by event_id, event_name, or summary (title, time, location, attendees)",
            "delete_event": "Delete an event by event_id, event_name, or summary - auto-lists events if neither given",
            "confirm_delete_event": "Confirm and execute deletion by event_id or event_name",
            "list_calendars": "List all user calendars",
            "create_calendar": "Create a new calendar",
            "resolve_conflict": "Resolve scheduling conflicts"
        },
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
    print(f"Starting Calendar Agent v2.3 on port {port}")
    print(f"Available tools: {list(CALENDAR_TOOLS.keys())}")
    print(f"Ready to receive requests from Supervisor Agent")
    uvicorn.run(app, host="0.0.0.0", port=port)
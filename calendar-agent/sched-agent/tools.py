'''# tools.py - Google Calendar Agent Tools with SUPERVISOR-COMPATIBLE OUTPUT'''
import os
from typing import List, Optional, Dict, Union
from pydantic import BaseModel
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from dateutil import parser
from datetime import datetime, timedelta
import pytz
import json

# Load environment variables
load_dotenv()
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")

# OAuth 2.0 scopes
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.events'
]

class CalendarInput(BaseModel):
    summary: str
    start: str
    end: str
    emails: List[str]

def get_calendar_service():
    """Authenticate using OAuth 2.0 and return Calendar service."""
    creds = None
    credentials_path = 'key/credentials.json'
    token_path = 'key/token.json'
    
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        
        os.makedirs('key', exist_ok=True)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
    
    return build('calendar', 'v3', credentials=creds)

def find_calendar_id_by_name(calendar_name: str) -> Optional[str]:
    """Find a calendar ID by name (case-insensitive)."""
    if not calendar_name:
        return None
    
    service = get_calendar_service()
    
    try:
        calendar_list = service.calendarList().list().execute()
        calendars = calendar_list.get('items', [])
        search_name = calendar_name.lower().strip()
        
        for cal in calendars:
            cal_summary = cal.get('summary', '').lower().strip()
            if search_name in cal_summary or cal_summary in search_name:
                return cal.get('id')
        return None
    except Exception as e:
        print(f"❌ Failed to search calendars: {str(e)}")
        return None

def format_datetime(dt_str: str) -> Optional[str]:
    """Format datetime string to RFC3339 with Asia/Manila timezone"""
    try:
        if not dt_str:
            raise ValueError("Empty datetime string")
        tz = pytz.timezone("Asia/Manila")
        now = datetime.now(tz)

        # Handle relative dates
        dt_str_lower = dt_str.lower()
        if "tomorrow" in dt_str_lower:
            tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
            dt_str = dt_str_lower.replace("tomorrow", tomorrow)
        elif "today" in dt_str_lower:
            dt_str = dt_str_lower.replace("today", now.strftime("%Y-%m-%d"))

        dt = parser.parse(dt_str)
        dt = dt if dt.tzinfo else tz.localize(dt)
        dt = dt.astimezone(tz)
        return dt.isoformat(timespec="seconds")
    except Exception as e:
        print(f"⚠️ Error formatting datetime '{dt_str}': {str(e)}")
        return None

def check_conflicts(start: str, end: str, calendar_id: str = None) -> List[Dict]:
    """Check for conflicting events"""
    service = get_calendar_service()
    formatted_start = format_datetime(start)
    formatted_end = format_datetime(end)
    cal_id = calendar_id or CALENDAR_ID

    if not formatted_start or not formatted_end:
        return []

    try:
        events_result = service.events().list(
            calendarId=cal_id,
            timeMin=formatted_start,
            timeMax=formatted_end,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        return events_result.get("items", [])
    except Exception as e:
        print(f"❌ Failed to check conflicts: {str(e)}")
        return []

# ============================================================
# SUPERVISOR-COMPATIBLE IMPLEMENTATIONS (Return Dict, not str)
# ============================================================

def create_event_impl(summary: str, start: str, end: str, emails: List[str],
                      description: str = "", location: str = "",
                      calendar_id: str = None, add_meet_link: bool = False) -> Dict:
    """
    Create event - RETURNS DICT for supervisor compatibility
    """
    service = get_calendar_service()
    cal_id = calendar_id or CALENDAR_ID
    formatted_start = format_datetime(start)
    formatted_end = format_datetime(end)

    if not formatted_start or not formatted_end:
        return {
            "success": False,
            "event_id": None,
            "event_url": None,
            "message": "Invalid datetime format",
            "error": "Invalid datetime format. Please provide valid date and time."
        }

    # Check conflicts
    conflicts = check_conflicts(start, end, cal_id)
    if conflicts:
        conflict = conflicts[0]
        return {
            "success": False,
            "status": "conflict",
            "conflict_id": conflict.get("id"),
            "conflict_title": conflict.get("summary", "No Title"),
            "message": f"⚠️ Scheduling conflict detected with '{conflict.get('summary')}'",
            "error": "Scheduling conflict detected",
            "new_event": {
                "summary": summary,
                "start": start,
                "end": end,
                "emails": emails,
                "description": description,
                "location": location,
                "calendar_id": cal_id
            }
        }

    attendees_list = [{"email": e} for e in emails if isinstance(e, str) and "@" in e]
    
    event = {
        "summary": summary or "Untitled Event",
        "start": {"dateTime": formatted_start, "timeZone": "Asia/Manila"},
        "end": {"dateTime": formatted_end, "timeZone": "Asia/Manila"},
    }
    
    if description:
        event["description"] = description
    elif attendees_list:
        event["description"] = f"Meeting with: {', '.join([a['email'] for a in attendees_list])}"
    
    if location:
        event["location"] = location
    
    if attendees_list:
        event["attendees"] = attendees_list
    
    # Add Google Meet link if requested
    if add_meet_link:
        event["conferenceData"] = {
            "createRequest": {
                "requestId": f"meet_{datetime.now().timestamp()}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"}
            }
        }

    try:
        created = service.events().insert(
            calendarId=cal_id, 
            body=event,
            conferenceDataVersion=1 if add_meet_link else 0,
            sendUpdates='all'
        ).execute()
        
        event_id = created.get("id")
        event_url = created.get("htmlLink", "")
        meet_link = created.get("conferenceData", {}).get("entryPoints", [{}])[0].get("uri") if add_meet_link else None
        
        message_parts = [f"✅ Successfully created event '{summary}' from {start} to {end}"]
        if emails:
            message_parts.append(f"📧 Invitations sent to: {', '.join(emails)}")
        if location:
            message_parts.append(f"📍 Location: {location}")
        if meet_link:
            message_parts.append(f"🎥 Google Meet: {meet_link}")
        message_parts.append(f"🔗 View event: {event_url}")
        
        return {
            "success": True,
            "event_id": event_id,
            "event_url": event_url,
            "meet_link": meet_link,
            "message": "\n".join(message_parts),
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "event_id": None,
            "event_url": None,
            "message": f"Failed to create event: {str(e)}",
            "error": str(e)
        }


def search_events_impl(max_results: int = 5, calendar_id: str = None) -> Dict:
    """
    Search events - RETURNS DICT with structured event data
    """
    service = get_calendar_service()
    cal_id = calendar_id or CALENDAR_ID
    now = datetime.now(pytz.timezone("Asia/Manila")).isoformat()
    
    try:
        events_result = service.events().list(
            calendarId=cal_id,
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        events = events_result.get("items", [])
        
        if not events:
            return {
                "success": True,
                "events": [],
                "count": 0,
                "message": "📅 No upcoming events found.",
                "error": None
            }
        
        # Structure event data for supervisor
        structured_events = []
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            try:
                parsed_start = parser.parse(start)
                formatted_start = parsed_start.strftime("%B %d, %Y at %I:%M %p")
            except:
                formatted_start = start
            
            structured_events.append({
                "event_id": event.get('id'),
                "summary": event.get('summary', 'No Title'),
                "start": start,
                "start_formatted": formatted_start,
                "end": event["end"].get("dateTime", event["end"].get("date")),
                "location": event.get("location", ""),
                "attendees": [att.get("email") for att in event.get("attendees", [])],
                "attendee_count": len(event.get("attendees", []))
            })
        
        # Also create human-readable message
        output = ["📅 Upcoming events:\n"]
        for i, evt in enumerate(structured_events, 1):
            attendee_info = f" 👥 ({evt['attendee_count']} attendees)" if evt['attendee_count'] > 0 else ""
            location_info = f"\n   📍 {evt['location']}" if evt['location'] else ""
            output.append(f"{i}. {evt['summary']} - {evt['start_formatted']}{attendee_info}{location_info}\n   🆔 ID: {evt['event_id']}")
        
        return {
            "success": True,
            "events": structured_events,
            "count": len(structured_events),
            "message": "\n".join(output),
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "events": [],
            "count": 0,
            "message": f"Failed to fetch events: {str(e)}",
            "error": str(e)
        }


def update_event_impl(event_id: str, new_summary: Optional[str] = None,
                      new_start: Optional[str] = None, new_end: Optional[str] = None,
                      new_description: Optional[str] = None, new_location: Optional[str] = None,
                      new_attendees: Optional[List[str]] = None,
                      calendar_id: str = None) -> Dict:
    """
    Update event - RETURNS DICT for supervisor compatibility
    """
    service = get_calendar_service()
    cal_id = calendar_id or CALENDAR_ID
    
    try:
        event = service.events().get(calendarId=cal_id, eventId=event_id).execute()
        old_summary = event.get("summary", "Untitled Event")
        changes = []

        if new_summary:
            event["summary"] = new_summary
            changes.append(f"title to '{new_summary}'")
        if new_start:
            formatted_start = format_datetime(new_start)
            if formatted_start:
                event["start"]["dateTime"] = formatted_start
                changes.append(f"start time to {new_start}")
        if new_end:
            formatted_end = format_datetime(new_end)
            if formatted_end:
                event["end"]["dateTime"] = formatted_end
                changes.append(f"end time to {new_end}")
        if new_description:
            event["description"] = new_description
            changes.append("description")
        if new_location:
            event["location"] = new_location
            changes.append(f"location to '{new_location}'")
        if new_attendees:
            event["attendees"] = [{"email": e} for e in new_attendees if "@" in e]
            changes.append(f"attendees to {', '.join(new_attendees)}")

        updated = service.events().update(
            calendarId=cal_id, 
            eventId=event_id, 
            body=event,
            sendUpdates='all'
        ).execute()
        
        changes_str = ", ".join(changes) if changes else "no changes"
        event_url = updated.get("htmlLink", "")
        has_attendees = event.get("attendees", [])
        notify_msg = " 📧 (attendees notified)" if has_attendees else ""
        
        return {
            "success": True,
            "event_id": event_id,
            "event_url": event_url,
            "changes": changes,
            "message": f"✏️ Successfully updated '{old_summary}': {changes_str}{notify_msg}\n🔗 View event: {event_url}",
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "event_id": event_id,
            "message": f"Failed to update event: {str(e)}",
            "error": str(e)
        }


def delete_event_impl(event_id: str, calendar_id: str = None, skip_confirmation: bool = False) -> Dict:
    """
    Delete event - RETURNS DICT with confirmation workflow support
    """
    service = get_calendar_service()
    cal_id = calendar_id or CALENDAR_ID
    
    try:
        # Get event details first
        event = service.events().get(calendarId=cal_id, eventId=event_id).execute()
        event_title = event.get("summary", "Untitled Event")
        event_start = event["start"].get("dateTime", event["start"].get("date"))
        has_attendees = event.get("attendees", [])
        
        # If not confirmed, return confirmation prompt
        if not skip_confirmation:
            return {
                "success": False,
                "deleted": False,
                "requires_confirmation": True,
                "event_id": event_id,
                "event_title": event_title,
                "event_start": event_start,
                "attendee_count": len(has_attendees),
                "confirmation_prompt": f"⚠️ Are you sure you want to delete '{event_title}' on {event_start}? This will send cancellation emails to {len(has_attendees)} attendees." if has_attendees else f"⚠️ Are you sure you want to delete '{event_title}' on {event_start}?",
                "message": "Confirmation required before deletion",
                "error": None
            }
        
        # Confirmed - proceed with deletion
        service.events().delete(
            calendarId=cal_id, 
            eventId=event_id,
            sendUpdates='all'
        ).execute()
        
        notify_msg = f" 📧 (cancellation emails sent to {len(has_attendees)} attendees)" if has_attendees else ""
        
        return {
            "success": True,
            "deleted": True,
            "event_id": event_id,
            "message": f"🗑️ Successfully deleted event '{event_title}'{notify_msg}",
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "deleted": False,
            "event_id": event_id,
            "message": f"Failed to delete event: {str(e)}",
            "error": str(e)
        }


def list_calendars_impl() -> Dict:
    """List all calendars - RETURNS DICT"""
    service = get_calendar_service()
    
    try:
        calendar_list = service.calendarList().list().execute()
        calendars = calendar_list.get('items', [])
        
        if not calendars:
            return {
                "success": True,
                "calendars": [],
                "message": "📅 No calendars found.",
                "error": None
            }
        
        structured_calendars = []
        output = ["📅 Your Calendars:\n"]
        
        for i, cal in enumerate(calendars, 1):
            cal_name = cal.get('summary', 'Untitled Calendar')
            cal_id = cal.get('id')
            is_primary = cal.get('primary', False)
            
            structured_calendars.append({
                "id": cal_id,
                "name": cal_name,
                "primary": is_primary
            })
            
            primary_marker = " ⭐ (Primary)" if is_primary else ""
            output.append(f"{i}. {cal_name}{primary_marker}\n   📋 ID: {cal_id}")
        
        return {
            "success": True,
            "calendars": structured_calendars,
            "message": "\n".join(output),
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "calendars": [],
            "message": f"Failed to list calendars: {str(e)}",
            "error": str(e)
        }


def create_calendar_impl(calendar_name: str, description: str = "") -> Dict:
    """Create calendar - RETURNS DICT"""
    service = get_calendar_service()
    
    calendar = {
        'summary': calendar_name,
        'description': description,
        'timeZone': 'Asia/Manila'
    }
    
    try:
        created = service.calendars().insert(body=calendar).execute()
        calendar_id = created['id']
        
        return {
            "success": True,
            "calendar_id": calendar_id,
            "message": f"✅ Successfully created calendar '{calendar_name}'\n📋 Calendar ID: {calendar_id}\n💡 You can now schedule events on this calendar by specifying its name!",
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "calendar_id": None,
            "message": f"Failed to create calendar: {str(e)}",
            "error": str(e)
        }


def handle_user_confirmation(conflict_id: str, new_event: dict, calendar_id: str = None) -> Dict:
    """
    Resolve conflict by moving event and creating new one - RETURNS DICT
    """
    cal_id = new_event.get("calendar_id") or calendar_id or CALENDAR_ID
    
    if isinstance(new_event, str):
        try:
            new_event = json.loads(new_event)
        except:
            return {"success": False, "message": "Invalid event data format", "error": "Invalid JSON"}
    
    # Move conflicting event
    service = get_calendar_service()
    try:
        event = service.events().get(calendarId=cal_id, eventId=conflict_id).execute()
        tz = pytz.timezone("Asia/Manila")
        start = parser.parse(event["start"]["dateTime"])
        end = parser.parse(event["end"]["dateTime"])
        new_start = start + timedelta(hours=1)
        new_end = end + timedelta(hours=1)
        
        event["start"]["dateTime"] = new_start.astimezone(tz).isoformat(timespec="seconds")
        event["end"]["dateTime"] = new_end.astimezone(tz).isoformat(timespec="seconds")
        
        service.events().update(calendarId=cal_id, eventId=conflict_id, body=event, sendUpdates='all').execute()
        move_msg = f"✅ Moved '{event.get('summary')}' to {new_start.strftime('%B %d, %Y at %I:%M %p')}"
    except Exception as e:
        return {"success": False, "message": f"Failed to move conflicting event: {str(e)}", "error": str(e)}
    
    # Create new event
    create_result = create_event_impl(
        summary=new_event.get("summary", "Untitled Event"),
        start=new_event.get("start", ""),
        end=new_event.get("end", ""),
        emails=new_event.get("emails", []),
        description=new_event.get("description", ""),
        location=new_event.get("location", ""),
        calendar_id=cal_id,
        add_meet_link=new_event.get("add_meet_link", False)
    )
    
    if not create_result.get("success"):
        return {
            "success": False,
            "message": f"{move_msg}\n\n⚠️ But failed to create new event: {create_result.get('error')}",
            "error": create_result.get("error")
        }
    
    return {
        "success": True,
        "message": f"{move_msg}\n\n{create_result.get('message')}",
        "event_id": create_result.get("event_id"),
        "error": None
    }


def notify_attendees_about_change(event_id: str, change_message: str, calendar_id: str = None) -> Dict:
    """Notify attendees - RETURNS DICT"""
    service = get_calendar_service()
    cal_id = calendar_id or CALENDAR_ID
    
    try:
        event = service.events().get(calendarId=cal_id, eventId=event_id).execute()
        attendees = event.get("attendees", [])
        
        if not attendees:
            return {
                "success": False,
                "message": "No attendees to notify",
                "error": "No attendees found"
            }
        
        current_desc = event.get("description", "")
        timestamp = datetime.now(pytz.timezone('Asia/Manila')).strftime('%B %d, %Y at %I:%M %p')
        updated_desc = f"{current_desc}\n\n---\n📢 Update ({timestamp}):\n{change_message}"
        event["description"] = updated_desc
        
        service.events().update(calendarId=cal_id, eventId=event_id, body=event, sendUpdates='all').execute()
        
        attendee_emails = [att.get('email') for att in attendees]
        return {
            "success": True,
            "message": f"✅ Notification sent to {len(attendees)} attendees: {', '.join(attendee_emails)}",
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to send notifications: {str(e)}",
            "error": str(e)
        }


def create_multiple_events_impl(events_data: List[Dict]) -> Dict:
    """Create multiple events - RETURNS DICT"""
    if len(events_data) > 5:
        return {
            "success": False,
            "created_count": 0,
            "failed_count": 0,
            "message": "Maximum 5 events can be created at once",
            "error": "Too many events"
        }
    
    results = []
    successful = 0
    failed = 0
    
    for i, event_data in enumerate(events_data, 1):
        result = create_event_impl(**event_data)
        results.append(result)
        if result.get("success"):
            successful += 1
        else:
            failed += 1
    
    return {
        "success": failed == 0,
        "created_count": successful,
        "failed_count": failed,
        "results": results,
        "message": f"Created {successful}/{len(events_data)} events successfully",
        "error": None if failed == 0 else f"{failed} events failed"
    }
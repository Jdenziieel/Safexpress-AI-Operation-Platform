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

# OAuth 2.0 scopes - enhanced for calendar management
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.events'
]

# Input schema for LangChain tool
class CalendarInput(BaseModel):
    summary: str
    start: str
    end: str
    emails: List[str]

# Setup Google Calendar service with OAuth
def get_calendar_service():
    """
    Authenticate using OAuth 2.0 and return Calendar service.
    This allows sending invitations and managing calendars on behalf of a user.
    """
    creds = None
    
    # Define paths for credentials and token
    credentials_path = 'key/credentials.json'
    token_path = 'key/token.json'
    
    # Token file stores the user's access and refresh tokens
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    # If there are no (valid) credentials available, let the user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        os.makedirs('key', exist_ok=True)  # Create key folder if it doesn't exist
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
    
    return build('calendar', 'v3', credentials=creds)

# NEW: Find calendar by name
def find_calendar_id_by_name(calendar_name: str) -> Optional[str]:
    """
    Find a calendar ID by name (case-insensitive).
    Returns calendar ID or None if not found.
    """
    if not calendar_name:
        return None
    
    service = get_calendar_service()
    
    try:
        calendar_list = service.calendarList().list().execute()
        calendars = calendar_list.get('items', [])
        
        search_name = calendar_name.lower().strip()
        
        for cal in calendars:
            cal_summary = cal.get('summary', '').lower().strip()
            # Match if search term is in calendar name or vice versa
            if search_name in cal_summary or cal_summary in search_name:
                return cal.get('id')
        
        return None
    except Exception as e:
        print(f"❌ Failed to search calendars: {str(e)}")
        return None

# Format datetime string to RFC3339 with Asia/Manila timezone
def format_datetime(dt_str: str) -> Optional[str]:
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

# Summarize conflict for agent response
def summarize_conflict(event: Dict) -> str:
    title = event.get("summary", "No Title")
    start_dt = event["start"].get("dateTime", event["start"].get("date"))
    
    # Parse and format the datetime for better readability
    try:
        parsed_start = parser.parse(start_dt)
        formatted_time = parsed_start.strftime("%B %d, %Y at %I:%M %p")
    except:
        formatted_time = start_dt
    
    return f"'{title}' scheduled for {formatted_time}"

# Check for conflicting events
def check_conflicts(start: str, end: str, calendar_id: str = None) -> List[Dict]:
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

# Move conflicting event later
def move_event_later(event_id: str, minutes: int = 60, calendar_id: str = None) -> str:
    service = get_calendar_service()
    cal_id = calendar_id or CALENDAR_ID
    try:
        event = service.events().get(calendarId=cal_id, eventId=event_id).execute()
        tz = pytz.timezone("Asia/Manila")

        start = parser.parse(event["start"]["dateTime"])
        end = parser.parse(event["end"]["dateTime"])
        new_start = start + timedelta(minutes=minutes)
        new_end = end + timedelta(minutes=minutes)

        event["start"]["dateTime"] = new_start.astimezone(tz).isoformat(timespec="seconds")
        event["end"]["dateTime"] = new_end.astimezone(tz).isoformat(timespec="seconds")

        # sendUpdates='all' notifies attendees about the time change
        updated = service.events().update(
            calendarId=cal_id, 
            eventId=event_id, 
            body=event,
            sendUpdates='all'
        ).execute()
        
        has_attendees = event.get("attendees", [])
        notify_msg = " (attendees notified)" if has_attendees else ""
        return f"✅ Moved '{event.get('summary', 'event')}' to {new_start.strftime('%B %d, %Y at %I:%M %p')}{notify_msg}"
    except Exception as e:
        return f"❌ Failed to move event: {str(e)}"

# Create event with conflict handling (ENHANCED VERSION)
def create_event_impl(summary: str, start: str, end: str, emails: List[str],
                      description: str = "", location: str = "",
                      calendar_id: str = None) -> Union[str, Dict]:
    service = get_calendar_service()
    cal_id = calendar_id or CALENDAR_ID
    formatted_start = format_datetime(start)
    formatted_end = format_datetime(end)

    if not formatted_start or not formatted_end:
        return "❌ Invalid datetime format. Please provide valid date and time."

    conflicts = check_conflicts(start, end, cal_id)
    if conflicts:
        conflict = conflicts[0]
        conflict_summary = summarize_conflict(conflict)
        
        # Return structured conflict data as JSON string for the agent to parse
        conflict_data = {
            "status": "conflict",
            "message": f"⚠️ Scheduling conflict detected: {conflict_summary}",
            "conflict_id": conflict.get("id"),
            "conflict_title": conflict.get("summary", "No Title"),
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
        return json.dumps(conflict_data)

    attendees_list = [{"email": e} for e in emails if isinstance(e, str) and "@" in e]
    
    event = {
        "summary": summary or "Untitled Event",
        "start": {"dateTime": formatted_start, "timeZone": "Asia/Manila"},
        "end": {"dateTime": formatted_end, "timeZone": "Asia/Manila"},
    }
    
    # Add optional fields
    if description:
        event["description"] = description
    elif attendees_list:
        event["description"] = f"Meeting with: {', '.join([a['email'] for a in attendees_list])}"
    
    if location:
        event["location"] = location
    
    # Add attendees if provided
    if attendees_list:
        event["attendees"] = attendees_list

    try:
        # sendUpdates='all' will send email invitations to all attendees
        created = service.events().insert(
            calendarId=cal_id, 
            body=event,
            sendUpdates='all'  # This sends email invitations!
        ).execute()
        event_link = created.get("htmlLink", "")
        attendee_msg = f"\n📧 Invitations sent to: {', '.join(emails)}" if emails else ""
        location_msg = f"\n📍 Location: {location}" if location else ""
        
        # Get calendar name for confirmation
        calendar_name = ""
        if cal_id != "primary":
            try:
                cal_info = service.calendars().get(calendarId=cal_id).execute()
                calendar_name = f"\n📅 Calendar: {cal_info.get('summary', '')}"
            except:
                pass
        
        return f"✅ Successfully created event '{summary}' from {start} to {end}{attendee_msg}{location_msg}{calendar_name}\nView event: {event_link}"
    except Exception as e:
        return f"❌ Failed to create event: {str(e)}"

# NEW: Create multiple events (batch scheduling)
def create_multiple_events_impl(events_data: List[Dict]) -> str:
    """
    Creates multiple events at once (up to 5).
    events_data should be a list of dicts with keys: summary, start, end, emails, description, location, calendar_id
    """
    if len(events_data) > 5:
        return "❌ Maximum 5 events can be created at once. Please reduce the number of events."
    
    if not events_data:
        return "❌ No events provided."
    
    results = []
    successful = 0
    failed = 0
    conflicts = []
    
    for i, event_data in enumerate(events_data, 1):
        summary = event_data.get("summary", f"Event {i}")
        start = event_data.get("start", "")
        end = event_data.get("end", "")
        emails = event_data.get("emails", [])
        description = event_data.get("description", "")
        location = event_data.get("location", "")
        calendar_id = event_data.get("calendar_id")
        
        result = create_event_impl(summary, start, end, emails, description, location, calendar_id)
        
        if isinstance(result, str) and '"status": "conflict"' in result:
            conflicts.append(f"Event {i} ({summary}): Conflict detected")
            failed += 1
        elif isinstance(result, str) and "✅" in result:
            results.append(f"Event {i}: {result}")
            successful += 1
        else:
            results.append(f"Event {i}: {result}")
            failed += 1
    
    summary_msg = f"\n\n📊 Summary: {successful} successful, {failed} failed"
    if conflicts:
        summary_msg += f"\n⚠️ Conflicts:\n" + "\n".join(conflicts)
    
    return "\n\n".join(results) + summary_msg

# Handle user confirmation to move and retry (ENHANCED VERSION)
def handle_user_confirmation(conflict_id: str, new_event: dict, calendar_id: str = None) -> str:
    """
    Moves the conflicting event and creates the new event.
    new_event should be a dict with keys: summary, start, end, emails, description, location
    """
    cal_id = new_event.get("calendar_id") or calendar_id or CALENDAR_ID
    
    # Parse new_event if it's a JSON string
    if isinstance(new_event, str):
        try:
            new_event = json.loads(new_event)
        except:
            return "❌ Invalid event data format"
    
    move_result = move_event_later(conflict_id, calendar_id=cal_id)
    print(f"📋 {move_result}")

    # Now create the new event
    result = create_event_impl(
        summary=new_event.get("summary", "Untitled Event"),
        start=new_event.get("start", ""),
        end=new_event.get("end", ""),
        emails=new_event.get("emails", []),
        description=new_event.get("description", ""),
        location=new_event.get("location", ""),
        calendar_id=cal_id
    )
    
    # Check if the new event also has a conflict (recursive conflict)
    if isinstance(result, str) and '"status": "conflict"' in result:
        return f"{move_result}\n\n⚠️ The new time slot also has a conflict. Please try a different time."
    
    return f"{move_result}\n\n{result}"

# NEW: Create a new calendar
def create_calendar_impl(calendar_name: str, description: str = "", timezone: str = "Asia/Manila") -> str:
    """Creates a new Google Calendar."""
    service = get_calendar_service()
    
    calendar = {
        'summary': calendar_name,
        'description': description,
        'timeZone': timezone
    }
    
    try:
        created_calendar = service.calendars().insert(body=calendar).execute()
        calendar_id = created_calendar['id']
        return f"✅ Successfully created calendar '{calendar_name}'\n📋 Calendar ID: {calendar_id}\n💡 You can now schedule events on this calendar by specifying its name!"
    except Exception as e:
        return f"❌ Failed to create calendar: {str(e)}"

# NEW: List all calendars
def list_calendars_impl() -> str:
    """Lists all calendars accessible to the user."""
    service = get_calendar_service()
    
    try:
        calendar_list = service.calendarList().list().execute()
        calendars = calendar_list.get('items', [])
        
        if not calendars:
            return "📅 No calendars found."
        
        output = ["📅 Your Calendars:\n"]
        for i, cal in enumerate(calendars, 1):
            cal_name = cal.get('summary', 'Untitled Calendar')
            cal_id = cal.get('id')
            is_primary = " ⭐ (Primary)" if cal.get('primary', False) else ""
            output.append(f"{i}. {cal_name}{is_primary}\n   📋 ID: {cal_id}")
        
        return "\n".join(output)
    except Exception as e:
        return f"❌ Failed to list calendars: {str(e)}"

# NEW: Send email notification about event changes
def notify_attendees_about_change(event_id: str, change_message: str, calendar_id: str = None) -> str:
    """
    Sends email notifications to all attendees about changes to an event.
    This updates the event description and notifies attendees via Google Calendar API.
    """
    service = get_calendar_service()
    cal_id = calendar_id or CALENDAR_ID
    
    try:
        # Get event details
        event = service.events().get(calendarId=cal_id, eventId=event_id).execute()
        attendees = event.get("attendees", [])
        
        if not attendees:
            return "⚠️ No attendees to notify for this event."
        
        # Update event description with change notification
        current_desc = event.get("description", "")
        timestamp = datetime.now(pytz.timezone('Asia/Manila')).strftime('%B %d, %Y at %I:%M %p')
        updated_desc = f"{current_desc}\n\n---\n📢 Update ({timestamp}):\n{change_message}"
        event["description"] = updated_desc
        
        # Update with notification
        service.events().update(
            calendarId=cal_id,
            eventId=event_id,
            body=event,
            sendUpdates='all'
        ).execute()
        
        attendee_emails = [att.get('email') for att in attendees]
        return f"✅ Notification sent to {len(attendees)} attendees: {', '.join(attendee_emails)}\n📧 Message: {change_message}"
    except Exception as e:
        return f"❌ Failed to send notifications: {str(e)}"

# Search upcoming events (ENHANCED VERSION)
def search_events_impl(max_results: int = 5, calendar_id: str = None) -> str:
    service = get_calendar_service()
    cal_id = calendar_id or CALENDAR_ID
    now = datetime.now(pytz.timezone("Asia/Manila")).isoformat()
    
    try:
        # Get calendar name for display
        calendar_name = ""
        if cal_id != "primary":
            try:
                cal_info = service.calendars().get(calendarId=cal_id).execute()
                calendar_name = f" from '{cal_info.get('summary', 'Unknown Calendar')}'"
            except:
                pass
        
        events_result = service.events().list(
            calendarId=cal_id,
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        events = events_result.get("items", [])
        if not events:
            return f"📅 No upcoming events found{calendar_name}."
        output = [f"📅 Upcoming events{calendar_name}:\n"]
        for i, event in enumerate(events, 1):
            start = event["start"].get("dateTime", event["start"].get("date"))
            try:
                parsed_start = parser.parse(start)
                formatted_start = parsed_start.strftime("%B %d, %Y at %I:%M %p")
            except:
                formatted_start = start
            
            attendees = event.get("attendees", [])
            attendee_info = f" 👥 ({len(attendees)} attendees)" if attendees else ""
            location = event.get("location", "")
            location_info = f"\n   📍 {location}" if location else ""
            
            output.append(f"{i}. {event.get('summary', 'No Title')} - {formatted_start}{attendee_info}{location_info}\n   🆔 ID: {event['id']}")
        return "\n".join(output)
    except Exception as e:
        return f"❌ Failed to fetch events: {str(e)}"

# Delete event by ID (ENHANCED VERSION)
def delete_event_impl(event_id: str, calendar_id: str = None) -> str:
    service = get_calendar_service()
    cal_id = calendar_id or CALENDAR_ID
    try:
        # Get event details before deletion for confirmation message
        event = service.events().get(calendarId=cal_id, eventId=event_id).execute()
        event_title = event.get("summary", "Untitled Event")
        has_attendees = event.get("attendees", [])
        
        # sendUpdates='all' sends cancellation emails to attendees
        service.events().delete(
            calendarId=cal_id, 
            eventId=event_id,
            sendUpdates='all'
        ).execute()
        
        notify_msg = " 📧 (cancellation emails sent to attendees)" if has_attendees else ""
        return f"🗑️ Successfully deleted event '{event_title}' (ID: {event_id}){notify_msg}"
    except Exception as e:
        return f"❌ Failed to delete event '{event_id}': {str(e)}"

# Update event (ENHANCED VERSION)
def update_event_impl(event_id: str, new_summary: Optional[str] = None,
                      new_start: Optional[str] = None, new_end: Optional[str] = None,
                      new_description: Optional[str] = None, new_location: Optional[str] = None,
                      calendar_id: str = None) -> str:
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

        # sendUpdates='all' notifies attendees about the changes
        updated = service.events().update(
            calendarId=cal_id, 
            eventId=event_id, 
            body=event,
            sendUpdates='all'
        ).execute()
        
        changes_str = ", ".join(changes) if changes else "no changes"
        event_link = updated.get("htmlLink", "")
        has_attendees = event.get("attendees", [])
        notify_msg = " 📧 (attendees notified)" if has_attendees else ""
        return f"✏️ Successfully updated '{old_summary}': {changes_str}{notify_msg}\n🔗 View event: {event_link}"
    except Exception as e:
        return f"❌ Failed to update event '{event_id}': {str(e)}"
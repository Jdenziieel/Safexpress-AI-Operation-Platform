import os
import json
from datetime import datetime
import pytz
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
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
)
from dateutil import parser as date_parser

# Load environment variables
load_dotenv()

# Parser model
llm_parser = ChatOpenAI(
    model="gpt-4",
    temperature=0,
    openai_api_key=os.getenv("OPENAI_API_KEY")
)

def parse_calendar_prompt(natural_prompt: str) -> dict:
    """Uses GPT to extract structured calendar data from a natural prompt."""
    now = datetime.now(pytz.timezone("Asia/Manila")).strftime("%Y-%m-%d")
    prompt = (
        f"Today's date is {now}. Extract scheduling details from this message. "
        "Return ONLY a valid JSON object with these keys: summary, start, end, emails, description, location. "
        "Use ISO 8601 format for start and end. Assume future dates (2025 or later). "
        "If no time is given, default to 10:00 AM - 11:00 AM. "
        "Example: {\"summary\": \"Meeting\", \"start\": \"2025-10-14T10:00:00\", "
        "\"end\": \"2025-10-14T11:00:00\", \"emails\": [\"test@example.com\"], "
        "\"description\": \"Quarterly review meeting\", \"location\": \"Conference Room A\"}"
    )
    response = llm_parser.invoke(f"{prompt}\n\nMessage: {natural_prompt}")
    try:
        return json.loads(response.content)
    except Exception as e:
        print(f"⚠️ Failed to parse prompt: {e}")
        return {
            "summary": "Untitled Event",
            "start": "",
            "end": "",
            "emails": [],
            "description": "",
            "location": ""
        }

def parse_multiple_events_prompt(natural_prompt: str) -> list:
    """Uses GPT to extract multiple event details from a natural prompt."""
    now = datetime.now(pytz.timezone("Asia/Manila")).strftime("%Y-%m-%d")
    prompt = (
        f"Today's date is {now}. Extract multiple event scheduling details from this message. "
        "Return ONLY a valid JSON array of event objects (max 5 events). "
        "Each event should have: summary, start, end, emails, description, location. "
        "Use ISO 8601 format for dates. Assume future dates (2025 or later). "
        "If no time given, default to 10:00 AM - 11:00 AM. "
        "Example: [{\"summary\": \"Meeting 1\", \"start\": \"2025-10-14T10:00:00\", "
        "\"end\": \"2025-10-14T11:00:00\", \"emails\": [\"test@example.com\"], "
        "\"description\": \"First meeting\", \"location\": \"Room A\"}]"
    )
    response = llm_parser.invoke(f"{prompt}\n\nMessage: {natural_prompt}")
    try:
        events = json.loads(response.content)
        if isinstance(events, list):
            return events[:5]  # Limit to 5 events
        return [events]  # If single object, wrap in list
    except Exception as e:
        print(f"⚠️ Failed to parse multiple events: {e}")
        return []

def find_calendar_by_name(calendar_name: str) -> dict:
    """
    Find a calendar by name (case-insensitive).
    Returns calendar object with id and summary, or None if not found.
    """
    service = get_calendar_service()
    
    try:
        calendar_list = service.calendarList().list().execute()
        calendars = calendar_list.get('items', [])
        
        search_name = calendar_name.lower().strip()
        
        for cal in calendars:
            cal_summary = cal.get('summary', '').lower().strip()
            if search_name in cal_summary or cal_summary in search_name:
                return {
                    'id': cal.get('id'),
                    'summary': cal.get('summary'),
                    'primary': cal.get('primary', False)
                }
        
        return None
    except Exception as e:
        print(f"❌ Failed to search calendars: {str(e)}")
        return None

def search_event_by_description(search_query: str, max_results: int = 10, calendar_id: str = None) -> list:
    """
    Search for events by title/summary keywords.
    Returns list of matching events with their IDs.
    """
    service = get_calendar_service()
    cal_id = calendar_id or os.getenv("GOOGLE_CALENDAR_ID", "primary")
    now = datetime.now(pytz.timezone("Asia/Manila")).isoformat()
    
    try:
        # Get upcoming events
        events_result = service.events().list(
            calendarId=cal_id,
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        events = events_result.get("items", [])
        
        if not events:
            return []
        
        # Filter events by search query (case-insensitive)
        search_terms = search_query.lower().split()
        matching_events = []
        
        for event in events:
            event_summary = event.get("summary", "").lower()
            event_description = event.get("description", "").lower()
            
            # Check if any search term matches the event title or description
            if any(term in event_summary or term in event_description for term in search_terms):
                matching_events.append(event)
        
        return matching_events
    except Exception as e:
        print(f"❌ Failed to search events: {str(e)}")
        return []

def create_calendar_agent():
    llm = ChatOpenAI(
        model="gpt-4",
        temperature=0,
        openai_api_key=os.getenv("OPENAI_API_KEY")
    )

    @tool
    def create_calendar_event(summary: str, start: str, end: str, emails: list[str], 
                              description: str = "", location: str = "", 
                              calendar_name: str = "") -> str:
        """
        Creates a Google Calendar event with title, time, attendees, description, and location.
        calendar_name: Name of the calendar (e.g., 'Work', 'Personal', 'Team Calendar'). 
                      Leave empty to ask user which calendar to use.
        """
        calendar_id = None
        
        # If no calendar specified, return a prompt to ask user
        if not calendar_name:
            calendars_list = list_calendars_impl()
            return f"📋 Please specify which calendar to use:\n\n{calendars_list}\n\n❓ Which calendar would you like to use for '{summary}'?"
        
        if calendar_name:
            cal = find_calendar_by_name(calendar_name)
            if cal:
                calendar_id = cal['id']
            else:
                return f"❌ Calendar '{calendar_name}' not found. Use list_all_calendars to see available calendars."
        
        result = create_event_impl(summary, start, end, emails, description, location, calendar_id)
        if isinstance(result, dict):
            return json.dumps(result)
        return str(result)

    @tool
    def create_multiple_events(events_json: str) -> str:
        """
        Creates up to 5 calendar events at once. 
        events_json should be a JSON array of event objects with keys: 
        summary, start, end, emails, description, location, calendar_id (optional)
        """
        try:
            events = json.loads(events_json)
            return create_multiple_events_impl(events)
        except json.JSONDecodeError:
            return "❌ Invalid JSON format for events"

    @tool
    def confirm_and_reschedule(conflict_id: str, new_event_json: str, calendar_id: str = "") -> str:
        """Moves the conflicting event 1 hour later and creates the new event."""
        try:
            new_event = json.loads(new_event_json) if isinstance(new_event_json, str) else new_event_json
            return handle_user_confirmation(conflict_id, new_event, calendar_id if calendar_id else None)
        except:
            return "❌ Invalid event data format"

    @tool
    def search_calendar_events(max_results: int = 5, calendar_name: str = "") -> str:
        """
        Lists upcoming events from a specific calendar or the primary calendar.
        calendar_name: Name of the calendar (e.g., 'Work', 'Personal'). 
                      Leave empty to ask user which calendar to search.
        """
        calendar_id = None
        
        # If no calendar specified, return a prompt to ask user
        if not calendar_name:
            calendars_list = list_calendars_impl()
            return f"📋 Please specify which calendar to search:\n\n{calendars_list}\n\n❓ Which calendar would you like to search?"
        
        if calendar_name:
            cal = find_calendar_by_name(calendar_name)
            if cal:
                calendar_id = cal['id']
            else:
                return f"❌ Calendar '{calendar_name}' not found. Use list_all_calendars to see available calendars."
        
        return search_events_impl(max_results, calendar_id)

    @tool
    def find_event_by_name(event_name: str, calendar_name: str = "") -> str:
        """
        Searches for events by name/title. Returns matching events with their IDs.
        Use this to find events before updating or deleting them.
        calendar_name: Name of the calendar to search in. 
                      Leave empty to ask user which calendar to search.
        Example: "team meeting", "project review", "lunch with client"
        """
        calendar_id = None
        
        # If no calendar specified, return a prompt to ask user
        if not calendar_name:
            calendars_list = list_calendars_impl()
            return f"📋 Please specify which calendar to search for '{event_name}':\n\n{calendars_list}\n\n❓ Which calendar should I search?"
        
        if calendar_name:
            cal = find_calendar_by_name(calendar_name)
            if cal:
                calendar_id = cal['id']
            else:
                return f"❌ Calendar '{calendar_name}' not found. Use list_all_calendars to see available calendars."
        
        events = search_event_by_description(event_name, calendar_id=calendar_id)
        
        if not events:
            return f"❌ No events found matching '{event_name}'"
        
        output = [f"📅 Found {len(events)} matching event(s):\n"]
        for i, event in enumerate(events, 1):
            start = event["start"].get("dateTime", event["start"].get("date"))
            try:
                parsed_start = date_parser.parse(start)
                formatted_start = parsed_start.strftime("%B %d, %Y at %I:%M %p")
            except:
                formatted_start = start
            
            attendees = event.get("attendees", [])
            attendee_info = f" 👥 ({len(attendees)} attendees)" if attendees else ""
            location = event.get("location", "")
            location_info = f"\n   📍 {location}" if location else ""
            
            output.append(
                f"{i}. {event.get('summary', 'No Title')} - {formatted_start}{attendee_info}{location_info}\n"
                f"   🆔 ID: {event['id']}"
            )
        
        return "\n".join(output)

    @tool
    def delete_calendar_event(event_id: str, calendar_name: str = "") -> str:
        """
        Deletes an event and sends cancellation emails to attendees.
        calendar_name: Name of the calendar. Leave empty for primary.
        """
        calendar_id = None
        if calendar_name:
            cal = find_calendar_by_name(calendar_name)
            if cal:
                calendar_id = cal['id']
            else:
                return f"❌ Calendar '{calendar_name}' not found. Use list_all_calendars to see available calendars."
        
        return delete_event_impl(event_id, calendar_id)

    @tool
    def update_calendar_event(event_id: str, new_summary: str = "", new_start: str = "", 
                             new_end: str = "", new_description: str = "", 
                             new_location: str = "", calendar_name: str = "") -> str:
        """
        Updates an event's details and notifies attendees of changes.
        calendar_name: Name of the calendar. Leave empty for primary.
        """
        calendar_id = None
        if calendar_name:
            cal = find_calendar_by_name(calendar_name)
            if cal:
                calendar_id = cal['id']
            else:
                return f"❌ Calendar '{calendar_name}' not found. Use list_all_calendars to see available calendars."
        
        return update_event_impl(event_id, new_summary, new_start, new_end, 
                                new_description, new_location, calendar_id)

    @tool
    def create_new_calendar(calendar_name: str, description: str = "") -> str:
        """Creates a new Google Calendar that can be used for organizing events."""
        return create_calendar_impl(calendar_name, description)

    @tool
    def list_all_calendars() -> str:
        """Lists all calendars accessible to the user with their IDs."""
        return list_calendars_impl()

    @tool
    def find_calendar_by_name_tool(calendar_name: str) -> str:
        """
        Find a calendar by name. Returns calendar details including ID.
        Useful when user mentions a calendar by name.
        Example: 'Work Calendar', 'Personal', 'Team Events'
        """
        cal = find_calendar_by_name(calendar_name)
        if cal:
            primary_tag = " ⭐ (Primary)" if cal.get('primary') else ""
            return f"✅ Found calendar: {cal['summary']}{primary_tag}\n📋 ID: {cal['id']}"
        return f"❌ Calendar '{calendar_name}' not found. Use list_all_calendars to see available calendars."

    @tool
    def notify_attendees(event_id: str, change_message: str, calendar_name: str = "") -> str:
        """
        Sends email notifications to attendees about changes to an event.
        calendar_name: Name of the calendar. Leave empty for primary.
        """
        calendar_id = None
        if calendar_name:
            cal = find_calendar_by_name(calendar_name)
            if cal:
                calendar_id = cal['id']
            else:
                return f"❌ Calendar '{calendar_name}' not found. Use list_all_calendars to see available calendars."
        
        return notify_attendees_about_change(event_id, change_message, calendar_id)

    tools = [
        create_calendar_event,
        create_multiple_events,
        confirm_and_reschedule,
        search_calendar_events,
        find_event_by_name,
        delete_calendar_event,
        update_calendar_event,
        create_new_calendar,
        list_all_calendars,
        find_calendar_by_name_tool,
        notify_attendees,
    ]

    return create_react_agent(model=llm, tools=tools)

def main():
    print("=" * 60)
    print("📅 ENHANCED GOOGLE CALENDAR AGENT")
    print("=" * 60)

    required_vars = ["OPENAI_API_KEY"]
    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        print("Missing required environment variables:")
        for var in missing:
            print(f" - {var}")
        return
    
    if not os.path.exists("key/credentials.json"):
        print("⚠️ Missing 'credentials.json' file!")
        print("Please download OAuth 2.0 credentials from Google Cloud Console")
        print("and save it as 'key/credentials.json' in the project directory.")
        return

    try:
        agent = create_calendar_agent()
        print("✅ Agent initialized successfully!\n")

        print("AVAILABLE FEATURES")
        print("=" * 60)
        print("1. Schedule a single meeting/appointment")
        print("2. Schedule multiple events (up to 5 at once)")
        print("3. Search upcoming events")
        print("4. Delete an event (by name)")
        print("5. Update an event (by name)")
        print("6. Create a new calendar")
        print("7. List all your calendars")
        print("8. Send custom notification to attendees")
        print("=" * 60)

        choice = input("\nEnter your choice (1-8): ").strip()

        if choice == "1":
            prompt = input("Describe your event (e.g., 'Schedule meeting with john@email.com tomorrow 2PM-3PM at Conference Room A'): ").strip()
            parsed = parse_calendar_prompt(prompt)
            test_message = (
                f"Schedule an event titled '{parsed['summary']}' from {parsed['start']} to {parsed['end']} "
                f"{'with ' + ', '.join(parsed['emails']) if parsed['emails'] else 'with no attendees'}"
            )
            if parsed.get('description'):
                test_message += f". Description: {parsed['description']}"
            if parsed.get('location'):
                test_message += f". Location: {parsed['location']}"

        elif choice == "2":
            prompt = input("Describe multiple events (e.g., 'Schedule team meetings: Monday 10AM with alice@email.com, Tuesday 2PM with bob@email.com'): ").strip()
            parsed_events = parse_multiple_events_prompt(prompt)
            if not parsed_events:
                print("❌ Could not parse events from prompt")
                return
            test_message = f"Create {len(parsed_events)} events: {json.dumps(parsed_events)}"

        elif choice == "3":
            prompt = input("How many events to show? (default 5): ").strip()
            max_results = int(prompt) if prompt.isdigit() else 5
            calendar_id = input("Calendar ID (press Enter for primary): ").strip()
            test_message = f"Show me {max_results} upcoming events" + (f" from calendar {calendar_id}" if calendar_id else "")

        elif choice == "4":
            event_name = input("Enter event name to delete (e.g., 'team meeting', 'project review'): ").strip()
            test_message = f"Delete the event named '{event_name}'"

        elif choice == "5":
            event_name = input("Enter event name to update (e.g., 'team meeting', 'project review'): ").strip()
            updates = input("What to update? (e.g., 'Change time to 3PM and location to Room B'): ").strip()
            test_message = f"Update the event named '{event_name}': {updates}"

        elif choice == "6":
            calendar_name = input("New calendar name: ").strip()
            description = input("Calendar description (optional): ").strip()
            test_message = f"Create a new calendar named '{calendar_name}'" + (f" with description '{description}'" if description else "")

        elif choice == "7":
            test_message = "List all my calendars"

        elif choice == "8":
            event_name = input("Enter event name: ").strip()
            message = input("Custom notification message: ").strip()
            test_message = f"Send notification to attendees of '{event_name}' with message: {message}"

        else:
            print("❌ Invalid choice.")
            return

        system_prompt = """
        You are the Calendar scheduling agent for SafexpressOps.
        Your job is to manage Google Calendar events efficiently.

        Available Tools:
        - create_calendar_event: Schedule events with optional calendar_name parameter
        - create_multiple_events: Batch schedule up to 5 events at once
        - confirm_and_reschedule: Resolve scheduling conflicts by moving conflicting events
        - search_calendar_events: List upcoming events with optional calendar_name parameter
        - find_event_by_name: Search for events by name (use before update/delete)
        - delete_calendar_event: Remove events with optional calendar_name parameter
        - update_calendar_event: Modify event details with optional calendar_name parameter
        - create_new_calendar: Create a new calendar for organizing events
        - list_all_calendars: Show all available calendars with their IDs
        - find_calendar_by_name_tool: Find calendar details by name
        - notify_attendees: Send custom notifications with optional calendar_name parameter

        CALENDAR NAME SUPPORT:
        - Users can now specify calendars by name instead of ID
        - Examples: "Schedule meeting in Work Calendar", "Add to Personal calendar"
        - If calendar name is mentioned, use the calendar_name parameter (NOT calendar_id)
        - The system automatically converts calendar names to IDs
        - If calendar not found, suggest using list_all_calendars
        
        CALENDAR SELECTION WORKFLOW:
        - If user doesn't specify a calendar when creating/searching/updating/deleting events:
          1. FIRST call list_all_calendars to show available options
          2. Ask user "Which calendar would you like to use?" with the list
          3. Wait for user response before proceeding
        - If user says "default" or "primary", use the primary calendar without asking
        - If only ONE calendar exists (just primary), use it without asking
        - This ensures users always know which calendar they're working with

        CRITICAL WORKFLOW FOR UPDATE/DELETE OPERATIONS:
        1. When user wants to UPDATE or DELETE an event by name:
           - FIRST call find_event_by_name with the event name (and calendar_name if specified)
           - If multiple events match, show them and ask which one to modify
           - If one event matches, proceed with update_calendar_event or delete_calendar_event using the event ID
           - NEVER ask the user for an event ID manually
        
        2. Example: "Delete team meeting from Work Calendar":
           Step 1: Call find_event_by_name("team meeting", calendar_name="Work Calendar")
           Step 2: If 1 match found, call delete_calendar_event(event_id, calendar_name="Work Calendar")
           Step 3: Confirm deletion with attendee notification

        3. Example: "Schedule sprint planning in Team Calendar with john@email.com tomorrow 2PM":
           Step 1: Call create_calendar_event with calendar_name="Team Calendar"
           Step 2: Confirm creation with attendee notification

        OTHER IMPORTANT GUIDELINES:
        1. CONFLICT HANDLING: When create_calendar_event returns a conflict:
           - Inform user about the conflicting event
           - Ask if they want to move the conflicting event 1 hour later
           - If yes, call confirm_and_reschedule with conflict_id and new_event details
           - If no, ask for an alternative time

        2. BATCH SCHEDULING: For multiple events (up to 5):
           - Use create_multiple_events with JSON array of events
           - Each event needs: summary, start, end, emails, description, location
           - Report success/failure for each event

        3. EMAIL NOTIFICATIONS:
           - All create/update/delete operations automatically notify attendees
           - Use notify_attendees for custom messages about changes
           - Always confirm when emails are sent

        4. CALENDAR MANAGEMENT:
           - Users can create their own calendars for better organization
           - Accept both calendar names and IDs (prefer names for better UX)
           - Default to "primary" if no calendar specified

        5. ATTENDEE MANAGEMENT:
           - Always include email addresses for invitations
           - Validate email formats before creating events
           - Confirm attendee list in your response

        Always provide clear confirmation messages with event links when available.
        Be conversational and helpful - the goal is to make calendar management effortless.
        """

        # Initialize conversation history
        conversation_history = [("system", system_prompt), ("user", test_message)]
        
        # Main conversation loop
        while True:
            result = agent.invoke({"messages": conversation_history})
            messages = result.get("messages", [])
            response_text = messages[-1].content if messages else str(result)

            print("\n" + "=" * 60)
            print("AGENT RESPONSE:")
            print("=" * 60)
            print(f"\n{response_text}\n")

            # Check if the response indicates a conflict or asks a question
            is_question = any(keyword in response_text.lower() for keyword in [
                "would you like", "do you want", "should i", "conflict", 
                "reschedule", "⚠️", "?", "detected", "which", "which one"
            ])

            # Check if it's a successful completion
            is_success = any(keyword in response_text.lower() for keyword in [
                "successfully created", "✅", "event created", "deleted successfully", 
                "updated successfully", "upcoming events:", "moved", "calendar created",
                "your calendars:", "notification sent", "successfully deleted", "successfully updated"
            ]) and not any(word in response_text.lower() for word in ["conflict", "failed", "error"])

            if is_success and not is_question:
                # Task completed successfully
                break

            if is_question:
                # Get user's follow-up response
                follow_up = input("\nYour response: ").strip()
                
                if not follow_up:
                    print("\n❌ No response provided. Exiting.")
                    break
                
                # Check if user wants to cancel
                if any(word in follow_up.lower() for word in ["no", "cancel", "nevermind", "stop", "don't"]):
                    conversation_history.append(("assistant", response_text))
                    conversation_history.append(("user", follow_up))
                    print("\n❌ Operation cancelled by user.")
                    break
                
                # Add assistant's response and user's follow-up to conversation history
                conversation_history.append(("assistant", response_text))
                conversation_history.append(("user", follow_up))
                
                # Continue the loop to process the follow-up
            else:
                # No question asked and not successful - might be an error
                break

        print("\n" + "=" * 60)
        print("✅ Session completed!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
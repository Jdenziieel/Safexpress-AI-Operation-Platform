import os
import json
from datetime import datetime
from typing import Optional, List
import pytz
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
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

# Initialize FastAPI app
app = FastAPI(
    title="SafexpressOps Calendar Agent API",
    description="AI-powered Google Calendar management API with natural language processing",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models for request/response
class EventCreate(BaseModel):
    summary: str = Field(..., description="Event title/summary")
    start: str = Field(..., description="Start datetime (ISO 8601 or natural language)")
    end: str = Field(..., description="End datetime (ISO 8601 or natural language)")
    emails: List[str] = Field(default=[], description="List of attendee email addresses")
    description: Optional[str] = Field("", description="Event description")
    location: Optional[str] = Field("", description="Event location")
    calendar_name: Optional[str] = Field("", description="Calendar name (e.g., 'Work', 'Personal')")

class MultipleEventsCreate(BaseModel):
    events: List[EventCreate] = Field(..., max_items=5, description="List of events (max 5)")

class EventUpdate(BaseModel):
    event_id: str = Field(..., description="Event ID to update")
    new_summary: Optional[str] = Field(None, description="New event title")
    new_start: Optional[str] = Field(None, description="New start datetime")
    new_end: Optional[str] = Field(None, description="New end datetime")
    new_description: Optional[str] = Field(None, description="New description")
    new_location: Optional[str] = Field(None, description="New location")
    calendar_name: Optional[str] = Field("", description="Calendar name")

class EventDelete(BaseModel):
    event_id: str = Field(..., description="Event ID to delete")
    calendar_name: Optional[str] = Field("", description="Calendar name")

class EventSearch(BaseModel):
    event_name: str = Field(..., description="Event name/keywords to search")
    calendar_name: Optional[str] = Field("", description="Calendar name to search in")

class CalendarCreate(BaseModel):
    calendar_name: str = Field(..., description="New calendar name")
    description: Optional[str] = Field("", description="Calendar description")

class NotifyAttendees(BaseModel):
    event_id: str = Field(..., description="Event ID")
    message: str = Field(..., description="Notification message")
    calendar_name: Optional[str] = Field("", description="Calendar name")

class NaturalLanguageRequest(BaseModel):
    prompt: str = Field(..., description="Natural language request (e.g., 'Schedule meeting with john@email.com tomorrow 2PM')")

class ConflictResolution(BaseModel):
    conflict_id: str = Field(..., description="Conflicting event ID")
    new_event: EventCreate = Field(..., description="New event details")

class AgentConversation(BaseModel):
    message: str = Field(..., description="Message to the agent")
    conversation_history: Optional[List[dict]] = Field(default=[], description="Previous conversation context")

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
        raise HTTPException(status_code=400, detail=f"Failed to parse prompt: {str(e)}")

def find_calendar_by_name(calendar_name: str) -> dict:
    """Find a calendar by name (case-insensitive)."""
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
        raise HTTPException(status_code=500, detail=f"Failed to search calendars: {str(e)}")

def search_event_by_description(search_query: str, max_results: int = 10, calendar_id: str = None) -> list:
    """Search for events by title/summary keywords."""
    service = get_calendar_service()
    cal_id = calendar_id or os.getenv("GOOGLE_CALENDAR_ID", "primary")
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
            return []
        
        search_terms = search_query.lower().split()
        matching_events = []
        
        for event in events:
            event_summary = event.get("summary", "").lower()
            event_description = event.get("description", "").lower()
            
            if any(term in event_summary or term in event_description for term in search_terms):
                matching_events.append(event)
        
        return matching_events
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search events: {str(e)}")

def create_calendar_agent():
    """Create the LangGraph calendar agent with all tools."""
    llm = ChatOpenAI(
        model="gpt-4",
        temperature=0,
        openai_api_key=os.getenv("OPENAI_API_KEY")
    )

    @tool
    def create_calendar_event(summary: str, start: str, end: str, emails: list[str], 
                              description: str = "", location: str = "", 
                              calendar_name: str = "") -> str:
        """Creates a Google Calendar event."""
        calendar_id = None
        if calendar_name:
            cal = find_calendar_by_name(calendar_name)
            if cal:
                calendar_id = cal['id']
        
        result = create_event_impl(summary, start, end, emails, description, location, calendar_id)
        if isinstance(result, dict):
            return json.dumps(result)
        return str(result)

    @tool
    def search_calendar_events(max_results: int = 5, calendar_name: str = "") -> str:
        """Lists upcoming events from a specific calendar."""
        calendar_id = None
        if calendar_name:
            cal = find_calendar_by_name(calendar_name)
            if cal:
                calendar_id = cal['id']
        
        return search_events_impl(max_results, calendar_id)

    @tool
    def find_event_by_name(event_name: str, calendar_name: str = "") -> str:
        """Searches for events by name/title."""
        calendar_id = None
        if calendar_name:
            cal = find_calendar_by_name(calendar_name)
            if cal:
                calendar_id = cal['id']
        
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
            
            output.append(f"{i}. {event.get('summary', 'No Title')} - {formatted_start}\n   🆔 ID: {event['id']}")
        
        return "\n".join(output)

    @tool
    def delete_calendar_event(event_id: str, calendar_name: str = "") -> str:
        """Deletes an event."""
        calendar_id = None
        if calendar_name:
            cal = find_calendar_by_name(calendar_name)
            if cal:
                calendar_id = cal['id']
        
        return delete_event_impl(event_id, calendar_id)

    @tool
    def update_calendar_event(event_id: str, new_summary: str = "", new_start: str = "", 
                             new_end: str = "", new_description: str = "", 
                             new_location: str = "", calendar_name: str = "") -> str:
        """Updates an event's details."""
        calendar_id = None
        if calendar_name:
            cal = find_calendar_by_name(calendar_name)
            if cal:
                calendar_id = cal['id']
        
        return update_event_impl(event_id, new_summary, new_start, new_end, 
                                new_description, new_location, calendar_id)

    @tool
    def list_all_calendars() -> str:
        """Lists all calendars."""
        return list_calendars_impl()

    tools = [
        create_calendar_event,
        search_calendar_events,
        find_event_by_name,
        delete_calendar_event,
        update_calendar_event,
        list_all_calendars,
    ]

    return create_react_agent(model=llm, tools=tools)

# Initialize agent
agent = None

@app.on_event("startup")
async def startup_event():
    """Initialize the agent on startup."""
    global agent
    required_vars = ["OPENAI_API_KEY"]
    missing = [var for var in required_vars if not os.getenv(var)]
    
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    
    if not os.path.exists("key/credentials.json"):
        raise RuntimeError("Missing 'key/credentials.json' file!")
    
    agent = create_calendar_agent()
    print("✅ Calendar Agent API initialized successfully!")

# Health check endpoint
@app.get("/")
async def root():
    """API health check."""
    return {
        "status": "online",
        "service": "SafexpressOps Calendar Agent API",
        "version": "1.0.0",
        "endpoints": {
            "docs": "/docs",
            "redoc": "/redoc"
        }
    }

# Natural language event creation
@app.post("/events/natural")
async def create_event_natural(request: NaturalLanguageRequest):
    """
    Create an event using natural language.
    Example: "Schedule meeting with john@email.com tomorrow 2PM-3PM at Conference Room A"
    """
    try:
        parsed = parse_calendar_prompt(request.prompt)
        calendar_id = None
        
        result = create_event_impl(
            summary=parsed['summary'],
            start=parsed['start'],
            end=parsed['end'],
            emails=parsed['emails'],
            description=parsed.get('description', ''),
            location=parsed.get('location', ''),
            calendar_id=calendar_id
        )
        
        return {"success": True, "message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Standard event creation
@app.post("/events")
async def create_event(event: EventCreate):
    """Create a single calendar event."""
    try:
        calendar_id = None
        if event.calendar_name:
            cal = find_calendar_by_name(event.calendar_name)
            if cal:
                calendar_id = cal['id']
            else:
                raise HTTPException(status_code=404, detail=f"Calendar '{event.calendar_name}' not found")
        
        result = create_event_impl(
            summary=event.summary,
            start=event.start,
            end=event.end,
            emails=event.emails,
            description=event.description,
            location=event.location,
            calendar_id=calendar_id
        )
        
        return {"success": True, "message": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Batch event creation
@app.post("/events/batch")
async def create_multiple_events(request: MultipleEventsCreate):
    """Create multiple events at once (max 5)."""
    try:
        events_data = []
        for event in request.events:
            event_dict = event.dict()
            if event.calendar_name:
                cal = find_calendar_by_name(event.calendar_name)
                if cal:
                    event_dict['calendar_id'] = cal['id']
            events_data.append(event_dict)
        
        result = create_multiple_events_impl(events_data)
        return {"success": True, "message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Search events
@app.get("/events")
async def search_events(max_results: int = 5, calendar_name: str = ""):
    """List upcoming events."""
    try:
        calendar_id = None
        if calendar_name:
            cal = find_calendar_by_name(calendar_name)
            if cal:
                calendar_id = cal['id']
            else:
                raise HTTPException(status_code=404, detail=f"Calendar '{calendar_name}' not found")
        
        result = search_events_impl(max_results, calendar_id)
        return {"success": True, "message": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Find event by name
@app.post("/events/search")
async def find_event(request: EventSearch):
    """Search for events by name/keywords."""
    try:
        calendar_id = None
        if request.calendar_name:
            cal = find_calendar_by_name(request.calendar_name)
            if cal:
                calendar_id = cal['id']
        
        events = search_event_by_description(request.event_name, calendar_id=calendar_id)
        
        if not events:
            return {"success": False, "message": f"No events found matching '{request.event_name}'", "events": []}
        
        return {
            "success": True,
            "message": f"Found {len(events)} matching event(s)",
            "events": events
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Update event
@app.put("/events")
async def update_event(request: EventUpdate):
    """Update an existing event."""
    try:
        calendar_id = None
        if request.calendar_name:
            cal = find_calendar_by_name(request.calendar_name)
            if cal:
                calendar_id = cal['id']
        
        result = update_event_impl(
            event_id=request.event_id,
            new_summary=request.new_summary,
            new_start=request.new_start,
            new_end=request.new_end,
            new_description=request.new_description,
            new_location=request.new_location,
            calendar_id=calendar_id
        )
        
        return {"success": True, "message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Delete event
@app.delete("/events")
async def delete_event(request: EventDelete):
    """Delete an event."""
    try:
        calendar_id = None
        if request.calendar_name:
            cal = find_calendar_by_name(request.calendar_name)
            if cal:
                calendar_id = cal['id']
        
        result = delete_event_impl(request.event_id, calendar_id)
        return {"success": True, "message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Conflict resolution
@app.post("/events/resolve-conflict")
async def resolve_conflict(request: ConflictResolution):
    """Resolve scheduling conflict by moving the conflicting event."""
    try:
        calendar_id = None
        if request.new_event.calendar_name:
            cal = find_calendar_by_name(request.new_event.calendar_name)
            if cal:
                calendar_id = cal['id']
        
        new_event_dict = request.new_event.dict()
        if calendar_id:
            new_event_dict['calendar_id'] = calendar_id
        
        result = handle_user_confirmation(
            conflict_id=request.conflict_id,
            new_event=new_event_dict,
            calendar_id=calendar_id
        )
        
        return {"success": True, "message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Calendar management
@app.post("/calendars")
async def create_calendar(request: CalendarCreate):
    """Create a new calendar."""
    try:
        result = create_calendar_impl(request.calendar_name, request.description)
        return {"success": True, "message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/calendars")
async def list_calendars():
    """List all calendars."""
    try:
        result = list_calendars_impl()
        return {"success": True, "message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Notify attendees
@app.post("/events/notify")
async def notify_attendees(request: NotifyAttendees):
    """Send custom notification to event attendees."""
    try:
        calendar_id = None
        if request.calendar_name:
            cal = find_calendar_by_name(request.calendar_name)
            if cal:
                calendar_id = cal['id']
        
        result = notify_attendees_about_change(
            event_id=request.event_id,
            change_message=request.message,
            calendar_id=calendar_id
        )
        
        return {"success": True, "message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Agent conversation endpoint
@app.post("/agent/chat")
async def agent_chat(request: AgentConversation):
    """
    Have a conversation with the AI agent using natural language.
    The agent can handle complex requests and multi-turn conversations.
    """
    try:
        system_prompt = """
        You are the Calendar scheduling agent for SafexpressOps.
        Help users manage their Google Calendar efficiently using natural language.
        """
        
        conversation_history = [("system", system_prompt)]
        
        # Add previous conversation context if provided
        if request.conversation_history:
            for msg in request.conversation_history:
                conversation_history.append((msg.get("role", "user"), msg.get("content", "")))
        
        # Add current message
        conversation_history.append(("user", request.message))
        
        # Get agent response
        result = agent.invoke({"messages": conversation_history})
        messages = result.get("messages", [])
        response_text = messages[-1].content if messages else str(result)
        
        return {
            "success": True,
            "response": response_text,
            "conversation_history": [
                {"role": "user", "content": request.message},
                {"role": "assistant", "content": response_text}
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
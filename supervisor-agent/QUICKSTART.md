# Supervisor Agent - Quick Start Guide

## Overview
The Supervisor Agent orchestrates multiple specialized agent microservices to execute complex workflows. It uses LangGraph to plan and execute tasks by calling external microservices via HTTP.

## Installation

1. **Install dependencies:**
```bash
cd supervisor-agent
pip install -r requirements.txt
```

2. **Configure environment:**
```bash
cp .env.example .env
# Edit .env with your OpenAI API key and agent URLs
```

3. **Run the supervisor:**
```bash
python supervisor_agent.py
```

The API will be available at `http://localhost:8000`

## Usage

### API Endpoint: POST /workflow

**Request:**
```json
{
  "input": "Create a document titled 'Project Plan' and email it to john@example.com",
  "memory": {},
  "policies": [{"rule": "allow all for demo"}]
}
```

**Response:**
```json
{
  "status": "success",
  "final_context": {
    "doc_url": "https://docs.google.com/document/d/...",
    "doc_id": "abc123",
    "status": "sent",
    "recipient": "john@example.com",
    "subject": "Project Plan Document"
  },
  "plan": {
    "plan": [
      {
        "agent": "docs_agent",
        "inputs": {"title": "Project Plan", "content": "..."},
        "description": "Create the document"
      },
      {
        "agent": "gmail_agent",
        "inputs": {
          "recipient": "john@example.com",
          "subject": "Project Plan Document",
          "body": "Here is the document: {{ doc_url }}"
        },
        "description": "Email the document link"
      }
    ]
  },
  "message": "Workflow executed successfully"
}
```

## Testing with cURL

```bash
curl -X POST http://localhost:8000/workflow \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Create a spreadsheet with sales data and share it with team@company.com"
  }'
```

## Testing with Python

```python
import requests

response = requests.post(
    "http://localhost:8000/workflow",
    json={
        "input": "Create a meeting for tomorrow at 2pm with john@example.com about project review"
    }
)

print(response.json())
```

## Environment Variables

- `PORT`: Server port (default: 8000)
- `OPENAI_API_KEY`: Your OpenAI API key (required)
- `DOCS_AGENT_URL`: Google Docs agent endpoint
- `GMAIL_AGENT_URL`: Gmail agent endpoint
- `SHEETS_AGENT_URL`: Google Sheets agent endpoint
- `CALENDAR_AGENT_URL`: Calendar agent endpoint
- `DRIVE_AGENT_URL`: Google Drive agent endpoint

## Architecture

```
User Request
     ↓
[Supervisor Agent] ← LLM generates plan
     ↓
[Orchestrator Node] ← Executes plan
     ↓
HTTP POST → [Docs Agent Microservice]
HTTP POST → [Gmail Agent Microservice]
HTTP POST → [Sheets Agent Microservice]
     ↓
Final Response
```

## Next Steps

1. Implement the specialized agent microservices (see MICROSERVICE_TEMPLATE.md)
2. Configure Google API credentials for each agent
3. Update .env with actual microservice URLs
4. Test the complete workflow

## API Documentation

Once running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

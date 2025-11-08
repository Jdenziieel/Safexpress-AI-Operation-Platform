# Example Specialized Agent Microservice Template

This is a template for creating specialized agent microservices that work with the Supervisor Agent.

## Gmail Agent Example

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
import os

app = FastAPI(title="Gmail Agent Microservice")

class GmailRequest(BaseModel):
    recipient: str
    subject: str
    body: str
    attachments: Optional[List[str]] = []

class GmailResponse(BaseModel):
    status: str
    recipient: str
    subject: str
    message_id: Optional[str] = None

@app.post("/execute", response_model=GmailResponse)
async def send_email(request: GmailRequest):
    """
    Execute Gmail send email operation.
    
    Args:
        request: GmailRequest with recipient, subject, body, and attachments
    
    Returns:
        GmailResponse with status and details
    """
    try:
        print(f"📧 Sending email to: {request.recipient}")
        print(f"   Subject: {request.subject}")
        
        # TODO: Implement actual Gmail API integration here
        # from google.oauth2 import service_account
        # from googleapiclient.discovery import build
        # service = build('gmail', 'v1', credentials=creds)
        # message = create_message(request.recipient, request.subject, request.body)
        # result = service.users().messages().send(userId='me', body=message).execute()
        
        # For now, return a mock response
        return GmailResponse(
            status="success",
            recipient=request.recipient,
            subject=request.subject,
            message_id="mock_message_id_12345"
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send email: {str(e)}"
        )

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "gmail-agent"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8002"))
    print(f"🚀 Starting Gmail Agent on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
```

## Docs Agent Example

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
import os

app = FastAPI(title="Google Docs Agent Microservice")

class DocsRequest(BaseModel):
    title: str
    content: str

class DocsResponse(BaseModel):
    status: str
    doc_url: str
    doc_id: str

@app.post("/execute", response_model=DocsResponse)
async def create_document(request: DocsRequest):
    """
    Execute Google Docs document creation.
    
    Args:
        request: DocsRequest with title and content
    
    Returns:
        DocsResponse with doc_url and doc_id
    """
    try:
        print(f"📄 Creating document: {request.title}")
        
        # TODO: Implement actual Google Docs API integration here
        # from google.oauth2 import service_account
        # from googleapiclient.discovery import build
        # service = build('docs', 'v1', credentials=creds)
        # doc = service.documents().create(body={'title': request.title}).execute()
        # doc_id = doc.get('documentId')
        
        # For now, return a mock response
        mock_doc_id = "mock_doc_id_67890"
        return DocsResponse(
            status="success",
            doc_url=f"https://docs.google.com/document/d/{mock_doc_id}/edit",
            doc_id=mock_doc_id
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create document: {str(e)}"
        )

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "docs-agent"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8001"))
    print(f"🚀 Starting Docs Agent on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
```

## Sheets Agent Example

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import uvicorn
import os

app = FastAPI(title="Google Sheets Agent Microservice")

class SheetsRequest(BaseModel):
    title: str
    data: List[List[str]]

class SheetsResponse(BaseModel):
    status: str
    sheet_url: str
    sheet_id: str

@app.post("/execute", response_model=SheetsResponse)
async def create_sheet(request: SheetsRequest):
    """
    Execute Google Sheets creation.
    
    Args:
        request: SheetsRequest with title and data
    
    Returns:
        SheetsResponse with sheet_url and sheet_id
    """
    try:
        print(f"📊 Creating sheet: {request.title}")
        print(f"   Rows: {len(request.data)}")
        
        # TODO: Implement actual Google Sheets API integration here
        
        mock_sheet_id = "mock_sheet_id_11111"
        return SheetsResponse(
            status="success",
            sheet_url=f"https://docs.google.com/spreadsheets/d/{mock_sheet_id}/edit",
            sheet_id=mock_sheet_id
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create sheet: {str(e)}"
        )

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "sheets-agent"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8003"))
    print(f"🚀 Starting Sheets Agent on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
```

## Running the Microservices

### 1. Start Supervisor Agent
```bash
cd supervisor-agent
python supervisor_agent.py
# Runs on http://localhost:8000
```

### 2. Start Specialized Agents (in separate terminals)
```bash
# Docs Agent
python docs_agent_microservice.py  # Port 8001

# Gmail Agent
python gmail_agent_microservice.py  # Port 8002

# Sheets Agent
python sheets_agent_microservice.py  # Port 8003
```

### 3. Test the Workflow
```bash
curl -X POST http://localhost:8000/workflow \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Create a document titled Launch Plan and email it to ana@example.com"
  }'
```

## Project Structure

```
Ai-Agents/
├── supervisor-agent/
│   ├── supervisor_agent.py
│   ├── requirements.txt
│   └── .env
├── docs-agent/
│   ├── docs_agent_microservice.py
│   └── requirements.txt
├── gmail-agent/
│   ├── gmail_agent_microservice.py
│   └── requirements.txt
└── sheets-agent/
    ├── sheets_agent_microservice.py
    └── requirements.txt
```

## API Flow

1. **User Request** → POST `/workflow` to Supervisor Agent
2. **Supervisor Agent** → Generates execution plan using LLM
3. **Orchestrator** → Calls specialized agent microservices via HTTP
4. **Specialized Agents** → Execute specific tasks and return results
5. **Response** → Supervisor returns final context with all results

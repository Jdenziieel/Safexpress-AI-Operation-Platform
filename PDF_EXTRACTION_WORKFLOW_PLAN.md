# 📄 PDF Extraction → Sheets Upload Workflow - Implementation Plan

## 🎯 Objective

Create an automated workflow that:
1. **Retrieves PDF attachments** from Gmail
2. **Extracts structured data** from PDFs (tables, text, forms)
3. **Transforms data** using intelligent mapping
4. **Uploads to Google Sheets** (with date matching)
5. **Logs all operations** to database
6. **Detects intent** automatically when user requests this workflow

---

## 🏗️ Current Architecture Analysis

### Existing Components

#### ✅ **Gmail Agent** (Port 8001)
- **Tools Available:**
  - `search_emails` - Find emails with attachments
  - `download_attachment` - Download PDF files locally
  - Returns: `message_id`, `attachment_id`, `filename`, `save_path`, `file_size`

#### ✅ **Mapping Agent** (Port 8004)
- **Tools Available:**
  - `parse_file` - Parse CSV/Excel/JSON (⚠️ NO PDF support yet)
  - `smart_column_mapping` - AI-powered column mapping
  - `transform_data` - Transform data structure
  - `extract_dates_from_all_rows` - Date extraction for matching

#### ✅ **Sheets Agent** (Port 8003)
- **Tools Available:**
  - `update_by_date_match` - Update rows by matching dates
  - `upload_mapped_data` - Append new data
  - Returns: `rows_updated`, `rows_not_found`, `rows_added`

#### ✅ **Drive Agent** (Port 8006)
- **Tools Available:**
  - `search_files` - Find existing sheets by name
  - `upload_file` - Upload files to Drive folders

#### ✅ **Supervisor Agent** (Port 8010)
- **Current Capabilities:**
  - Multi-step workflow orchestration
  - LLM-based plan generation
  - Context variable passing (`{{ variable_name }}`)
  - Conversational intent detection
  - SQLite database (threads.db) for conversation history

#### ✅ **Database Infrastructure**
- **Location:** `supervisor-agent/thread_manager.py`
- **Existing Tables:**
  - `threads` - Conversation metadata
  - `thread_states` - Conversation state (JSON)
  - `memory_states` - Memory tracking
  - `messages` - Individual conversation turns
- **Features:** Foreign key constraints, indexes, cascade deletes

---

## 🚧 Missing Components (Need to Build)

### 1. **PDF Extraction Tool** ⚠️ CRITICAL
**Problem:** Mapping agent only supports CSV/Excel/JSON, NOT PDF

**Solution Options:**

#### **Option A: Create New PDF Agent** (Recommended)
- **New microservice:** `pdf-agent` on port 8007
- **Tool:** `extract_pdf_data`
- **Libraries:** 
  - `pdfplumber` - Extract tables and text
  - `tabula-py` - Extract tables from PDFs
  - `PyPDF2` - Basic PDF operations
  - `camelot-py` - Advanced table extraction

**Tool Specification:**
```python
{
    "tool": "extract_pdf_data",
    "args": {
        "file_path": "str (required) — Local path to PDF",
        "extraction_mode": "str (optional) — 'table', 'text', 'form', 'auto' (default: 'auto')",
        "pages": "str (optional) — Page range (e.g., '1-3', 'all')",
        "table_settings": "dict (optional) — Advanced table extraction config"
    },
    "returns": {
        "success": "bool",
        "data": "str — JSON string of extracted data (compatible with mapping_agent)",
        "columns": "list — Column names detected",
        "row_count": "int",
        "extraction_method": "str — Method used (pdfplumber, tabula, etc.)",
        "confidence_score": "float — Extraction quality (0-1)",
        "raw_text": "str — Full text content (optional)",
        "error": "str"
    }
}
```

#### **Option B: Extend Mapping Agent** (Faster Implementation)
- Add PDF parsing to existing `mapping_agent_api.py`
- Add new tool `parse_pdf` alongside existing `parse_file`
- Reuse existing transformation pipeline

**Pros:**
- Faster to implement
- Reuses existing infrastructure
- No new port allocation

**Cons:**
- Violates separation of concerns
- Mapping agent becomes bloated
- PDF extraction is complex enough to warrant separate service

**Recommendation:** **Option A** - Create dedicated PDF agent for maintainability

---

### 2. **Workflow Logging Database** ⚠️ CRITICAL

**Problem:** No tracking of data insertion operations, success/failure logs

**Solution:** Extend existing SQLite database with new tables

#### **New Database Tables:**

```sql
-- Workflow execution logs
CREATE TABLE workflow_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,              -- Unique workflow execution ID
    workflow_type TEXT NOT NULL,            -- 'pdf_to_sheets', 'email_to_docs', etc.
    thread_id TEXT,                         -- Link to conversation thread
    user_id TEXT NOT NULL,
    status TEXT NOT NULL,                   -- 'running', 'completed', 'failed', 'partial'
    started_at TEXT NOT NULL,
    completed_at TEXT,
    total_steps INTEGER,
    completed_steps INTEGER DEFAULT 0,
    error_message TEXT,
    FOREIGN KEY (thread_id) REFERENCES threads(thread_id) ON DELETE SET NULL
);

-- Individual step logs
CREATE TABLE workflow_steps (
    step_id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    step_number INTEGER NOT NULL,
    agent_name TEXT NOT NULL,               -- 'gmail_agent', 'pdf_agent', 'sheets_agent'
    tool_name TEXT NOT NULL,                -- 'search_emails', 'extract_pdf_data', etc.
    inputs TEXT,                            -- JSON string of input parameters
    outputs TEXT,                           -- JSON string of tool results
    status TEXT NOT NULL,                   -- 'success', 'failed', 'skipped'
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    FOREIGN KEY (workflow_id) REFERENCES workflow_logs(workflow_id) ON DELETE CASCADE
);

-- Data insertion tracking (specific to Sheets uploads)
CREATE TABLE data_insertions (
    insertion_id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    sheet_id TEXT NOT NULL,                 -- Google Sheets ID
    sheet_name TEXT NOT NULL,               -- Sheet tab name
    sheet_url TEXT,                         -- Full Google Sheets URL
    source_file TEXT,                       -- Original PDF filename
    rows_inserted INTEGER DEFAULT 0,
    rows_updated INTEGER DEFAULT 0,
    rows_failed INTEGER DEFAULT 0,
    date_range_start TEXT,                  -- First date in uploaded data
    date_range_end TEXT,                    -- Last date in uploaded data
    inserted_at TEXT NOT NULL,
    data_preview TEXT,                      -- JSON preview of inserted data (first 5 rows)
    FOREIGN KEY (workflow_id) REFERENCES workflow_logs(workflow_id) ON DELETE CASCADE
);

-- Error tracking for debugging
CREATE TABLE workflow_errors (
    error_id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    step_id INTEGER,
    error_type TEXT NOT NULL,               -- 'extraction_error', 'mapping_error', 'upload_error'
    error_message TEXT NOT NULL,
    error_details TEXT,                     -- Stack trace, additional context
    occurred_at TEXT NOT NULL,
    resolved BOOLEAN DEFAULT FALSE,
    resolution_notes TEXT,
    FOREIGN KEY (workflow_id) REFERENCES workflow_logs(workflow_id) ON DELETE CASCADE,
    FOREIGN KEY (step_id) REFERENCES workflow_steps(step_id) ON DELETE SET NULL
);

-- Indexes for performance
CREATE INDEX idx_workflow_logs_user ON workflow_logs(user_id);
CREATE INDEX idx_workflow_logs_status ON workflow_logs(status);
CREATE INDEX idx_workflow_logs_type ON workflow_logs(workflow_type);
CREATE INDEX idx_workflow_steps_workflow ON workflow_steps(workflow_id);
CREATE INDEX idx_data_insertions_workflow ON data_insertions(workflow_id);
CREATE INDEX idx_data_insertions_sheet ON data_insertions(sheet_id);
CREATE INDEX idx_workflow_errors_workflow ON workflow_errors(workflow_id);
```

#### **Database Manager Module:**

**New File:** `supervisor-agent/workflow_logger.py`

```python
"""
Workflow Logger - Tracks multi-step workflow executions and data insertions
"""

import sqlite3
import json
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path
import uuid


class WorkflowLogger:
    """
    Manages workflow execution logging with SQLite.
    
    Features:
    - Track workflow start/end
    - Log individual step execution
    - Track data insertions to Sheets
    - Error tracking and debugging
    - Query logs by user/workflow/date
    """
    
    def __init__(self, db_path: str = "threads.db"):
        self.db_path = Path(db_path)
        self._init_tables()
    
    def start_workflow(
        self, 
        workflow_type: str, 
        user_id: str,
        thread_id: Optional[str] = None,
        total_steps: int = 0
    ) -> str:
        """Start a new workflow execution"""
        workflow_id = f"wf_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO workflow_logs 
            (workflow_id, workflow_type, thread_id, user_id, status, started_at, total_steps)
            VALUES (?, ?, ?, ?, 'running', ?, ?)
        """, (workflow_id, workflow_type, thread_id, user_id, now, total_steps))
        
        conn.commit()
        conn.close()
        
        print(f"📊 Started workflow: {workflow_id} ({workflow_type})")
        return workflow_id
    
    def complete_workflow(self, workflow_id: str, status: str = 'completed', error: Optional[str] = None):
        """Mark workflow as completed or failed"""
        now = datetime.utcnow().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE workflow_logs 
            SET status = ?, completed_at = ?, error_message = ?
            WHERE workflow_id = ?
        """, (status, now, error, workflow_id))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Completed workflow: {workflow_id} - Status: {status}")
    
    def log_step(
        self,
        workflow_id: str,
        step_number: int,
        agent_name: str,
        tool_name: str,
        inputs: Dict[str, Any],
        outputs: Optional[Dict[str, Any]] = None,
        status: str = 'success',
        error: Optional[str] = None
    ) -> int:
        """Log a single workflow step"""
        now = datetime.utcnow().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO workflow_steps
            (workflow_id, step_number, agent_name, tool_name, inputs, outputs, 
             status, started_at, completed_at, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            workflow_id, step_number, agent_name, tool_name,
            json.dumps(inputs), json.dumps(outputs) if outputs else None,
            status, now, now, error
        ))
        
        step_id = cursor.lastrowid
        
        # Update workflow completed_steps count
        cursor.execute("""
            UPDATE workflow_logs 
            SET completed_steps = completed_steps + 1
            WHERE workflow_id = ?
        """, (workflow_id,))
        
        conn.commit()
        conn.close()
        
        return step_id
    
    def log_data_insertion(
        self,
        workflow_id: str,
        sheet_id: str,
        sheet_name: str,
        sheet_url: str,
        source_file: str,
        rows_inserted: int = 0,
        rows_updated: int = 0,
        rows_failed: int = 0,
        date_range: Optional[tuple] = None,
        data_preview: Optional[List[Dict]] = None
    ):
        """Log data insertion to Google Sheets"""
        now = datetime.utcnow().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO data_insertions
            (workflow_id, sheet_id, sheet_name, sheet_url, source_file,
             rows_inserted, rows_updated, rows_failed, date_range_start, 
             date_range_end, inserted_at, data_preview)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            workflow_id, sheet_id, sheet_name, sheet_url, source_file,
            rows_inserted, rows_updated, rows_failed,
            date_range[0] if date_range else None,
            date_range[1] if date_range else None,
            now,
            json.dumps(data_preview[:5]) if data_preview else None
        ))
        
        conn.commit()
        conn.close()
        
        print(f"📝 Logged data insertion: {rows_inserted} inserted, {rows_updated} updated to {sheet_name}")
    
    def get_workflow_summary(self, workflow_id: str) -> Dict[str, Any]:
        """Get complete workflow execution summary"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get workflow info
        cursor.execute("SELECT * FROM workflow_logs WHERE workflow_id = ?", (workflow_id,))
        workflow = dict(cursor.fetchone())
        
        # Get steps
        cursor.execute("SELECT * FROM workflow_steps WHERE workflow_id = ? ORDER BY step_number", (workflow_id,))
        steps = [dict(row) for row in cursor.fetchall()]
        
        # Get data insertions
        cursor.execute("SELECT * FROM data_insertions WHERE workflow_id = ?", (workflow_id,))
        insertions = [dict(row) for row in cursor.fetchall()]
        
        # Get errors
        cursor.execute("SELECT * FROM workflow_errors WHERE workflow_id = ?", (workflow_id,))
        errors = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        return {
            "workflow": workflow,
            "steps": steps,
            "data_insertions": insertions,
            "errors": errors
        }
```

---

### 3. **Default Sheets Configuration** 

**Problem:** User wants to set a default destination sheet by link

**Solution:** Add configuration storage

#### **New Database Table:**

```sql
-- User preferences for workflow defaults
CREATE TABLE workflow_preferences (
    preference_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    workflow_type TEXT NOT NULL,            -- 'pdf_to_sheets'
    preference_key TEXT NOT NULL,           -- 'default_sheet_id', 'default_sheet_name'
    preference_value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, workflow_type, preference_key)
);

CREATE INDEX idx_preferences_user ON workflow_preferences(user_id);
CREATE INDEX idx_preferences_workflow ON workflow_preferences(workflow_type);
```

#### **API Endpoints to Add:**

```python
# In supervisor_agent.py

@app.post("/set_workflow_preference")
async def set_workflow_preference(
    user_id: str,
    workflow_type: str,
    preference_key: str,
    preference_value: str
):
    """
    Set user's workflow preference (e.g., default sheet)
    
    Example:
    POST /set_workflow_preference
    {
        "user_id": "user123",
        "workflow_type": "pdf_to_sheets",
        "preference_key": "default_sheet_url",
        "preference_value": "https://docs.google.com/spreadsheets/d/ABC123/edit"
    }
    """
    # Extract sheet_id from URL
    import re
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', preference_value)
    sheet_id = match.group(1) if match else preference_value
    
    # Store both URL and ID
    preferences = {
        "default_sheet_url": preference_value,
        "default_sheet_id": sheet_id
    }
    
    # Save to database
    # ... implementation
    
    return {
        "success": True,
        "message": f"Default sheet set for {workflow_type}"
    }

@app.get("/get_workflow_preferences/{user_id}/{workflow_type}")
async def get_workflow_preferences(user_id: str, workflow_type: str):
    """Get user's workflow preferences"""
    # Fetch from database
    # ... implementation
    
    return {
        "success": True,
        "preferences": {
            "default_sheet_url": "...",
            "default_sheet_id": "..."
        }
    }
```

---

## 🔄 Complete Workflow Design

### **Workflow: PDF → Sheets with Date Matching**

#### **User Inputs:**
- Natural language: _"Extract data from the PDF in my email and update my SafeExpressOps sheet"_
- Or: _"Get the PDF attachment from john@example.com and add it to my tracking sheet"_

#### **Step-by-Step Execution:**

```json
{
  "plan": [
    {
      "step": 1,
      "agent": "gmail_agent",
      "tool": "search_emails",
      "purpose": "Find email with PDF attachment",
      "inputs": {
        "query": "has:attachment filename:pdf",
        "max_results": 5
      },
      "output_variables": {
        "email_results": "emails"
      }
    },
    {
      "step": 2,
      "agent": "gmail_agent",
      "tool": "download_attachment",
      "purpose": "Download PDF file locally",
      "inputs": {
        "message_id": "{{ email_results[0].message_id }}",
        "attachment_id": "{{ email_results[0].attachments[0].attachment_id }}",
        "save_path": "C:\\temp\\downloaded.pdf"
      },
      "output_variables": {
        "pdf_path": "save_path",
        "pdf_filename": "filename"
      }
    },
    {
      "step": 3,
      "agent": "pdf_agent",
      "tool": "extract_pdf_data",
      "purpose": "Extract structured data from PDF",
      "inputs": {
        "file_path": "{{ pdf_path }}",
        "extraction_mode": "auto"
      },
      "output_variables": {
        "extracted_data": "data",
        "pdf_columns": "columns",
        "pdf_row_count": "row_count"
      }
    },
    {
      "step": 4,
      "agent": "mapping_agent",
      "tool": "extract_dates_from_all_rows",
      "purpose": "Extract dates from PDF data for matching",
      "inputs": {
        "data": "{{ extracted_data }}",
        "date_column_name": "Date"
      },
      "output_variables": {
        "rows_with_dates": "rows_with_dates"
      }
    },
    {
      "step": 5,
      "agent": "mapping_agent",
      "tool": "smart_column_mapping",
      "purpose": "Map PDF columns to Sheet columns",
      "inputs": {
        "source_columns": "{{ pdf_columns }}",
        "sample_data": "{{ extracted_data }}",
        "skip_temporal": true
      },
      "output_variables": {
        "column_mappings": "mappings"
      }
    },
    {
      "step": 6,
      "agent": "mapping_agent",
      "tool": "transform_data",
      "purpose": "Transform data to match Sheet structure",
      "inputs": {
        "source_data": "{{ extracted_data }}",
        "mappings": "{{ column_mappings }}"
      },
      "output_variables": {
        "transformed_data": "transformed_data"
      }
    },
    {
      "step": 7,
      "agent": "sheets_agent",
      "tool": "update_by_date_match",
      "purpose": "Update Sheet by matching dates",
      "inputs": {
        "sheet_id": "{{ user_preferences.default_sheet_id }}",
        "transformed_data": "{{ transformed_data }}",
        "rows_with_dates": "{{ rows_with_dates }}",
        "sheet_name": "DATA ENTRY",
        "date_column": "Date"
      },
      "output_variables": {
        "update_result": "rows_updated",
        "not_found": "rows_not_found"
      }
    }
  ]
}
```

---

## 🧠 Intent Detection Enhancement

### **Problem:** Supervisor must detect PDF extraction workflow from natural language

### **Solution:** Update supervisor's planning prompt

#### **Current Location:** `supervisor_agent.py` - `supervisor_node()` function

#### **Add to System Prompt:**

```python
system_prompt = f"""You are the Supervisor agent creating multi-step execution plans.

CURRENT DATE CONTEXT:
- Today's date: {today_date}
- Yesterday's date: {yesterday_date}

SPECIAL WORKFLOW DETECTION:
🔍 PDF-to-Sheets Workflow Detection:
If user mentions ANY of these patterns:
- "extract from PDF"
- "PDF attachment" + "sheet/spreadsheet"
- "parse PDF and upload"
- "get data from PDF email"
- "download PDF and add to sheet"

Then create a multi-step plan using:
1. gmail_agent.search_emails (find email with PDF)
2. gmail_agent.download_attachment (download PDF)
3. pdf_agent.extract_pdf_data (extract data from PDF)
4. mapping_agent.extract_dates_from_all_rows (if date matching needed)
5. mapping_agent.smart_column_mapping (map columns)
6. mapping_agent.transform_data (transform structure)
7. sheets_agent.update_by_date_match (upload to sheet)

Use user's default sheet from preferences if available, otherwise ask for sheet_id.

PLANNING RULES:
1. Reference previous outputs using {{{{ variable_name }}}} syntax
2. Declare output_variables as {{"new_name": "source_field"}}
3. Use date context variables: {{{{ today_date }}}}, {{{{ yesterday_date }}}}
4. For email arrays: {{{{ emails[0].message_id }}}}, {{{{ emails[0].attachments[0].attachment_id }}}}
5. For PDF workflow: Always extract dates if updating by date, always map columns

Available agents and tools:
{capability_summary}

Schema:
{schema_text}

CRITICAL: Return ONLY valid JSON matching the schema above."""
```

---

## 📝 Implementation Checklist

### **Phase 1: PDF Extraction (Week 1)**

- [ ] **1.1 Create PDF Agent Microservice**
  - [ ] Create `pdf-agent/` directory
  - [ ] Install dependencies: `pdfplumber`, `tabula-py`, `PyPDF2`, `camelot-py`
  - [ ] Create `pdf_agent_api.py` with FastAPI
  - [ ] Implement `extract_pdf_data` tool
  - [ ] Add table extraction logic
  - [ ] Add text extraction logic
  - [ ] Add form extraction logic
  - [ ] Test with sample PDFs

- [ ] **1.2 Add PDF Agent to Supervisor**
  - [ ] Add to `AGENT_ENDPOINTS` in `config.py`
  - [ ] Add to `agent_capabilities_v2.py`
  - [ ] Document tool args and returns
  - [ ] Add to agent filtering logic

### **Phase 2: Database Logging (Week 1)**

- [ ] **2.1 Extend Database Schema**
  - [ ] Add new tables to `thread_manager.py._init_database()`
  - [ ] Create migrations if needed
  - [ ] Test foreign key constraints
  - [ ] Add indexes

- [ ] **2.2 Create Workflow Logger**
  - [ ] Create `workflow_logger.py`
  - [ ] Implement `WorkflowLogger` class
  - [ ] Add logging methods
  - [ ] Test database operations

- [ ] **2.3 Add Preferences Storage**
  - [ ] Create `workflow_preferences` table
  - [ ] Add API endpoints for preferences
  - [ ] Implement get/set methods
  - [ ] Add URL parsing for sheet links

### **Phase 3: Workflow Integration (Week 2)**

- [ ] **3.1 Update Supervisor Planning**
  - [ ] Add PDF workflow detection to prompt
  - [ ] Update `supervisor_node()` function
  - [ ] Add preference loading logic
  - [ ] Test plan generation

- [ ] **3.2 Add Workflow Logging to Execution**
  - [ ] Import `WorkflowLogger` in `supervisor_agent.py`
  - [ ] Add `workflow_logger.start_workflow()` at workflow start
  - [ ] Add `workflow_logger.log_step()` for each step
  - [ ] Add `workflow_logger.log_data_insertion()` for sheet updates
  - [ ] Add `workflow_logger.complete_workflow()` at end
  - [ ] Handle errors with `workflow_logger.log_error()`

- [ ] **3.3 Update Execution Node**
  - [ ] Modify `execute_node()` to log steps
  - [ ] Pass workflow_id through state
  - [ ] Capture step outputs for logging
  - [ ] Handle step failures

### **Phase 4: API Endpoints (Week 2)**

- [ ] **4.1 Add Workflow Query Endpoints**
  - [ ] `GET /workflow_logs/{user_id}` - List user's workflows
  - [ ] `GET /workflow_logs/{workflow_id}` - Get workflow details
  - [ ] `GET /data_insertions/{user_id}` - List data insertions
  - [ ] `GET /workflow_errors/{workflow_id}` - Get workflow errors

- [ ] **4.2 Add Preference Endpoints**
  - [ ] `POST /set_workflow_preference` - Set default sheet
  - [ ] `GET /get_workflow_preferences/{user_id}/{workflow_type}`
  - [ ] `DELETE /delete_workflow_preference`

### **Phase 5: Testing & Documentation (Week 2)**

- [ ] **5.1 End-to-End Testing**
  - [ ] Test with sample PDF email
  - [ ] Test date matching
  - [ ] Test column mapping
  - [ ] Test error scenarios
  - [ ] Test with multiple PDFs

- [ ] **5.2 Documentation**
  - [ ] Update README with PDF workflow
  - [ ] Document API endpoints
  - [ ] Add usage examples
  - [ ] Create troubleshooting guide

---

## 🔧 Code Modifications Required

### **1. config.py**

```python
# Add PDF agent endpoint
AGENT_ENDPOINTS = {
    "gmail_agent": "http://localhost:8001/execute_task",
    "docs_agent": "http://localhost:8002/execute_task",
    "sheets_agent": "http://localhost:8003/execute_task",
    "mapping_agent": "http://localhost:8004/execute_task",
    "calendar_agent": "http://localhost:8005/execute_task",
    "drive_agent": "http://localhost:8006/execute_task",
    "pdf_agent": "http://localhost:8007/execute_task",  # NEW
}
```

### **2. agent_capabilities_v2.py**

```python
agent_capabilities = {
    # ... existing agents ...
    
    "pdf_agent": {
        "description": "Extract structured data from PDF files (tables, forms, text)",
        "tools": {
            "extract_pdf_data": {
                "description": "Extract tables and structured data from PDF files",
                "args": {
                    "file_path": "str (required) — Absolute path to PDF file",
                    "extraction_mode": "str (optional) — 'table', 'text', 'form', 'auto' (default: 'auto')",
                    "pages": "str (optional) — Page range (e.g., '1-3', 'all')",
                },
                "returns": {
                    "success": "bool",
                    "data": "str — JSON string of extracted data (array of row objects)",
                    "columns": "list — Detected column names",
                    "row_count": "int — Number of rows extracted",
                    "extraction_method": "str — Method used (pdfplumber, tabula)",
                    "confidence_score": "float — Quality score (0-1)",
                    "raw_text": "str — Full text content",
                    "error": "str",
                },
                "can_be_derived_from": {
                    "file_path": {
                        "source_tool": "gmail_agent.download_attachment",
                    }
                }
            }
        }
    }
}
```

### **3. supervisor_agent.py - Add Logging**

```python
from workflow_logger import WorkflowLogger

# Initialize workflow logger
workflow_logger = WorkflowLogger(db_path="threads.db")

# In execute_node() function:
async def execute_node(state: SharedState) -> SharedState:
    plan = state["plan"]
    context = state.get("context", {})
    
    # Start workflow logging
    workflow_id = workflow_logger.start_workflow(
        workflow_type="multi_step_execution",
        user_id=context.get("user_id", "unknown"),
        thread_id=context.get("thread_id"),
        total_steps=len(plan)
    )
    
    results = {}
    
    for i, step in enumerate(plan, 1):
        agent_name = step["agent"]
        tool_name = step["tool"]
        raw_inputs = step.get("inputs", {})
        
        try:
            # ... existing execution logic ...
            
            response_data = await call_agent_with_retry(
                agent_name=agent_name,
                tool_name=tool_name,
                inputs=resolved_inputs,
                credentials_dict=credentials_dict,
                max_retries=3,
                delay=2,
            )
            
            # Log successful step
            workflow_logger.log_step(
                workflow_id=workflow_id,
                step_number=i,
                agent_name=agent_name,
                tool_name=tool_name,
                inputs=resolved_inputs,
                outputs=response_data.get("result"),
                status='success'
            )
            
            # Special logging for sheet updates
            if agent_name == "sheets_agent" and "update_by_date_match" in tool_name:
                result = response_data.get("result", {})
                workflow_logger.log_data_insertion(
                    workflow_id=workflow_id,
                    sheet_id=resolved_inputs.get("sheet_id"),
                    sheet_name=resolved_inputs.get("sheet_name", "Sheet1"),
                    sheet_url=f"https://docs.google.com/spreadsheets/d/{resolved_inputs.get('sheet_id')}",
                    source_file=context.get("source_pdf", "unknown.pdf"),
                    rows_inserted=0,
                    rows_updated=result.get("rows_updated", 0),
                    rows_failed=len(result.get("rows_not_found", []))
                )
            
        except Exception as e:
            # Log failed step
            workflow_logger.log_step(
                workflow_id=workflow_id,
                step_number=i,
                agent_name=agent_name,
                tool_name=tool_name,
                inputs=resolved_inputs,
                outputs=None,
                status='failed',
                error=str(e)
            )
            
            workflow_logger.complete_workflow(workflow_id, status='failed', error=str(e))
            raise
    
    # Complete workflow successfully
    workflow_logger.complete_workflow(workflow_id, status='completed')
    
    return {"results": results, "context": context}
```

---

## 🚀 Deployment Steps

### **1. Install Dependencies**

```bash
# PDF Agent dependencies
cd pdf-agent
pip install fastapi uvicorn pdfplumber tabula-py PyPDF2 camelot-py[cv] opencv-python

# Supervisor dependencies (already installed)
cd ../supervisor-agent
pip install sqlite3  # Built-in with Python
```

### **2. Start Services**

```bash
# Update start-all-services.ps1
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd pdf-agent; python pdf_agent_api.py"
```

### **3. Database Migration**

```bash
# The tables will auto-create on first run
# Or run manual migration:
python supervisor-agent/thread_manager.py  # Runs _init_database()
```

---

## 📊 Example Usage

### **User Request:**

```
"Extract the data from the PDF John sent me yesterday and update my SafeExpressOps tracking sheet"
```

### **Supervisor Response:**

```json
{
  "response": "I'll extract data from the PDF attachment and update your SafeExpressOps sheet. Here's my plan:

1. Search for John's email from yesterday with PDF attachment
2. Download the PDF file
3. Extract data from the PDF
4. Match dates in the PDF with your sheet
5. Map columns intelligently
6. Update your sheet by matching dates

Starting execution...",
  "workflow_id": "wf_a1b2c3d4e5f6",
  "conversation_id": "conv_xyz123"
}
```

### **Workflow Log Query:**

```bash
GET /workflow_logs/wf_a1b2c3d4e5f6
```

**Response:**
```json
{
  "workflow": {
    "workflow_id": "wf_a1b2c3d4e5f6",
    "workflow_type": "pdf_to_sheets",
    "user_id": "user123",
    "status": "completed",
    "started_at": "2025-01-28T10:30:00Z",
    "completed_at": "2025-01-28T10:32:15Z",
    "total_steps": 7,
    "completed_steps": 7
  },
  "steps": [
    {
      "step_number": 1,
      "agent_name": "gmail_agent",
      "tool_name": "search_emails",
      "status": "success",
      "completed_at": "2025-01-28T10:30:15Z"
    },
    {
      "step_number": 7,
      "agent_name": "sheets_agent",
      "tool_name": "update_by_date_match",
      "status": "success",
      "completed_at": "2025-01-28T10:32:10Z"
    }
  ],
  "data_insertions": [
    {
      "sheet_id": "ABC123XYZ",
      "sheet_name": "DATA ENTRY",
      "sheet_url": "https://docs.google.com/spreadsheets/d/ABC123XYZ",
      "source_file": "SafeExpressOps_Jan2025.pdf",
      "rows_inserted": 0,
      "rows_updated": 45,
      "rows_failed": 3,
      "date_range_start": "2025-01-01",
      "date_range_end": "2025-01-25",
      "inserted_at": "2025-01-28T10:32:10Z"
    }
  ],
  "errors": []
}
```

---

## 🎯 Success Metrics

Track these to validate implementation:

1. **Workflow Completion Rate:** >90% successful
2. **Average Execution Time:** <2 minutes for standard PDFs
3. **Data Accuracy:** >95% correct column mapping
4. **Date Match Rate:** >85% successful date matches
5. **User Satisfaction:** <5% manual correction rate

---

## 🔐 Security Considerations

1. **File Storage:** Store downloaded PDFs in temp directory, auto-delete after processing
2. **Database Access:** Use parameterized queries (already implemented)
3. **Sheet Permissions:** Verify user has write access to target sheet
4. **Error Messages:** Don't expose file paths or credentials in logs
5. **Rate Limiting:** Add rate limits to prevent abuse

---

## 🐛 Error Handling

### **Common Failure Scenarios:**

1. **PDF has no extractable tables**
   - Fallback to text extraction
   - Ask user to confirm data manually

2. **Column mapping confidence <0.7**
   - Ask user to confirm mappings
   - Show suggested mappings with confidence scores

3. **Date matching finds 0 matches**
   - Fallback to append mode
   - Ask user if they want to create new rows

4. **Sheet doesn't exist**
   - Create new sheet
   - Ask user for confirmation

---

## 📚 References

- **PDF Libraries:**
  - [pdfplumber](https://github.com/jsvine/pdfplumber) - Table extraction
  - [tabula-py](https://github.com/chezou/tabula-py) - Alternative table extraction
  - [camelot](https://camelot-py.readthedocs.io/) - Advanced table detection

- **Database:**
  - SQLite foreign keys: [docs](https://www.sqlite.org/foreignkeys.html)
  - Python sqlite3: [docs](https://docs.python.org/3/library/sqlite3.html)

---

## ✅ Next Steps

1. **Review this plan** - Confirm architecture fits requirements
2. **Choose PDF library** - Test with sample PDFs
3. **Start Phase 1** - Build PDF agent microservice
4. **Test incrementally** - Don't wait until everything is done
5. **Iterate based on feedback** - User testing is critical

---

**Estimated Total Implementation Time:** 2 weeks (1 developer)

**Priority Order:**
1. PDF Agent (critical path)
2. Database logging (enables tracking)
3. Workflow integration (connects pieces)
4. API endpoints (user visibility)
5. Testing & polish (reliability)

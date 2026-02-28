# Delivery Order Automation Workflow - IMPLEMENTATION COMPLETE

## Overview
The delivery order automation workflow has been fully implemented and is ready for use. The system enables end-to-end automation from Gmail search through data transformation and Google Sheets upload.

## What's Implemented

### 1. Gmail Agent (Port 8000)
**Location:** `gmail-agent/tools.py` + `gmail-agent/api.py`

#### Tool 1: `search_emails_with_delivery_order_attachments`
- **Function:** `_search_emails_with_delivery_order_attachments_impl()`
- **Purpose:** Search Gmail for delivery orders with PDF/Excel attachments
- **Features:**
  - Custom Gmail query support
  - Automatic filtering by MIME type (PDF, Excel, CSV)
  - Optional file download to temp directory
  - Metadata extraction (sender, subject, timestamp, file size)
  - Error handling for API failures

#### Tool 2: `save_attachment_metadata`
- **Function:** `_save_attachment_metadata_impl()`
- **Purpose:** Persist attachment metadata to SQLite database
- **Features:**
  - Automatic database creation (gmail_agent_data.db)
  - Metadata storage: message_id, filename, file_path, sender, subject, timestamp, mime_type, size
  - Duplicate prevention (UNIQUE constraint on message_id + filename)
  - Timestamp tracking (saved_at)

#### Tool 3: `process_delivery_order_workflow`
- **Function:** `_process_delivery_order_workflow_impl()`
- **Purpose:** End-to-end orchestration of delivery order processing
- **Workflow Steps:**
  1. **Search:** Call `search_emails_with_delivery_order_attachments` to find orders
  2. **Parse:** Send files to mapping-agent via POST `/execute_task` (tool: `parse_file`)
  3. **Transform:** Send parsed data to mapping-agent (tool: `transform_data`)
  4. **Upload:** Send transformed data to sheets-agent (tool: `upload_mapped_data`)
  5. **Save:** Call `save_attachment_metadata` to persist metadata
- **Features:**
  - Per-step error handling (continues on individual failures)
  - Configurable agent URLs (params or env vars: MAPPING_AGENT_URL, SHEETS_AGENT_URL)
  - Optional steps (upload_to_sheets, save_to_db flags)
  - Cleanup of temp files after processing
  - Detailed results reporting

### 2. Supervisor Agent (Port 8010)
**Location:** `supervisor-agent/agent_capabilities_v2.py`

#### Integration
Three new capability entries added to the `gmail_agent.tools` dictionary:

1. **search_emails_with_delivery_order_attachments**
   - Args: query, max_results, download_attachments, temp_dir
   - Returns: success, emails_with_attachments[], total_emails_found, total_attachments_downloaded, temp_directory, error

2. **save_attachment_metadata**
   - Args: metadata (dict), db_path (optional)
   - Returns: success, inserted_id, db_path, saved_at, error

3. **process_delivery_order_workflow**
   - Args: query, max_results, download_attachments, save_to_db, upload_to_sheets, sheets_sheet_id, mapping_agent_url, sheets_agent_url
   - Returns: success, processed[], search_summary, errors[], error
   - **Workflow Metadata:** Includes step-by-step breakdown for LLM planner awareness

**Impact:** Supervisor's LLM planner and tool filter can now discover and reason about these tools for multi-agent orchestration.

## API Endpoints

### Gmail Agent (`/execute_task`)
```bash
POST http://localhost:8000/execute_task
Content-Type: application/json

{
  "tool": "search_emails_with_delivery_order_attachments",
  "inputs": {
    "query": "delivery order from:partner@company.com",
    "max_results": 10,
    "download_attachments": true,
    "temp_dir": "/tmp/delivery_orders"
  },
  "credentials_dict": { "access_token": "...", "refresh_token": "..." }
}
```

### Workflow Orchestration
```bash
POST http://localhost:8000/execute_task
Content-Type: application/json

{
  "tool": "process_delivery_order_workflow",
  "inputs": {
    "query": "subject:PO is:unread from:sales@partner.com",
    "max_results": 5,
    "download_attachments": true,
    "save_to_db": true,
    "upload_to_sheets": true,
    "sheets_sheet_id": "YOUR_SHEETS_ID",
    "mapping_agent_url": "http://localhost:8002",
    "sheets_agent_url": "http://localhost:8001"
  },
  "credentials_dict": { "access_token": "...", "refresh_token": "..." }
}
```

## Conversational Flow (Example)

```
User: "Search for delivery orders from our batangas supplier"
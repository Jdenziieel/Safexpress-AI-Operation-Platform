# DocuExtract Architecture Documentation

> **Last Updated:** November 30, 2025  
> **Version:** 2.1 (with Session Persistence & Updated Override Flow)

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Technology Stack](#technology-stack)
3. [Database Architecture](#database-architecture)
4. [API Endpoints](#api-endpoints)
5. [Step-by-Step Process Flow](#step-by-step-process-flow)
6. [Duplicate Detection System](#duplicate-detection-system)
7. [Document Versioning System](#document-versioning-system)
8. [Session Persistence System](#session-persistence-system)
9. [Frontend Components](#frontend-components)

---

## System Overview

DocuExtract is a document processing and knowledge base management system that:
- Extracts and parses PDF documents
- Chunks content for vector storage
- Stores document embeddings in Weaviate for semantic search
- Tracks document metadata in SQLite
- Implements duplicate detection to prevent redundant processing
- Maintains version history for document updates
- Persists parsed documents in localStorage to survive page refresh
- Clears session data on logout for security

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (React)                                │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐  │
│  │ DocumentExtract │  │  Chat Interface │  │     Knowledge Base UI       │  │
│  │    Component    │  │    Component    │  │        Component            │  │
│  └────────┬────────┘  └────────┬────────┘  └─────────────┬───────────────┘  │
└───────────┼────────────────────┼────────────────────────┼───────────────────┘
            │                    │                        │
            ▼                    ▼                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           BACKEND (FastAPI)                                  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐  │
│  │   PDF Routes    │  │   Chat Routes   │  │        KB Routes            │  │
│  │  /pdf/parse-pdf │  │   /chat/send    │  │  /kb/upload-to-kb           │  │
│  │                 │  │                 │  │  /kb/list-kb                │  │
│  │                 │  │                 │  │  /kb/document-versions/{fn} │  │
│  └────────┬────────┘  └────────┬────────┘  └─────────────┬───────────────┘  │
│           │                    │                        │                    │
│           ▼                    ▼                        ▼                    │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                          SERVICES LAYER                                 ││
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────────┐  ││
│  │  │ PDF Service  │ │ Chat Service │ │OpenAI Service│ │Weaviate Service│  ││
│  │  │              │ │              │ │ (Embeddings) │ │ (Vector Store) │  ││
│  │  └──────────────┘ └──────────────┘ └──────────────┘ └────────────────┘  ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│           │                                              │                   │
│           ▼                                              ▼                   │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                          DATABASE LAYER                                 ││
│  │  ┌────────────────────────────┐  ┌────────────────────────────────────┐ ││
│  │  │     SQLite (Local DB)      │  │      Weaviate Cloud (Vector DB)    │ ││
│  │  │  - documents table         │  │  - Document collection             │ ││
│  │  │  - document_versions table │  │  - DocumentChunk collection        │ ││
│  │  │  - chat_sessions table     │  │  - text-embedding-3-small (1536d)  │ ││
│  │  └────────────────────────────┘  └────────────────────────────────────┘ ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| Frontend | React + Vite | User interface |
| API | FastAPI (Python) | REST API server |
| Vector Database | Weaviate Cloud | Semantic search & embeddings |
| Local Database | SQLite | Document tracking & metadata |
| Embedding Model | OpenAI text-embedding-3-small | 1536-dimensional vectors |
| PDF Processing | Custom PDF Extractor | Text & table extraction |
| Authentication | JWT | User authentication |

---

## Database Architecture

### SQLite Tables

#### 1. `documents` Table
Tracks all uploaded documents currently active in the knowledge base.

| Field | Type | Description |
|-------|------|-------------|
| `doc_id` | TEXT (PK) | Unique document identifier (UUID) |
| `file_name` | TEXT (UNIQUE) | Original filename of uploaded PDF |
| `upload_date` | TEXT | ISO 8601 timestamp (Philippine Time UTC+8) |
| `file_size_bytes` | INTEGER | File size in bytes |
| `chunks` | INTEGER | Number of chunks created from document |
| `uploaded_by` | TEXT | Username of uploader (from JWT) |
| `content_hash` | TEXT (UNIQUE) | SHA256 hash of file content |
| `page_count` | INTEGER | Number of pages in PDF |
| `weaviate_doc_id` | TEXT | Reference ID in Weaviate |
| `metadata` | TEXT (JSON) | Additional document metadata |
| `current_version` | INTEGER | Current version number (default: 1) |

**Indexes:**
- `idx_file_name` - UNIQUE index on file_name
- `idx_content_hash` - UNIQUE index on content_hash
- `idx_uploaded_by` - Index for user filtering
- `idx_upload_date` - Index for date sorting

#### 2. `document_versions` Table
Archives previous versions when documents are replaced.

| Field | Type | Description |
|-------|------|-------------|
| `version_id` | TEXT (PK) | Unique version identifier (UUID) |
| `doc_id` | TEXT (FK) | Original document ID |
| `file_name` | TEXT | Filename at time of archival |
| `version_number` | INTEGER | Version number (1, 2, 3...) |
| `upload_date` | TEXT | Original upload date |
| `archived_date` | TEXT | When this version was archived |
| `file_size_bytes` | INTEGER | File size at archival |
| `chunks` | INTEGER | Number of chunks |
| `uploaded_by` | TEXT | Original uploader |
| `content_hash` | TEXT | Content hash at archival |
| `page_count` | INTEGER | Page count |
| `replaced_by` | TEXT | User who replaced this version |

**Indexes:**
- `idx_version_doc_id` - Index for document version lookups

### Weaviate Collections

#### 1. `Document` Collection
Stores document-level metadata.

| Property | Type | Description |
|----------|------|-------------|
| `doc_id` | string | Unique document identifier |
| `file_name` | string | Original filename |
| `page_count` | int | Number of pages |

#### 2. `DocumentChunk` Collection
Stores individual text chunks with embeddings.

| Property | Type | Description |
|----------|------|-------------|
| `chunk_id` | string | Unique chunk identifier |
| `doc_id` | string | Parent document ID (cross-reference) |
| `text` | text | Chunk text content (vectorized) |
| `page` | int | Source page number |
| `chunk_type` | string | Type: "paragraph", "table", "heading" |
| `metadata` | object | Additional chunk metadata |

**Vector Configuration:**
- Model: `text-embedding-3-small`
- Dimensions: 1536
- Distance Metric: Cosine similarity

---

## API Endpoints

### PDF Routes (`/pdf`)

#### `POST /pdf/parse-pdf`
Parse PDF and perform early duplicate detection.

**Request:**
```
Content-Type: multipart/form-data
- file: PDF file (required)
- force_reparse: string (optional, default: "false") - "true" to skip duplicate check
```

> **Note:** `force_reparse` is sent as a Form field string and converted to boolean on the backend.

**Response (Success - 200):**
```json
{
  "chunks": [...],
  "document_metadata": {...},
  "content_hash": "sha256...",
  "file_size_bytes": 123456
}
```

**Response (Duplicate - 409):**
```json
{
  "detail": {
    "error": "duplicate_detected",
    "message": "This document already exists...",
    "duplicate_type": "filename|content_hash",
    "existing_doc": {
      "doc_id": "...",
      "file_name": "...",
      "upload_date": "...",
      "chunks": 42,
      "file_size_bytes": 123456,
      "uploaded_by": "user@example.com"
    },
    "action_required": "Use the 'Override' button..."
  }
}
```

### Knowledge Base Routes (`/kb`)

#### `POST /kb/upload-to-kb`
Upload processed chunks to knowledge base.

**Request:**
```json
{
  "chunks": [...],
  "document_metadata": {...},
  "source_filename": "document.pdf",
  "content_hash": "sha256...",
  "file_size_bytes": 123456,
  "force_replace": false
}
```

**Response:**
```json
{
  "success": true,
  "message": "Successfully uploaded 42 chunks...",
  "doc_id": "uuid...",
  "weaviate_doc_id": "uuid...",
  "action": "uploaded|replaced",
  "version": 1,
  "version_info": {
    "previous_version_archived": true,
    "new_version": 2,
    "previous_version": {
      "version_number": 1,
      "doc_id": "...",
      "uploaded_by": "...",
      "upload_date": "..."
    }
  }
}
```

#### `GET /kb/list-kb`
List all documents in knowledge base.

**Query Parameters:**
- `limit` (int): Max results (default: 100)
- `offset` (int): Pagination offset (default: 0)
- `uploaded_by` (string): Filter by user
- `order_by` (string): Sort field (default: upload_date)
- `order_dir` (string): ASC/DESC (default: DESC)

#### `GET /kb/document-versions/{file_name}`
Get version history for a document.

**Response:**
```json
{
  "success": true,
  "file_name": "document.pdf",
  "current_version": {
    "doc_id": "...",
    "version": 2,
    "upload_date": "...",
    "uploaded_by": "...",
    "chunks": 42,
    "file_size_bytes": 123456,
    "is_current": true
  },
  "version_history": [
    {
      "version_id": "...",
      "version": 1,
      "upload_date": "...",
      "archived_date": "...",
      "uploaded_by": "...",
      "chunks": 40,
      "is_current": false
    }
  ],
  "total_versions": 2
}
```

#### `DELETE /kb/delete-document/{doc_id}`
Delete a document from knowledge base.

---

## Step-by-Step Process Flow

### 1. Document Upload Flow

```
Step 1: User selects PDF file
        ↓
Step 2: Frontend sends file to POST /pdf/parse-pdf
        ↓
Step 3: Backend calculates SHA256 content hash
        ↓
Step 4: Duplicate Detection Check
        ├─→ Check SQLite by filename (UNIQUE constraint)
        └─→ Check SQLite by content_hash (UNIQUE constraint)
        ↓
Step 5: If duplicate found → Return 409 with existing doc info
        If no duplicate → Continue parsing
        ↓
Step 6: PDF Extraction
        ├─→ Extract text from pages
        ├─→ Extract tables
        └─→ Extract metadata (page count, etc.)
        ↓
Step 7: Chunking Process
        ├─→ Split text into semantic chunks
        ├─→ Assign chunk IDs
        └─→ Calculate bounding boxes for highlights
        ↓
Step 8: Return chunks to frontend for preview
        ↓
Step 9: User reviews and edits chunks (optional)
        ↓
Step 10: User clicks "Upload to Knowledge Base"
         ↓
Step 11: Frontend sends POST /kb/upload-to-kb
         ↓
Step 12: Backend inserts to Weaviate
         ├─→ Create Document record
         └─→ Create DocumentChunk records (with embeddings)
         ↓
Step 13: Backend saves to SQLite documents table
         ↓
Step 14: Return success response to frontend
```

### 2. Duplicate Override Flow (Updated)

```
Step 1: User uploads file that triggers duplicate detection (409)
        ↓
Step 2: Frontend shows "Duplicate Detected" modal
        ├─→ Shows existing document details
        └─→ Shows "View Version History" button
        ↓
Step 3: User clicks "Override" button
        ↓
Step 4: Frontend shows "Confirm Override" modal
        ├─→ Warning message about replacement
        └─→ Info about version history preservation
        ↓
Step 5: User clicks "Yes, Override"
        ↓
Step 6: Frontend RE-PARSES the PDF first
        ├─→ POST /pdf/parse-pdf with force_reparse="true"
        ├─→ Sets forceReplaceMode=true in state
        └─→ Saves parsed data to localStorage
        ↓
Step 7: Backend skips duplicate check (force_reparse=true)
        ├─→ Parses PDF and extracts chunks
        └─→ Returns chunks to frontend
        ↓
Step 8: User reviews parsed chunks (optional editing)
        ↓
Step 9: User clicks "Upload to Knowledge Base"
        ↓
Step 10: Frontend sends POST /kb/upload-to-kb with force_replace=true
         ↓
Step 11: Backend archives current version
         ├─→ Copy document record to document_versions table
         ├─→ Set archived_date and replaced_by
         └─→ Calculate next version number
         ↓
Step 12: Backend deletes old document
         ├─→ Delete from SQLite documents table
         └─→ Delete from Weaviate using weaviate_doc_id
         ↓
Step 13: Backend inserts new document
         ├─→ New UUID for doc_id
         ├─→ Set current_version to next version number
         └─→ Insert to Weaviate and SQLite
         ↓
Step 14: Return success with version info
         ↓
Step 15: Frontend clears localStorage and shows success modal
```

> **Key Change:** The override flow now re-parses the PDF before uploading, allowing users to review/edit the new chunks before replacing the existing document.

### 3. Query/Search Flow

```
Step 1: User enters query in chat interface
        ↓
Step 2: Frontend sends POST /chat/send
        ↓
Step 3: Backend generates query embedding
        └─→ OpenAI text-embedding-3-small
        ↓
Step 4: Weaviate vector similarity search
        ├─→ Find top-k similar chunks
        └─→ Return chunks with similarity scores
        ↓
Step 5: Context assembly
        ├─→ Rank chunks by relevance
        └─→ Build context from top chunks
        ↓
Step 6: Generate AI response
        └─→ Send context + query to OpenAI GPT
        ↓
Step 7: Return response to frontend
```

---

## Duplicate Detection System

### Detection Strategy

The system uses **early detection** in the `/pdf/parse-pdf` endpoint to avoid unnecessary API costs.

### Detection Methods

| Method | Field Checked | Purpose |
|--------|---------------|---------|
| Filename Match | `file_name` | Detect same document re-upload |
| Content Hash Match | `content_hash` | Detect identical content (different filename) |

### Detection Logic

```python
def check_duplicates(filename, content_hash):
    # Check filename first (fast lookup via index)
    existing_by_name = check_duplicate_by_filename(filename)
    
    # Check content hash (fast lookup via index)
    existing_by_hash = check_duplicate_by_hash(content_hash)
    
    if existing_by_name or existing_by_hash:
        return {
            'is_duplicate': True,
            'duplicate_type': 'filename' or 'content_hash',
            'existing_doc': {...},
            'message': 'Duplicate detected...'
        }
    
    return {'is_duplicate': False}
```

### Cost Optimization

- Detection happens **before** PDF parsing
- No OpenAI API calls for duplicates
- No Weaviate operations for duplicates
- Estimated savings: ~$0.02-0.10 per duplicate blocked

---

## Document Versioning System

### Version Strategy: Replace with History Tracking

When a document is replaced:
1. Current version is archived to `document_versions` table
2. Old data is deleted from Weaviate (no vector storage of old versions)
3. New version is inserted with incremented version number
4. Only the latest version is searchable

### Version Number Calculation

```python
def get_next_version_number(file_name):
    # Get highest version from archives
    max_archived = SELECT MAX(version_number) FROM document_versions 
                   WHERE file_name = ?
    
    # Get current document version
    current_version = SELECT current_version FROM documents 
                      WHERE file_name = ?
    
    # Return next version
    return max(max_archived, current_version) + 1
```

### Version History Access

Users can view version history:
- From the duplicate detection modal ("View Version History" button)
- From the document list (History icon button per row)

---

## Session Persistence System

### Purpose

Parsed document chunks are stored in localStorage to:
- Survive page refresh without re-parsing
- Allow users to navigate away and return to their work
- Preserve `forceReplaceMode` state for override operations

### Storage Structure

**Location:** Browser localStorage

**Keys:**
| Key | Purpose |
|-----|---------|
| `docuextract_parsed_data` | Chunked output from parsing |
| `docuextract_filename` | Original filename |
| `docuextract_force_replace` | Force replace mode flag |

### Storage Functions (token.js)

```javascript
// Storage keys
export const PARSED_DOCUMENT_DATA = 'docuextract_parsed_data';
export const PARSED_DOCUMENT_FILENAME = 'docuextract_filename';
export const FORCE_REPLACE_MODE = 'docuextract_force_replace';

// Clear all document storage
export const clearDocumentStorage = () => {
  localStorage.removeItem(PARSED_DOCUMENT_DATA);
  localStorage.removeItem(PARSED_DOCUMENT_FILENAME);
  localStorage.removeItem(FORCE_REPLACE_MODE);
};

// Save parsed document to storage
export const saveDocumentToStorage = (chunkedOutput, filename, forceReplaceMode) => {
  try {
    localStorage.setItem(PARSED_DOCUMENT_DATA, JSON.stringify(chunkedOutput));
    localStorage.setItem(PARSED_DOCUMENT_FILENAME, filename);
    localStorage.setItem(FORCE_REPLACE_MODE, String(forceReplaceMode));
  } catch (e) {
    console.error('Failed to save document to storage:', e);
  }
};

// Load parsed document from storage
export const loadDocumentFromStorage = () => {
  try {
    const data = localStorage.getItem(PARSED_DOCUMENT_DATA);
    const filename = localStorage.getItem(PARSED_DOCUMENT_FILENAME);
    const forceReplace = localStorage.getItem(FORCE_REPLACE_MODE);
    
    if (data && filename) {
      return {
        chunkedOutput: JSON.parse(data),
        filename,
        forceReplaceMode: forceReplace === 'true'
      };
    }
  } catch (e) {
    console.error('Failed to load document from storage:', e);
  }
  return null;
};
```

### Storage Lifecycle

| Event | Action |
|-------|--------|
| Successful parse | Save to localStorage |
| Force reparse (override) | Clear old, save new |
| Select new file | Clear localStorage |
| Clear Selection click | Clear localStorage |
| Upload to KB success | Clear localStorage |
| Logout | Clear localStorage |
| Component mount | Load from localStorage if exists |

### Security Considerations

- Data cleared on logout via `handleLogout()` in App.jsx
- No sensitive data (tokens) stored in document storage
- Clear on new file selection prevents cross-document contamination

---

## Frontend Components

### DocumentExtraction.jsx

**State Variables:**
```javascript
// Core states
const [selectedFile, setSelectedFile] = useState(null);
const [chunkedOutput, setChunkedOutput] = useState(null);
const [isLoading, setIsLoading] = useState(false);

// Duplicate detection states
const [showDuplicateModal, setShowDuplicateModal] = useState(false);
const [duplicateInfo, setDuplicateInfo] = useState(null);
const [showOverrideConfirm, setShowOverrideConfirm] = useState(false);
const [forceReplaceMode, setForceReplaceMode] = useState(false); // Track override mode

// Session persistence states
const [persistedFilename, setPersistedFilename] = useState(null); // For restored sessions

// Version history states
const [showVersionHistory, setShowVersionHistory] = useState(false);
const [versionHistoryData, setVersionHistoryData] = useState(null);
const [isLoadingVersions, setIsLoadingVersions] = useState(false);

// Upload states
const [isUploadingToKB, setIsUploadingToKB] = useState(false);
const [showSuccessModal, setShowSuccessModal] = useState(false);
const [uploadSuccess, setUploadSuccess] = useState(null);
```

**Key Functions:**
| Function | Purpose |
|----------|---------|
| `handleFileChange()` | Handle PDF file selection, clear localStorage |
| `handleParse()` | Parse PDF, save to localStorage |
| `handleUploadToKB()` | Upload to KB (uses `forceReplaceMode` flag) |
| `handleForceReparse()` | Re-parse PDF for override flow, sets `forceReplaceMode=true` |
| `getCurrentFilename()` | Get filename from selectedFile or persistedFilename |
| `fetchVersionHistory()` | Load version history for document |
| `fetchUploadHistory()` | Load document list |
| `handleDeleteHistory()` | Delete document from KB |

### Modal Components

1. **Duplicate Detection Modal**
   - Shows when duplicate is detected
   - Displays existing document details
   - Options: Cancel, View History, Override

2. **Override Confirmation Modal**
   - Second confirmation before replacement
   - Warning about version archival
   - Options: Cancel, Yes Override

3. **Version History Modal**
   - Shows current version details
   - Lists all archived versions
   - Displays upload/archive dates

4. **Success Modal**
   - Confirms successful upload
   - Shows version number
   - Shows previous version info (if replaced)

---

## Security Considerations

1. **Authentication**: JWT tokens required for uploads
2. **Input Validation**: Filename sanitization, chunk limits
3. **File Validation**: PDF format verification
4. **SQL Injection**: Parameterized queries in SQLite
5. **CORS**: Configured for allowed origins

---

## Performance Optimizations

1. **Early Duplicate Detection**: Saves API costs
2. **Database Indexes**: Fast lookups by filename/hash
3. **Pagination**: Efficient document listing
4. **Lazy Loading**: Version history loaded on demand
5. **Client-side Filtering**: Reduces API calls

---

## Error Handling

| HTTP Code | Scenario | Response |
|-----------|----------|----------|
| 200 | Success | Operation completed |
| 400 | Bad Request | Invalid input data |
| 401 | Unauthorized | Missing/invalid JWT |
| 404 | Not Found | Document doesn't exist |
| 409 | Conflict | Duplicate detected |
| 500 | Server Error | Internal error |

---

*For diagrams, see [DOCUEXTRACT_DIAGRAMS.md](./DOCUEXTRACT_DIAGRAMS.md)*

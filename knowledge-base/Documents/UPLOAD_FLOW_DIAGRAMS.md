# Upload Flow Comparison: Before vs After

## BEFORE: Duplicate Detection After Parsing ❌

```
┌─────────────┐
│   User      │
│ Uploads PDF │
└──────┬──────┘
       │
       ▼
┌─────────────────────────┐
│  POST /pdf/parse-pdf    │
│  - Validate file        │
│  - Calculate hash       │
└──────┬──────────────────┘
       │
       ▼
┌─────────────────────────┐
│  Parse PDF              │  🕐 2-5 seconds
│  - pdfplumber extract   │
│  - fitz images          │
└──────┬──────────────────┘
       │
       ▼
┌─────────────────────────┐
│  AI Chunking            │  🕐 3-8 seconds
│  - GPT-4o text          │  💰 $0.05-0.20 cost
│  - GPT-4o vision        │
└──────┬──────────────────┘
       │
       ▼
┌─────────────────────────┐
│  Anchoring              │  🕐 1-3 seconds
│  - Match coordinates    │
└──────┬──────────────────┘
       │
       ▼ Return chunks
┌─────────────────────────┐
│ POST /kb/upload-to-kb   │
│ - Check duplicate ❌    │  ⚠️ TOO LATE!
└──────┬──────────────────┘
       │
       ├─ IF DUPLICATE:
       │  └─ Return 409 (already wasted $0.05-0.20)
       │
       └─ IF NEW:
          └─ Save to Weaviate + JSON

Total Time for Duplicate: 10-25 seconds + wasted AI costs
```

---

## AFTER: Early Duplicate Detection ✅

```
┌─────────────┐
│   User      │
│ Uploads PDF │
└──────┬──────┘
       │
       ▼
┌─────────────────────────┐
│  POST /pdf/parse-pdf    │
│  - Validate file        │
│  - Calculate hash       │  🕐 ~10ms
└──────┬──────────────────┘
       │
       ▼
┌─────────────────────────┐
│  Check document_db      │  🕐 1-5ms (indexed)
│  1. Query by filename   │
│  2. Query by hash       │
└──────┬──────────────────┘
       │
       ├─────────────────────────────┐
       │                             │
       ▼ DUPLICATE FOUND ❌          ▼ NEW FILE ✅
┌─────────────────────────┐    ┌─────────────────────────┐
│  Return 409 Conflict    │    │  Parse PDF              │  🕐 2-5 seconds
│  - existing_doc info    │    │  - pdfplumber extract   │
│  - cost_saved message   │    │  - fitz images          │
│  - suggestion           │    └──────┬──────────────────┘
└─────────────────────────┘           │
                                      ▼
  Total: 10ms ⚡              ┌─────────────────────────┐
  Cost: $0 💰                 │  AI Chunking            │  🕐 3-8 seconds
  Saved: $0.05-0.20 ✨        │  - GPT-4o text          │  💰 $0.05-0.20 cost
                              │  - GPT-4o vision        │
                              └──────┬──────────────────┘
                                     │
                                     ▼
                              ┌─────────────────────────┐
                              │  Anchoring              │  🕐 1-3 seconds
                              │  - Match coordinates    │
                              └──────┬──────────────────┘
                                     │
                                     ▼ Return chunks
                              ┌─────────────────────────┐
                              │ POST /kb/upload-to-kb   │
                              │ - Save to Weaviate      │
                              │ - Save to document_db ✅│
                              │ - Save JSON backup      │
                              └─────────────────────────┘

Total Time for Duplicate: 10ms (1000x faster!)
Total Time for New File: 10-25 seconds (same as before)
```

---

## Database Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     FRONTEND (React)                        │
│  - Upload component                                         │
│  - Document list table                                      │
│  - Duplicate warning modal                                  │
└────────────┬───────────────────────────┬────────────────────┘
             │                           │
             │ POST /pdf/parse-pdf       │ GET /kb/list-kb
             │ POST /kb/upload-to-kb     │ POST /kb/check-duplicate
             │                           │
             ▼                           ▼
┌─────────────────────────────────────────────────────────────┐
│                   BACKEND (FastAPI)                         │
│                                                             │
│  ┌──────────────────┐        ┌────────────────────┐        │
│  │  pdf_routes.py   │        │   kb_routes.py     │        │
│  │  - parse-pdf     │        │   - upload-to-kb   │        │
│  │  - duplicate     │        │   - list-kb        │        │
│  │    check (NEW) ✅│        │   - check-duplicate│        │
│  └────────┬─────────┘        └─────────┬──────────┘        │
│           │                            │                    │
│           ▼                            ▼                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         database/document_db.py (NEW) ✅            │   │
│  │  - check_duplicate_by_filename()                    │   │
│  │  - check_duplicate_by_hash()                        │   │
│  │  - insert_document()                                │   │
│  │  - list_documents()                                 │   │
│  │  - get_document_count()                             │   │
│  └──────────────────┬──────────────────────────────────┘   │
│                     │                                       │
└─────────────────────┼───────────────────────────────────────┘
                      │
                      ▼
         ┌────────────────────────┐
         │   documents.db         │  ◄── LOCAL SQLITE DATABASE (NEW) ✅
         │   (SQLite)             │
         │                        │
         │  documents table:      │
         │  - doc_id              │
         │  - file_name           │
         │  - upload_date         │
         │  - file_size_bytes     │
         │  - chunks              │
         │  - uploaded_by ✅      │
         │  - content_hash        │
         │  - page_count          │
         │  - weaviate_doc_id     │
         │  - json_backup_path    │
         │  - metadata            │
         │                        │
         │  Indexes:              │
         │  - idx_file_name       │  ◄── Fast filename lookup
         │  - idx_content_hash    │  ◄── Fast content lookup
         │  - idx_uploaded_by     │  ◄── Filter by user
         │  - idx_upload_date     │  ◄── Sort by date
         └────────────────────────┘

         ┌────────────────────────┐
         │   Weaviate Cloud       │  ◄── VECTOR DATABASE (unchanged)
         │                        │
         │  Document collection:  │
         │  - file_name           │
         │  - page_count          │
         │  - content_hash        │
         │  - file_size_bytes     │
         │  - upload_timestamp    │
         │                        │
         │  KnowledgeBase:        │
         │  - text (vectorized)   │
         │  - type, section       │
         │  - tags, page          │
         │  - ofDocument ref      │
         └────────────────────────┘

         ┌────────────────────────┐
         │   JSON Backups         │  ◄── DEBUG FILES (unchanged)
         │   kb_*.json            │
         └────────────────────────┘
```

---

## Data Flow: Upload with Duplicate Detection

```
Step 1: User selects file
        ↓
Step 2: Frontend uploads to /pdf/parse-pdf
        {
          file: <binary>,
          force_reparse: false
        }
        ↓
Step 3: Backend calculates SHA256 hash
        hash = "a3f5b8c2d1e4f6a9..."
        ↓
Step 4: Check document_db.check_duplicate_by_filename()
        Query: SELECT * FROM documents WHERE file_name = ?
        Index: idx_file_name (UNIQUE)
        Time: ~1ms
        ↓
        ├─ Found? → Return 409 Conflict (STOP HERE)
        └─ Not found? → Continue...
        ↓
Step 5: Check document_db.check_duplicate_by_hash()
        Query: SELECT * FROM documents WHERE content_hash = ?
        Index: idx_content_hash (UNIQUE)
        Time: ~1-5ms
        ↓
        ├─ Found? → Return 409 Conflict (renamed duplicate)
        └─ Not found? → Continue...
        ↓
Step 6: Parse PDF (2-5s)
        ↓
Step 7: AI Chunking (3-8s, $0.05-0.20)
        ↓
Step 8: Anchoring (1-3s)
        ↓
Step 9: Return chunks + hash + size
        ↓
Step 10: Frontend uploads to /kb/upload-to-kb
         {
           chunks: [...],
           source_filename: "policy.pdf",
           content_hash: "a3f5b8c2...",
           file_size_bytes: 2621440
         }
         ↓
Step 11: Save to Weaviate (vector embeddings)
         insert_document(file_metadata, chunks)
         ↓
Step 12: Save to document_db
         doc_db.insert_document({
           doc_id: uuid.uuid4(),
           file_name: "policy.pdf",
           chunks: 8,
           uploaded_by: "user@email.com",  ◄── NEW ✅
           content_hash: "a3f5b8c2...",
           ...
         })
         ↓
Step 13: Save JSON backup
         kb_20251121_103100_policy.json
         ↓
Step 14: Return success
         {
           doc_id: "...",
           weaviate_doc_id: "...",
           action: "uploaded"
         }
```

---

## List Documents Flow

### BEFORE (Reading JSON Files) ❌
```
GET /kb/list-kb
  ↓
Find all kb_*.json files (glob)
  ↓
For each file:
  - Open file
  - Parse JSON (CPU intensive)
  - Extract metadata
  ↓
Sort by upload_time
  ↓
Return list

Time: 100-500ms for 50 files
Scalability: Poor (O(n) file reads)
```

### AFTER (Database Query) ✅
```
GET /kb/list-kb?limit=100&offset=0&order_by=upload_date&order_dir=DESC
  ↓
doc_db.list_documents(limit, offset, order_by, order_dir)
  ↓
SQL Query:
SELECT doc_id, file_name, upload_date, file_size_bytes, 
       chunks, uploaded_by, content_hash, page_count
FROM documents
ORDER BY upload_date DESC
LIMIT 100 OFFSET 0
  ↓
Index: idx_upload_date (for fast sorting)
  ↓
Return formatted list with human-readable sizes

Time: 10-20ms for 100 documents
Scalability: Excellent (indexed queries)
Pagination: Built-in support
```

---

## API Response Examples

### Parse PDF - Duplicate Filename
```json
POST /pdf/parse-pdf
Response: 409 Conflict

{
  "detail": {
    "error": "duplicate_filename",
    "message": "Document 'policy.pdf' has already been uploaded and parsed.",
    "existing_doc": {
      "doc_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
      "file_name": "policy.pdf",
      "upload_date": "2025-11-21T10:30:45.123456",
      "chunks": 8,
      "file_size_bytes": 2621440
    },
    "suggestion": "Use force_reparse=true to parse again, or use the existing parsed data.",
    "cost_saved": "Avoided re-parsing. Saved ~$0.05-0.20 in OpenAI API costs."
  }
}
```

### Parse PDF - Duplicate Content (Renamed)
```json
POST /pdf/parse-pdf
Response: 409 Conflict

{
  "detail": {
    "error": "duplicate_content",
    "message": "This file content has already been uploaded as 'old_policy.pdf'.",
    "existing_doc": {
      "doc_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
      "file_name": "old_policy.pdf",
      "upload_date": "2025-11-20T15:20:30.000000",
      "chunks": 8,
      "file_size_bytes": 2621440
    },
    "suggestion": "This is a renamed duplicate. Use the existing parsed data.",
    "cost_saved": "Avoided re-parsing identical content. Saved ~$0.05-0.20 in OpenAI API costs."
  }
}
```

### List Documents
```json
GET /kb/list-kb?limit=10&offset=0
Response: 200 OK

{
  "success": true,
  "total_count": 25,
  "count": 10,
  "offset": 0,
  "limit": 10,
  "documents": [
    {
      "doc_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
      "file_name": "company_policy.pdf",
      "upload_date": "2025-11-21T10:30:45.123456",
      "file_size_bytes": 2621440,
      "file_size_formatted": "2.50 MB",
      "chunks": 8,
      "uploaded_by": "john.doe@company.com",  ◄── NEW ✅
      "page_count": 2
    },
    {
      "doc_id": "b2c3d4e5-f6a7-8b9c-0d1e-2f3a4b5c6d7e",
      "file_name": "employee_handbook.pdf",
      "upload_date": "2025-11-20T14:15:30.000000",
      "file_size_bytes": 5242880,
      "file_size_formatted": "5.00 MB",
      "chunks": 15,
      "uploaded_by": "jane.smith@company.com",  ◄── NEW ✅
      "page_count": 10
    }
  ]
}
```

---

## Cost Savings Calculator

### Scenario: 1000 document uploads per year

**Without early duplicate detection**:
- Duplicate rate: 30% (300 duplicates)
- Cost per duplicate: $0.10 (average)
- Annual waste: 300 × $0.10 = **$30**

**With early duplicate detection**:
- Duplicates detected in 10ms
- Cost per duplicate: $0
- Annual savings: **$30**

### Scenario: 10,000 document uploads per year

**Without early duplicate detection**:
- Duplicate rate: 30% (3,000 duplicates)
- Cost per duplicate: $0.10 (average)
- Annual waste: 3,000 × $0.10 = **$300**

**With early duplicate detection**:
- Duplicates detected in 10ms
- Cost per duplicate: $0
- Annual savings: **$300**

### Time Savings

**Per duplicate upload**:
- Before: 10-25 seconds (full parsing)
- After: 10ms (database query)
- Time saved: ~10-25 seconds per duplicate

**1000 duplicates per year**:
- Time saved: 1000 × 15s (avg) = **15,000 seconds = 4.2 hours**

**10,000 duplicates per year**:
- Time saved: 10,000 × 15s (avg) = **150,000 seconds = 41.7 hours**

---

**Diagram Version**: 1.0
**Last Updated**: November 21, 2025

# Document Tracking Database Implementation

## Overview
This implementation adds a local SQLite database to track all uploaded documents with metadata, separate from the Weaviate vector database. It also optimizes duplicate detection to happen **before** PDF parsing, saving significant processing costs.

---

## Key Improvements

### 1. **Early Duplicate Detection (Cost Savings)**
- **Before**: Duplicates detected after parsing → wasted OpenAI API costs ($0.05-0.20 per document)
- **After**: Duplicates detected before parsing → parsing only happens for new files
- **Savings**: ~$5-20 per 100 duplicate uploads avoided

### 2. **Local Document Database**
- **Purpose**: Fast metadata access for frontend display
- **Database**: SQLite (`documents.db`)
- **Benefits**: No need to query Weaviate for listing documents

### 3. **User Tracking**
- JWT token extraction for `uploaded_by` field
- Track which user uploaded each document

---

## Database Schema

### **documents** Table
```sql
CREATE TABLE documents (
    doc_id TEXT PRIMARY KEY,              -- UUID for this database
    file_name TEXT NOT NULL,               -- Original filename (e.g., "company_policy.pdf")
    upload_date TEXT NOT NULL,             -- ISO datetime (e.g., "2025-11-21T10:30:45.123456")
    file_size_bytes INTEGER NOT NULL,      -- File size in bytes
    chunks INTEGER NOT NULL,               -- Number of chunks created
    uploaded_by TEXT,                      -- User who uploaded (from JWT)
    content_hash TEXT UNIQUE NOT NULL,     -- SHA256 hash for duplicate detection
    page_count INTEGER,                    -- Number of pages in PDF
    weaviate_doc_id TEXT,                  -- Reference to Weaviate Document ID
    json_backup_path TEXT,                 -- Path to backup JSON file
    metadata TEXT                          -- JSON string of additional metadata
);

-- Indexes for fast lookups
CREATE UNIQUE INDEX idx_file_name ON documents(file_name);
CREATE UNIQUE INDEX idx_content_hash ON documents(content_hash);
CREATE INDEX idx_uploaded_by ON documents(uploaded_by);
CREATE INDEX idx_upload_date ON documents(upload_date);
```

---

## API Changes

### **POST /pdf/parse-pdf** (Updated)

**New Behavior**: Checks for duplicates BEFORE parsing

**Request Parameters**:
```javascript
POST /pdf/parse-pdf
Headers: {
  'Content-Type': 'multipart/form-data',
  'Authorization': 'Bearer <jwt_token>'  // Optional for user tracking
}
Body: FormData {
  file: <PDF binary>,
  force_reparse: false  // Set true to bypass duplicate check
}
```

**Response (409 Conflict - Duplicate Found)**:
```json
{
  "detail": {
    "error": "duplicate_filename",
    "message": "Document 'company_policy.pdf' has already been uploaded and parsed.",
    "existing_doc": {
      "doc_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
      "file_name": "company_policy.pdf",
      "upload_date": "2025-11-21T10:30:45.123456",
      "chunks": 8,
      "file_size_bytes": 2621440
    },
    "suggestion": "Use force_reparse=true to parse again, or use the existing parsed data.",
    "cost_saved": "Avoided re-parsing. Saved ~$0.05-0.20 in OpenAI API costs."
  }
}
```

**Response (409 Conflict - Content Duplicate)**:
```json
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

**Success Response (200 OK - New File)**:
```json
{
  "chunks": [/* array of chunks */],
  "document_metadata": {
    "total_pages": 2,
    "total_chunks": 8
  },
  "content_hash": "a3f5b8c2d1e4f6a9...",
  "file_size_bytes": 2621440
}
```

---

### **POST /kb/upload-to-kb** (Updated)

**New Behavior**: Saves to both Weaviate AND local document database

**Request Body**:
```json
{
  "chunks": [/* chunks from parse-pdf */],
  "document_metadata": {
    "total_pages": 2,
    "total_chunks": 8
  },
  "source_filename": "company_policy.pdf",
  "content_hash": "a3f5b8c2d1e4f6a9...",  // Required
  "file_size_bytes": 2621440,              // Required
  "force_replace": false
}
```

**Response (Success)**:
```json
{
  "success": true,
  "message": "Successfully uploaded 8 chunks to knowledge base",
  "doc_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",       // Document DB ID
  "weaviate_doc_id": "d7e8f9a0-b1c2-3d4e-5f6a-7b8c9d0e1f2a",  // Weaviate ID
  "filename": "kb_20251121_103100_company_policy.json",
  "action": "uploaded"
}
```

---

### **GET /kb/list-kb** (Completely Rewritten)

**Old Behavior**: Read from JSON files
**New Behavior**: Query document database (much faster!)

**Request Parameters**:
```
GET /kb/list-kb?limit=100&offset=0&order_by=upload_date&order_dir=DESC
```

**Query Parameters**:
- `limit` (int): Max results (default: 100)
- `offset` (int): Pagination offset (default: 0)
- `uploaded_by` (string): Filter by user (optional)
- `order_by` (string): Sort field - `upload_date`, `file_name`, `file_size_bytes`, `chunks` (default: `upload_date`)
- `order_dir` (string): `ASC` or `DESC` (default: `DESC`)

**Response**:
```json
{
  "success": true,
  "total_count": 25,
  "count": 10,
  "offset": 0,
  "limit": 100,
  "documents": [
    {
      "doc_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
      "file_name": "company_policy.pdf",
      "upload_date": "2025-11-21T10:30:45.123456",
      "file_size_bytes": 2621440,
      "file_size_formatted": "2.50 MB",
      "chunks": 8,
      "uploaded_by": "john.doe@company.com",
      "page_count": 2
    },
    {
      "doc_id": "b2c3d4e5-f6a7-8b9c-0d1e-2f3a4b5c6d7e",
      "file_name": "employee_handbook.pdf",
      "upload_date": "2025-11-20T14:15:30.000000",
      "file_size_bytes": 5242880,
      "file_size_formatted": "5.00 MB",
      "chunks": 15,
      "uploaded_by": "jane.smith@company.com",
      "page_count": 10
    }
  ]
}
```

---

### **POST /kb/check-duplicate** (Updated)

**New Behavior**: Queries local database instead of Weaviate

**Request**:
```json
POST /kb/check-duplicate
{
  "filename": "company_policy.pdf",
  "content_hash": "a3f5b8c2d1e4f6a9..."  // Optional
}
```

**Response (Duplicate Found)**:
```json
{
  "exists": true,
  "duplicate_type": "filename",  // or "content"
  "existing_doc": {
    "doc_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
    "file_name": "company_policy.pdf",
    "upload_date": "2025-11-21T10:30:45.123456",
    "file_size_bytes": 2621440,
    "chunks": 8,
    "uploaded_by": "john.doe@company.com"
  }
}
```

---

## Data Flow (Updated)

### **Upload Flow with Early Duplicate Detection**

```
1. User uploads PDF file
   ↓
2. Frontend: POST /pdf/parse-pdf with file
   ↓
3. Backend: Security validation (size, type, etc.)
   ↓
4. Backend: Calculate SHA256 hash (fast - ~10ms)
   ↓
5. Backend: Check document_db for duplicates
   ├─ Check by filename (fastest)
   └─ Check by content_hash (detects renamed files)
   ↓
6a. IF DUPLICATE FOUND:
    ├─ Return 409 Conflict with existing doc info
    ├─ Save cost: ~$0.05-0.20 per document
    └─ Frontend can use existing parsed data
   ↓
6b. IF NEW FILE:
    ├─ Parse PDF with pdfplumber/fitz (~2-5s)
    ├─ AI chunking with GPT-4 (~3-8s)
    ├─ Anchoring (~1-3s)
    └─ Return chunks + hash + size
   ↓
7. Frontend: POST /kb/upload-to-kb with chunks
   ↓
8. Backend: Save to Weaviate (vector embeddings)
   ↓
9. Backend: Save to document_db (metadata)
   ↓
10. Backend: Save JSON backup file
    ↓
11. Done! Document searchable and tracked
```

---

## Python Usage Examples

### **DocumentDatabase Class**

```python
from database.document_db import DocumentDatabase

# Initialize
doc_db = DocumentDatabase()

# Check for duplicate by filename
existing = doc_db.check_duplicate_by_filename("policy.pdf")
if existing:
    print(f"Duplicate found: {existing['doc_id']}")

# Check for duplicate by content hash
existing = doc_db.check_duplicate_by_hash("a3f5b8c2...")
if existing:
    print(f"Renamed duplicate of: {existing['file_name']}")

# Insert new document
doc_db.insert_document({
    "doc_id": "a1b2c3d4-...",
    "file_name": "policy.pdf",
    "file_size_bytes": 2621440,
    "chunks": 8,
    "uploaded_by": "john.doe@company.com",
    "content_hash": "a3f5b8c2...",
    "page_count": 2,
    "weaviate_doc_id": "d7e8f9a0-...",
    "json_backup_path": "kb_20251121_103100_policy.json",
    "metadata": {"total_pages": 2}
})

# List documents
docs = doc_db.list_documents(
    limit=50,
    offset=0,
    order_by="upload_date",
    order_dir="DESC"
)

# Get total count
count = doc_db.get_document_count()
print(f"Total documents: {count}")

# Filter by user
user_docs = doc_db.list_documents(
    uploaded_by="john.doe@company.com",
    limit=100
)

# Update document
doc_db.update_document("a1b2c3d4-...", {
    "chunks": 10,
    "page_count": 3
})

# Delete document
doc_db.delete_document("a1b2c3d4-...")
```

---

## Migration Script

### **Importing Existing Data**

If you have existing `kb_*.json` files, run the migration script to populate the database:

```bash
cd backend
python migrate_documents.py
```

**What it does**:
1. Scans for all `kb_*.json` files
2. Extracts metadata (filename, hash, size, chunks)
3. Parses upload date from filename
4. Inserts into `documents.db`
5. Skips duplicates automatically
6. Preserves original upload dates

**Example Output**:
```
================================================================================
DOCUMENT DATABASE MIGRATION
================================================================================

This will import all existing kb_*.json files into the document database.
Duplicates will be skipped automatically.

📁 Found 5 kb_*.json files

Processing: CV.pdf
  - Chunks: 12
  - Size: 1234567 bytes
  - Hash: a3f5b8c2d1e4f6a9...
  ✅ Imported successfully (ID: a1b2c3d4...)

Processing: Resume.pdf
  - Chunks: 8
  - Size: 987654 bytes
  - Hash: b4c5d6e7f8a9b0c1...
  ⏭️  Skipped (already exists as 'Resume.pdf')

================================================================================
MIGRATION COMPLETE
================================================================================
✅ Imported:  4 documents
⏭️  Skipped:   1 documents (already exist)
❌ Errors:    0 documents
📊 Total:     5 files processed

✨ Document database is now ready to use!
📍 Database location: documents.db
```

---

## Frontend Integration

### **Upload with Duplicate Handling**

```javascript
// Step 1: Parse PDF (with duplicate check)
async function uploadPDF(file) {
  const formData = new FormData();
  formData.append('file', file);
  
  try {
    const response = await fetch('/pdf/parse-pdf', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${jwtToken}`
      },
      body: formData
    });
    
    if (response.status === 409) {
      // Duplicate found!
      const data = await response.json();
      
      if (data.detail.error === 'duplicate_filename') {
        alert(`This file was already uploaded on ${data.detail.existing_doc.upload_date}`);
        // Option 1: Use existing data
        return { isDuplicate: true, existingDoc: data.detail.existing_doc };
      } else if (data.detail.error === 'duplicate_content') {
        alert(`This is a renamed copy of "${data.detail.existing_doc.file_name}"`);
        return { isDuplicate: true, existingDoc: data.detail.existing_doc };
      }
    }
    
    // New file - proceed to upload
    const parseData = await response.json();
    
    // Step 2: Upload to KB
    const uploadResponse = await fetch('/kb/upload-to-kb', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${jwtToken}`
      },
      body: JSON.stringify({
        chunks: parseData.chunks,
        document_metadata: parseData.document_metadata,
        source_filename: file.name,
        content_hash: parseData.content_hash,
        file_size_bytes: parseData.file_size_bytes
      })
    });
    
    const uploadData = await uploadResponse.json();
    return { success: true, docId: uploadData.doc_id };
    
  } catch (error) {
    console.error('Upload failed:', error);
    return { success: false, error: error.message };
  }
}
```

### **Display Document List**

```javascript
async function fetchDocuments(page = 1, limit = 20) {
  const offset = (page - 1) * limit;
  
  const response = await fetch(
    `/kb/list-kb?limit=${limit}&offset=${offset}&order_by=upload_date&order_dir=DESC`,
    {
      headers: {
        'Authorization': `Bearer ${jwtToken}`
      }
    }
  );
  
  const data = await response.json();
  
  return {
    documents: data.documents,
    totalCount: data.total_count,
    currentPage: page,
    totalPages: Math.ceil(data.total_count / limit)
  };
}

// Display in table
function renderDocumentsTable(documents) {
  const tableHTML = `
    <table>
      <thead>
        <tr>
          <th>File Name</th>
          <th>Upload Date</th>
          <th>File Size</th>
          <th>Chunks</th>
          <th>Uploaded By</th>
        </tr>
      </thead>
      <tbody>
        ${documents.map(doc => `
          <tr>
            <td>${doc.file_name}</td>
            <td>${new Date(doc.upload_date).toLocaleString()}</td>
            <td>${doc.file_size_formatted}</td>
            <td>${doc.chunks}</td>
            <td>${doc.uploaded_by}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
  
  document.getElementById('documentsTable').innerHTML = tableHTML;
}
```

---

## Performance Benefits

### **Cost Savings**
- **Old Flow**: Parse every file → $0.05-0.20 per duplicate
- **New Flow**: Check database first → $0 for duplicates
- **Savings**: ~$5-20 per 100 duplicate uploads

### **Speed Improvements**
- **Old Flow**: Parse (10-25s) → Check duplicate → Upload
- **New Flow**: Check duplicate (10ms) → Skip if exists
- **Speedup**: 1000x faster for duplicate detection

### **Database Performance**
- Filename lookup: ~1ms (indexed)
- Content hash lookup: ~1-5ms (indexed)
- List 100 documents: ~10-20ms
- Weaviate query (old): ~50-100ms

---

## Database Maintenance

### **Backup Database**
```bash
# SQLite database is just a file
cp documents.db documents_backup_20251121.db
```

### **View Database Content**
```bash
sqlite3 documents.db

# List all documents
SELECT file_name, upload_date, chunks FROM documents ORDER BY upload_date DESC;

# Count documents by user
SELECT uploaded_by, COUNT(*) FROM documents GROUP BY uploaded_by;

# Find large files
SELECT file_name, file_size_bytes FROM documents WHERE file_size_bytes > 5000000;
```

### **Database Size**
- ~1-2 KB per document record
- 10,000 documents = ~10-20 MB
- Very lightweight compared to Weaviate

---

## Troubleshooting

### **Migration Issues**

**Problem**: "No kb_*.json files found"
**Solution**: Run migration from `backend/` directory where JSON files are located

**Problem**: Duplicate entries during migration
**Solution**: Migration automatically skips duplicates based on content_hash

### **Database Locked Error**

**Problem**: `sqlite3.OperationalError: database is locked`
**Solution**: 
- Close other connections to `documents.db`
- SQLite doesn't handle high concurrency well
- For production, consider PostgreSQL

### **Missing uploaded_by Field**

**Problem**: Documents show "anonymous" in uploaded_by
**Solution**: 
- Ensure JWT token is sent in Authorization header
- Check JWT_SECRET_KEY in config matches auth server
- Verify token contains `sub`, `user_id`, or `email` claim

---

## Future Enhancements

1. **PostgreSQL Support**: For better concurrency
2. **Document Analytics**: Track views, searches per document
3. **Folder Organization**: Group documents by folders/tags
4. **Version History**: Track document updates over time
5. **Soft Delete**: Mark deleted instead of removing records
6. **Full-Text Search**: SQLite FTS5 for fast filename search

---

**Last Updated**: November 21, 2025
**Version**: 1.0

# Document Duplicate Detection & Validation

## Overview

This system prevents duplicate document uploads to the knowledge base using a **multi-layered validation approach** that checks both filename and content hash.

## Why Both Checks?

### 1. **Filename Check** (Fast)
- Catches obvious duplicates when users re-upload the same file
- Prevents accidental overwrites
- Quick database lookup

### 2. **Content Hash Check** (Comprehensive)
- Detects renamed duplicates (same content, different filename)
- Uses SHA256 hash for reliable content identification
- Prevents wasted storage and duplicate search results

## Implementation

### Database Schema Updates

The `Document` collection now includes:
```python
{
    "file_name": str,           # Original filename
    "page_count": int,          # Number of pages
    "content_hash": str,        # SHA256 hash of file content
    "file_size_bytes": int,     # File size in bytes
    "upload_timestamp": str     # ISO format timestamp
}
```

### New Validation Functions

**`document_validator.py`** provides:

1. **`calculate_file_hash(file_bytes)`**
   - Calculates SHA256 hash of file content
   - Returns hex string

2. **`check_document_exists_by_filename(filename)`**
   - Queries Weaviate for matching filename
   - Returns doc info if found, None otherwise

3. **`check_document_exists_by_hash(content_hash)`**
   - Queries Weaviate for matching content hash
   - Detects renamed duplicates

4. **`validate_document_upload(filename, file_bytes, allow_duplicates)`**
   - Comprehensive validation combining both checks
   - Returns validation result with error details

## API Changes

### 1. Enhanced Parse PDF Endpoint

**`POST /pdf/parse-pdf`**

Now automatically calculates and returns:
```json
{
  "chunks": [...],
  "document_metadata": {...},
  "content_hash": "abc123...",
  "file_size_bytes": 1234567
}
```

### 2. Enhanced Upload to KB Endpoint

**`POST /kb/upload-to-kb`**

New request fields:
```json
{
  "chunks": [...],
  "document_metadata": {...},
  "source_filename": "example.pdf",
  "content_hash": "abc123...",        // Optional
  "file_size_bytes": 1234567,         // Optional
  "force_replace": false              // Optional
}
```

**Behavior:**
- If duplicate detected → Returns `409 Conflict` with details
- If `force_replace=true` → Replaces existing document
- Otherwise → Inserts new document

**Error Response (409 Conflict):**
```json
{
  "detail": {
    "error": "duplicate_filename",  // or "duplicate_content"
    "message": "Document with filename 'example.pdf' already exists.",
    "existing_doc_id": "uuid-here",
    "existing_file_name": "example.pdf",
    "suggestion": "Set force_replace=true to overwrite the existing document."
  }
}
```

### 3. New Check Duplicate Endpoint

**`POST /kb/check-duplicate`**

Query params:
- `filename` (required): File to check
- `content_hash` (optional): Content hash to check

Response:
```json
{
  "exists": true,
  "duplicate_type": "filename",  // or "content"
  "existing_doc": {
    "doc_id": "uuid-here",
    "file_name": "example.pdf",
    "page_count": 10
  }
}
```

## Usage Workflow

### Standard Upload (with validation)

```python
# Frontend workflow:

# 1. Parse PDF
response = await fetch('/pdf/parse-pdf', {
    method: 'POST',
    body: formData
})
const { chunks, document_metadata, content_hash, file_size_bytes } = await response.json()

# 2. Upload to KB (will check for duplicates)
try {
    response = await fetch('/kb/upload-to-kb', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            chunks,
            document_metadata,
            source_filename: file.name,
            content_hash,
            file_size_bytes
        })
    })
    
    if (response.status === 409) {
        const error = await response.json()
        // Show user: "File already exists. Replace?"
        // If yes, retry with force_replace=true
    }
} catch (error) {
    console.error('Upload failed:', error)
}
```

### Force Replace Existing Document

```javascript
// User confirms replacement
await fetch('/kb/upload-to-kb', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        chunks,
        document_metadata,
        source_filename: file.name,
        content_hash,
        file_size_bytes,
        force_replace: true  // ← Replace existing
    })
})
```

### Pre-Upload Check

```javascript
// Check before parsing (optional optimization)
const checkResponse = await fetch(
    `/kb/check-duplicate?filename=${encodeURIComponent(file.name)}`
)
const { exists, duplicate_type, existing_doc } = await checkResponse.json()

if (exists) {
    // Warn user before parsing
    const proceed = confirm(
        `File "${existing_doc.file_name}" already exists. ` +
        `Upload anyway?`
    )
    if (!proceed) return
}
```

## Benefits

### Storage Efficiency
- **Prevents duplicate vector embeddings** (expensive in Weaviate)
- Saves storage space for identical content
- Reduces redundant processing

### Search Quality
- Avoids duplicate results in semantic search
- Cleaner knowledge base structure
- Better relevance scoring

### User Experience
- Clear error messages with actionable suggestions
- Option to replace or skip duplicates
- Transparent validation process

### Data Integrity
- Content-based detection catches renamed files
- Prevents accidental data loss via overwrites
- Maintains referential integrity with document IDs

## Error Handling

### Duplicate Filename
```json
{
  "error": "duplicate_filename",
  "message": "Document with filename 'report.pdf' already exists.",
  "suggestion": "Set force_replace=true to overwrite."
}
```

**Resolution:**
- Rename file
- Set `force_replace=true`
- Cancel upload

### Duplicate Content
```json
{
  "error": "duplicate_content",
  "message": "Document with identical content already exists as 'old-report.pdf'.",
  "suggestion": "This appears to be a renamed duplicate."
}
```

**Resolution:**
- Don't upload (content already exists)
- Verify this is actually different content
- Contact admin if hash collision suspected (extremely rare)

## Configuration

No configuration needed - validation is automatic.

To disable validation temporarily (not recommended):
```python
# In kb_routes.py, you could add a config flag:
ENABLE_DUPLICATE_CHECK = os.getenv("ENABLE_DUPLICATE_CHECK", "true").lower() == "true"
```

## Performance Considerations

### Filename Check
- **Speed:** Very fast (~10-50ms)
- **Method:** Single Weaviate query
- **Index:** Uses file_name property

### Content Hash Check
- **Speed:** Fast (~10-50ms)
- **Method:** Single Weaviate query
- **Index:** Uses content_hash property

### Hash Calculation
- **Speed:** Depends on file size
- **Small files (<1MB):** <10ms
- **Large files (10MB):** ~100ms
- Performed only once during PDF parsing

### Total Overhead
- **Typical case:** <100ms additional latency
- **Benefit:** Prevents expensive duplicate processing (embedding generation takes seconds)

## Testing

### Test Scenarios

1. **Upload new file** → Success
2. **Upload same file twice** → 409 Conflict on second attempt
3. **Upload renamed duplicate** → 409 Conflict (content hash matches)
4. **Force replace** → Success, old document replaced
5. **Different content, same name** → 409 Conflict (unless force_replace=true)

### Manual Testing

```bash
# 1. Upload a file
curl -X POST http://localhost:8009/pdf/parse-pdf \
  -F "file=@test.pdf"
# Save the content_hash from response

# 2. Upload to KB
curl -X POST http://localhost:8009/kb/upload-to-kb \
  -H "Content-Type: application/json" \
  -d '{
    "chunks": [...],
    "source_filename": "test.pdf",
    "content_hash": "abc123...",
    "document_metadata": {}
  }'

# 3. Try uploading same file again (should fail)
curl -X POST http://localhost:8009/kb/upload-to-kb \
  -H "Content-Type: application/json" \
  -d '{
    "chunks": [...],
    "source_filename": "test.pdf",
    "content_hash": "abc123...",
    "document_metadata": {}
  }'
# Expected: 409 Conflict

# 4. Check for duplicate
curl -X POST "http://localhost:8009/kb/check-duplicate?filename=test.pdf"
# Expected: {"exists": true, ...}
```

## Future Enhancements

### Possible Additions

1. **Partial Hash Matching**
   - Detect similar (not identical) documents
   - Use perceptual hashing for images
   - Similarity threshold configuration

2. **Version Control**
   - Keep multiple versions of same document
   - Track modification history
   - Restore previous versions

3. **Batch Duplicate Detection**
   - Check multiple files at once
   - Return list of duplicates before upload
   - Bulk operations

4. **Smart Merging**
   - Combine similar documents
   - Merge overlapping content
   - Intelligent deduplication

5. **Admin Dashboard**
   - View all documents with duplicates
   - Bulk delete/merge operations
   - Storage analytics

## Troubleshooting

### Hash Mismatches
**Problem:** Same file shows different hashes

**Causes:**
- File modified between checks
- Encoding issues
- Transfer corruption

**Solution:**
- Re-upload file
- Verify file integrity
- Check file permissions

### False Positives
**Problem:** Different files flagged as duplicates

**Causes:**
- Hash collision (extremely rare)
- Database sync issues

**Solution:**
- Check content_hash values manually
- Verify file content
- Report if genuine collision

### Performance Issues
**Problem:** Slow upload validation

**Causes:**
- Large file size
- Slow network to Weaviate
- High concurrent uploads

**Solution:**
- Optimize Weaviate indexes
- Consider async validation
- Add caching layer

## Security Considerations

### Hash Algorithm
- **SHA256** is cryptographically secure
- Collision probability: ~0 for practical purposes
- No risk of malicious collision attacks

### Data Privacy
- Hashes don't reveal file content
- Can be used as unique identifiers
- Safe to log/display

### Access Control
- Validation respects existing auth
- No new security surfaces introduced
- Same permissions as upload endpoint

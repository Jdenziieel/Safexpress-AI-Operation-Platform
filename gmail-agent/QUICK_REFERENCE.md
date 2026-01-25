# Quick Reference: Delivery Order Search Function

## Function Signature

```python
_search_emails_with_delivery_order_attachments_impl(
    query: str = "delivery order",
    max_results: int = 10,
    download_attachments: bool = True,
    temp_dir: str = None,
    credentials_dict: Dict = None
) -> Dict[str, Any]
```

## Basic Usage

```python
from tools import _search_emails_with_delivery_order_attachments_impl

result = _search_emails_with_delivery_order_attachments_impl(
    credentials_dict=your_oauth_credentials
)
```

## Common Patterns

### Pattern 1: Simple Search & Download
```python
result = _search_emails_with_delivery_order_attachments_impl(
    credentials_dict=creds
)
print(f"Downloaded {result['total_attachments_downloaded']} files")
print(f"Location: {result['temp_directory']}")
```

### Pattern 2: Custom Query
```python
result = _search_emails_with_delivery_order_attachments_impl(
    query="from:vendor@company.com subject:purchase",
    max_results=20,
    credentials_dict=creds
)
```

### Pattern 3: Metadata Only
```python
result = _search_emails_with_delivery_order_attachments_impl(
    download_attachments=False,  # Skip downloads
    credentials_dict=creds
)
```

### Pattern 4: Process Downloaded Files
```python
import pandas as pd
import os

result = _search_emails_with_delivery_order_attachments_impl(
    credentials_dict=creds
)

try:
    for email in result["emails_with_attachments"]:
        for att in email["attachments"]:
            if "spreadsheet" in att["mime_type"]:
                df = pd.read_excel(att["file_path"])
                # Process data...
finally:
    if result.get("temp_directory"):
        import shutil
        shutil.rmtree(result["temp_directory"])
```

### Pattern 5: Custom Save Location
```python
import os

save_dir = os.path.expanduser("~/delivery_orders")
os.makedirs(save_dir, exist_ok=True)

result = _search_emails_with_delivery_order_attachments_impl(
    temp_dir=save_dir,
    credentials_dict=creds
)
```

## Response Handling

```python
result = _search_emails_with_delivery_order_attachments_impl(...)

# Check success
if not result["success"]:
    if result.get("no_results"):
        print("No emails found")
    elif result.get("no_attachments"):
        print("No PDF/Excel files found")
    else:
        print(f"Error: {result['error']}")
else:
    # Success
    print(f"Found {len(result['emails_with_attachments'])} emails")
    print(f"Downloaded {result['total_attachments_downloaded']} files")
    print(f"Saved to: {result['temp_directory']}")
```

## Access Downloaded Files

```python
result = _search_emails_with_delivery_order_attachments_impl(...)

for email in result["emails_with_attachments"]:
    sender = email["from"]
    subject = email["subject"]
    timestamp = email["timestamp"]
    
    for attachment in email["attachments"]:
        filename = attachment["filename"]
        file_path = attachment["file_path"]
        mime_type = attachment["mime_type"]
        size = attachment["size"]
        
        print(f"{filename} ({mime_type}) - {size} bytes")
        print(f"Path: {file_path}")
```

## Error Scenarios

| Condition | Check |
|-----------|-------|
| No emails found | `if result.get("no_results"):` |
| No attachments | `if result.get("no_attachments"):` |
| API error | `if not result["success"]:` |
| Download failed | `if attachment.get("download_error"):` |

## Via API Endpoint

```bash
# Simple request
curl -X POST http://localhost:8000/execute_task \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "search_emails_with_delivery_order_attachments",
    "inputs": {
      "query": "delivery order",
      "max_results": 10
    },
    "credentials_dict": {"access_token": "...", "refresh_token": "..."}
  }'

# Custom query
curl -X POST http://localhost:8000/execute_task \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "search_emails_with_delivery_order_attachments",
    "inputs": {
      "query": "from:vendor@example.com",
      "max_results": 20,
      "download_attachments": true
    },
    "credentials_dict": {...}
  }'
```

## Key Parameters

| Parameter | Values | Default | Notes |
|-----------|--------|---------|-------|
| `query` | Any Gmail query string | `"delivery order"` | Use Gmail search syntax |
| `max_results` | 1-100 | 10 | Higher = slower but more results |
| `download_attachments` | true/false | true | Set false for metadata only |
| `temp_dir` | File path or None | None | Auto-creates if not provided |

## Supported File Types

- ✅ PDF (`.pdf`)
- ✅ Excel (`.xlsx`)
- ✅ Excel (`.xls`)
- ✅ Google Sheets
- ❌ Images, videos, archives not supported

## Performance Tips

1. **Metadata Only**: Set `download_attachments=False` to get results 2-3x faster
2. **Reduce Results**: Smaller `max_results` = faster execution
3. **Custom Query**: More specific queries = fewer emails to process
4. **Parallel Processing**: Download all files, then process in parallel

## Cleanup

```python
import shutil

result = _search_emails_with_delivery_order_attachments_impl(...)

try:
    # Process files...
    for email in result["emails_with_attachments"]:
        for att in email["attachments"]:
            process_file(att["file_path"])
finally:
    # Always cleanup temp directory
    if result.get("temp_directory"):
        shutil.rmtree(result["temp_directory"])
```

## Return Value Fields Reference

### Top-level Fields
- `success` (bool): Operation succeeded
- `emails_with_attachments` (list): Matched emails
- `total_emails_found` (int): Emails matching query
- `total_attachments_downloaded` (int): Files saved
- `temp_directory` (str): Directory path
- `query` (str): Search query used
- `error` (str): Error message
- `no_results` (bool): No emails found flag
- `no_attachments` (bool): No PDFs/Excel flag

### Email Object Fields
- `message_id` (str): Gmail ID
- `from` (str): Sender email
- `subject` (str): Subject line
- `date` (str): Date string
- `timestamp` (str): ISO 8601 format
- `internal_date_ms` (str): Gmail timestamp
- `attachments` (list): File list
- `attachment_count` (int): Number of files

### Attachment Fields
- `filename` (str): Original name
- `attachment_id` (str): Gmail ID
- `mime_type` (str): Content type
- `size` (int): Bytes
- `file_path` (str): Local path
- `download_error` (str): Error message (optional)

## Common Queries

```python
# Find all delivery orders
query = "delivery order"

# From specific sender
query = "from:supplier@company.com"

# By subject
query = "subject:purchase order"

# Recent emails
query = "delivery order after:2024/01/01"

# Specific sender AND subject
query = 'from:supplier@company.com subject:"delivery order"'

# Has attachments (automatic in this function)
# Filters for PDF and Excel only (automatic)
```

---

For complete documentation, see [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md)

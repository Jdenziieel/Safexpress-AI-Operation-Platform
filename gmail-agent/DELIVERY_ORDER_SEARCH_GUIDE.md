# Delivery Order Email Search & Attachment Download Guide

## Overview
The new `search_emails_with_delivery_order_attachments` function provides automated searching, filtering, and downloading of delivery order PDFs and Excel files from Gmail.

## Function Signature

```python
def _search_emails_with_delivery_order_attachments_impl(
    query: str = "delivery order",
    max_results: int = 10,
    download_attachments: bool = True,
    temp_dir: str = None,
    credentials_dict: Dict = None
) -> Dict[str, Any]
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | str | `"delivery order"` | Gmail search query to find relevant emails. Can include custom keywords. |
| `max_results` | int | `10` | Maximum number of emails to search through |
| `download_attachments` | bool | `True` | Whether to download attachment files locally |
| `temp_dir` | str | `None` | Directory path to save attachments. If None, auto-creates a temp directory |
| `credentials_dict` | Dict | Required | Gmail OAuth2 credentials with access tokens |

## Return Value

The function returns a structured dictionary with the following fields:

```python
{
    "success": bool,                           # Operation success status
    "emails_with_attachments": [              # List of emails with matching attachments
        {
            "message_id": str,                # Gmail message ID
            "from": str,                      # Sender email address
            "subject": str,                   # Email subject
            "date": str,                      # Email date string
            "timestamp": str,                 # ISO 8601 format timestamp
            "internal_date_ms": str,          # Gmail internal timestamp (ms)
            "attachments": [                  # List of downloaded attachment metadata
                {
                    "filename": str,          # Original filename
                    "attachment_id": str,     # Gmail attachment ID
                    "mime_type": str,         # MIME type (application/pdf, etc.)
                    "size": int,              # File size in bytes
                    "file_path": str,         # Local file path (if downloaded)
                    "download_error": str     # Error message if download failed (optional)
                }
            ],
            "attachment_count": int           # Number of attachments in email
        }
    ],
    "total_emails_found": int,                # Total emails matching query
    "total_attachments_downloaded": int,      # Number of files downloaded
    "temp_directory": str,                    # Temp directory path (if auto-created)
    "query": str,                             # Search query used
    "download_attachments": bool,             # Whether downloads were attempted
    "error": str,                             # Error message (if failed)
    "no_results": bool,                       # True if no emails matched (optional)
    "no_attachments": bool                    # True if no PDF/Excel found (optional)
}
```

## Supported File Types

The function automatically filters for:

- **PDF Documents**
  - MIME type: `application/pdf`
  - Extension: `.pdf`

- **Excel Spreadsheets**
  - MIME type: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` (`.xlsx`)
  - MIME type: `application/vnd.ms-excel` (`.xls`)
  - MIME type: `application/vnd.google-apps.spreadsheet` (Google Sheets)

## Usage Examples

### Basic Usage - Search for Delivery Orders
```python
result = _search_emails_with_delivery_order_attachments_impl(
    credentials_dict=user_credentials,
    query="delivery order",
    max_results=5
)

if result["success"]:
    print(f"Found {result['total_attachments_downloaded']} attachments")
    print(f"Saved to: {result['temp_directory']}")
```

### Custom Query
```python
result = _search_emails_with_delivery_order_attachments_impl(
    credentials_dict=user_credentials,
    query="from:supplier@company.com subject:invoice",
    max_results=20,
    download_attachments=True
)
```

### Specify Custom Temp Directory
```python
import os

custom_dir = os.path.expanduser("~/Downloads/delivery_orders")
os.makedirs(custom_dir, exist_ok=True)

result = _search_emails_with_delivery_order_attachments_impl(
    credentials_dict=user_credentials,
    query="delivery order",
    temp_dir=custom_dir,
    download_attachments=True
)
```

### Metadata-Only (No Downloads)
```python
result = _search_emails_with_delivery_order_attachments_impl(
    credentials_dict=user_credentials,
    query="delivery order",
    download_attachments=False  # Only get metadata
)

for email in result["emails_with_attachments"]:
    print(f"From: {email['from']}")
    print(f"Subject: {email['subject']}")
    for attachment in email['attachments']:
        print(f"  - {attachment['filename']} ({attachment['size']} bytes)")
```

## API Integration

### FastAPI Endpoint
The function is exposed via the `/execute_task` endpoint:

```bash
curl -X POST http://localhost:8000/execute_task \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "search_emails_with_delivery_order_attachments",
    "inputs": {
      "query": "delivery order",
      "max_results": 10,
      "download_attachments": true
    },
    "credentials_dict": {
      "access_token": "...",
      "refresh_token": "..."
    }
  }'
```

### Python SDK Usage
```python
import httpx

response = httpx.post(
    "http://localhost:8000/execute_task",
    json={
        "tool": "search_emails_with_delivery_order_attachments",
        "inputs": {
            "query": "delivery order",
            "max_results": 10,
            "download_attachments": True
        },
        "credentials_dict": credentials
    }
)

result = response.json()
```

## File Organization

When attachments are downloaded, they are organized as follows:

```
temp_directory/
├── message_id_1/
│   ├── delivery_order_001.pdf
│   ├── delivery_order_002.pdf
│   └── invoice.xlsx
├── message_id_2/
│   ├── order_details.pdf
│   └── shipment_info.xlsx
└── message_id_3/
    └── po_2024.xlsx
```

Each message gets its own subdirectory to prevent filename conflicts and maintain email context.

## Error Handling

The function handles multiple error scenarios:

| Scenario | Response |
|----------|----------|
| No emails found | `success: False`, `no_results: True` |
| No PDF/Excel files | `success: False`, `no_attachments: True` |
| Individual download fails | Attachment includes `download_error` field |
| Gmail API error | `success: False`, `error: "Gmail API error: ..."` |
| Invalid credentials | `success: False`, `error: "Gmail API error: ..."` |
| Invalid temp directory | Attachments not downloaded, but metadata returned |

## Metadata Extraction

The function extracts the following metadata from each email:

- **Sender**: Full email address from `From` header
- **Subject**: Email subject line
- **Date**: RFC 2822 formatted date
- **Timestamp**: ISO 8601 formatted timestamp (converted from Gmail's internal format)
- **Internal Date**: Original Gmail timestamp in milliseconds
- **Attachment Info**:
  - Filename
  - MIME type
  - Size in bytes
  - Local file path (if downloaded)

## Performance Considerations

- **Search Limit**: `max_results` limits API calls. Each email requires an additional API call to fetch full details.
- **Attachment Download**: Downloading takes time proportional to file sizes.
- **Temp Directory**: Auto-created temp directories persist until manually deleted.
- **Rate Limiting**: Gmail API has rate limits; large `max_results` may throttle.

### Estimated Performance
- Search 10 emails: ~2-3 seconds
- Download 10 PDFs (1-5MB each): ~5-10 seconds
- Total for typical workflow: ~10-15 seconds

## Downstream Processing

The returned file paths can be used for:

1. **PDF Extraction**
   ```python
   pdf_paths = [att['file_path'] for email in result['emails_with_attachments'] 
                for att in email['attachments'] if 'pdf' in att['mime_type']]
   # Process PDFs for text extraction, OCR, etc.
   ```

2. **Excel Data Processing**
   ```python
   import pandas as pd
   excel_paths = [att['file_path'] for email in result['emails_with_attachments'] 
                  for att in email['attachments'] if 'spreadsheet' in att['mime_type']]
   for path in excel_paths:
       df = pd.read_excel(path)
       # Process data
   ```

3. **Data Integration**
   ```python
   for email in result['emails_with_attachments']:
       sender = email['from']
       timestamp = email['timestamp']
       files = email['attachments']
       # Store metadata + file references in database
   ```

## Cleanup

When temp directories are auto-created:

```python
import shutil
import os

result = _search_emails_with_delivery_order_attachments_impl(...)

if result['temp_directory']:
    # Process files...
    
    # Clean up when done
    shutil.rmtree(result['temp_directory'])
```

For custom directories, manual cleanup is recommended after processing.

## Troubleshooting

### Issue: "No emails found matching query"
- Verify the search query is correct for your emails
- Try simpler queries like `"pdf"` or `"attachment"`
- Increase `max_results` to search more emails

### Issue: Downloads are slow
- Reduce `max_results` to search fewer emails
- Use `download_attachments=False` to get metadata first
- Check network connection and Gmail API quota

### Issue: Permission errors on file write
- Ensure `temp_dir` is writable
- Check disk space availability
- Verify process has file system permissions

### Issue: Missing attachments in results
- Verify emails actually have PDF/Excel files
- Check file extensions match supported types
- Review `download_error` field in attachment metadata

## Integration with Supervisor Agent

The function is registered in the supervisor agent's capabilities:

```python
"search_emails_with_delivery_order_attachments": {
    "description": "Search Gmail for delivery order emails with PDF/Excel attachments",
    "inputs": {
        "query": "Search query (optional, default: 'delivery order')",
        "max_results": "Number of emails to search",
        "download_attachments": "Whether to download files (boolean)",
        "temp_dir": "Custom temp directory path (optional)"
    }
}
```

This allows the supervisor to orchestrate multi-step workflows involving delivery order processing.

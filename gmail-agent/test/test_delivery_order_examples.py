"""
Quick test examples for the new delivery order search function.
Run these examples to verify the function works correctly.
"""

# Example 1: Basic usage with default parameters
def example_basic_search():
    """Search for delivery orders with default settings"""
    from tools import _search_emails_with_delivery_order_attachments_impl
    
    credentials = {
        "access_token": "YOUR_ACCESS_TOKEN",
        "refresh_token": "YOUR_REFRESH_TOKEN",
        "client_id": "YOUR_CLIENT_ID",
        "client_secret": "YOUR_CLIENT_SECRET"
    }
    
    result = _search_emails_with_delivery_order_attachments_impl(
        credentials_dict=credentials
    )
    
    print("Result:", result)
    if result["success"]:
        print(f"✅ Found {result['total_attachments_downloaded']} attachments")
        print(f"📁 Saved to: {result['temp_directory']}")
        
        # List downloaded files
        for email in result["emails_with_attachments"]:
            print(f"\n📧 From: {email['from']}")
            print(f"   Subject: {email['subject']}")
            print(f"   Timestamp: {email['timestamp']}")
            for attachment in email['attachments']:
                print(f"   📎 {attachment['filename']} ({attachment['size']} bytes)")
                if attachment.get('file_path'):
                    print(f"      Saved to: {attachment['file_path']}")


# Example 2: Custom search query
def example_custom_query():
    """Search for emails from a specific supplier"""
    from tools import _search_emails_with_delivery_order_attachments_impl
    
    credentials = {
        "access_token": "YOUR_ACCESS_TOKEN",
        "refresh_token": "YOUR_REFRESH_TOKEN",
        "client_id": "YOUR_CLIENT_ID",
        "client_secret": "YOUR_CLIENT_SECRET"
    }
    
    result = _search_emails_with_delivery_order_attachments_impl(
        query="from:supplier@company.com subject:purchase order",
        max_results=20,
        credentials_dict=credentials
    )
    
    print(f"Found {result['total_emails_found']} matching emails")
    print(f"Downloaded {result['total_attachments_downloaded']} attachments")


# Example 3: Metadata-only (no downloads)
def example_metadata_only():
    """Get attachment metadata without downloading files"""
    from tools import _search_emails_with_delivery_order_attachments_impl
    
    credentials = {
        "access_token": "YOUR_ACCESS_TOKEN",
        "refresh_token": "YOUR_REFRESH_TOKEN",
        "client_id": "YOUR_CLIENT_ID",
        "client_secret": "YOUR_CLIENT_SECRET"
    }
    
    result = _search_emails_with_delivery_order_attachments_impl(
        query="delivery order",
        max_results=10,
        download_attachments=False,  # Don't download, just get metadata
        credentials_dict=credentials
    )
    
    print("Email Metadata (without downloads):")
    for email in result["emails_with_attachments"]:
        print(f"\n📧 {email['subject']}")
        print(f"   From: {email['from']}")
        print(f"   Date: {email['timestamp']}")
        print(f"   Attachments: {email['attachment_count']}")
        for att in email['attachments']:
            print(f"   - {att['filename']} ({att['mime_type']})")


# Example 4: Custom temp directory
def example_custom_temp_dir():
    """Save attachments to a specific directory"""
    import os
    from tools import _search_emails_with_delivery_order_attachments_impl
    
    credentials = {
        "access_token": "YOUR_ACCESS_TOKEN",
        "refresh_token": "YOUR_REFRESH_TOKEN",
        "client_id": "YOUR_CLIENT_ID",
        "client_secret": "YOUR_CLIENT_SECRET"
    }
    
    # Create custom directory
    custom_dir = os.path.expanduser("~/Downloads/delivery_orders_backup")
    os.makedirs(custom_dir, exist_ok=True)
    
    result = _search_emails_with_delivery_order_attachments_impl(
        query="delivery order",
        max_results=15,
        temp_dir=custom_dir,
        download_attachments=True,
        credentials_dict=credentials
    )
    
    if result["success"]:
        print(f"✅ Saved {result['total_attachments_downloaded']} files to {custom_dir}")


# Example 5: Processing downloaded files
def example_process_downloads():
    """Download files and process them (PDFs and Excel)"""
    import pandas as pd
    from tools import _search_emails_with_delivery_order_attachments_impl
    
    credentials = {
        "access_token": "YOUR_ACCESS_TOKEN",
        "refresh_token": "YOUR_REFRESH_TOKEN",
        "client_id": "YOUR_CLIENT_ID",
        "client_secret": "YOUR_CLIENT_SECRET"
    }
    
    result = _search_emails_with_delivery_order_attachments_impl(
        query="delivery order",
        max_results=10,
        credentials_dict=credentials
    )
    
    if result["success"]:
        # Process Excel files
        for email in result["emails_with_attachments"]:
            for attachment in email['attachments']:
                if 'spreadsheet' in attachment['mime_type']:
                    file_path = attachment['file_path']
                    print(f"Reading Excel file: {file_path}")
                    try:
                        df = pd.read_excel(file_path)
                        print(f"  Shape: {df.shape}")
                        print(f"  Columns: {list(df.columns)}")
                        # Process data...
                    except Exception as e:
                        print(f"  Error: {e}")


# Example 6: API endpoint usage
def example_api_usage():
    """Call the function via FastAPI endpoint"""
    import httpx
    import json
    
    payload = {
        "tool": "search_emails_with_delivery_order_attachments",
        "inputs": {
            "query": "delivery order",
            "max_results": 10,
            "download_attachments": True
        },
        "credentials_dict": {
            "access_token": "YOUR_ACCESS_TOKEN",
            "refresh_token": "YOUR_REFRESH_TOKEN",
            "client_id": "YOUR_CLIENT_ID",
            "client_secret": "YOUR_CLIENT_SECRET"
        }
    }
    
    response = httpx.post(
        "http://localhost:8000/execute_task",
        json=payload
    )
    
    result = response.json()
    print(json.dumps(result, indent=2, default=str))


# Example 7: Error handling
def example_error_handling():
    """Demonstrate error handling"""
    from tools import _search_emails_with_delivery_order_attachments_impl
    
    credentials = {
        "access_token": "YOUR_ACCESS_TOKEN",
        "refresh_token": "YOUR_REFRESH_TOKEN",
        "client_id": "YOUR_CLIENT_ID",
        "client_secret": "YOUR_CLIENT_SECRET"
    }
    
    result = _search_emails_with_delivery_order_attachments_impl(
        query="delivery order",
        credentials_dict=credentials
    )
    
    # Check for different error conditions
    if not result["success"]:
        if result.get("no_results"):
            print(f"❌ No emails found: {result['error']}")
        elif result.get("no_attachments"):
            print(f"⚠️ No PDF/Excel files found: {result['error']}")
        else:
            print(f"❌ Error: {result['error']}")
    else:
        print(f"✅ Success: Downloaded {result['total_attachments_downloaded']} files")
        
        # Check individual attachment errors
        for email in result["emails_with_attachments"]:
            for attachment in email['attachments']:
                if attachment.get('download_error'):
                    print(f"⚠️ Failed to download {attachment['filename']}: {attachment['download_error']}")


# Example 8: Cleanup after processing
def example_cleanup():
    """Download files, process, and cleanup"""
    import shutil
    from tools import _search_emails_with_delivery_order_attachments_impl
    
    credentials = {
        "access_token": "YOUR_ACCESS_TOKEN",
        "refresh_token": "YOUR_REFRESH_TOKEN",
        "client_id": "YOUR_CLIENT_ID",
        "client_secret": "YOUR_CLIENT_SECRET"
    }
    
    result = _search_emails_with_delivery_order_attachments_impl(
        query="delivery order",
        credentials_dict=credentials
    )
    
    try:
        if result["success"]:
            # Process files...
            for email in result["emails_with_attachments"]:
                print(f"Processing email from {email['from']}: {email['subject']}")
                for attachment in email['attachments']:
                    if attachment.get('file_path'):
                        print(f"  Processing: {attachment['filename']}")
    
    finally:
        # Always cleanup temp directory
        if result.get("temp_directory"):
            print(f"Cleaning up: {result['temp_directory']}")
            shutil.rmtree(result['temp_directory'])


if __name__ == "__main__":
    print("=" * 60)
    print("Delivery Order Search Examples")
    print("=" * 60)
    print("\nAvailable examples:")
    print("1. example_basic_search() - Basic search with defaults")
    print("2. example_custom_query() - Custom search query")
    print("3. example_metadata_only() - Get metadata without downloads")
    print("4. example_custom_temp_dir() - Save to custom directory")
    print("5. example_process_downloads() - Process downloaded files")
    print("6. example_api_usage() - Call via FastAPI endpoint")
    print("7. example_error_handling() - Demonstrate error handling")
    print("8. example_cleanup() - Download, process, and cleanup")
    print("\nReplace YOUR_* placeholders with actual credentials before running.")

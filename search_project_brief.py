#!/usr/bin/env python3
"""
Script to search for Project_Brief.docx in Google Drive
"""

import sys
import os
import json
sys.path.append(os.path.join(os.path.dirname(__file__), 'gdrive-agent'))

from tools import get_token_drive_service, search_files_in_safeexpress_impl

def search_all_files(service, search_term: str):
    """Search for files in all Drive"""
    try:
        query = f"name contains '{search_term}' and trashed=false"
        results = service.files().list(
            q=query,
            fields="files(id, name, mimeType, size, createdTime, webViewLink)",
            pageSize=20
        ).execute()
        
        files = results.get('files', [])
        
        if not files:
            return {
                "success": True,
                "results": [],
                "count": 0,
                "search_term": search_term,
                "message": f"No files found matching '{search_term}'",
                "error": None
            }
        
        # Format results
        output = [f"Found {len(files)} file(s) matching '{search_term}':"]
        for file in files:
            output.append(f"  {file['name']} (ID: {file['id']})")
        
        return {
            "success": True,
            "results": files,
            "count": len(files),
            "search_term": search_term,
            "message": "\n".join(output),
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "results": [],
            "count": 0,
            "message": f"Failed to search files: {str(e)}",
            "error": str(e)
        }

def main():
    try:
        service = get_token_drive_service()
        result = search_all_files(service, "Project Brief")
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
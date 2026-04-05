#!/usr/bin/env python3
"""
Script to create a copy of project_brief.docx as Copy_of_Project_Brief.docx
"""

import sys
import os
import json
import importlib.util

# Load gdrive tools
gdrive_tools_path = os.path.join(os.path.dirname(__file__), 'gdrive-agent', 'tools.py')
spec = importlib.util.spec_from_file_location("gdrive_tools", gdrive_tools_path)
gdrive_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gdrive_tools)

# Load gdocs tools
gdocs_tools_path = os.path.join(os.path.dirname(__file__), 'gdocs-agent', 'tools.py')
spec = importlib.util.spec_from_file_location("gdocs_tools", gdocs_tools_path)
gdocs_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gdocs_tools)

def main():
    try:
        # Get credentials from gdrive
        service = gdrive_tools.get_token_drive_service()
        
        # Get creds dict
        TOKEN_PATH = os.path.join(os.path.dirname(__file__), 'gdrive-agent', 'key', 'token.json')
        if os.path.exists(TOKEN_PATH):
            with open(TOKEN_PATH, 'r') as f:
                creds_data = json.load(f)
                creds_dict = {
                    'access_token': creds_data.get('token'),
                    'refresh_token': creds_data.get('refresh_token'),
                    'client_id': creds_data.get('client_id'),
                    'client_secret': creds_data.get('client_secret'),
                    'token_uri': creds_data.get('token_uri', 'https://oauth2.googleapis.com/token')
                }
        else:
            print("Token file not found")
            return
        
        template_file_id = "1v4AX7e_Z7b4uzmoQbp6G39zNp9Qu6aDq"
        new_title = "Copy_of_Project_Brief.docx"
        
        result = gdocs_tools._create_from_uploaded_template_impl(
            template_file_id, new_title, {}, creds_dict, "google_docs"
        )
        print(result)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
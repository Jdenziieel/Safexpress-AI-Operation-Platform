import json
from sheets_agent_api import (
    create_sheet, read_sheet, update_sheet, update_rows_by_date,
    update_rows_by_anchor, update_cells_by_column, append_rows,
    batch_update_cells, insert_rows,
    upload_multi_sheet_data, get_sheet_metadata, preview_cell_changes,
    CredentialsDict
)

TOOL_REGISTRY = {
    "create_sheet": create_sheet,
    "read_sheet": read_sheet,
    "update_sheet": update_sheet,
    "update_rows_by_date": update_rows_by_date,
    "update_rows_by_anchor": update_rows_by_anchor,
    "update_cells_by_column": update_cells_by_column,
    "append_rows": append_rows,
    "batch_update_cells": batch_update_cells,
    "insert_rows": insert_rows,
    "upload_multi_sheet_data": upload_multi_sheet_data,
    "get_sheet_metadata": get_sheet_metadata,
    "preview_cell_changes": preview_cell_changes,
}

def lambda_handler(event, context):
    try:
        print(f"Sheets Agent received event keys: {list(event.keys())}")

        if 'body' in event and 'tool' not in event:
            body = event['body']
            if isinstance(body, str):
                body = json.loads(body)
        else:
            body = event

        tool_name = body.get('tool')
        inputs = body.get('inputs', {})
        credentials_dict_raw = body.get('credentials_dict')

        if not tool_name:
            return {'success': False, 'error': 'Missing tool name'}

        if tool_name not in TOOL_REGISTRY:
            return {'success': False, 'error': f'Unknown tool: {tool_name}'}

        credentials = None
        if credentials_dict_raw:
            credentials = CredentialsDict(
                access_token=credentials_dict_raw.get('access_token', ''),
                refresh_token=credentials_dict_raw.get('refresh_token', ''),
                client_id=credentials_dict_raw.get('client_id'),
                client_secret=credentials_dict_raw.get('client_secret'),
            )

        print(f"Executing tool: {tool_name}")
        result = TOOL_REGISTRY[tool_name](**inputs, credentials_dict=credentials)
        print(f"Tool completed: {tool_name}")

        return result

    except Exception as e:
        print(f"lambda_handler error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}

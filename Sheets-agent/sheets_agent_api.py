"""
Google Sheets Agent API - Pure CRUD Operations
Focused solely on Google Sheets operations (no parsing or mapping logic)
Works with pre-transformed data from the Mapping Agent
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Any, Optional
import os
import uvicorn
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import json
from dotenv import load_dotenv


# Load environment variables from .env file
load_dotenv()

# FastAPI app
app = FastAPI(title="Google Sheets Agent API", version="2.0.0")


# Pydantic Models
class CredentialsDict(BaseModel):
    """Google OAuth credentials"""

    access_token: str
    refresh_token: str
    client_id: Optional[str] = None
    client_secret: Optional[str] = None


class ToolRequest(BaseModel):
    """Generic tool execution request"""

    tool: str
    inputs: Dict[str, Any]
    credentials_dict: CredentialsDict


class ToolResponse(BaseModel):
    """Generic tool execution response"""

    success: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# ============================================================
# HELPER FUNCTIONS
# ============================================================


def create_sheets_service(credentials_dict: CredentialsDict):
    """Create authenticated Google Sheets service"""
    try:
        creds = Credentials(
            token=credentials_dict.access_token or os.getenv("GOOGLE_ACCESS_TOKEN"),
            refresh_token=credentials_dict.refresh_token or os.getenv("GOOGLE_REFRESH_TOKEN"),
            client_id=credentials_dict.client_id or os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=credentials_dict.client_secret or os.getenv("GOOGLE_CLIENT_SECRET"),
            token_uri="https://oauth2.googleapis.com/token",
        )
        return build("sheets", "v4", credentials=creds)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")


# ============================================================
# TOOL IMPLEMENTATIONS
# ============================================================


def create_sheet(
    title: str,
    sheet_names: Optional[List[str]] = None,
    initial_data: Optional[List[List[Any]]] = None,
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Create a new Google Spreadsheet

    Args:
        title: Name of the spreadsheet
        sheet_names: Optional list of sheet tab names (default: ["Sheet1"])
        initial_data: Optional 2D list of data to populate first sheet
        credentials_dict: Google OAuth credentials

    Returns:
        Dictionary with new sheet details
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        service = create_sheets_service(credentials_dict)

        # Prepare sheets configuration
        sheets = []
        if sheet_names:
            for name in sheet_names:
                sheets.append({"properties": {"title": name}})
        else:
            sheets.append({"properties": {"title": "Sheet1"}})

        # Create spreadsheet
        spreadsheet = {"properties": {"title": title}, "sheets": sheets}

        result = service.spreadsheets().create(body=spreadsheet).execute()
        sheet_id = result.get("spreadsheetId")
        sheet_url = result.get("spreadsheetUrl")

        # Add initial data if provided
        if initial_data and len(initial_data) > 0:
            first_sheet_name = sheet_names[0] if sheet_names else "Sheet1"
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=f"{first_sheet_name}!A1",
                valueInputOption="RAW",
                body={"values": initial_data},
            ).execute()

        return {
            "success": True,
            "sheet_id": sheet_id,
            "sheet_url": sheet_url,
            "title": title,
            "message": f"Created spreadsheet: {title}",
        }

    except HttpError as e:
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to create sheet: {str(e)}"}


def read_sheet(
    sheet_id: str,
    range_name: str = "Sheet1",
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Read data from a Google Sheet

    Args:
        sheet_id: Google Sheets ID
        range_name: Range to read (e.g., 'Sheet1' or 'Sheet1!A1:D10')
        credentials_dict: Google OAuth credentials

    Returns:
        Dictionary with sheet data
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        service = create_sheets_service(credentials_dict)

        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=sheet_id, range=range_name)
            .execute()
        )

        values = result.get("values", [])

        if not values:
            return {
                "success": True,
                "data": [],
                "row_count": 0,
                "column_count": 0,
                "range": range_name,
                "message": "No data found in range",
            }

        return {
            "success": True,
            "data": values,
            "row_count": len(values),
            "column_count": len(values[0]) if values else 0,
            "range": range_name,
        }

    except HttpError as e:
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to read sheet: {str(e)}"}


def update_sheet(
    sheet_id: str,
    range_name: str,
    data: List[List[Any]],
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Update data in a specific range of a Google Sheet

    Args:
        sheet_id: Google Sheets ID
        range_name: Range to update (e.g., 'Sheet1!A1:D10')
        data: 2D list of values to write
        credentials_dict: Google OAuth credentials

    Returns:
        Dictionary with update results
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        service = create_sheets_service(credentials_dict)

        result = (
            service.spreadsheets()
            .values()
            .update(
                spreadsheetId=sheet_id,
                range=range_name,
                valueInputOption="RAW",
                body={"values": data},
            )
            .execute()
        )

        return {
            "success": True,
            "updated_cells": result.get("updatedCells", 0),
            "updated_rows": result.get("updatedRows", 0),
            "updated_columns": result.get("updatedColumns", 0),
            "range": range_name,
            "message": f"Updated {result.get('updatedCells', 0)} cells in {range_name}",
        }

    except HttpError as e:
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to update sheet: {str(e)}"}


def append_rows(
    sheet_id: str,
    data: List[List[Any]],
    sheet_name: str = "Sheet1",
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Append rows to the end of a sheet

    Args:
        sheet_id: Google Sheets ID
        data: 2D list of rows to append
        sheet_name: Name of the sheet tab (default: "Sheet1")
        credentials_dict: Google OAuth credentials

    Returns:
        Dictionary with append results
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        service = create_sheets_service(credentials_dict)

        # Find the next empty row
        range_name = f"{sheet_name}!A:A"
        result = (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=sheet_id,
                range=range_name,
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": data},
            )
            .execute()
        )

        return {
            "success": True,
            "rows_added": len(data),
            "range_updated": result.get("updates", {}).get("updatedRange"),
            "updated_cells": result.get("updates", {}).get("updatedCells", 0),
            "message": f"Appended {len(data)} rows to {sheet_name}",
        }

    except HttpError as e:
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to append rows: {str(e)}"}


def upload_mapped_data(
    sheet_id: str,
    transformed_data: str,  # JSON string from mapping agent's transform_data
    sheet_name: str = "Sheet1",
    append_mode: bool = True,
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Upload pre-transformed data from mapping agent to Google Sheets
    This is the main integration point with the mapping agent

    Args:
        sheet_id: Google Sheets ID
        transformed_data: JSON string of transformed data (from mapping agent)
        sheet_name: Sheet tab name to write to
        append_mode: If True, append to sheet. If False, overwrite from A1
        credentials_dict: Google OAuth credentials

    Returns:
        Dictionary with upload results
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        service = create_sheets_service(credentials_dict)

        # Parse transformed data
        import pandas as pd

        df = pd.read_json(transformed_data)

        if df.empty:
            return {"success": False, "error": "Transformed data is empty"}
        # ✅ FIX: Convert timestamps to strings
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')

        # Convert DataFrame to 2D list
        # Include headers
        headers = [df.columns.tolist()]
        data_rows = df.values.tolist()
        all_data = headers + data_rows

        if append_mode:
            # Append to existing data
            result = (
                service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=sheet_id,
                    range=f"{sheet_name}!A:A",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": all_data},
                )
                .execute()
            )

            return {
                "success": True,
                "rows_added": len(all_data),
                "range_updated": result.get("updates", {}).get("updatedRange"),
                "mode": "append",
                "message": f"Appended {len(data_rows)} data rows to {sheet_name}",
            }
        else:
            # Overwrite from A1
            result = (
                service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=sheet_id,
                    range=f"{sheet_name}!A1",
                    valueInputOption="RAW",
                    body={"values": all_data},
                )
                .execute()
            )

            return {
                "success": True,
                "rows_written": len(all_data),
                "updated_cells": result.get("updatedCells", 0),
                "mode": "overwrite",
                "message": f"Wrote {len(data_rows)} data rows to {sheet_name}",
            }

    except HttpError as e:
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to upload data: {str(e)}"}


def get_sheet_metadata(
    sheet_id: str,
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Get metadata about a spreadsheet (sheet names, row counts, etc.)

    Args:
        sheet_id: Google Sheets ID
        credentials_dict: Google OAuth credentials

    Returns:
        Dictionary with spreadsheet metadata
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        service = create_sheets_service(credentials_dict)

        spreadsheet = service.spreadsheets().get(spreadsheetId=sheet_id).execute()

        sheets_info = []
        for sheet in spreadsheet.get("sheets", []):
            props = sheet.get("properties", {})
            grid_props = props.get("gridProperties", {})

            sheets_info.append(
                {
                    "sheet_id": props.get("sheetId"),
                    "title": props.get("title"),
                    "index": props.get("index"),
                    "row_count": grid_props.get("rowCount", 0),
                    "column_count": grid_props.get("columnCount", 0),
                }
            )

        return {
            "success": True,
            "spreadsheet_id": sheet_id,
            "title": spreadsheet.get("properties", {}).get("title"),
            "sheets": sheets_info,
            "sheet_count": len(sheets_info),
        }

    except HttpError as e:
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to get metadata: {str(e)}"}


def clear_sheet(
    sheet_id: str,
    range_name: str = "Sheet1",
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Clear data from a sheet range

    Args:
        sheet_id: Google Sheets ID
        range_name: Range to clear (e.g., 'Sheet1' or 'Sheet1!A1:D10')
        credentials_dict: Google OAuth credentials

    Returns:
        Dictionary with clear results
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        service = create_sheets_service(credentials_dict)

        result = (
            service.spreadsheets()
            .values()
            .clear(spreadsheetId=sheet_id, range=range_name, body={})
            .execute()
        )

        return {
            "success": True,
            "cleared_range": result.get("clearedRange"),
            "message": f"Cleared data from {range_name}",
        }

    except HttpError as e:
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to clear sheet: {str(e)}"}


# ============================================================
# TOOL REGISTRY
# ============================================================

TOOL_REGISTRY = {
    "create_sheet": {
        "func": create_sheet,
        "description": "Create a new Google Spreadsheet",
    },
    "read_sheet": {"func": read_sheet, "description": "Read data from a Google Sheet"},
    "update_sheet": {
        "func": update_sheet,
        "description": "Update data in a specific range",
    },
    "append_rows": {
        "func": append_rows,
        "description": "Append rows to the end of a sheet",
    },
    "upload_mapped_data": {
        "func": upload_mapped_data,
        "description": "Upload pre-transformed data from mapping agent",
    },
    "get_sheet_metadata": {
        "func": get_sheet_metadata,
        "description": "Get spreadsheet metadata (sheets, row counts)",
    },
    "clear_sheet": {
        "func": clear_sheet,
        "description": "Clear data from a sheet range",
    },
}


# ============================================================
# API ENDPOINTS
# ============================================================


@app.post("/execute", response_model=ToolResponse)
async def execute_tool(request: ToolRequest):
    """
    Execute a Google Sheets tool

    Request body:
        - tool: Name of the tool to execute
        - inputs: Dictionary of tool inputs
        - credentials_dict: Google OAuth credentials

    Returns:
        ToolResponse with success status and result/error
    """
    try:
        print(f"\n📊 Sheets Agent - Tool: {request.tool}")
        print(f"   Inputs: {list(request.inputs.keys())}")

        # Get tool from registry
        tool_info = TOOL_REGISTRY.get(request.tool)
        if not tool_info:
            available_tools = list(TOOL_REGISTRY.keys())
            return ToolResponse(
                success=False,
                error=f"Unknown tool: {request.tool}. Available: {available_tools}",
            )

        # Add credentials to inputs
        request.inputs["credentials_dict"] = request.credentials_dict

        # Execute tool
        result = tool_info["func"](**request.inputs)

        print(
            f"   {'✅' if result.get('success') else '❌'} Result: {result.get('success', False)}"
        )

        return ToolResponse(
            success=result.get("success", False),
            result=result if result.get("success") else None,
            error=result.get("error") if not result.get("success") else None,
        )

    except Exception as e:
        print(f"   ❌ Error: {str(e)}")
        import traceback

        traceback.print_exc()
        return ToolResponse(
            success=False,
            error=f"Tool execution failed: {str(e)}",
        )


@app.get("/tools")
async def list_tools():
    """List all available tools"""
    return {
        "tools": [
            {"name": name, "description": info["description"]}
            for name, info in TOOL_REGISTRY.items()
        ],
        "count": len(TOOL_REGISTRY),
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "google-sheets-agent",
        "version": "2.0.0",
        "description": "Pure CRUD operations for Google Sheets",
    }


@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "service": "Google Sheets Agent API",
        "version": "2.0.0",
        "description": "Pure CRUD operations for Google Sheets (no parsing/mapping)",
        "features": [
            "Create spreadsheets",
            "Read sheet data",
            "Update ranges",
            "Append rows",
            "Upload pre-mapped data",
            "Get metadata",
            "Clear sheets",
        ],
        "endpoints": {
            "execute": "/execute (POST) - Execute a sheets tool",
            "tools": "/tools (GET) - List available tools",
            "health": "/health (GET) - Health check",
            "docs": "/docs (GET) - Swagger documentation",
        },
        "note": "Works with pre-transformed data from Mapping Agent",
    }


# Run the server
if __name__ == "__main__":
    port = int(os.getenv("SHEETS_AGENT_PORT", "8003"))
    print(f"🚀 Starting Google Sheets Agent (v2.0 - Pure CRUD) on port {port}")
    print(f"📚 API Documentation: http://localhost:{port}/docs")
    print(f"🔧 Available tools: {list(TOOL_REGISTRY.keys())}")
    print(f"📝 Note: This agent works with pre-transformed data from Mapping Agent")
    uvicorn.run(app, host="0.0.0.0", port=port)

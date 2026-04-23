"""
Google Sheets Agent API - Pure CRUD Operations
Focused solely on Google Sheets operations (no parsing or mapping logic)
Works with pre-transformed data from the Mapping Agent
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Any, Optional, Tuple
import os
import re
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
    error_type: Optional[str] = None


# ============================================================
# HELPER FUNCTIONS
# ============================================================


def _build_google_credentials(credentials_dict: CredentialsDict) -> Credentials:
    """Build a Credentials object from the request payload + env fallbacks."""
    from google.auth.transport.requests import Request as AuthRequest

    creds = Credentials(
        token=credentials_dict.access_token or os.getenv("GOOGLE_ACCESS_TOKEN"),
        refresh_token=credentials_dict.refresh_token
        or os.getenv("GOOGLE_REFRESH_TOKEN"),
        client_id=credentials_dict.client_id or os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=credentials_dict.client_secret
        or os.getenv("GOOGLE_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
    )
    if creds.refresh_token:
        try:
            creds.refresh(AuthRequest())
        except Exception:
            pass
    return creds


def create_sheets_service(credentials_dict: CredentialsDict):
    """Create authenticated Google Sheets service"""
    try:
        creds = _build_google_credentials(credentials_dict)
        return build("sheets", "v4", credentials=creds)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")


def create_drive_service(credentials_dict: CredentialsDict):
    """Create an authenticated Google Drive service reusing the sheets creds.

    The same OAuth token is used to move newly-created sheets into a target
    folder via Drive's files().update (add/remove parents). Requires the
    consent flow to have included the `drive` scope.
    """
    try:
        creds = _build_google_credentials(credentials_dict)
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Drive auth failed: {str(e)}")


# ============================================================
# TOOL IMPLEMENTATIONS
# ============================================================


def create_sheet(
    title: str,
    sheet_names: Optional[List[str]] = None,
    initial_data: Optional[List[List[Any]]] = None,
    folder_id: Optional[str] = None,
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Create a new Google Spreadsheet, optionally inside a specific Drive folder.

    Args:
        title: Name of the spreadsheet
        sheet_names: Optional list of sheet tab names (default: ["Sheet1"])
        initial_data: Optional 2D list of data to populate first sheet
        folder_id: Optional Drive folder ID to place the new sheet in. The
                   sheet is first created at the Drive root (Sheets API does
                   not accept a parent at creation time), then reparented via
                   Drive API. If omitted, the sheet stays in My Drive root.
                   Planners should resolve a folder_path to folder_id with
                   drive_agent.get_folder_info (strict) or
                   drive_agent.create_folder (explicit create) beforehand.
        credentials_dict: Google OAuth credentials

    Returns:
        Dictionary with new sheet details (includes folder_id + folder_moved flag)
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        service = create_sheets_service(credentials_dict)

        sheets = []
        if sheet_names:
            for name in sheet_names:
                sheets.append({"properties": {"title": name}})
        else:
            sheets.append({"properties": {"title": "Sheet1"}})

        spreadsheet = {"properties": {"title": title}, "sheets": sheets}

        result = service.spreadsheets().create(body=spreadsheet).execute()
        sheet_id = result.get("spreadsheetId")
        sheet_url = result.get("spreadsheetUrl")

        if initial_data and len(initial_data) > 0:
            first_sheet_name = sheet_names[0] if sheet_names else "Sheet1"
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=f"{first_sheet_name}!A1",
                valueInputOption="RAW",
                body={"values": initial_data},
            ).execute()

        # Reparent into the target folder if requested. We do NOT fail the
        # whole creation if the move fails — the sheet still exists at root,
        # so we return success + a warning field instead.
        folder_moved = False
        move_warning: Optional[str] = None
        if folder_id:
            try:
                drive = create_drive_service(credentials_dict)
                current = (
                    drive.files()
                    .get(fileId=sheet_id, fields="parents")
                    .execute()
                )
                current_parents = ",".join(current.get("parents") or [])
                drive.files().update(
                    fileId=sheet_id,
                    addParents=folder_id,
                    removeParents=current_parents or None,
                    fields="id, parents",
                ).execute()
                folder_moved = True
            except Exception as move_err:
                move_warning = (
                    f"Sheet created but move to folder '{folder_id}' failed: {move_err}"
                )

        message = f"Created spreadsheet: {title}"
        if folder_moved:
            message += f" (in folder {folder_id})"
        elif move_warning:
            message += f" — {move_warning}"

        return {
            "success": True,
            "sheet_id": sheet_id,
            "sheet_url": sheet_url,
            "title": title,
            "folder_id": folder_id,
            "folder_moved": folder_moved,
            "warning": move_warning,
            "message": message,
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

        sheet_id = _extract_sheet_id(sheet_id)

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

        sheet_id = _extract_sheet_id(sheet_id)

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

        sheet_id = _extract_sheet_id(sheet_id)

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

        sheet_id = _extract_sheet_id(sheet_id)

        service = create_sheets_service(credentials_dict)

        # Parse transformed data
        import pandas as pd

        df = pd.read_json(transformed_data)

        if df.empty:
            return {"success": False, "error": "Transformed data is empty"}
        # ✅ FIX: Convert timestamps to strings
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M:%S")

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

        sheet_id = _extract_sheet_id(sheet_id)

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

        sheet_id = _extract_sheet_id(sheet_id)

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


def get_sheet_headers(
    sheet_id: str,
    sheet_name: str = "Sheet1",
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """Get the header row of an existing sheet — needed for column mapping"""
    try:
        sheet_id = _extract_sheet_id(sheet_id)
        service = create_sheets_service(credentials_dict)
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=f"{sheet_name}!1:1"
        ).execute()
        headers = result.get("values", [[]])[0]
        return {
            "success": True,
            "headers": headers,
            "column_count": len(headers),
            "sheet_name": sheet_name,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_by_date_match(
    sheet_id: str,
    transformed_data: str,  # JSON string
    rows_with_dates: Any,  # Can be list, dict, or string
    sheet_name: str = "DATA ENTRY",
    date_column: str = "Date",
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Update Google Sheets rows by matching dates (no append, only update)

    Args:
        sheet_id: Google Sheets ID
        transformed_data: JSON string of transformed operational data
        rows_with_dates: List of {row_index, date, row_data} from mapping agent (can be string or list)
        sheet_name: Name of the sheet to update
        date_column: Column name for date matching (default: "Date")
        credentials_dict: Google credentials

    Returns:
        Success status and number of rows updated
    """
    try:
        print(f"\n📊 Update by Date Match")
        print(f"   Sheet: {sheet_id}/{sheet_name}")
        print(f"   Date column: {date_column}")

        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        sheet_id = _extract_sheet_id(sheet_id)

        # ✅ BULLETPROOF PARSING - Handle any format
        print(f"\n🔍 Parsing rows_with_dates...")
        print(f"   Received type: {type(rows_with_dates).__name__}")

        if isinstance(rows_with_dates, str):
            print(f"   String length: {len(rows_with_dates)}")
            print(f"   First 200 chars: {rows_with_dates[:200]}")

            import ast

            # Try multiple parsing strategies
            parsed = None

            # Strategy 1: Standard JSON
            try:
                import json

                parsed = json.loads(rows_with_dates)
                print(f"   ✅ Parsed with json.loads()")
            except json.JSONDecodeError as e1:
                print(f"   ❌ json.loads() failed: {str(e1)}")

                # Strategy 2: Fix single quotes and try again
                try:
                    fixed = rows_with_dates.replace("'", '"')
                    parsed = json.loads(fixed)
                    print(f"   ✅ Parsed after fixing quotes")
                except json.JSONDecodeError as e2:
                    print(f"   ❌ Quote fix failed: {str(e2)}")

                    # Strategy 3: Python literal_eval (handles Python dict format)
                    try:
                        parsed = ast.literal_eval(rows_with_dates)
                        print(f"   ✅ Parsed with ast.literal_eval()")
                    except (ValueError, SyntaxError) as e3:
                        print(f"   ❌ literal_eval failed: {str(e3)}")

                        # Strategy 4: Extract from wrapper if it has one
                        try:
                            # Sometimes it comes wrapped like: "rows_with_dates=[...]"
                            if "=" in rows_with_dates:
                                json_part = rows_with_dates.split("=", 1)[1].strip()
                                parsed = ast.literal_eval(json_part)
                                print(f"   ✅ Parsed after extracting from wrapper")
                            else:
                                raise ValueError("No wrapper found")
                        except Exception as e4:
                            return {
                                "success": False,
                                "error": f"Could not parse rows_with_dates after trying all strategies. Last error: {str(e4)}",
                            }

            rows_with_dates = parsed

        elif isinstance(rows_with_dates, dict):
            # Sometimes it comes as a dict with 'rows_with_dates' key
            if "rows_with_dates" in rows_with_dates:
                rows_with_dates = rows_with_dates["rows_with_dates"]
                print(f"   ✅ Extracted from dict wrapper")
            else:
                return {
                    "success": False,
                    "error": f"Received dict but no 'rows_with_dates' key. Keys: {list(rows_with_dates.keys())}",
                }

        # Validate it's now a list
        if not isinstance(rows_with_dates, list):
            return {
                "success": False,
                "error": f"After parsing, expected list but got {type(rows_with_dates).__name__}",
            }

        if len(rows_with_dates) == 0:
            return {"success": False, "error": "rows_with_dates is empty"}

        print(f"   ✅ Validated: {len(rows_with_dates)} rows with dates")
        print(f"   Sample row: {rows_with_dates[0]}")

        # Parse transformed data
        import pandas as pd

        transformed_df = pd.read_json(transformed_data)

        print(
            f"\n   Transformed data: {len(transformed_df)} rows, {len(transformed_df.columns)} columns"
        )

        # Get Google Sheets service
        service = create_sheets_service(credentials_dict)

        # Read existing sheet to get date column and row positions
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=sheet_id, range=f"{sheet_name}!A:AZ")
            .execute()
        )

        sheet_values = result.get("values", [])
        if not sheet_values:
            return {"success": False, "error": "Sheet is empty"}

        # Get header row
        header_row = sheet_values[0]
        print(f"\n   Sheet header ({len(header_row)} columns): {header_row[:10]}...")

        # Find date column index in Google Sheets
        date_col_index = None
        try:
            date_col_index = header_row.index(date_column)
            print(
                f"   Found '{date_column}' at column index {date_col_index} (Column {chr(65 + date_col_index)})"
            )
        except ValueError:
            # Try alternate date column names
            date_alternatives = ["Date", "DATE", "date", "Day"]
            for alt in date_alternatives:
                try:
                    date_col_index = header_row.index(alt)
                    date_column = alt
                    print(f"   Found date column '{alt}' at index {date_col_index}")
                    break
                except ValueError:
                    continue

        if date_col_index is None:
            return {
                "success": False,
                "error": f"Date column not found in sheet. Available columns: {header_row}",
            }

        # Find where operational columns start in Google Sheets
        operational_start_col = None
        operational_markers = [
            "Total Manhours",
            "Total manhours",
            "Safe man-hours",
            "Safe Man-hours",
        ]
        for marker in operational_markers:
            try:
                operational_start_col = header_row.index(marker)
                print(
                    f"   Operational data starts at column {operational_start_col} ({chr(65 + operational_start_col)}) - '{marker}'"
                )
                break
            except ValueError:
                continue

        if operational_start_col is None:
            # Fallback: assume operational starts after Day column (column E = index 4)
            operational_start_col = 4
            print(
                f"   ⚠️ Could not find operational column marker, using default: column E (index 4)"
            )

        # Create date-to-row mapping from Google Sheets
        sheet_date_map = {}
        for row_idx, row in enumerate(sheet_values[1:], start=2):
            if len(row) > date_col_index:
                date_value = row[date_col_index]
                try:
                    from datetime import datetime

                    parsed = None
                    for fmt in [
                        "%d-%b-%y",
                        "%d-%b-%Y",
                        "%Y-%m-%d",
                        "%m/%d/%Y",
                        "%d/%m/%Y",
                    ]:
                        try:
                            parsed = datetime.strptime(str(date_value).strip(), fmt)
                            break
                        except:
                            continue

                    if parsed:
                        formatted_date = parsed.strftime("%Y-%m-%d")
                        sheet_date_map[formatted_date] = row_idx
                except Exception:
                    continue

        if not sheet_date_map:
            return {"success": False, "error": "No valid dates found in Google Sheets"}

        min_date = min(sheet_date_map.keys())
        max_date = max(sheet_date_map.keys())
        print(f"\n   Found {len(sheet_date_map)} dated rows in Google Sheets")
        print(f"   Date range in sheet: {min_date} to {max_date}")

        # Match dates and prepare updates
        updates = []
        rows_updated = 0
        rows_not_found = []

        print(f"\n🔍 Date Matching Debug:")
        print(f"   Excel dates to match: {len(rows_with_dates)}")
        if len(rows_with_dates) > 0:
            print(
                f"   First Excel date: {rows_with_dates[0].get('date')} (formatted: {rows_with_dates[0].get('date_formatted', 'N/A')})"
            )
        print(f"   Sheet dates available: {len(sheet_date_map)}")
        if len(sheet_date_map) > 0:
            sample_sheet_dates = list(sheet_date_map.keys())[:3]
            print(f"   First 3 Sheet dates: {sample_sheet_dates}")

        for row_with_date in rows_with_dates:
            # Handle different row_with_date formats
            if isinstance(row_with_date, dict):
                date = row_with_date.get("date")
                row_idx = row_with_date.get("row_index", 0)
                date_formatted = row_with_date.get("date_formatted", "")
            else:
                print(f"   ⚠️ Unexpected row_with_date format: {type(row_with_date)}")
                continue

            if not date:
                print(f"   ⚠️ Row missing 'date' field: {row_with_date}")
                continue

            # ✅ TRY MULTIPLE DATE FORMATS FOR MATCHING
            dates_to_try = [date]  # Start with the primary format

            # Also try the formatted version if available
            if date_formatted:
                try:
                    from datetime import datetime

                    # Parse the formatted date and convert to YYYY-MM-DD
                    parsed = datetime.strptime(date_formatted, "%d-%b-%y")
                    alt_format = parsed.strftime("%Y-%m-%d")
                    if alt_format not in dates_to_try:
                        dates_to_try.append(alt_format)
                except:
                    pass

            # Try parsing the date itself in different formats
            try:
                from datetime import datetime

                for fmt in ["%Y-%m-%d", "%d-%b-%y", "%d-%b-%Y", "%m/%d/%Y", "%d/%m/%Y"]:
                    try:
                        parsed = datetime.strptime(str(date), fmt)
                        normalized = parsed.strftime("%Y-%m-%d")
                        if normalized not in dates_to_try:
                            dates_to_try.append(normalized)
                    except:
                        pass
            except:
                pass

            # Try to find a match
            matched = False
            matched_date = None

            for date_variant in dates_to_try:
                if date_variant in sheet_date_map:
                    matched = True
                    matched_date = date_variant
                    break

            if matched:
                sheet_row_number = sheet_date_map[matched_date]

                # Get transformed data for this row
                if row_idx < len(transformed_df):
                    transformed_row = transformed_df.iloc[row_idx]

                    # Prepare row values (only operational columns)
                    row_values = []
                    for col in transformed_df.columns:
                        value = transformed_row[col]
                        row_values.append(str(value) if pd.notna(value) else "")

                    # Calculate end column dynamically
                    end_col_index = operational_start_col + len(row_values) - 1

                    # Create update range
                    start_col_letter = chr(65 + operational_start_col)
                    # Handle columns beyond Z (AA, AB, etc.)
                    if end_col_index > 25:
                        end_col_letter = chr(64 + (end_col_index // 26)) + chr(
                            65 + (end_col_index % 26)
                        )
                    else:
                        end_col_letter = chr(65 + end_col_index)

                    update_range = f"{sheet_name}!{start_col_letter}{sheet_row_number}:{end_col_letter}{sheet_row_number}"

                    updates.append({"range": update_range, "values": [row_values]})

                    rows_updated += 1
                    if rows_updated <= 3:  # Only print first 3 for brevity
                        print(
                            f"   ✓ Matched {date} ({matched_date}) → Row {sheet_row_number} (range: {update_range})"
                        )
            else:
                rows_not_found.append(date)
                if len(rows_not_found) <= 3:  # Only print first 3 for brevity
                    print(
                        f"   ✗ Date {date} (tried: {dates_to_try}) not found in Google Sheets"
                    )

        if rows_updated > 3:
            print(f"   ... and {rows_updated - 3} more successful matches")
        if len(rows_not_found) > 3:
            print(f"   ... and {len(rows_not_found) - 3} more dates not found")

        # Batch update
        print(f"\n📤 Updating {len(updates)} rows...")
        body = {"valueInputOption": "USER_ENTERED", "data": updates}

        result = (
            service.spreadsheets()
            .values()
            .batchUpdate(spreadsheetId=sheet_id, body=body)
            .execute()
        )

        total_updated = result.get("totalUpdatedRows", 0)
        print(f"   ✅ Successfully updated {total_updated} rows in Google Sheets")

        return {
            "success": True,
            "rows_updated": rows_updated,
            "total_rows_processed": len(rows_with_dates),
            "rows_not_found": rows_not_found,
            "message": f"Successfully updated {rows_updated} rows by date matching",
        }

    except HttpError as e:
        print(f"❌ Google Sheets API error: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        print(f"❌ Error updating by date: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": f"Update failed: {str(e)}"}
    
    


# ============================================================
# DELIVERY ORDER SHEET TOOLS
# ============================================================

_SHEET_URL_RE = re.compile(r"spreadsheets/d/([a-zA-Z0-9_-]+)")

_EXPECTED_HEADERS = ["Date", "Order Reference", "Item Code", "Item Description", "QTY", "UOM", "CB Date", "Requested by"]
_EXPECTED_TABS = {"Food", "non-food"}


# ----------------------------------------------------------------------
# Delivery-order duplicate detection.
# ----------------------------------------------------------------------
# "Same data" means a row whose (Date, Order Reference, Item Code) triple
# already exists in the destination tab. That combination is the natural
# identity for a requisition line item: the same PDF re-uploaded produces
# identical triples, while legitimate re-use of a reference number on a
# different day (e.g. a rolling monthly ref) lands on a different Date
# and therefore writes a new row.
#
# Date normalization tolerates superficial formatting noise:
# - day-of-week suffix ("Nov 05, Wed" == "Nov 05")
# - whitespace collapsing, case folding
# Parsing into datetime and re-formatting is deliberately avoided; Sheets
# may round-trip dates through locale formatters and strip information
# (e.g. the "Wed" suffix), so string-normalized comparison is the most
# robust way to keep duplicate detection stable across that round-trip.

_WEEKDAY_SUFFIX_RE = re.compile(
    r",\s*(?:Mon|Tue|Tues|Wed|Thu|Thur|Fri|Sat|Sun)[a-z]*\.?\s*$",
    re.IGNORECASE,
)


def _norm_date_for_dedup(val: Any) -> str:
    """Normalize a date cell value for duplicate-key comparison.

    Collapses "Nov 05, Wed" and "Nov 05" to the same key, folds
    whitespace and case. Returns an empty string for empty input.
    """
    s = str(val or "").strip()
    if not s:
        return ""
    s = _WEEKDAY_SUFFIX_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _row_dedup_key(row: List[Any]) -> Tuple[str, str, str]:
    """Build a duplicate-detection key from a requisition row's first
    three columns (Date, Order Reference, Item Code).

    Rows read back from the sheet may be shorter than 3 cells when the
    row is empty or partial — defensively pad to three slots.
    """
    date_cell = row[0] if len(row) > 0 else ""
    ref_cell = row[1] if len(row) > 1 else ""
    code_cell = row[2] if len(row) > 2 else ""
    return (
        _norm_date_for_dedup(date_cell),
        str(ref_cell or "").strip().lower(),
        str(code_cell or "").strip().lower(),
    )


def _parse_orders_input(parsed_orders: Any) -> list:
    """Robustly parse the parsed_orders argument which may arrive as a
    JSON string, Python repr string (from Jinja2 rendering), dict wrapper,
    or a native list.  Returns the list of order objects or raises ValueError."""
    if isinstance(parsed_orders, str):
        try:
            parsed_orders = json.loads(parsed_orders)
        except json.JSONDecodeError:
            import ast
            try:
                parsed_orders = ast.literal_eval(parsed_orders)
            except (ValueError, SyntaxError) as e:
                raise ValueError(f"Could not parse parsed_orders string: {e}")
    if isinstance(parsed_orders, dict) and "parsed_orders" in parsed_orders:
        parsed_orders = parsed_orders["parsed_orders"]
    if not isinstance(parsed_orders, list):
        raise ValueError(f"parsed_orders must be a list, got {type(parsed_orders).__name__}")
    return parsed_orders


def _extract_sheet_id(sheet_id_or_url: str) -> str:
    """Extract the spreadsheet ID from a URL or return as-is if already an ID."""
    m = _SHEET_URL_RE.search(sheet_id_or_url)
    if m:
        return m.group(1)
    return sheet_id_or_url.strip()


def _classify_http_error(e: HttpError) -> Dict[str, Any]:
    """Map a Google API HttpError to a user-friendly message explaining the
    access/permission problem."""
    status = e.resp.status if hasattr(e, "resp") else 0
    if status == 404:
        return {
            "success": False,
            "error": (
                "The spreadsheet was not found. This usually means the link is "
                "incorrect, the sheet has been deleted, or it has not been shared "
                "with you at all. Please double-check the URL and ensure the "
                "owner has shared it with your Google account."
            ),
            "error_type": "not_found",
        }
    if status == 403:
        detail = str(e)
        if "insufficientPermissions" in detail or "PERMISSION_DENIED" in detail:
            return {
                "success": False,
                "error": (
                    "You do not have permission to access this spreadsheet. "
                    "Ask the sheet owner to share it with your Google account."
                ),
                "error_type": "permission_denied",
            }
        return {
            "success": False,
            "error": (
                "Access to this spreadsheet was denied. You may only have "
                "view/read-only access. To write data you need Editor access — "
                "ask the sheet owner to change your permission from Viewer to Editor."
            ),
            "error_type": "permission_denied",
        }
    return {"success": False, "error": f"Google Sheets API error (HTTP {status}): {e}"}


def _find_tab(tab_names: List[str], target: str) -> Optional[str]:
    """Case-insensitive tab lookup. Returns the actual tab name as it appears
    in the spreadsheet, or None if no match."""
    target_lower = target.lower()
    for t in tab_names:
        if t.lower() == target_lower:
            return t
    return None


# The only two categories the requisition sheet template accepts. Keys cover
# every normalisation form that `_resolve_tab_for_category` might see after
# `.upper().replace(" ", "")` / underscore handling. Tech / IT / other
# categories are NOT in this map — a PDF with that content should have been
# rejected at the Mapping agent's category gate before reaching this
# function, and if it somehow slips through we skip + warn rather than
# force-routing into the wrong tab.
_CATEGORY_TAB_MAP: Dict[str, str] = {
    "FOOD": "Food",
    "NON-FOOD": "non-food",
    "NONFOOD": "non-food",
    "NON_FOOD": "non-food",
}


def _resolve_tab_for_category(
    category: str, tab_names: List[str]
) -> tuple[Optional[str], Optional[str]]:
    """Return ``(actual_tab, warning_or_none)`` for a given category string.

    Strictly binary: only FOOD and NON-FOOD resolve to a tab. Any other
    category returns ``(None, <warning>)`` so the calling code skips the
    order. This is the defensive layer behind the Mapping agent's category
    gate; in steady state the Mapping agent rejects non-FOOD/NON-FOOD PDFs
    before they ever reach the Sheets agent, but this function remains the
    source of truth for routing so we never silently mis-route.

    This is a pure function of ``category`` and ``tab_names`` — no I/O.
    """
    raw = (category or "").strip()
    normalised = raw.upper().replace(" ", "").replace("_", "-")

    preferred = _CATEGORY_TAB_MAP.get(normalised)
    if not preferred:
        return None, (
            f"Category {raw!r} is not FOOD or NON-FOOD — order skipped. "
            "Only the two requisition categories have a destination in the "
            "Food / non-food sheet template."
        )

    actual = _find_tab(tab_names, preferred)
    if actual:
        return actual, None

    return None, (
        f"Tab '{preferred}' is missing from the spreadsheet — order skipped. "
        "The requisition template requires both 'Food' and 'non-food' tabs. "
        f"Available tabs: {tab_names!r}."
    )


def _check_write_permission(service, sheet_id: str) -> Optional[str]:
    """Attempt a no-op write that only editors can perform.
    Returns an error string if write is not possible, or None if OK.

    Strategy: update the spreadsheet title to its current value.  This is a
    no-data-change write that the API still gate-keeps behind editor
    permissions."""
    try:
        spreadsheet = service.spreadsheets().get(
            spreadsheetId=sheet_id, fields="properties.title"
        ).execute()
        current_title = spreadsheet.get("properties", {}).get("title", "")
        service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={
                "requests": [{
                    "updateSpreadsheetProperties": {
                        "properties": {"title": current_title},
                        "fields": "title",
                    }
                }]
            },
        ).execute()
        return None
    except HttpError as e:
        status = e.resp.status if hasattr(e, "resp") else 0
        if status == 403:
            return (
                "You have read-only (Viewer) access to this spreadsheet. "
                "To write delivery order data you need Editor access. "
                "Ask the sheet owner to change your sharing permission to Editor."
            )
        return f"Write permission check failed (HTTP {status}): {e}"
    except Exception as e:
        return f"Write permission check failed: {e}"


def validate_delivery_sheet(
    sheet_id: str,
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Validate that a Google Sheet matches the Production Materials Requisition
    List template (headers A-H and Food/non-food tabs).  Also verifies the
    caller has **Editor** (write) access so issues surface early.

    Args:
        sheet_id: Google Sheets ID or full URL.
        credentials_dict: Google OAuth credentials.

    Returns:
        Validation result with is_valid, headers_found, tabs_found, mismatch_details.
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        real_id = _extract_sheet_id(sheet_id)
        service = create_sheets_service(credentials_dict)

        # --- 1. Fetch spreadsheet metadata (tests basic read access) --------
        try:
            spreadsheet = service.spreadsheets().get(spreadsheetId=real_id).execute()
        except HttpError as e:
            return _classify_http_error(e)

        tab_names = [
            s.get("properties", {}).get("title", "")
            for s in spreadsheet.get("sheets", [])
        ]

        # --- 2. Case-insensitive tab matching ------------------------------
        matching_tabs: List[str] = []
        missing_expected: List[str] = []
        for expected_tab in _EXPECTED_TABS:
            actual = _find_tab(tab_names, expected_tab)
            if actual:
                matching_tabs.append(actual)
            else:
                missing_expected.append(expected_tab)

        # --- 3. Check headers in EVERY matching tab -------------------------
        all_headers: Dict[str, List[str]] = {}
        mismatches: List[Dict[str, Any]] = []

        tabs_to_check = matching_tabs if matching_tabs else tab_names[:1]
        for tab in tabs_to_check:
            try:
                result = (
                    service.spreadsheets()
                    .values()
                    .get(spreadsheetId=real_id, range=f"'{tab}'!1:1")
                    .execute()
                )
                row = result.get("values", [[]])[0] if result.get("values") else []
            except HttpError:
                row = []
            all_headers[tab] = row

            for idx, expected in enumerate(_EXPECTED_HEADERS):
                actual = row[idx] if idx < len(row) else "<missing>"
                if actual.strip().lower() != expected.strip().lower():
                    mismatches.append({
                        "tab": tab,
                        "column": chr(65 + idx),
                        "expected": expected,
                        "found": actual,
                    })

        is_valid = len(mismatches) == 0 and len(matching_tabs) == len(_EXPECTED_TABS)

        if not is_valid:
            details = []
            if mismatches:
                details.append("Header mismatches: " + ", ".join(
                    f"[{m['tab']}] Column {m['column']} expected '{m['expected']}' but found '{m['found']}'"
                    for m in mismatches
                ))
            if missing_expected:
                details.append(f"Missing tabs: {', '.join(missing_expected)}")

            spreadsheet_title = spreadsheet.get("properties", {}).get("title", "")

            # A completely-missing tab set almost always means the user
            # pointed us at a DIFFERENT spreadsheet entirely (not the
            # requisition template). Call that out explicitly — it's a
            # much more actionable message than "header mismatch".
            if len(missing_expected) == len(_EXPECTED_TABS):
                error_msg = (
                    f"This is not the designated requisition sheet. The "
                    f"spreadsheet {spreadsheet_title!r} does not have the "
                    f"required 'Food' and 'non-food' tabs — it looks like a "
                    f"different sheet. Its tabs are: {tab_names!r}. The "
                    f"Production Materials Requisition List template is "
                    f"required."
                )
            else:
                error_msg = (
                    f"The spreadsheet {spreadsheet_title!r} does not match "
                    f"the Production Materials Requisition List template. "
                    + "; ".join(details)
                )

            return {
                "success": False,
                "is_valid": False,
                "sheet_id": real_id,
                "sheet_title": spreadsheet_title,
                "headers_by_tab": all_headers,
                "tabs_found": tab_names,
                "mismatch_details": mismatches,
                "missing_tabs": missing_expected,
                "error_type": "wrong_sheet",
                "error": error_msg,
            }

        # --- 4. Proactive write-permission check ----------------------------
        write_err = _check_write_permission(service, real_id)
        if write_err:
            return {
                "success": False,
                "is_valid": True,
                "sheet_id": real_id,
                "tabs_found": tab_names,
                "matching_tabs": matching_tabs,
                "error": write_err,
                "error_type": "read_only",
            }

        return {
            "success": True,
            "is_valid": True,
            "sheet_id": real_id,
            "headers_by_tab": all_headers,
            "tabs_found": tab_names,
            "matching_tabs": matching_tabs,
            "message": "Sheet is a valid requisition list template with write access confirmed",
        }

    except HttpError as e:
        return _classify_http_error(e)
    except Exception as e:
        return {"success": False, "error": f"Validation failed: {str(e)}"}


def preview_delivery_order_insertion(
    sheet_id: str,
    parsed_orders: Any,
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Preview what will be written to the requisition sheet.  Detects duplicates
    (same Order Reference + Item Code already in sheet), missing data, and rows
    that would override existing data.

    Args:
        sheet_id: Google Sheets ID or URL.
        parsed_orders: JSON string (or list) of parsed orders from
                       mapping_agent.parse_delivery_order_pdfs.
        credentials_dict: Google OAuth credentials.

    Returns:
        Preview report with rows, duplicates, warnings, target_tab info.
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        try:
            parsed_orders = _parse_orders_input(parsed_orders)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        real_id = _extract_sheet_id(sheet_id)
        service = create_sheets_service(credentials_dict)

        try:
            spreadsheet = service.spreadsheets().get(spreadsheetId=real_id).execute()
        except HttpError as e:
            return _classify_http_error(e)

        tab_names = [
            s.get("properties", {}).get("title", "")
            for s in spreadsheet.get("sheets", [])
        ]

        # Build flat rows and group by target tab (case-insensitive lookup)
        tab_rows: Dict[str, List[List[str]]] = {}
        all_preview_rows = []
        warnings: List[str] = []

        for order in parsed_orders:
            header = order.get("header", {})
            category = header.get("category") or ""
            actual_tab, route_warning = _resolve_tab_for_category(category, tab_names)

            if not actual_tab:
                # Non-FOOD/NON-FOOD category, or a missing destination tab.
                # Either way this order is skipped — don't force it anywhere.
                warnings.append(
                    f"{route_warning} (order {header.get('reference_number', '?')})"
                )
                continue

            date_val = header.get("date", "")
            ref = header.get("reference_number", "")
            requested_by = header.get("requested_by", "")
            header_cb_date = header.get("cb_date", "")

            for item in order.get("line_items", []):
                row = [
                    date_val,
                    ref,
                    item.get("item_code", ""),
                    item.get("item_description", ""),
                    str(item.get("qty", "")),
                    item.get("uom", ""),
                    item.get("cb_date", "") or header_cb_date,
                    requested_by,
                ]
                tab_rows.setdefault(actual_tab, []).append(row)
                all_preview_rows.append({
                    "tab": actual_tab,
                    "values": row,
                })

                if not item.get("item_code"):
                    warnings.append(f"Missing Item Code in row: {item.get('item_description', '?')[:40]}")
                if not item.get("qty") and item.get("qty") != 0:
                    warnings.append(f"Missing QTY for {item.get('item_code', '?')}")

        # Duplicate detection using the (Date, Order Reference, Item Code)
        # key. Catches both rows that already exist in the destination tab
        # AND rows that are duplicated WITHIN the same preview batch (e.g.
        # the same PDF was passed to parse_delivery_order_pdfs twice in
        # one call). The preview and the write paths share the same
        # helper `_row_dedup_key` so the user sees exactly the rows the
        # write will skip.
        duplicates: List[Dict[str, Any]] = []
        for tab_name, new_rows in tab_rows.items():
            try:
                existing = (
                    service.spreadsheets()
                    .values()
                    .get(spreadsheetId=real_id, range=f"'{tab_name}'!A:H")
                    .execute()
                )
                existing_values = existing.get("values", [])
                existing_keys = {_row_dedup_key(erow) for erow in existing_values[1:]}

                batch_keys: set = set()
                for row in new_rows:
                    key = _row_dedup_key(row)
                    if key in existing_keys:
                        duplicates.append({
                            "tab": tab_name,
                            "reason": "already in sheet",
                            "date": row[0] if len(row) > 0 else "",
                            "order_reference": row[1] if len(row) > 1 else "",
                            "item_code": row[2] if len(row) > 2 else "",
                        })
                    elif key in batch_keys:
                        duplicates.append({
                            "tab": tab_name,
                            "reason": "duplicate within batch",
                            "date": row[0] if len(row) > 0 else "",
                            "order_reference": row[1] if len(row) > 1 else "",
                            "item_code": row[2] if len(row) > 2 else "",
                        })
                    else:
                        batch_keys.add(key)
            except Exception as e:
                warnings.append(f"Could not read existing data from tab '{tab_name}': {str(e)}")

        total_new = sum(len(rows) for rows in tab_rows.values())

        return {
            "success": True,
            "preview_rows": all_preview_rows,
            "total_new_rows": total_new,
            "duplicates": duplicates,
            "duplicate_count": len(duplicates),
            "warnings": warnings,
            "target_tabs": list(tab_rows.keys()),
            "message": f"{total_new} row(s) ready to insert across {len(tab_rows)} tab(s). "
                       + (f"{len(duplicates)} duplicate(s) detected." if duplicates else "No duplicates detected."),
        }

    except HttpError as e:
        return _classify_http_error(e)
    except Exception as e:
        return {"success": False, "error": f"Preview failed: {str(e)}"}


def write_delivery_order_data(
    sheet_id: str,
    parsed_orders: Any,
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Write confirmed delivery order data to the requisition sheet.
    Appends rows to the correct tab (Food / non-food) based on category.

    Args:
        sheet_id: Google Sheets ID or URL.
        parsed_orders: JSON string (or list) of parsed orders.
        credentials_dict: Google OAuth credentials.

    Returns:
        Summary of rows written per tab.
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        try:
            parsed_orders = _parse_orders_input(parsed_orders)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        real_id = _extract_sheet_id(sheet_id)
        service = create_sheets_service(credentials_dict)

        try:
            spreadsheet = service.spreadsheets().get(spreadsheetId=real_id).execute()
        except HttpError as e:
            return _classify_http_error(e)

        tab_names = [
            s.get("properties", {}).get("title", "")
            for s in spreadsheet.get("sheets", [])
        ]

        # Build flat rows grouped by target tab (case-insensitive lookup)
        tab_rows: Dict[str, List[List[str]]] = {}
        skipped_warnings: List[str] = []

        for order in parsed_orders:
            header = order.get("header", {})
            category = header.get("category") or ""
            actual_tab, route_warning = _resolve_tab_for_category(category, tab_names)

            if not actual_tab:
                # Non-FOOD/NON-FOOD category, or a missing destination tab.
                # Skip — the requisition template only has homes for FOOD
                # and NON-FOOD, never Tech / IT / anything else.
                skipped_warnings.append(
                    f"{route_warning} (order {header.get('reference_number', '?')})"
                )
                continue

            date_val = header.get("date", "")
            ref = header.get("reference_number", "")
            requested_by = header.get("requested_by", "")
            header_cb_date = header.get("cb_date", "")

            for item in order.get("line_items", []):
                row = [
                    date_val,
                    ref,
                    item.get("item_code", ""),
                    item.get("item_description", ""),
                    str(item.get("qty", "")),
                    item.get("uom", ""),
                    item.get("cb_date", "") or header_cb_date,
                    requested_by,
                ]
                tab_rows.setdefault(actual_tab, []).append(row)

        if not tab_rows:
            return {
                "success": False,
                "error": "No rows to write. " + (" ".join(skipped_warnings) if skipped_warnings else "parsed_orders may be empty."),
            }

        # Duplicate filter — shared semantics with preview_delivery_order_insertion.
        # For each destination tab we read what's already in the sheet
        # and drop any incoming row whose (Date, Order Reference, Item
        # Code) triple already exists. We also dedupe within the same
        # batch so two uploads of the same PDF in a single call don't
        # write identical rows twice. The Google Sheets API does not
        # offer a native "upsert / skip-duplicate" for append calls, so
        # this client-side filter is the only thing keeping the sheet
        # clean when the user re-submits the same PDF.
        filtered_tab_rows: Dict[str, List[List[str]]] = {}
        duplicates_skipped: List[Dict[str, Any]] = []

        for tab_name, rows in tab_rows.items():
            try:
                existing = (
                    service.spreadsheets()
                    .values()
                    .get(spreadsheetId=real_id, range=f"'{tab_name}'!A:H")
                    .execute()
                )
                existing_values = existing.get("values", [])
            except HttpError as e:
                status = e.resp.status if hasattr(e, "resp") else 0
                if status == 403:
                    return {
                        "success": False,
                        "error": (
                            f"Failed to read existing rows from tab '{tab_name}' "
                            "for duplicate checking: you only have read access "
                            "permissions above what this write needs. Ask the "
                            "sheet owner to grant you Editor permission."
                        ),
                        "error_type": "read_only",
                    }
                return _classify_http_error(e)
            except Exception as e:
                # A read failure shouldn't silently drop duplicate
                # detection — surface it instead of writing blind.
                return {
                    "success": False,
                    "error": f"Could not read existing rows from tab '{tab_name}' for duplicate check: {str(e)}",
                }

            existing_keys = {_row_dedup_key(erow) for erow in existing_values[1:]}
            batch_keys: set = set()
            kept_rows: List[List[str]] = []

            for row in rows:
                key = _row_dedup_key(row)
                if key in existing_keys:
                    duplicates_skipped.append({
                        "tab": tab_name,
                        "reason": "already in sheet",
                        "date": row[0] if len(row) > 0 else "",
                        "order_reference": row[1] if len(row) > 1 else "",
                        "item_code": row[2] if len(row) > 2 else "",
                    })
                    continue
                if key in batch_keys:
                    duplicates_skipped.append({
                        "tab": tab_name,
                        "reason": "duplicate within batch",
                        "date": row[0] if len(row) > 0 else "",
                        "order_reference": row[1] if len(row) > 1 else "",
                        "item_code": row[2] if len(row) > 2 else "",
                    })
                    continue
                batch_keys.add(key)
                kept_rows.append(row)

            if kept_rows:
                filtered_tab_rows[tab_name] = kept_rows

        total_incoming = sum(len(r) for r in tab_rows.values())
        if not filtered_tab_rows:
            # Every incoming row was a duplicate. This is a legitimate
            # no-op outcome (user re-submitted the same PDF) and reports
            # as success with rows_written=0 so the caller can surface a
            # "nothing new to add" message without treating it as error.
            return {
                "success": True,
                "rows_written": 0,
                "duplicates_skipped": len(duplicates_skipped),
                "skipped_samples": duplicates_skipped[:10],
                "tabs_used": [],
                "warnings": skipped_warnings if skipped_warnings else None,
                "message": (
                    f"No new rows written — all {total_incoming} row(s) were "
                    f"already present in the sheet or duplicated within the batch."
                ),
            }

        total_written = 0
        tabs_used = []
        errors = []

        for tab_name, rows in filtered_tab_rows.items():
            try:
                service.spreadsheets().values().append(
                    spreadsheetId=real_id,
                    range=f"'{tab_name}'!A:H",
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                    body={"values": rows},
                ).execute()
                total_written += len(rows)
                tabs_used.append({"tab": tab_name, "rows_written": len(rows)})
            except HttpError as e:
                status = e.resp.status if hasattr(e, "resp") else 0
                if status == 403:
                    return {
                        "success": False,
                        "error": (
                            f"Failed to write to tab '{tab_name}': you only have "
                            "read-only access to this spreadsheet. Ask the sheet "
                            "owner to grant you Editor permission."
                        ),
                        "error_type": "read_only",
                    }
                errors.append(f"Error writing to '{tab_name}': {e}")
            except Exception as e:
                errors.append(f"Error writing to '{tab_name}': {e}")

        if errors and total_written == 0:
            return {"success": False, "error": "; ".join(errors)}

        return {
            "success": True,
            "rows_written": total_written,
            "duplicates_skipped": len(duplicates_skipped),
            "skipped_samples": duplicates_skipped[:10] if duplicates_skipped else None,
            "tabs_used": tabs_used,
            "errors": errors if errors else None,
            # Surface routing fallbacks (e.g. Tech items that landed in
            # non-food because the sheet has no Tech tab) so the user knows
            # WHY their rows ended up where they did.
            "warnings": skipped_warnings if skipped_warnings else None,
            "message": (
                f"Successfully wrote {total_written} row(s) to {len(tabs_used)} tab(s)"
                + (f"; skipped {len(duplicates_skipped)} duplicate row(s) already in the sheet" if duplicates_skipped else "")
            ),
        }

    except HttpError as e:
        return _classify_http_error(e)
    except Exception as e:
        return {"success": False, "error": f"Write failed: {str(e)}"}


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
    "update_by_date_match": {
        "func": update_by_date_match,
        "description": "Update Google Sheets rows by matching dates (no append, only update)",
    },
    "get_sheet_headers": {
        "func": get_sheet_headers,
        "description": "Get header row of an existing sheet for column mapping",
    },
    "validate_delivery_sheet": {
        "func": validate_delivery_sheet,
        "description": "Validate that a sheet matches the requisition list template",
    },
    "preview_delivery_order_insertion": {
        "func": preview_delivery_order_insertion,
        "description": "Preview delivery order data before writing to sheet",
    },
    "write_delivery_order_data": {
        "func": write_delivery_order_data,
        "description": "Write confirmed delivery order data to the requisition sheet",
    },
}


# ============================================================
# API ENDPOINTS
# ============================================================


@app.post("/execute_task", response_model=ToolResponse)
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
        
        # Print complete result before returning
        print(f"\n📤 Complete Result:")
        print(json.dumps(result, indent=2, default=str))
        print(f"{'='*60}\n")

        return ToolResponse(
            success=result.get("success", False),
            result=result if result.get("success") else None,
            error=result.get("error") if not result.get("success") else None,
            error_type=result.get("error_type") if not result.get("success") else None,
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

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
            refresh_token=credentials_dict.refresh_token
            or os.getenv("GOOGLE_REFRESH_TOKEN"),
            client_id=credentials_dict.client_id or os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=credentials_dict.client_secret
            or os.getenv("GOOGLE_CLIENT_SECRET"),
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

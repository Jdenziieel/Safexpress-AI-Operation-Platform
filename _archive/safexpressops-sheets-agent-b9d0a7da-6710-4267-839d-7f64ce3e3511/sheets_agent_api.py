"""
Google Sheets Agent API - Lambda Compatible Version
FIXED: Single correct update_rows_by_date() for OPR workflow
"""

import json
from pydantic import BaseModel
from typing import Dict, List, Any, Optional
import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


# ============================================================
# PYDANTIC MODELS
# ============================================================

class CredentialsDict(BaseModel):
    """Google OAuth credentials"""
    access_token: str
    refresh_token: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def create_sheets_service(credentials_dict):
    """Create authenticated Google Sheets service"""
    
    # Handle both dict and CredentialsDict pydantic object
    if hasattr(credentials_dict, 'access_token'):
        # It's a CredentialsDict pydantic object
        access_token = credentials_dict.access_token
        refresh_token = credentials_dict.refresh_token
        client_id = credentials_dict.client_id
        client_secret = credentials_dict.client_secret
    else:
        # It's a plain dict
        access_token = credentials_dict.get('access_token', '')
        refresh_token = credentials_dict.get('refresh_token')
        client_id = credentials_dict.get('client_id')
        client_secret = credentials_dict.get('client_secret')

    if not access_token:
        print("No access token, using service account from Secrets Manager")
        return create_service_account_sheets_service()

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("sheets", "v4", credentials=creds)

def create_service_account_sheets_service():
    """Fallback: create Sheets service using tokens from Secrets Manager"""
    import boto3
    secrets_client = boto3.client('secretsmanager', region_name='ap-southeast-1')
    secret_name = os.environ.get('GOOGLE_OAUTH_SECRET', 'prod/app/google-oauth')
    response = secrets_client.get_secret_value(SecretId=secret_name)
    secret_data = json.loads(response['SecretString'])

    creds = Credentials(
        token=secret_data.get('access_token', ''),
        refresh_token=secret_data.get('refresh_token', ''),
        client_id=secret_data.get('GOOGLE_CLIENT_ID'),
        client_secret=secret_data.get('GOOGLE_CLIENT_SECRET'),
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("sheets", "v4", credentials=creds)


def col_index_to_letter(col_index):
    """Convert 0-based column index to Excel-style column letter (A, B, ... Z, AA, AB, etc.)"""
    result = ""
    col_index += 1  # Convert to 1-based
    
    while col_index > 0:
        col_index -= 1
        result = chr(65 + (col_index % 26)) + result
        col_index //= 26
    
    return result

def parse_date_flexible(date_value):
    """Parse various date formats flexibly"""
    if pd.isna(date_value) or date_value == '' or date_value is None:
        return None
    
    # If already a datetime object
    if isinstance(date_value, (datetime, pd.Timestamp)):
        return date_value. strftime('%Y-%m-%d')
    
    # If it's a number (Excel date serial)
    if isinstance(date_value, (int, float)):
        try:
            from datetime import timedelta
            base_date = datetime(1899, 12, 30)
            parsed = base_date + timedelta(days=int(date_value))
            return parsed. strftime('%Y-%m-%d')
        except:
            return None
    
    # If it's a string, try multiple formats
    if isinstance(date_value, str):
        date_str = str(date_value).strip()
        
        # PRIORITY: Excel-style formats like "01-Jan-25"
        date_formats = [
            '%d-%b-%y',      # 01-Jan-25 (YOUR PRIMARY FORMAT)
            '%d-%b-%Y',      # 01-Jan-2025
            '%d/%b/%y',      # 01/Jan/25
            '%d/%b/%Y',      # 01/Jan/2025
            '%Y-%m-%d',      # 2025-01-01
            '%m/%d/%Y',      # 01/01/2025
            '%d/%m/%Y',      # 01/01/2025
            '%m/%d/%y',      # 01/01/25
            '%d/%m/%y',      # 01/01/25
            '%d-%B-%y',      # 01-January-25
            '%d-%B-%Y',      # 01-January-2025
        ]
        
        for fmt in date_formats:
            try:
                parsed = datetime.strptime(date_str, fmt)
                
                # FIX: Handle 2-digit years correctly
                if parsed. year < 100:
                    parsed = parsed.replace(year=parsed.year + 2000)
                elif parsed.year < 1950:
                    parsed = parsed.replace(year=parsed.year + 100)
                
                return parsed.strftime('%Y-%m-%d')
            except ValueError:
                continue
        
        # Fallback to pandas
        try:
            parsed = pd.to_datetime(date_str, dayfirst=True)
            return parsed.strftime('%Y-%m-%d')
        except:
            pass
    
    return None
# ============================================================
# TOOL IMPLEMENTATIONS
# ============================================================

def create_sheet(title: str, sheet_names: list = None, initial_data: list = None, 
                credentials_dict: CredentialsDict = None):
    """Create a new Google Spreadsheet"""
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}
        
        print(f"Creating sheet: {title}")
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
        
        print(f"   Created: {sheet_url}")
        return {
            "success": True,
            "sheet_id": sheet_id,
            "sheet_url": sheet_url,
            "title": title,
        }
    except HttpError as e:
        print(f"   API Error: {str(e)}")
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        print(f"   Error: {str(e)}")
        return {"success": False, "error": f"Failed to create sheet: {str(e)}"}


def read_sheet(sheet_id: str, range_name: str = "Sheet1",
               credentials_dict: CredentialsDict = None,
               value_render_option: str = "FORMATTED_VALUE") -> Dict[str, Any]:
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        service = create_sheets_service(credentials_dict)

        # Wrap in single quotes if sheet name contains spaces
        if ' ' in range_name and not range_name.startswith("'"):
            range_name = f"'{range_name}'"

        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=range_name,
            valueRenderOption=value_render_option
        ).execute()

        values = result.get("values", [])
        return {
            "success": True,
            "data": values,
            "row_count": len(values),
            "column_count": len(values[0]) if values else 0,
        }
    except HttpError as e:
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to read sheet: {str(e)}"}


def update_sheet(sheet_id: str, range_name: str, data: List[List[Any]], 
                credentials_dict: CredentialsDict = None) -> Dict[str, Any]:
    """Update data in a specific range"""
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}
        
        service = create_sheets_service(credentials_dict)
        result = service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=range_name,
            valueInputOption="RAW",
            body={"values": data},
        ).execute()
        
        return {
            "success": True,
            "updated_cells": result.get("updatedCells", 0),
        }
    except HttpError as e:
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to update sheet: {str(e)}"}


def batch_update_cells(
    sheet_id: str,
    updates: List[Dict[str, Any]],
    credentials_dict: CredentialsDict = None,
    value_input_option: str = 'USER_ENTERED',
) -> Dict[str, Any]:
    """
    Apply many non-contiguous cell updates in a single Sheets API call.

    `updates` is a list of `{'range': 'Sheet!A1', 'values': [[...]]}` entries
    (same shape that Sheets' values.batchUpdate accepts).  Using this tool
    instead of looping `update_sheet` avoids the per-call round-trip cost that
    previously caused the horizontal / multi-section write paths to appear to
    "hang" or time out on larger writes and also lets us surface a single
    truthful success/error signal to the orchestrator.
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        if not updates:
            return {"success": True, "cells_updated": 0, "updates_applied": 0}

        service = create_sheets_service(credentials_dict)

        cleaned = []
        for u in updates:
            rng = u.get('range')
            vals = u.get('values')
            if not rng or vals is None:
                continue
            norm_vals = []
            for row in vals:
                norm_row = []
                for cell in row:
                    if cell is None:
                        norm_row.append('')
                    elif isinstance(cell, (np.integer, np.int64, np.int32)):
                        norm_row.append(int(cell))
                    elif isinstance(cell, (np.floating, np.float64, np.float32)):
                        norm_row.append(float(cell))
                    else:
                        try:
                            if pd.isna(cell):
                                norm_row.append('')
                                continue
                        except (TypeError, ValueError):
                            pass
                        if isinstance(cell, (int, float)):
                            norm_row.append(cell)
                        else:
                            norm_row.append(str(cell))
                norm_vals.append(norm_row)
            cleaned.append({'range': rng, 'values': norm_vals})

        if not cleaned:
            return {"success": True, "cells_updated": 0, "updates_applied": 0}

        print(f"\nBatch-updating {len(cleaned)} cell ranges...")

        response = service.spreadsheets().values().batchUpdate(
            spreadsheetId=sheet_id,
            body={'valueInputOption': value_input_option, 'data': cleaned}
        ).execute()

        total_cells = response.get('totalUpdatedCells', 0)
        print(f"   Batch update: {total_cells} cells updated across {len(cleaned)} ranges")

        return {
            'success': True,
            'cells_updated': total_cells,
            'updates_applied': len(cleaned),
        }

    except HttpError as e:
        print(f"   Google Sheets API Error: {str(e)}")
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        print(f"   Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"Failed to batch update cells: {str(e)}"}


def update_rows_by_date(
    sheet_id: str,
    sheet_name: str,
    date_column_name: str,
    rows_with_dates: List[Dict[str, Any]],
    credentials_dict: CredentialsDict = None,
    header_row: int = 0,
    data_start_row: int = None,
    data_end_row: int = None
) -> Dict[str, Any]:
    """
    Update specific rows by matching dates.
    header_row: 0-indexed row containing column headers (default 0, use 1+ for grouped headers).

    Section row-range pinning (Fix L for the cross-section anchor collision bug):
        ``data_start_row`` and ``data_end_row`` are 1-indexed sheet-row bounds
        (both inclusive). When provided, only rows whose ``sheet_row_number``
        falls within ``[data_start_row..data_end_row]`` are added to the
        date-to-row map and considered for matching. This prevents a date
        anchor that appears in MULTIPLE sections of the same tab from
        triggering writes against the wrong section. ``None`` on either
        bound means "no limit on that side", preserving the legacy
        whole-tab behavior so single-section targets are unaffected.
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}
        
        print(f"\nUpdating rows by date in {sheet_name}...")
        print(f"   Sheet ID: {sheet_id}")
        print(f"   Date column: {date_column_name}")
        print(f"   Rows to update: {len(rows_with_dates)}")
        if header_row > 0:
            print(f"   Header row: {header_row} (grouped headers)")
        if data_start_row is not None or data_end_row is not None:
            print(f"   Section row-range pin: rows {data_start_row}..{data_end_row} (1-indexed, inclusive)")
        
        service = create_sheets_service(credentials_dict)
        
        print(f"\n   Step 1: Reading existing sheet...")
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=f"{sheet_name}!A:ZZ"
        ).execute()
        
        existing_values = result.get('values', [])
        
        if not existing_values or len(existing_values) < header_row + 2:
            return {
                'success': False,
                'error': 'Sheet is empty or has no data rows'
            }
        
        headers = existing_values[header_row]
        data_rows = existing_values[header_row + 1:]
        
        # Step 2: Find the Date column index
        print(f"\n   Step 2: Finding date column...")
        date_col_index = None
        for i, header in enumerate(headers):
            if header.strip().lower() == date_column_name.strip().lower():
                date_col_index = i
                break
        
        if date_col_index is None:
            return {
                'success': False,
                'error': f"Date column '{date_column_name}' not found in headers"
            }
        
        print(f"      Date column '{date_column_name}' found at index {date_col_index}")
        
        # Step 3: Build a date-to-row-index map for existing data
        print(f"\n    Step 3: Building date mapping...")
        date_to_row_map = {}
        rows_skipped_outside_section = 0
        
        for row_idx, row in enumerate(data_rows):
            sheet_row_number = row_idx + header_row + 2
            
            # Section row-range pin: skip rows outside the chosen section so a
            # date that appears in BOTH sections (Inbound row 7 + Outbound
            # row 13 for the same date) does not silently overwrite the wrong
            # section. The legacy unbounded behavior is preserved when both
            # bounds are None.
            if data_start_row is not None and sheet_row_number < data_start_row:
                rows_skipped_outside_section += 1
                continue
            if data_end_row is not None and sheet_row_number > data_end_row:
                # Rows are scanned top-down so once we cross the end bound
                # nothing below it can be in the section; break early.
                break
            
            if len(row) > date_col_index:
                date_value = row[date_col_index]
                parsed_date = parse_date_flexible(date_value)
                
                if parsed_date:
                    date_to_row_map[parsed_date] = {
                        'row_number': sheet_row_number,
                        'row_index': row_idx,
                        'original_date': date_value
                    }
        
        if rows_skipped_outside_section:
            print(f"      Skipped {rows_skipped_outside_section} row(s) outside section bounds "
                  f"({data_start_row}..{data_end_row})")
        print(f"      Found {len(date_to_row_map)} dates in sheet")
        if date_to_row_map:
            sample_dates = list(date_to_row_map.keys())[:3]
            print(f"      Sample dates: {sample_dates}")
        
        # Step 4: Match uploaded rows to sheet rows
        print(f"\n   Step 4: Matching uploaded dates to sheet rows...")
        updates = []
        matched_dates = []
        unmatched_dates = []
        
        for item in rows_with_dates:
            # Try both 'date' and 'date_formatted' keys
            date_value = item.get('date_formatted') or item.get('date')
            parsed_date = parse_date_flexible(date_value)
            row_data = item.get('row_data', {})
            
            if not parsed_date:
                continue
            
            # Check if this date exists in the sheet
            if parsed_date in date_to_row_map:
                sheet_info = date_to_row_map[parsed_date]
                sheet_row_number = sheet_info['row_number']
                
                # NEW APPROACH: Update only specific columns, not entire row
                # This preserves formulas in calculated columns
                for col_name, value in row_data.items():
                    try:
                        # Case-insensitive + whitespace-normalized header matching
                        col_index = None
                        col_name_normalized = ' '.join(col_name.strip().split()).lower()
                        for i, header in enumerate(headers):
                            header_normalized = ' '.join(header.strip().replace('\n', ' ').split()).lower()
                            if col_name_normalized == header_normalized:
                                col_index = i
                                break
                        
                        if col_index is None:
                            continue 
                        col_letter = col_index_to_letter(col_index)
                        
                        # Clean value
                        if pd.isna(value) or value is None:
                            clean_value = ''
                        elif isinstance(value, (np.integer, np.int64, np.int32)):
                            clean_value = int(value)
                        elif isinstance(value, (np.floating, np.float64, np.float32)):
                            clean_value = float(value)
                        else:
                            clean_value = str(value)
                        
                        # Add individual cell update (preserves formulas in other columns)
                        range_notation = f"{sheet_name}!{col_letter}{sheet_row_number}"
                        updates.append({
                            'range': range_notation,
                            'values': [[clean_value]]
                        })
                        
                    except ValueError:
                        continue  # Column not found in headers
                
                matched_dates.append(parsed_date)
            else:
                unmatched_dates.append(parsed_date)
        
        print(f"      Matched: {len(matched_dates)} rows")
        if matched_dates:
            print(f"         {matched_dates[:5]}{'...' if len(matched_dates) > 5 else ''}")
        
        if unmatched_dates:
            print(f"      Unmatched: {len(unmatched_dates)} dates")
        
        # Step 5: Execute batch update
        if updates:
            print(f"\n   Step 5: Updating {len(updates)} cells (preserving formulas)...")
            
            body = {
                'valueInputOption': 'USER_ENTERED',
                'data': updates
            }
            
            response = service.spreadsheets().values().batchUpdate(
                spreadsheetId=sheet_id,
                body=body
            ).execute()
            
            total_updated_cells = response.get('totalUpdatedCells', 0)
            rows_with_data = len(matched_dates)
            print(f"      Updated {total_updated_cells} cells across {rows_with_data} rows")
            
            return {
                'success': True,
                'rows_updated': rows_with_data,
                'cells_updated': total_updated_cells,
                'matched_dates': matched_dates,
                'unmatched_dates': unmatched_dates,
                'total_processed': len(rows_with_dates),
            }
        else:
            return {
                'success': False,
                'error': 'No matching dates found in sheet',
                'matched_dates': matched_dates,
                'unmatched_dates': unmatched_dates,
                'total_processed': len(rows_with_dates)
            }
            
    except HttpError as e:
        print(f"   Google Sheets API Error: {str(e)}")
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        print(f"   Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"Failed to update rows by date: {str(e)}"}


def update_rows_by_anchor(
    sheet_id: str,
    sheet_name: str,
    anchor_column=None,
    rows: List[Dict[str, Any]] = None,
    anchor_columns: list = None,
    credentials_dict: CredentialsDict = None,
    header_row: int = 0,
    data_start_row: int = None,
    data_end_row: int = None
) -> Dict[str, Any]:
    """
    Update specific rows by matching anchor column(s) (SKU, ID, name, composite key, etc.).
    Supports both single anchor_column (string) and composite anchor_columns (list).

    Section row-range pinning (Fix L companion to update_rows_by_date):
        ``data_start_row`` and ``data_end_row`` are 1-indexed sheet-row bounds
        (both inclusive). When provided, only rows in that range are added to
        the anchor-to-row map. Same rationale as update_rows_by_date — keeps
        an anchor value that appears in two sections (e.g. an SKU shared
        between an "In Stock" section and a "Backorders" section) from
        silently writing into the wrong one.
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        if anchor_columns is None and anchor_column is not None:
            anchor_columns = anchor_column if isinstance(anchor_column, list) else [anchor_column]
        if not anchor_columns:
            return {"success": False, "error": "anchor_column or anchor_columns required"}

        rows = rows or []
        print(f"\nUpdating rows by anchor {anchor_columns} in {sheet_name}...")
        print(f"   Rows to update: {len(rows)}")
        if data_start_row is not None or data_end_row is not None:
            print(f"   Section row-range pin: rows {data_start_row}..{data_end_row} (1-indexed, inclusive)")

        service = create_sheets_service(credentials_dict)

        safe_name = f"'{sheet_name}'" if ' ' in sheet_name and not sheet_name.startswith("'") else sheet_name
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"{safe_name}!A:ZZ"
        ).execute()

        existing_values = result.get('values', [])
        if not existing_values or len(existing_values) < header_row + 2:
            return {'success': False, 'error': 'Sheet is empty or has no data rows'}

        headers = existing_values[header_row]
        data_rows = existing_values[header_row + 1:]

        anchor_col_indices = []
        for ac in anchor_columns:
            found = None
            for i, h in enumerate(headers):
                if ' '.join(h.strip().split()).lower() == ' '.join(ac.strip().split()).lower():
                    found = i
                    break
            if found is None:
                return {'success': False, 'error': f"Anchor column '{ac}' not found in headers: {headers[:20]}"}
            anchor_col_indices.append(found)

        anchor_to_row = {}
        rows_skipped_outside_section = 0
        for row_idx, row in enumerate(data_rows):
            sheet_row_number = row_idx + header_row + 2
            # Section row-range pin (mirror of update_rows_by_date): skip rows
            # outside the chosen section so an anchor present in two sections
            # doesn't get silently routed to whichever one happens to be later
            # in the sheet. ``None`` on either bound preserves legacy behavior.
            if data_start_row is not None and sheet_row_number < data_start_row:
                rows_skipped_outside_section += 1
                continue
            if data_end_row is not None and sheet_row_number > data_end_row:
                break
            parts = []
            for idx in anchor_col_indices:
                val = str(row[idx]).strip() if idx < len(row) else ''
                parts.append(val)
            key = '|'.join(p.lower() for p in parts)
            if key and key != '|'.join('' for _ in parts):
                anchor_to_row[key] = sheet_row_number

        if rows_skipped_outside_section:
            print(f"   Skipped {rows_skipped_outside_section} row(s) outside section bounds "
                  f"({data_start_row}..{data_end_row})")
        print(f"   Found {len(anchor_to_row)} anchors in sheet")

        updates = []
        matched = []
        unmatched = []
        anchor_col_set = set(ac.strip().lower() for ac in anchor_columns)

        for row_data in rows:
            parts = []
            for ac in anchor_columns:
                parts.append(str(row_data.get(ac, '')).strip())
            key = '|'.join(p.lower() for p in parts)
            display_key = '|'.join(parts)
            if not any(parts):
                continue

            sheet_row = anchor_to_row.get(key)
            if sheet_row is None:
                unmatched.append(display_key)
                continue

            matched.append(display_key)
            for col_name, value in row_data.items():
                if ' '.join(col_name.strip().split()).lower() in anchor_col_set:
                    continue
                col_index = None
                cn = ' '.join(col_name.strip().split()).lower()
                for i, h in enumerate(headers):
                    if ' '.join(h.strip().replace('\n', ' ').split()).lower() == cn:
                        col_index = i
                        break
                if col_index is None:
                    continue

                if value is None:
                    clean_value = ''
                elif isinstance(value, (int, float)):
                    clean_value = value
                else:
                    clean_value = str(value)

                col_letter = col_index_to_letter(col_index)
                updates.append({
                    'range': f"{safe_name}!{col_letter}{sheet_row}",
                    'values': [[clean_value]]
                })

        if updates:
            print(f"   Writing {len(updates)} cell updates...")
            response = service.spreadsheets().values().batchUpdate(
                spreadsheetId=sheet_id,
                body={'valueInputOption': 'USER_ENTERED', 'data': updates}
            ).execute()
            total_updated = response.get('totalUpdatedCells', 0)
            print(f"   Updated {total_updated} cells across {len(matched)} rows")
            return {
                'success': True,
                'rows_updated': len(matched),
                'cells_updated': total_updated,
                'matched_anchors': matched,
                'unmatched_anchors': unmatched,
            }
        else:
            return {
                'success': False,
                'error': 'No matching anchors found in sheet',
                'unmatched_anchors': unmatched,
            }

    except HttpError as e:
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"Failed to update rows by anchor: {str(e)}"}


def update_cells_by_column(
    sheet_id: str,
    sheet_name: str,
    source_data: Dict[str, List[Any]],
    credentials_dict: CredentialsDict = None,
    header_row: int = 0
) -> Dict[str, Any]:
    """
    Write values down columns (horizontal strategy).
    source_data is {column_name: [values...]}.
    Matches column names to sheet headers and writes values starting after header_row.
    header_row: 0-indexed row containing headers (default 0).
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        print(f"\nUpdating cells by column in {sheet_name}...")

        service = create_sheets_service(credentials_dict)

        safe_name = f"'{sheet_name}'" if ' ' in sheet_name and not sheet_name.startswith("'") else sheet_name
        header_row_1indexed = header_row + 1
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"{safe_name}!{header_row_1indexed}:{header_row_1indexed}"
        ).execute()

        headers = result.get('values', [[]])[0]
        if not headers:
            return {'success': False, 'error': 'Sheet has no headers'}

        header_map = {}
        for i, h in enumerate(headers):
            header_map[' '.join(h.strip().replace('\n', ' ').split()).lower()] = i

        updates = []
        columns_written = 0

        for col_name, values in source_data.items():
            cn = ' '.join(col_name.strip().split()).lower()
            col_index = header_map.get(cn)
            if col_index is None:
                continue

            col_letter = col_index_to_letter(col_index)
            start_row = header_row_1indexed + 1
            cell_values = []
            for v in values:
                if v is None:
                    cell_values.append([''])
                elif isinstance(v, (int, float)):
                    cell_values.append([v])
                else:
                    cell_values.append([str(v)])

            updates.append({
                'range': f"{safe_name}!{col_letter}{start_row}:{col_letter}{start_row + len(cell_values) - 1}",
                'values': cell_values
            })
            columns_written += 1

        if updates:
            print(f"   Writing {columns_written} columns...")
            response = service.spreadsheets().values().batchUpdate(
                spreadsheetId=sheet_id,
                body={'valueInputOption': 'USER_ENTERED', 'data': updates}
            ).execute()
            total_updated = response.get('totalUpdatedCells', 0)
            print(f"   Updated {total_updated} cells across {columns_written} columns")
            return {
                'success': True,
                'columns_written': columns_written,
                'cells_updated': total_updated,
            }
        else:
            return {'success': False, 'error': 'No matching columns found in sheet'}

    except HttpError as e:
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"Failed to update cells by column: {str(e)}"}


def append_rows(
    sheet_id: str,
    sheet_name: str,
    rows: List[List[Any]],
    credentials_dict: CredentialsDict = None
) -> Dict[str, Any]:
    """
    Append new rows to the bottom of the sheet.
    rows is a list of lists (each inner list is one row of cell values).
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        print(f"\nAppending {len(rows)} rows to {sheet_name}...")

        service = create_sheets_service(credentials_dict)

        safe_name = f"'{sheet_name}'" if ' ' in sheet_name and not sheet_name.startswith("'") else sheet_name

        clean_rows = []
        for row in rows:
            clean_row = []
            for cell in row:
                if cell is None:
                    clean_row.append('')
                elif isinstance(cell, (int, float)):
                    clean_row.append(cell)
                elif isinstance(cell, (np.integer, np.int64, np.int32)):
                    clean_row.append(int(cell))
                elif isinstance(cell, (np.floating, np.float64, np.float32)):
                    clean_row.append(float(cell))
                elif pd.isna(cell):
                    clean_row.append('')
                else:
                    clean_row.append(str(cell))
            clean_rows.append(clean_row)

        result = service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range=f"{safe_name}!A1",
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body={'values': clean_rows}
        ).execute()

        updated = result.get('updates', {})
        rows_appended = updated.get('updatedRows', len(clean_rows))
        print(f"   Appended {rows_appended} rows")

        return {
            'success': True,
            'rows_appended': rows_appended,
            'cells_updated': updated.get('updatedCells', 0),
        }

    except HttpError as e:
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"Failed to append rows: {str(e)}"}


def upload_multi_sheet_data(sheet_id: str, sheets_data: str,
                           credentials_dict: CredentialsDict = None) -> Dict[str, Any]:
    """Upload data to multiple sheets in a spreadsheet"""
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}
        
        print(f"Uploading multi-sheet data to: {sheet_id}")
        service = create_sheets_service(credentials_dict)
        
        # Parse sheets data
        sheets_dict = json.loads(sheets_data) if isinstance(sheets_data, str) else sheets_data
        
        sheets_updated = []
        
        for sheet_name, data in sheets_dict.items():
            try:
                print(f"   Uploading: {sheet_name} ({len(data)} rows)")
                
                # Convert numpy types to native Python types
                clean_data = []
                for row in data:
                    clean_row = []
                    for cell in row:
                        if isinstance(cell, (np.integer, np.int64, np.int32)):
                            clean_row.append(int(cell))
                        elif isinstance(cell, (np.floating, np.float64, np.float32)):
                            clean_row.append(float(cell))
                        elif isinstance(cell, np.bool_):
                            clean_row.append(bool(cell))
                        elif pd.isna(cell):
                            clean_row.append("")
                        else:
                            clean_row.append(str(cell) if cell is not None else "")
                    clean_data.append(clean_row)
                
                service.spreadsheets().values().update(
                    spreadsheetId=sheet_id,
                    range=f"'{sheet_name}'!A1",
                    valueInputOption="RAW",
                    body={"values": clean_data},
                ).execute()
                
                sheets_updated.append(sheet_name)
                
            except Exception as e:
                print(f"   Error uploading {sheet_name}: {str(e)}")
        
        print(f"   Uploaded {len(sheets_updated)} sheets")
        return {
            "success": True,
            "sheets_updated": sheets_updated,
            "sheet_count": len(sheets_updated),
        }
        
    except Exception as e:
        print(f"   Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"Failed to upload data: {str(e)}"}


def insert_rows(
    sheet_id: str,
    sheet_name: str,
    start_row_index: int,
    num_rows: int,
    credentials_dict: CredentialsDict = None,
) -> Dict[str, Any]:
    """Insert ``num_rows`` empty rows at ``start_row_index`` (0-indexed).

    Rows at and below ``start_row_index`` are shifted down to make room. Uses
    Google Sheets ``insertDimension`` — the only API that can physically shift
    content on the server, which is what lets section-aware writers insert
    dated rows in the middle of a stacked-section template without clobbering
    the next section's title.

    Returns ``{success, rows_inserted, sheet_tab_id}``. A no-op ``num_rows<=0``
    call returns success without a Sheets round-trip so callers can call this
    unconditionally from sort-merge code paths.
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}
        if num_rows is None or int(num_rows) <= 0:
            return {"success": True, "rows_inserted": 0, "sheet_tab_id": None}

        service = create_sheets_service(credentials_dict)
        spreadsheet = service.spreadsheets().get(spreadsheetId=sheet_id).execute()

        tab_id = None
        for sh in spreadsheet.get("sheets", []):
            props = sh.get("properties", {})
            if props.get("title") == sheet_name:
                tab_id = props.get("sheetId")
                break
        if tab_id is None:
            return {
                "success": False,
                "error": f"Sheet tab '{sheet_name}' not found in spreadsheet",
            }

        start_idx = max(int(start_row_index), 0)
        end_idx = start_idx + int(num_rows)

        print(
            f"\nInserting {num_rows} row(s) into '{sheet_name}' "
            f"at row index {start_idx} (shifts rows {start_idx + 1}+ down)..."
        )

        service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={
                "requests": [
                    {
                        "insertDimension": {
                            "range": {
                                "sheetId": tab_id,
                                "dimension": "ROWS",
                                "startIndex": start_idx,
                                "endIndex": end_idx,
                            },
                            "inheritFromBefore": start_idx > 0,
                        }
                    }
                ]
            },
        ).execute()

        return {
            "success": True,
            "rows_inserted": int(num_rows),
            "sheet_tab_id": tab_id,
            "start_row_index": start_idx,
        }

    except HttpError as e:
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"Failed to insert rows: {str(e)}"}


def get_sheet_metadata(sheet_id: str, credentials_dict: CredentialsDict = None) -> Dict[str, Any]:
    """Get spreadsheet metadata"""
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}
        
        service = create_sheets_service(credentials_dict)
        spreadsheet = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        
        sheets_info = []
        for sheet in spreadsheet.get("sheets", []):
            props = sheet.get("properties", {})
            sheets_info.append({
                "title": props.get("title"),
                "sheetId": props.get("sheetId"),
                "index": props.get("index"),
            })
        
        return {
            "success": True,
            "title": spreadsheet.get("properties", {}).get("title"),
            "sheets": sheets_info,
        }
    except HttpError as e:
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to get metadata: {str(e)}"}

def preview_cell_changes(sheet_id, sheet_name, date_column_name, rows_with_dates, credentials_dict):
    """
    Preview what will be CHANGED in Google Sheets
    Shows current cell values vs new values from Excel
    """
    try:
        print(f"PREVIEW: Checking cell changes for {len(rows_with_dates)} rows...")
        
        # DEBUG: Check incoming data
        if rows_with_dates and len(rows_with_dates) > 0:
            sample = rows_with_dates[0]
            print(f"Sample row structure:")
            print(f"   - date: {sample. get('date')}")
            print(f"   - date_formatted: {sample.get('date_formatted')}")
            print(f"   - row_data keys: {list(sample.get('row_data', {}).keys())[:5]}...")
        
        # Create sheets service
        service = create_sheets_service(credentials_dict)
        
        # Read the entire sheet
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=f"'{sheet_name}'"
        ).execute()
        
        values = result.get('values', [])
        
        if not values:
            raise ValueError("Sheet is empty")
        
        headers = values[0]
        print(f"Found {len(headers)} columns in sheet")
        print(f"Headers sample: {headers[:10]}")
        
        # Find date column index
        date_col_index = None
        for i, header in enumerate(headers):
            if header. strip(). lower() == date_column_name.strip().lower():
                date_col_index = i
                break
        
        if date_col_index is None:
            raise ValueError(f"Date column '{date_column_name}' not found in sheet headers")
        
        print(f"Date column found at index {date_col_index}")
        
        # Build a map of dates to row numbers
        date_to_row = {}
        sheet_data_by_row = {}
        
        for i, row in enumerate(values[1:], start=2):  # Start at row 2 (skip header)
            if date_col_index < len(row):
                date_str = row[date_col_index]
                if date_str:
                    parsed_date = parse_date_flexible(date_str)
                    if parsed_date:
                        date_to_row[parsed_date] = i
                        sheet_data_by_row[i] = row
        
        print(f"Found {len(date_to_row)} dates in Google Sheet")
        if date_to_row:
            sample_dates = list(date_to_row.keys())[:5]
            print(f"   Sample sheet dates: {sample_dates}")
        
        # Process each Excel row and build preview
        preview_rows = []
        matched_dates = []
        unmatched_dates = []
        total_changes = 0
        cells_to_update = 0
        
        for excel_row in rows_with_dates:
            excel_date = excel_row.get('date_formatted') or excel_row. get('date')
            parsed_date = parse_date_flexible(excel_date)
            excel_data = excel_row.get('row_data', {})
            
            if not parsed_date:
                print(f"Could not parse date: {excel_date}")
                continue
            
            # Check if date exists in sheet
            if parsed_date not in date_to_row:
                unmatched_dates.append(parsed_date)
                continue
            
            matched_dates.append(parsed_date)
            sheet_row_number = date_to_row[parsed_date]
            current_row_data = sheet_data_by_row.get(sheet_row_number, [])
            
            # Compare each column
            changes = []
            
            for col_name, new_value in excel_data.items():
                # Skip the date column itself
                if col_name. strip(). lower() == date_column_name.strip().lower():
                    continue
                
                # Find column index in sheet
                col_index = None
                for i, header in enumerate(headers):
                    if header.strip().lower() == col_name.strip(). lower():
                        col_index = i
                        break
                
                if col_index is None:
                    continue  # Column not found in sheet
                
                col_letter = col_index_to_letter(col_index)
                
                # Get current value from sheet
                current_value = current_row_data[col_index] if col_index < len(current_row_data) else ''
                
                # Clean values for comparison
                if pd.isna(new_value) or new_value is None:
                    clean_new = ''
                elif isinstance(new_value, (np.integer, np.int64, np.int32)):
                    clean_new = str(int(new_value))
                elif isinstance(new_value, (np.floating, np.float64, np.float32)):
                    # Round floats for comparison
                    clean_new = str(round(float(new_value), 2))
                else:
                    clean_new = str(new_value). strip()
                
                current_value_str = str(current_value). strip() if current_value else ''
                
                # IMPROVED: Better comparison (handle numeric strings)
                will_change = False
                try:
                    # Try numeric comparison first
                    current_num = float(current_value_str) if current_value_str else 0
                    new_num = float(clean_new) if clean_new else 0
                    will_change = abs(current_num - new_num) > 0.001
                except (ValueError, TypeError):
                    # Fall back to string comparison
                    will_change = (current_value_str != clean_new)
                
                # Only count as change if both values are not empty or if there's an actual difference
                if clean_new or current_value_str:  # At least one has a value
                    cells_to_update += 1
                    
                    if will_change:
                        total_changes += 1
                        changes. append({
                            'column': col_name,
                            'column_letter': col_letter,
                            'current_value': current_value_str,
                            'new_value': clean_new,
                            'will_change': True
                        })
            
            if changes:  # Only add rows that have actual changes
                preview_rows.append({
                    'date': parsed_date,
                    'row_number': sheet_row_number,
                    'changes': changes
                })
        
        print(f"\nPreview complete:")
        print(f"   - Matched dates: {len(matched_dates)}")
        print(f"   - Unmatched dates: {len(unmatched_dates)}")
        print(f"   - Total changes: {total_changes}")
        print(f"   - Cells checked: {cells_to_update}")
        
        return {
            'success': True,
            'preview_rows': preview_rows,
            'matched_dates': matched_dates,
            'unmatched_dates': unmatched_dates,
            'total_changes': total_changes,
            'cells_to_update': cells_to_update,
            'matched_count': len(matched_dates),
            'unmatched_count': len(unmatched_dates)
        }
        
    except Exception as e:
        print(f"Preview cell changes error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'error': str(e)
        }


# ============================================================
# TOOL REGISTRYsd
# ============================================================

TOOL_REGISTRY = {
    "create_sheet": {
        "func": create_sheet,
        "description": "Create a new Google Spreadsheet",
    },
    "read_sheet": {
        "func": read_sheet,
        "description": "Read data from a Google Sheet",
    },
    "update_sheet": {
        "func": update_sheet,
        "description": "Update data in a specific range",
    },
    "update_rows_by_date": {
        "func": update_rows_by_date,
        "description": "Update specific rows by matching dates (OPR workflow)",
    },
    "update_rows_by_anchor": {
        "func": update_rows_by_anchor,
        "description": "Update rows by matching an anchor column (SKU/ID/name)",
    },
    "update_cells_by_column": {
        "func": update_cells_by_column,
        "description": "Write values down columns (horizontal strategy)",
    },
    "append_rows": {
        "func": append_rows,
        "description": "Append new rows to the bottom of a sheet",
    },
    "upload_multi_sheet_data": {
        "func": upload_multi_sheet_data,
        "description": "Upload data to multiple sheets",
    },
    "get_sheet_metadata": {
        "func": get_sheet_metadata,
        "description": "Get spreadsheet metadata",
    },
    "preview_cell_changes": {
        "func": preview_cell_changes,
        "description": "Preview what will be CHANGED in Google Sheets",
    }
}
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
    initial_data: Any = None,
    folder_id: Optional[str] = None,
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Create a new Google Spreadsheet, optionally inside a specific Drive folder.

    Args:
        title: Name of the spreadsheet
        sheet_names: Optional list of sheet tab names (default: ["Sheet1"])
        initial_data: Optional data to populate first sheet. Accepts a
            native `List[List[Any]]`, a single 1D list (promoted to one
            row — commonly used as the header row when seeding a new
            sheet before `append_rows`), a JSON string, a Python-repr
            string, a markdown-fenced code block wrapping either, or a
            newline-separated collection of per-line list reprs.
            Normalized to `List[List[Any]]` via `_coerce_rows` before
            the API call.
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

        coerced_initial: List[List[Any]] = []
        if initial_data is not None:
            try:
                coerced_initial = _coerce_rows(initial_data)
            except ValueError as e:
                return {
                    "success": False,
                    "error": f"Invalid initial_data shape for create_sheet: {e}",
                    "error_type": "bad_input",
                }

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

        if coerced_initial:
            first_sheet_name = sheet_names[0] if sheet_names else "Sheet1"
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=f"{first_sheet_name}!A1",
                valueInputOption="RAW",
                body={"values": coerced_initial},
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


def find_or_create_sheet(
    title: str,
    sheet_names: Optional[List[str]] = None,
    initial_data: Any = None,
    folder_id: Optional[str] = None,
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Find an existing Google Spreadsheet by EXACT title, or create a new one
    when no match exists. Idempotent — safe to re-run without producing
    duplicate spreadsheets.

    Use this instead of `create_sheet` when the user asks for duplicate-
    prevention semantics ("don't create if it already exists", "use the
    existing one if there is one", "reject duplicate sends", "treat as
    already processed if the same request comes in again", "find or
    create"). Mechanically equivalent to a Drive `name=` exact-match
    pre-flight followed by `create_sheet` only on miss; this tool packages
    both into one atomic step so the planner does not need a fragile two-
    step chain that loses the `existed` flag.

    Match semantics:
      * `name = '<title>'` — full-string equality on the spreadsheet's
        Drive name (case-sensitive — Drive's `name = 'X'` is exact). DOES
        NOT use name-contains semantics (so "ASDWER" does not match
        "ASDWER backup" or "old ASDWER").
      * Restricted to `mimeType = 'application/vnd.google-apps.spreadsheet'`
        so a doc/folder/file with the same title never collides.
      * Excludes trashed files — a deleted "ASDWER" in the bin does not
        prevent a fresh creation.
      * Optionally scoped to `folder_id` so two sheets named the same in
        DIFFERENT folders do not collide.

    On match (>= 1 existing):
      * `existed=True`, `sheet_id`/`sheet_url` point at the most recently
        modified match, `duplicates_found` reports how many sheets share
        the title. When duplicates_found > 1, `warning` surfaces a tidy-
        up suggestion. The user-facing `message` is sentence-style and
        explains the duplicate prevention happened.

    On no match:
      * Delegates to `create_sheet` to do the actual work (sheet_names,
        initial_data, folder_id are passed through unchanged), then
        returns `existed=False` with the new sheet's metadata.

    On Drive lookup failure:
      * Returns `success=False` with `error_type='lookup_failed'` rather
        than silently falling through to creation. The duplicate-prevention
        contract requires the lookup to succeed before we can guarantee
        no duplicate is created — silently bypassing the check would be
        worse than reporting the failure.

    Args:
        title: Exact spreadsheet title to look for / create. Whitespace
            is stripped on both sides; case is preserved for the create
            branch and matched verbatim on the lookup branch.
        sheet_names: Forwarded to `create_sheet` on miss. Ignored on hit
            (the existing sheet's tabs are not modified).
        initial_data: Forwarded to `create_sheet` on miss. Ignored on hit
            (no data is written into the existing sheet — that would be a
            destructive surprise and violates the idempotent contract).
        folder_id: Drive folder ID to (a) restrict the lookup scope and
            (b) reparent the sheet on create-miss. Pass the resolved
            folder ID, not a path. URL-shaped values are not extracted
            here — resolve to a bare ID via `drive_agent.get_folder_info`
            in a prior step.
        credentials_dict: Google OAuth credentials.

    Returns:
        success: bool
        existed: bool — True if an existing spreadsheet was found and
            returned; False if a new one was created.
        sheet_id: str — Drive ID of the spreadsheet (existing or new).
        sheet_url: str — Web view URL.
        title: str — The title actually used (whitespace-stripped).
        folder_id: str | None — folder_id input echoed back.
        folder_moved: bool (only on create-miss) — whether the new sheet
            was successfully reparented into the requested folder.
        modified_time: str | None (only on hit) — ISO-8601 modifiedTime
            of the matched sheet.
        duplicates_found: int — count of pre-existing matches found
            during the lookup (0 when create branch was taken).
        warning: str | None — tidy-up advice when duplicates_found > 1,
            or the create-branch's `warning` (e.g. folder move failed).
        message: str — Sentence-style user-facing summary suitable for
            direct rendering in chat.
        error / error_type: present only on failure.
    """
    try:
        if not credentials_dict:
            return {
                "success": False,
                "error": "Credentials required",
                "error_type": "auth",
            }

        if title is None or not str(title).strip():
            return {
                "success": False,
                "error": "title is required",
                "error_type": "bad_input",
            }
        title = str(title).strip()

        # Pre-flight existence check via Drive. Exact match on name +
        # spreadsheet mimeType. We deliberately escape both backslash and
        # single quote in the title for the Drive query string — a title
        # containing a literal apostrophe (e.g. "Q1'26 Budget") would
        # otherwise produce a malformed Drive query and 400.
        drive = create_drive_service(credentials_dict)
        safe_title = title.replace("\\", "\\\\").replace("'", "\\'")
        query_parts = [
            f"name = '{safe_title}'",
            "mimeType = 'application/vnd.google-apps.spreadsheet'",
            "trashed = false",
        ]
        if folder_id:
            query_parts.append(f"'{folder_id}' in parents")
        query = " and ".join(query_parts)

        try:
            list_result = drive.files().list(
                q=query,
                fields="files(id, name, modifiedTime, webViewLink, parents)",
                orderBy="modifiedTime desc",
                pageSize=10,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
            existing = list_result.get("files", []) or []
        except Exception as search_err:
            # Hard fail: we cannot guarantee no-duplicate without a
            # successful lookup, so we surface the error rather than
            # silently creating.
            return {
                "success": False,
                "error": (
                    "Couldn't check Drive for an existing spreadsheet "
                    f"with the title '{title}': {search_err}"
                ),
                "error_type": "lookup_failed",
                "title": title,
                "folder_id": folder_id,
            }

        if existing:
            chosen = existing[0]  # most recently modified per orderBy
            chosen_id = chosen["id"]
            chosen_url = (
                chosen.get("webViewLink")
                or f"https://docs.google.com/spreadsheets/d/{chosen_id}/edit"
            )
            duplicates_count = len(existing)

            if duplicates_count > 1:
                user_message = (
                    f"A spreadsheet titled \"{title}\" already exists in "
                    f"your Drive ({duplicates_count} matches found). To "
                    f"prevent creating yet another duplicate, I'm reusing "
                    f"the most recently modified one."
                )
                warning = (
                    f"Found {duplicates_count} existing spreadsheets sharing "
                    f"the title \"{title}\". You may want to rename or remove "
                    f"the older copies to keep your Drive tidy."
                )
            else:
                user_message = (
                    f"A spreadsheet titled \"{title}\" already exists in "
                    f"your Drive — I'm using the existing one instead of "
                    f"creating a duplicate."
                )
                warning = None

            return {
                "success": True,
                "existed": True,
                "sheet_id": chosen_id,
                "sheet_url": chosen_url,
                "title": title,
                "folder_id": folder_id,
                "modified_time": chosen.get("modifiedTime"),
                "duplicates_found": duplicates_count,
                "warning": warning,
                "message": user_message,
            }

        # No match — delegate to create_sheet so we don't duplicate the
        # creation logic (folder reparenting, initial_data coercion,
        # sheet_names handling, etc.).
        result = create_sheet(
            title=title,
            sheet_names=sheet_names,
            initial_data=initial_data,
            folder_id=folder_id,
            credentials_dict=credentials_dict,
        )
        if not result.get("success"):
            # Bubble create_sheet's failure up untouched (preserves its
            # error/error_type/HTTP-error wording).
            return result

        new_message = (
            f"Created a new spreadsheet titled \"{title}\" — no existing "
            f"copy was found in your Drive, so this is a fresh one."
        )
        if result.get("folder_moved"):
            new_message += " It's been placed in the requested folder."
        elif result.get("warning"):
            new_message += f" Note: {result['warning']}"

        return {
            "success": True,
            "existed": False,
            "sheet_id": result.get("sheet_id"),
            "sheet_url": result.get("sheet_url"),
            "title": title,
            "folder_id": result.get("folder_id"),
            "folder_moved": result.get("folder_moved", False),
            "duplicates_found": 0,
            "warning": result.get("warning"),
            "message": new_message,
        }

    except HttpError as e:
        return {
            "success": False,
            "error": f"Google Sheets API error: {str(e)}",
            "error_type": "api_error",
            "title": title if isinstance(title, str) else None,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"find_or_create_sheet failed: {str(e)}",
            "error_type": "internal",
            "title": title if isinstance(title, str) else None,
        }


def read_sheet(
    sheet_id: str,
    range_name: Optional[str] = None,
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Read data from a Google Sheet

    Args:
        sheet_id: Google Sheets ID, or a full URL. A `?gid=` tab
            identifier in the URL is used when `range_name` is a bare
            tab reference (e.g. the legacy "Sheet1" default).
        range_name: Range to read (e.g., 'Sheet1' or 'Sheet1!A1:D10').
            Optional — when omitted (or when it is the legacy "Sheet1"
            default), the tool resolves the tab via the URL's `gid=`
            parameter or falls back to the first tab.
        credentials_dict: Google OAuth credentials

    Returns:
        Dictionary with sheet data
    """
    effective_range: Optional[str] = None
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        gid = _extract_gid(sheet_id)
        sheet_id = _extract_sheet_id(sheet_id)
        effective_range = _apply_tab_to_range(
            range_name, sheet_id, gid, credentials_dict
        )

        service = create_sheets_service(credentials_dict)

        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=sheet_id, range=effective_range)
            .execute()
        )

        values = result.get("values", [])

        if not values:
            return {
                "success": True,
                "data": [],
                "row_count": 0,
                "column_count": 0,
                "range": effective_range,
                "message": "No data found in range",
            }

        return {
            "success": True,
            "data": values,
            "row_count": len(values),
            "column_count": len(values[0]) if values else 0,
            "range": effective_range,
        }

    except HttpError as e:
        # Google Sheets returns HTTP 400 with body "Unable to parse range:
        # <X>" when the requested tab does not exist in the spreadsheet.
        # The literal HTTP 400 reads as a generic "bad request" error to
        # downstream consumers, so we tag it with `error_type='tab_not_found'`
        # so the planner / response composer can distinguish "the tab is
        # missing" (recoverable — call add_sheet_tab and retry) from a
        # truly bad request (malformed sheet ID, etc.). Backwards-compatible:
        # callers that ignore `error_type` still see the same `error` string.
        # `effective_range` is pre-bound to None at the top of this function
        # so the response shape stays consistent even if _apply_tab_to_range
        # itself raised before computing it.
        err_str = str(e)
        if "Unable to parse range" in err_str:
            return {
                "success": False,
                "error": f"Google Sheets API error: {err_str}",
                "error_type": "tab_not_found",
                "requested_range": effective_range or range_name,
            }
        return {"success": False, "error": f"Google Sheets API error: {err_str}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to read sheet: {str(e)}"}


def update_sheet(
    sheet_id: str,
    range_name: str,
    data: Any,
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Update data in a specific range of a Google Sheet.

    Args:
        sheet_id: Google Sheets ID, or a full URL. A `?gid=` tab
            identifier in the URL is honored when `range_name` uses
            the legacy "Sheet1" prefix.
        range_name: Range to update (e.g., 'Sheet1!A1:D10'). If the
            prefix is exactly the legacy "Sheet1" default it is
            rewritten to the tab identified by the URL's `gid=`
            parameter. Other explicit tab prefixes are honored as-is.
        data: Values to write. Accepts a native `List[List[Any]]`, a
            single 1D list (promoted to one row), a JSON string, a
            Python-repr string, a markdown-fenced code block wrapping
            either, or a newline-separated collection of per-line
            list reprs. Everything is normalized to `List[List[Any]]`
            via `_coerce_rows` before the API call.
        credentials_dict: Google OAuth credentials

    Returns:
        Dictionary with update results
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        try:
            rows = _coerce_rows(data)
        except ValueError as e:
            return {
                "success": False,
                "error": f"Invalid data shape for update_sheet: {e}",
                "error_type": "bad_input",
            }

        gid = _extract_gid(sheet_id)
        sheet_id = _extract_sheet_id(sheet_id)
        effective_range = _apply_tab_to_range(
            range_name, sheet_id, gid, credentials_dict
        )

        service = create_sheets_service(credentials_dict)

        result = (
            service.spreadsheets()
            .values()
            .update(
                spreadsheetId=sheet_id,
                range=effective_range,
                valueInputOption="RAW",
                body={"values": rows},
            )
            .execute()
        )

        return {
            "success": True,
            "updated_cells": result.get("updatedCells", 0),
            "updated_rows": result.get("updatedRows", 0),
            "updated_columns": result.get("updatedColumns", 0),
            "range": effective_range,
            "message": f"Updated {result.get('updatedCells', 0)} cells in {effective_range}",
        }

    except HttpError as e:
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to update sheet: {str(e)}"}


def _col_index_to_a1_letter(idx: int) -> str:
    """Convert a 0-based column index to an A1 column letter (A, B, ..., Z,
    AA, AB, ..., AZ, BA, ...). Used by `append_rows(dedup_on=...)` to build
    a single-column range for reading existing values."""
    if idx < 0:
        raise ValueError(f"Column index must be non-negative, got {idx}")
    s = ""
    n = idx
    while True:
        s = chr(ord("A") + (n % 26)) + s
        n = n // 26 - 1
        if n < 0:
            break
    return s


def append_rows(
    sheet_id: str,
    data: Any,
    sheet_name: Optional[str] = None,
    dedup_on: Optional[str] = None,
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Append rows to the end of a sheet, with optional idempotent dedup.

    Args:
        sheet_id: Google Sheets ID, or a full URL. A `?gid=` tab
            identifier in the URL is honored when `sheet_name` is not
            explicitly provided.
        data: Rows to append. Accepts a native `List[List[Any]]`, a
            single 1D list (promoted to one row), a JSON string, a
            Python-repr string, a markdown-fenced code block wrapping
            either, or a newline-separated collection of per-line
            list reprs. Everything is normalized to `List[List[Any]]`
            via `_coerce_rows` before the API call.
        sheet_name: Name of the sheet tab. Optional — when omitted the
            tool resolves the tab via the URL's `gid=` parameter, or
            falls back to the first tab. Pass an explicit name to
            override that resolution.
        dedup_on: Optional column name (exact match against row 1 of the
            resolved tab; case-insensitive, whitespace-trimmed). When
            set, the tool reads existing values in that column, skips
            incoming rows whose value in the same column already exists,
            and also dedupes within the same batch. Enables idempotent
            re-runs without duplicate inflation. Common stable-ID
            columns: "message_id", "order_ref", "event_id", "date"+
            "order_ref" pairing (two-column keys not supported — pick
            one canonical ID column).
        credentials_dict: Google OAuth credentials

    Returns:
        Dictionary with append results. When dedup_on was set, also
        includes `rows_skipped`, `skipped_keys` (up to 10 samples), and
        `dedup_column`. On a completely-deduplicated run, `rows_added`
        is 0 and no API append call is made.
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        try:
            rows = _coerce_rows(data)
        except ValueError as e:
            return {
                "success": False,
                "error": f"Invalid data shape for append_rows: {e}",
                "error_type": "bad_input",
            }

        if not rows:
            return {
                "success": True,
                "rows_added": 0,
                "range_updated": None,
                "updated_cells": 0,
                "sheet_name": sheet_name,
                "message": "No rows to append (empty input after coercion)",
            }

        gid = _extract_gid(sheet_id)
        sheet_id = _extract_sheet_id(sheet_id)
        resolved_tab = _pick_sheet_name(
            sheet_name, sheet_id, gid, credentials_dict
        )

        service = create_sheets_service(credentials_dict)

        rows_skipped = 0
        skipped_keys: List[str] = []
        dedup_column_name: Optional[str] = None

        if dedup_on:
            dedup_column_name = str(dedup_on).strip()
            if not dedup_column_name:
                return {
                    "success": False,
                    "error": "dedup_on must be a non-empty column name",
                    "error_type": "bad_input",
                }

            header_result = (
                service.spreadsheets()
                .values()
                .get(spreadsheetId=sheet_id, range=f"{resolved_tab}!1:1")
                .execute()
            )
            headers_row = (header_result.get("values") or [[]])[0] if header_result.get("values") else []
            header_norm = [_norm_header(c) for c in headers_row]
            target_norm = _norm_header(dedup_column_name)
            if target_norm not in header_norm:
                return {
                    "success": False,
                    "error": (
                        f"dedup_on column '{dedup_column_name}' not found in "
                        f"row 1 of {resolved_tab}. Existing headers: {headers_row!r}. "
                        f"Add the column via ensure_headers first, or drop dedup_on."
                    ),
                    "error_type": "missing_dedup_column",
                    "existing_headers": headers_row,
                    "sheet_name": resolved_tab,
                }
            col_idx = header_norm.index(target_norm)
            col_letter = _col_index_to_a1_letter(col_idx)

            existing_result = (
                service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=sheet_id,
                    range=f"{resolved_tab}!{col_letter}2:{col_letter}",
                )
                .execute()
            )
            existing_col_values = existing_result.get("values") or []
            existing_keys: set = {
                str((row[0] if row else "") or "").strip().lower()
                for row in existing_col_values
            }
            existing_keys.discard("")  # blank cells are not "duplicate of each other"

            batch_keys: set = set()
            filtered_rows: List[List[Any]] = []
            for row in rows:
                cell = str((row[col_idx] if col_idx < len(row) else "") or "").strip()
                key = cell.lower()
                if not key:
                    # Empty dedup value — let it through so the caller can
                    # diagnose; the row is NOT deduplicated on blanks.
                    filtered_rows.append(row)
                    continue
                if key in existing_keys or key in batch_keys:
                    rows_skipped += 1
                    if len(skipped_keys) < 10:
                        skipped_keys.append(cell)
                    continue
                batch_keys.add(key)
                filtered_rows.append(row)
            rows = filtered_rows

            if not rows:
                return {
                    "success": True,
                    "rows_added": 0,
                    "rows_skipped": rows_skipped,
                    "skipped_keys": skipped_keys,
                    "dedup_column": dedup_column_name,
                    "range_updated": None,
                    "updated_cells": 0,
                    "sheet_name": resolved_tab,
                    "message": (
                        f"All {rows_skipped} incoming rows already present in "
                        f"{resolved_tab}.{col_letter} — nothing to append"
                    ),
                }

        range_name = f"{resolved_tab}!A:A"
        result = (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=sheet_id,
                range=range_name,
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": rows},
            )
            .execute()
        )

        response: Dict[str, Any] = {
            "success": True,
            "rows_added": len(rows),
            "range_updated": result.get("updates", {}).get("updatedRange"),
            "updated_cells": result.get("updates", {}).get("updatedCells", 0),
            "sheet_name": resolved_tab,
            "message": f"Appended {len(rows)} rows to {resolved_tab}",
        }
        if dedup_on:
            response["rows_skipped"] = rows_skipped
            response["skipped_keys"] = skipped_keys
            response["dedup_column"] = dedup_column_name
            if rows_skipped:
                response["message"] = (
                    f"Appended {len(rows)} rows to {resolved_tab} "
                    f"({rows_skipped} duplicate{'s' if rows_skipped != 1 else ''} skipped)"
                )
        return response

    except HttpError as e:
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to append rows: {str(e)}"}


def upload_mapped_data(
    sheet_id: str,
    transformed_data: str,  # JSON string from mapping agent's transform_data
    sheet_name: Optional[str] = None,
    append_mode: bool = True,
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Upload pre-transformed data from mapping agent to Google Sheets
    This is the main integration point with the mapping agent

    Args:
        sheet_id: Google Sheets ID, or a full URL. A `?gid=` tab
            identifier in the URL is honored when `sheet_name` is not
            explicitly provided.
        transformed_data: JSON string of transformed data (from mapping agent)
        sheet_name: Sheet tab name to write to. Optional — when omitted
            the tool resolves the tab via the URL's `gid=` parameter,
            or falls back to the first tab.
        append_mode: If True, append to sheet. If False, overwrite from A1
        credentials_dict: Google OAuth credentials

    Returns:
        Dictionary with upload results
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        gid = _extract_gid(sheet_id)
        sheet_id = _extract_sheet_id(sheet_id)
        resolved_tab = _pick_sheet_name(
            sheet_name, sheet_id, gid, credentials_dict
        )

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
                    range=f"{resolved_tab}!A:A",
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
                "sheet_id": sheet_id,
                "sheet_url": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
                "sheet_name": resolved_tab,
                "message": f"Appended {len(data_rows)} data rows to {resolved_tab}",
            }
        else:
            # Overwrite from A1
            result = (
                service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=sheet_id,
                    range=f"{resolved_tab}!A1",
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
                "sheet_id": sheet_id,
                "sheet_url": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
                "sheet_name": resolved_tab,
                "message": f"Wrote {len(data_rows)} data rows to {resolved_tab}",
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


def add_sheet_tab(
    sheet_id: str,
    tab_name: str,
    headers: Optional[List[str]] = None,
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Add a new tab (worksheet) to an EXISTING Google Spreadsheet.

    Idempotent: if a tab with the same title (case-insensitive) already
    exists, the tool returns success with `created=False` and surfaces the
    existing tab's metadata. This matches the planner's needs for "create
    these tabs if they don't exist" workflows — call once per desired tab,
    no need for a pre-flight existence check via get_sheet_metadata.

    NOT to be confused with `create_sheet`, which creates a brand-new
    SPREADSHEET (with tabs inside it). `add_sheet_tab` adds a tab to an
    already-existing spreadsheet identified by `sheet_id`.

    Args:
        sheet_id: Google Sheets ID, or a full spreadsheet URL. URLs are
            auto-parsed via `_extract_sheet_id` (invariant 13). The
            `?gid=` portion is ignored — that identifies a tab, but
            this tool ADDS a tab.
        tab_name: Title of the new tab (e.g. "Food", "Non-Food", "Q1 Data").
            Whitespace-trimmed. Must be non-empty after stripping.
            Existence check is case-insensitive against existing tab
            titles, but the new tab is created with the exact casing
            provided.
        headers: Optional list of column header strings to seed row 1
            of the newly-created tab. Skipped on the idempotent no-op
            branch (tab already existed) — the existing tab's headers
            are NOT touched. Use `ensure_headers` separately for that.
        credentials_dict: Google OAuth credentials.

    Returns:
        Dictionary with:
            - success: True on both create and idempotent no-op.
            - created: True if a new tab was added, False if it already
              existed. Lets the caller distinguish the branches without
              parsing the message.
            - tab_name: The resolved (existing or newly-created) tab
              title with original casing.
            - tab_id: Numeric sheet ID of the tab (the `gid` value).
            - sheet_id: Spreadsheet ID after URL normalization.
            - headers_applied: True if headers were written to row 1
              (only on the create branch with headers provided).
            - message: Human-readable status line.
            - error / error_type: Populated on failure.
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        if not isinstance(tab_name, str):
            return {
                "success": False,
                "error": f"tab_name must be a string, got {type(tab_name).__name__}",
                "error_type": "bad_input",
            }
        cleaned_tab = tab_name.strip()
        if not cleaned_tab:
            return {
                "success": False,
                "error": "tab_name cannot be empty or whitespace-only",
                "error_type": "bad_input",
            }

        sheet_id = _extract_sheet_id(sheet_id)
        service = create_sheets_service(credentials_dict)

        # Idempotent existence check — if the tab is already present, skip
        # the addSheet call. We compare case-insensitively (matches Google
        # Sheets' UI behavior where tab titles are case-preserving but
        # uniqueness is not strictly case-sensitive on the user side).
        existing_meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        target_lower = cleaned_tab.lower()
        for sheet in existing_meta.get("sheets", []):
            props = sheet.get("properties", {})
            existing_title = props.get("title", "")
            if existing_title.lower() == target_lower:
                return {
                    "success": True,
                    "created": False,
                    "tab_name": existing_title,
                    "tab_id": props.get("sheetId"),
                    "sheet_id": sheet_id,
                    "headers_applied": False,
                    "warning": None,
                    "message": (
                        f"Tab '{existing_title}' already exists in the "
                        f"spreadsheet — no change made."
                    ),
                }

        # Tab does not exist — add it via batchUpdate(addSheet).
        batch_request = {
            "requests": [
                {
                    "addSheet": {
                        "properties": {"title": cleaned_tab}
                    }
                }
            ]
        }
        batch_response = (
            service.spreadsheets()
            .batchUpdate(spreadsheetId=sheet_id, body=batch_request)
            .execute()
        )

        replies = batch_response.get("replies", [])
        new_tab_id: Optional[int] = None
        new_tab_title: str = cleaned_tab
        if replies and isinstance(replies[0], dict):
            add_reply = replies[0].get("addSheet", {})
            new_props = add_reply.get("properties", {})
            new_tab_id = new_props.get("sheetId")
            new_tab_title = new_props.get("title", cleaned_tab)

        # Optional headers seeding for the new tab. Failure here is
        # logged into the response (warning + headers_applied=False)
        # rather than aborting the workflow — the tab itself was
        # successfully created and the caller may want to retry just
        # the headers via ensure_headers.
        headers_applied = False
        headers_warning: Optional[str] = None
        if headers:
            try:
                normalized_headers: List[str] = []
                for h in headers:
                    if h is None:
                        normalized_headers.append("")
                    else:
                        normalized_headers.append(str(h))
                if any(h.strip() for h in normalized_headers):
                    service.spreadsheets().values().update(
                        spreadsheetId=sheet_id,
                        range=f"{new_tab_title}!A1",
                        valueInputOption="RAW",
                        body={"values": [normalized_headers]},
                    ).execute()
                    headers_applied = True
            except HttpError as he:
                headers_warning = (
                    f"Tab '{new_tab_title}' was created, but writing the "
                    f"header row failed: {he}"
                )
            except Exception as he:
                headers_warning = (
                    f"Tab '{new_tab_title}' was created, but writing the "
                    f"header row failed: {he}"
                )

        message = f"Tab '{new_tab_title}' added to the spreadsheet."
        if headers_applied:
            message += f" Headers ({len(headers or [])} columns) seeded in row 1."
        elif headers_warning:
            message += f" {headers_warning}"

        return {
            "success": True,
            "created": True,
            "tab_name": new_tab_title,
            "tab_id": new_tab_id,
            "sheet_id": sheet_id,
            "headers_applied": headers_applied,
            "warning": headers_warning,
            "message": message,
        }

    except HttpError as e:
        # Google's "addSheet" with a duplicate title returns 400 with a
        # message like "A sheet with the name 'Food' already exists".
        # That branch should have been caught by our pre-check above, but
        # we surface a clean error_type if it slips through (e.g. due to
        # a race condition where the tab was created between our get()
        # and our batchUpdate()).
        err_str = str(e)
        if "already exists" in err_str.lower():
            return {
                "success": False,
                "error": f"Tab creation conflict: {err_str}",
                "error_type": "duplicate_tab",
            }
        return {
            "success": False,
            "error": f"Google Sheets API error: {err_str}",
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to add sheet tab: {str(e)}"}


def mirror_tabs(
    source_sheet_id: str,
    target_sheet_id: str,
    create_missing: bool = True,
    clear_existing: bool = True,
    copy_data: bool = True,
    include_tabs: Optional[List[str]] = None,
    exclude_tabs: Optional[List[str]] = None,
    tab_mapping: Optional[Dict[str, str]] = None,
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Mirror all tabs (or a filtered subset) from a source spreadsheet to a
    target spreadsheet in a single tool call.

    This is the compound tool that solves the "for each tab, copy it to
    the target" pattern that the static plan format cannot express via
    composition (DEMO SHEET 1.2.log root cause). The orchestrator emits
    ONE step calling mirror_tabs; the per-tab loop runs inside this
    function.

    Behavior per tab (in order):
      1. Resolve the destination tab name. By default the source tab
         name is reused on the target. If a `tab_mapping` entry exists
         for the source tab (case-insensitive key match), the mapped
         value is used as the target tab name instead — this enables
         the "put Source.A into Target.B" rename case without touching
         the source spreadsheet.
      2. If the destination tab is missing from the target AND
         create_missing is True → add it via batchUpdate(addSheet).
         If create_missing is False → skip the tab and record
         status="skipped_missing".
      3. If the destination tab exists in the target AND clear_existing
         is True → clear all values via spreadsheets.values.clear. Cell
         formatting and conditional rules are preserved by Sheets'
         clear() semantics.
      4. If copy_data is True → read all values from the source tab and
         write them to the destination tab in a single update() call.
         Formulas are read with valueRenderOption="UNFORMATTED_VALUE"
         so we copy literal cell contents (formulas survive, dates
         remain serial), and write with valueInputOption="USER_ENTERED"
         so the target re-parses formulas. Cells beyond the source
         range are NOT touched on the target — pair with
         clear_existing=True for a true overwrite.

    Per-tab failures are non-fatal. The function aggregates per-tab
    results and reports overall success only if at least one tab
    succeeded with no errors. The plan continues to the next tab after
    a per-tab error, so a transient permission glitch on one tab does
    not lose progress on the others.

    Args:
        source_sheet_id: Google Sheets ID or full URL of the source
            spreadsheet. URL is auto-parsed via _extract_sheet_id.
        target_sheet_id: Google Sheets ID or full URL of the target
            spreadsheet. Must differ from source_sheet_id.
        create_missing: When True, missing destination tabs are created
            in the target. Default True. Set to False for the "only
            mirror tabs that already exist on both sides" pattern —
            unmatched source tabs are skipped with
            status="skipped_missing".
        clear_existing: When True, existing destination tabs in the
            target are cleared (values only — formatting preserved)
            before the source data is written. Default True. Setting
            this False with copy_data=True will MERGE the source over
            the existing target data cell-for-cell, leaving any cells
            outside the source range untouched — usually NOT what the
            user wants.
        copy_data: When True, source tab values are written to the
            destination tab. Default True. Set False to ONLY create
            missing tabs without copying data (rare).
        include_tabs: Optional whitelist — only tab names in this list
            are mirrored. Match is case-insensitive against SOURCE tab
            titles (i.e. you whitelist what to copy FROM). When None or
            empty, all source tabs are considered. Ignored when
            tab_mapping is provided (mapping doubles as a whitelist).
        exclude_tabs: Optional blacklist — tab names in this list are
            skipped. Case-insensitive. Applied after include_tabs.
            Ignored when tab_mapping is provided.
        tab_mapping: Optional {source_name: target_name} dict for the
            "put Source.A into Target.B" rename case. When provided,
            ONLY mappings in this dict are processed — unmapped source
            tabs are NOT mirrored even if they share a name with a
            target tab. Source-name lookup is case-insensitive; the
            target-name value is used verbatim (preserves user's
            preferred case). When the source tab named in a mapping
            does not exist on the source spreadsheet, the mapping is
            skipped with status="skipped_source_missing". When None or
            empty, the default same-name behavior applies and all
            source tabs are processed (subject to include/exclude).
        credentials_dict: Google OAuth credentials.

    Returns:
        Dictionary with overall summary plus per-tab detail. See the
        "Returns" entry in agent_capabilities_v3 for the full schema.
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        source_sheet_id = _extract_sheet_id(source_sheet_id)
        target_sheet_id = _extract_sheet_id(target_sheet_id)

        if source_sheet_id == target_sheet_id:
            return {
                "success": False,
                "error": (
                    "source_sheet_id and target_sheet_id must differ — "
                    "mirror_tabs cannot mirror a spreadsheet onto itself."
                ),
                "error_type": "bad_input",
            }

        # Normalize the optional filter lists once. We compare against
        # source titles in lowercase, so pre-lowercase the filter sets.
        include_lower = {
            (name or "").strip().lower() for name in (include_tabs or [])
            if isinstance(name, str) and name.strip()
        }
        exclude_lower = {
            (name or "").strip().lower() for name in (exclude_tabs or [])
            if isinstance(name, str) and name.strip()
        }

        # Normalize tab_mapping: lowercase the source-side keys for
        # case-insensitive lookup; preserve target-side values verbatim
        # so the user's preferred case is honored on the target.
        # Skip empty/whitespace keys or values defensively — those would
        # produce undefined behavior (empty target tab name) and are
        # almost certainly user error.
        mapping_lower: Dict[str, str] = {}
        if tab_mapping:
            for src_name, tgt_name in tab_mapping.items():
                if not isinstance(src_name, str) or not isinstance(tgt_name, str):
                    continue
                src_clean = src_name.strip()
                tgt_clean = tgt_name.strip()
                if not src_clean or not tgt_clean:
                    continue
                mapping_lower[src_clean.lower()] = tgt_clean

        # Surface a warning when both tab_mapping and include/exclude
        # filters are passed — mapping wins, but we tell the caller.
        warnings: List[str] = []
        if mapping_lower and (include_lower or exclude_lower):
            warnings.append(
                "tab_mapping was provided alongside include_tabs/exclude_tabs; "
                "the mapping takes precedence and the include/exclude "
                "filters are ignored for this run."
            )

        # Surface a warning when tab_mapping has duplicate target names
        # (e.g. {"A": "X", "B": "X"}). Each iteration over a duplicate
        # target overwrites the previous iteration's data, so the user
        # ends up with only the LAST source's data in that target. This
        # is almost always a user error worth flagging up-front.
        if mapping_lower:
            target_counts: Dict[str, List[str]] = {}
            for src_lower, tgt_name in mapping_lower.items():
                target_counts.setdefault(tgt_name.lower(), []).append(src_lower)
            duplicates = {
                k: v for k, v in target_counts.items() if len(v) > 1
            }
            if duplicates:
                dup_summary = "; ".join(
                    f"{k!r} ← {', '.join(v)}" for k, v in duplicates.items()
                )
                warnings.append(
                    f"tab_mapping has duplicate target names: {dup_summary}. "
                    f"Each target tab will end up with the data from the "
                    f"LAST mapped source; earlier sources' data WILL BE "
                    f"OVERWRITTEN. If you wanted distinct target tabs, "
                    f"give each mapping a unique target name."
                )

        service = create_sheets_service(credentials_dict)

        source_meta = service.spreadsheets().get(
            spreadsheetId=source_sheet_id
        ).execute()
        target_meta = service.spreadsheets().get(
            spreadsheetId=target_sheet_id
        ).execute()

        source_sheets = source_meta.get("sheets", [])
        target_sheets = target_meta.get("sheets", [])
        source_title = source_meta.get("properties", {}).get("title", "")
        target_title = target_meta.get("properties", {}).get("title", "")

        # Build a lowercase->original map of source titles so we can
        # honor a tab_mapping key like "food" against a real source tab
        # titled "Food" without requiring exact-case input from the user.
        source_titles_lower = {
            s.get("properties", {}).get("title", "").lower(): s.get("properties", {}).get("title", "")
            for s in source_sheets
        }
        target_titles_lower = {
            s.get("properties", {}).get("title", "").lower(): s.get("properties", {})
            for s in target_sheets
        }

        tabs_processed: List[Dict[str, Any]] = []
        tabs_total = 0
        tabs_succeeded = 0
        tabs_failed = 0
        tabs_created = 0
        tabs_cleared = 0
        rows_total = 0

        # Compute the iteration list. When tab_mapping is provided we
        # iterate the mapping (so the user's enumerated rename pairs
        # drive the loop). Otherwise we iterate all source tabs and
        # apply include/exclude filters.
        # Each element is a tuple (source_title, dest_title,
        # source_missing) where source_missing=True means the user
        # named a source tab in tab_mapping that doesn't exist on the
        # source — we still record it as a per-tab result with status
        # "skipped_source_missing" so the user can see the typo.
        iteration_list: List[Tuple[str, str, bool]] = []

        if mapping_lower:
            for src_lower, tgt_name in mapping_lower.items():
                if src_lower in source_titles_lower:
                    iteration_list.append(
                        (source_titles_lower[src_lower], tgt_name, False)
                    )
                else:
                    # Use the user's original key casing in the result so
                    # the message matches what they typed.
                    user_key = next(
                        (k for k in (tab_mapping or {}).keys()
                         if isinstance(k, str) and k.strip().lower() == src_lower),
                        src_lower,
                    )
                    iteration_list.append((user_key, tgt_name, True))
        else:
            for src_sheet in source_sheets:
                src_props = src_sheet.get("properties", {})
                src_title = src_props.get("title", "")
                src_title_lower = src_title.lower()
                if include_lower and src_title_lower not in include_lower:
                    continue
                if src_title_lower in exclude_lower:
                    continue
                iteration_list.append((src_title, src_title, False))

        for src_title, dest_title, src_missing in iteration_list:
            tabs_total += 1
            tab_result: Dict[str, Any] = {
                "tab_name": src_title,
                "target_tab_name": dest_title,
                "created": False,
                "cleared": False,
                "rows_copied": 0,
                "columns_copied": 0,
                "status": "pending",
                "error": None,
            }

            # Pre-flight: the user's tab_mapping referenced a source tab
            # that doesn't exist. Record and move on.
            if src_missing:
                tab_result["status"] = "skipped_source_missing"
                tab_result["error"] = (
                    f"Source tab '{src_title}' was named in tab_mapping "
                    f"but does not exist on the source spreadsheet — "
                    f"check the spelling (case-insensitive)."
                )
                tabs_processed.append(tab_result)
                continue

            try:
                dest_lower = dest_title.lower()
                exists_in_target = dest_lower in target_titles_lower

                # Step 1 — ensure the destination tab exists in the target.
                if not exists_in_target:
                    if not create_missing:
                        tab_result["status"] = "skipped_missing"
                        tab_result["error"] = (
                            f"Destination tab '{dest_title}' is missing "
                            f"from the target and create_missing=False — "
                            f"skipped."
                        )
                        tabs_processed.append(tab_result)
                        continue

                    add_request = {
                        "requests": [
                            {"addSheet": {"properties": {"title": dest_title}}}
                        ]
                    }
                    try:
                        service.spreadsheets().batchUpdate(
                            spreadsheetId=target_sheet_id,
                            body=add_request,
                        ).execute()
                        tab_result["created"] = True
                        tabs_created += 1
                    except HttpError as add_err:
                        # Race condition: tab created between our get() and
                        # our addSheet(). Treat as exists_in_target.
                        if "already exists" in str(add_err).lower():
                            warnings.append(
                                f"Tab '{dest_title}' was created by another "
                                f"process during mirror_tabs — proceeding "
                                f"with the existing tab."
                            )
                            exists_in_target = True
                        else:
                            raise

                # Step 2 — read source data BEFORE clearing the target.
                # Doing the source read first protects the target from
                # being stranded in a cleared state if the source read
                # fails (insufficient permission, network blip, source
                # tab renamed mid-flight). The clear step has been
                # known to leave a target tab empty if the subsequent
                # source read errored — this ordering prevents that
                # data-loss window.
                source_values = None
                if copy_data:
                    try:
                        read_result = service.spreadsheets().values().get(
                            spreadsheetId=source_sheet_id,
                            range=src_title,
                            valueRenderOption="UNFORMATTED_VALUE",
                            dateTimeRenderOption="SERIAL_NUMBER",
                        ).execute()
                        source_values = read_result.get("values", [])
                    except HttpError as read_err:
                        # Abort BEFORE clearing the target so we don't
                        # destroy data we cannot replace.
                        tab_result["status"] = "error"
                        tab_result["error"] = (
                            f"Could not read source tab '{src_title}': "
                            f"{read_err}. Target tab was NOT cleared."
                        )
                        tabs_failed += 1
                        tabs_processed.append(tab_result)
                        continue

                # Step 3 — clear existing data when requested.
                # Skip if the tab was JUST created (it's already empty).
                # Now that the source read has succeeded (or copy_data
                # is False), it's safe to clear the target.
                if exists_in_target and clear_existing and not tab_result["created"]:
                    try:
                        service.spreadsheets().values().clear(
                            spreadsheetId=target_sheet_id,
                            range=dest_title,
                            body={},
                        ).execute()
                        tab_result["cleared"] = True
                        tabs_cleared += 1
                    except HttpError as clear_err:
                        # Not fatal — the tab is there but we couldn't
                        # clear it. Most common cause: insufficient edit
                        # permission on a specific tab. Log a warning,
                        # try the write anyway (it'll merge on top of
                        # whatever's there).
                        warnings.append(
                            f"Could not clear existing data in target tab "
                            f"'{dest_title}' before write: {clear_err}"
                        )

                # Step 4 — write source values to destination.
                if copy_data and source_values:
                    try:
                        service.spreadsheets().values().update(
                            spreadsheetId=target_sheet_id,
                            range=f"{dest_title}!A1",
                            valueInputOption="USER_ENTERED",
                            body={"values": source_values},
                        ).execute()
                        tab_result["rows_copied"] = len(source_values)
                        tab_result["columns_copied"] = (
                            max((len(row) for row in source_values), default=0)
                        )
                        rows_total += len(source_values)
                    except HttpError as write_err:
                        # The clear succeeded but the write failed —
                        # the target tab is now empty and we couldn't
                        # restore it. Surface this loudly so the user
                        # knows manual recovery is needed.
                        tab_result["status"] = "error"
                        tab_result["error"] = (
                            f"Wrote NOTHING to target tab '{dest_title}' — "
                            f"the tab was cleared but the subsequent write "
                            f"failed: {write_err}. Target tab is now EMPTY; "
                            f"manual recovery may be needed."
                        )
                        tabs_failed += 1
                        tabs_processed.append(tab_result)
                        continue
                elif copy_data and not source_values:
                    # Empty source tab — record but don't error.
                    tab_result["rows_copied"] = 0
                    tab_result["columns_copied"] = 0

                tab_result["status"] = "success"
                tabs_succeeded += 1

            except HttpError as he:
                tab_result["status"] = "error"
                tab_result["error"] = f"Google Sheets API error: {he}"
                tabs_failed += 1
            except Exception as he:
                tab_result["status"] = "error"
                tab_result["error"] = f"Failed to mirror tab: {he}"
                tabs_failed += 1

            tabs_processed.append(tab_result)

        # Build the summary message. Overall success requires:
        #   - No HTTP/Sheets failures (tabs_failed == 0), AND
        #   - At least one tab made it through (tabs_succeeded > 0)
        #     OR the only "skips" were intentional (create_missing=False
        #     with no matching target tab — the user explicitly opted
        #     out of new-tab creation, so 0-of-N is the correct outcome).
        # When ALL skips are typos (tab_mapping referenced source tabs
        # that don't exist) and nothing else succeeded, we mark this as
        # a hard failure so the user notices and corrects. Mixed cases
        # (1 success + 1 typo) stay successful but we add a warning.
        tabs_skipped_typo = sum(
            1 for t in tabs_processed
            if (t.get("status") or "") == "skipped_source_missing"
        )
        tabs_skipped_missing = sum(
            1 for t in tabs_processed
            if (t.get("status") or "") == "skipped_missing"
        )
        tabs_skipped = tabs_skipped_typo + tabs_skipped_missing

        overall_success = (
            tabs_failed == 0
            and (tabs_succeeded > 0 or tabs_skipped_typo == 0)
        )

        # If there are typo skips but at least one tab succeeded,
        # surface them as a warning so the user is alerted without
        # downgrading the run to a failure.
        if tabs_skipped_typo > 0 and tabs_succeeded > 0:
            warnings.append(
                f"{tabs_skipped_typo} tab_mapping entry/entries referenced "
                f"source tabs that don't exist (typo?) — those entries "
                f"were skipped. See per-tab `skipped_source_missing` "
                f"status for details."
            )

        # Format-aware skip hint reused by several branches.
        def _skip_hint(prefix: str) -> str:
            parts = []
            if tabs_skipped_missing:
                parts.append(f"{tabs_skipped_missing} skipped (no target match)")
            if tabs_skipped_typo:
                parts.append(f"{tabs_skipped_typo} typo'd source name(s)")
            return f"{prefix}{', '.join(parts)}" if parts else ""

        if tabs_total == 0:
            message = (
                "No source tabs matched the include/exclude filters — "
                "nothing was mirrored."
            )
            error_type = None
        elif tabs_succeeded == 0 and tabs_failed == 0:
            # Nothing actually executed — every iteration was a skip.
            if tabs_skipped_typo > 0 and tabs_skipped_missing == 0:
                message = (
                    f"Could not mirror any tabs from '{source_title}' to "
                    f"'{target_title}' — all {tabs_skipped_typo} "
                    f"tab_mapping entries referenced source tabs that "
                    f"do not exist. Check the spelling (matching is "
                    f"case-insensitive)."
                )
                error_type = "bad_input"
            elif tabs_skipped_typo > 0 and tabs_skipped_missing > 0:
                message = (
                    f"Mirrored 0 of {tabs_total} tab(s) from "
                    f"'{source_title}' to '{target_title}' — "
                    f"{tabs_skipped_typo} tab_mapping entry/entries "
                    f"referenced unknown source tabs (typo?), and "
                    f"{tabs_skipped_missing} other tab(s) had no "
                    f"matching target with create_missing=False."
                )
                error_type = "bad_input"
            else:
                # Pure intentional skips — every source tab was missing
                # from the target and create_missing=False.
                message = (
                    f"Mirrored 0 of {tabs_total} tab(s) from "
                    f"'{source_title}' to '{target_title}' — all "
                    f"{tabs_total} source tab(s) were missing from the "
                    f"target and create_missing=False, so no new tabs "
                    f"were created and no data was written."
                )
                error_type = None
        elif tabs_failed == 0:
            # At least one success; possibly some skips. Skips are
            # surfaced via warnings + per-tab status, so the message
            # stays in the "success" framing.
            hint = _skip_hint(" — ")
            verb = "Successfully mirrored" if not tabs_skipped else "Mirrored"
            message = (
                f"{verb} {tabs_succeeded} of {tabs_total} tab(s) "
                f"from '{source_title}' to '{target_title}'{hint}."
            )
            error_type = None
        elif tabs_succeeded == 0:
            # Pure failures, possibly with skips.
            hint = _skip_hint(", ")
            message = (
                f"Failed to mirror any tabs from '{source_title}' to "
                f"'{target_title}' — {tabs_failed} tab(s) errored"
                f"{hint}."
            )
            error_type = "partial_failure"
        else:
            # Mixed: some succeeded, some failed, possibly some skipped.
            hint = _skip_hint(", ")
            message = (
                f"Partially mirrored {tabs_succeeded} of {tabs_total} "
                f"tab(s) from '{source_title}' to '{target_title}' — "
                f"{tabs_failed} failed{hint}."
            )
            error_type = "partial_failure"

        # error string mirrors error_type for downstream consumers
        # (summarization service categorizes via _categorize_error).
        # When success is True the per-tab warnings already capture any
        # non-fatal skips, so error stays None.
        if overall_success:
            error_msg = None
        elif tabs_failed > 0:
            error_msg = (
                f"{tabs_failed} of {tabs_total} tab(s) failed during mirror"
            )
        else:
            # tabs_failed == 0, tabs_succeeded == 0, tabs_skipped_typo > 0:
            # all-typo case (no legit work done).
            error_msg = (
                f"{tabs_skipped_typo} tab_mapping entry/entries "
                f"referenced unknown source tabs and nothing was mirrored"
            )

        return {
            "success": overall_success,
            "source_sheet_id": source_sheet_id,
            "target_sheet_id": target_sheet_id,
            "source_title": source_title,
            "target_title": target_title,
            "tabs_processed": tabs_processed,
            "tabs_total": tabs_total,
            "tabs_succeeded": tabs_succeeded,
            "tabs_failed": tabs_failed,
            "tabs_skipped": tabs_skipped,
            "tabs_created": tabs_created,
            "tabs_cleared": tabs_cleared,
            "rows_total": rows_total,
            "warnings": warnings,
            "message": message,
            "error": error_msg,
            "error_type": error_type,
        }

    except HttpError as e:
        return {
            "success": False,
            "error": f"Google Sheets API error: {str(e)}",
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to mirror tabs: {str(e)}"}


def clear_sheet(
    sheet_id: str,
    range_name: Optional[str] = None,
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """
    Clear data from a sheet range

    Args:
        sheet_id: Google Sheets ID, or a full URL. A `?gid=` tab
            identifier in the URL is used when `range_name` is a bare
            tab reference (e.g. the legacy "Sheet1" default).
        range_name: Range to clear (e.g., 'Sheet1' or 'Sheet1!A1:D10').
            Optional — when omitted (or when the prefix is the legacy
            "Sheet1" default), the tool resolves the tab via the URL's
            `gid=` parameter or falls back to the first tab.
        credentials_dict: Google OAuth credentials

    Returns:
        Dictionary with clear results
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        gid = _extract_gid(sheet_id)
        sheet_id = _extract_sheet_id(sheet_id)
        effective_range = _apply_tab_to_range(
            range_name, sheet_id, gid, credentials_dict
        )

        service = create_sheets_service(credentials_dict)

        result = (
            service.spreadsheets()
            .values()
            .clear(spreadsheetId=sheet_id, range=effective_range, body={})
            .execute()
        )

        return {
            "success": True,
            "cleared_range": result.get("clearedRange"),
            "range": effective_range,
            "message": f"Cleared data from {effective_range}",
        }

    except HttpError as e:
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to clear sheet: {str(e)}"}


def get_sheet_headers(
    sheet_id: str,
    sheet_name: Optional[str] = None,
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """Get the header row of an existing sheet — needed for column mapping.

    When `sheet_name` is omitted, the tool resolves the tab via the URL's
    `gid=` parameter or falls back to the first tab. Pass an explicit name
    to override that resolution.
    """
    try:
        gid = _extract_gid(sheet_id)
        sheet_id = _extract_sheet_id(sheet_id)
        resolved_tab = _pick_sheet_name(
            sheet_name, sheet_id, gid, credentials_dict
        )
        service = create_sheets_service(credentials_dict)
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=f"{resolved_tab}!1:1"
        ).execute()
        headers = result.get("values", [[]])[0] if result.get("values") else []
        return {
            "success": True,
            "headers": headers,
            "column_count": len(headers),
            "sheet_name": resolved_tab,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _norm_header(val: Any) -> str:
    """Canonicalize a header cell for comparison.

    Normalization steps (applied in order):
      1. `str()` + `.strip()` + `.lower()` — neutralize null, case, edge whitespace.
      2. Collapse runs of whitespace / underscore / hyphen into a single space.

    Step 2 exists because the planner often guesses at dedup_on names with
    one separator style ("message_id", "order-ref") while the actual sheet
    header uses another ("Message ID", "Order Ref"). Without this
    tolerance, those drops into `missing_dedup_column` even though the
    columns are semantically the same. The trade-off is that two columns
    genuinely named "Order Ref" and "Order_Ref" in the same sheet would
    collide — an unusual schema we're willing to reject as ambiguous.
    """
    normalized = str(val or "").strip().lower()
    return re.sub(r"[\s_\-]+", " ", normalized).strip()


def ensure_headers(
    sheet_id: str,
    headers: Any,
    sheet_name: Optional[str] = None,
    force: bool = False,
    credentials_dict: Optional[CredentialsDict] = None,
) -> Dict[str, Any]:
    """Idempotent header writer / validator.

    Three branches:
      1. Row 1 is empty   -> write `headers`,   return action="created".
      2. Row 1 matches    -> no-op,             return action="matched".
         (Exact-length, order-sensitive, case-insensitive, whitespace-trimmed.)
      3. Row 1 mismatches -> if force=False, return an error with
                             `existing_headers` + `requested_headers`.
                             if force=True, overwrite,
                             return action="overwritten" + `prior_headers`.

    Called by Rule 17 as a fallback when get_sheet_headers returned []
    (fresh tab); called by Rule 18 as an alternate to seeding headers
    via create_sheet.initial_data.

    Args:
        sheet_id: Google Sheets ID or URL. `?gid=` in URLs honored.
        headers: Canonical header row. Accepts a native `List[str]`, a
            JSON string (e.g. '["Date","Ref"]'), a Python-repr string
            (e.g. "['Date', 'Ref']"), OR a nested single-row 2D list
            (e.g. [["Date","Ref"]]) — the nested form is flattened since
            `ensure_headers` always writes row 1. The string forms exist
            because Jinja renders a list variable as a Python-repr
            string in the normal-execution substitution path (see
            AUTO-UNWRAP ASYMMETRY in supervisor_agent.py). Must end up
            as a non-empty list of non-blank strings.
        sheet_name: Optional tab name; resolved via gid or first tab when
            omitted.
        force: When True, overwrites a mismatching row 1 instead of
            returning an error. Defaults to False — destructive overwrite
            must be explicit.
        credentials_dict: Google OAuth credentials.

    Returns:
        Always includes `success`. On success also includes `action`
        (created|matched|overwritten), `headers_set` (bool), `headers`
        (the final row-1 values), `sheet_name`, and — when action was
        overwritten — `prior_headers`. On mismatch without force:
        `error`, `error_type="header_conflict"`, `existing_headers`,
        `requested_headers`.
    """
    try:
        if not credentials_dict:
            return {"success": False, "error": "Credentials required"}

        # Defensive parse: `headers` may arrive as a str (Jinja render of
        # a list variable) or as a 2D single-row list ([["Date","Ref"]]
        # if the caller mistakenly passed create_sheet.initial_data
        # shape). Normalize to a flat List[str] before validating.
        try:
            coerced = _coerce_rows(headers)
        except ValueError as e:
            return {
                "success": False,
                "error": f"Invalid headers shape for ensure_headers: {e}",
                "error_type": "bad_input",
            }
        if not coerced:
            return {
                "success": False,
                "error": "headers is empty after parsing",
                "error_type": "bad_input",
            }
        if len(coerced) > 1:
            return {
                "success": False,
                "error": (
                    f"headers must be a single row (got {len(coerced)} rows). "
                    f"Pass a flat list like ['Date','Ref'], not a 2D table."
                ),
                "error_type": "bad_input",
            }
        header_row = coerced[0]
        if not header_row:
            return {
                "success": False,
                "error": "headers is an empty row",
                "error_type": "bad_input",
            }
        normalized_headers = [str(h or "").strip() for h in header_row]
        if any(not h for h in normalized_headers):
            return {
                "success": False,
                "error": "headers contains a blank entry; all column names must be non-empty strings",
                "error_type": "bad_input",
            }

        gid = _extract_gid(sheet_id)
        sheet_id = _extract_sheet_id(sheet_id)
        resolved_tab = _pick_sheet_name(
            sheet_name, sheet_id, gid, credentials_dict
        )

        service = create_sheets_service(credentials_dict)

        read_result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=sheet_id, range=f"{resolved_tab}!1:1")
            .execute()
        )
        existing = (read_result.get("values") or [[]])[0] if read_result.get("values") else []
        existing_has_content = any(bool(str(c or "").strip()) for c in existing)

        # Branch 1: empty row 1 -> write headers
        if not existing_has_content:
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=f"{resolved_tab}!A1",
                valueInputOption="RAW",
                body={"values": [normalized_headers]},
            ).execute()
            return {
                "success": True,
                "action": "created",
                "headers_set": True,
                "headers": normalized_headers,
                "sheet_name": resolved_tab,
                "message": f"Wrote {len(normalized_headers)} header columns to {resolved_tab}",
            }

        existing_norm = [_norm_header(c) for c in existing]
        expected_norm = [_norm_header(c) for c in normalized_headers]

        matches_exactly = existing_norm == expected_norm
        if matches_exactly:
            return {
                "success": True,
                "action": "matched",
                "headers_set": False,
                "headers": existing,
                "sheet_name": resolved_tab,
                "message": f"Headers already match in {resolved_tab} ({len(existing)} columns)",
            }

        if not force:
            return {
                "success": False,
                "error": (
                    f"Header mismatch in {resolved_tab}: existing headers "
                    f"differ from requested. Pass force=true to overwrite, "
                    f"or resolve the schema manually."
                ),
                "error_type": "header_conflict",
                "existing_headers": existing,
                "requested_headers": normalized_headers,
                "sheet_name": resolved_tab,
            }

        # Branch 3 (force=True): overwrite. Pad trailing cells with empty
        # strings when the new schema is narrower than the old one, so
        # Sheets doesn't leave stale header names in columns beyond the
        # new width (Sheets values.update with a short values[] leaves
        # cells past values[][-1] UNTOUCHED; padding forces them to be
        # cleared). When the new schema is wider or same width, no
        # padding is needed.
        padded = list(normalized_headers)
        if len(existing) > len(padded):
            padded.extend([""] * (len(existing) - len(padded)))
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=f"{resolved_tab}!A1",
            valueInputOption="RAW",
            body={"values": [padded]},
        ).execute()
        return {
            "success": True,
            "action": "overwritten",
            "headers_set": True,
            "headers": normalized_headers,
            "prior_headers": existing,
            "sheet_name": resolved_tab,
            "message": f"Overwrote row 1 in {resolved_tab} (prior headers preserved in prior_headers)",
        }

    except HttpError as e:
        return {"success": False, "error": f"Google Sheets API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to ensure headers: {str(e)}"}


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
            "sheet_id": sheet_id,
            "sheet_url": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
            "sheet_name": sheet_name,
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
# Gid identifies a specific tab inside a spreadsheet. Shows up in Google
# URLs as either `?gid=123` or `#gid=123` (and sometimes both, e.g.
# `/edit?gid=123#gid=123`). We accept any of those forms.
_GID_URL_RE = re.compile(r"[?#&]gid=(\d+)")

# Historical default tab name when no `sheet_name` was supplied to the
# generic sheet tools. If a user pasted a URL pointing at a different
# tab (via `?gid=…`) but omitted `sheet_name`, the old code hardcoded
# "Sheet1" and crashed with "Unable to parse range: Sheet1!A:A" when
# the spreadsheet had no tab literally called "Sheet1". The helpers
# below treat this literal as a "resolve via gid / first tab" signal
# while still honoring explicit non-default names.
_LEGACY_DEFAULT_TAB = "Sheet1"

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
    or a native list.  Returns the list of order objects or raises ValueError.

    Sibling of `_coerce_rows` (defined below). `_parse_orders_input` targets
    the delivery-order shape (list of dicts); `_coerce_rows` targets the
    generic append/update shape (list of lists). Kept separate because the
    two callers expect different inner shapes; consolidation deferred until
    a third caller with overlapping needs emerges.
    """
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


def _try_json_for_rows(s: str) -> Any:
    """Try json.loads; return parsed value or None on any parse failure.
    Broad exception catch — some JSON decoders raise ValueError, some
    raise JSONDecodeError, some TypeError on unexpected inputs."""
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def _try_literal_eval_for_rows(s: str) -> Any:
    """Try ast.literal_eval; return parsed value or None on any parse
    failure. Used as the Python-repr fallback when JSON fails (Python
    repr uses single quotes which JSON rejects)."""
    import ast
    try:
        return ast.literal_eval(s)
    except (ValueError, SyntaxError, MemoryError, TypeError):
        return None


def _strip_md_fences(s: str) -> str:
    """Strip a leading ```lang\\n (or bare ```\\n) and a trailing ``` from
    a markdown-fenced code block. Returns the cleaned content. If no
    fences are present returns the input stripped of outer whitespace
    (idempotent)."""
    stripped = s.strip()
    changed = False
    if stripped.startswith("```"):
        nl = stripped.find("\n")
        if nl != -1:
            stripped = stripped[nl + 1 :]
            changed = True
        # If no newline after the opening fence, it's just "```" with no
        # body — leave the original alone rather than nuking it.
    if stripped.endswith("```"):
        stripped = stripped[:-3].rstrip()
        changed = True
    return stripped.strip() if changed else s.strip()


def _coerce_rows(data: Any) -> List[List[Any]]:
    """Normalize `data` for append_rows / update_sheet / create_sheet.initial_data
    to List[List[Any]], accepting a variety of upstream-degraded shapes.

    Sibling of `_parse_orders_input` (~40-60% overlap). This helper exists
    because llm_tool.transform_text, when asked to output "a list of rows",
    tends to emit ONE of several strings that Jinja then renders verbatim
    into the substituted inputs:
      - a clean JSON 2D array: `[["a","b"],["c","d"]]`
      - a Python-repr 2D list: `[['a','b'],['c','d']]`
      - a Python-repr per line (DEMO5.2 shape): `['a','b']\\n['c','d']\\n['e','f']`
      - any of the above wrapped in ```json ... ``` fences
      - a dict wrapper: `{"rows": [["a","b"]]}`

    The orchestrator's pause-time auto-unwrap (search for the
    approval-pause branch in supervisor_agent.py) handles single-expression
    JSON/repr but cannot parse multi-line or fenced shapes. The
    normal-execution substitution path has NO unwrap at all — Jinja output
    is passed through as a raw string (search tag: "AUTO-UNWRAP ASYMMETRY"
    in supervisor_agent.py). This asymmetry is intentional so sub-agents
    that actually want a raw string keep working; the cost is that tools
    which do expect native types must be defensive, which is what this
    helper is for.

    Strategy order (each falls through to the next on failure):
      1. list — all items sequences -> passthrough (coerce tuples to lists);
                no items sequences   -> 1D promoted to single-row 2D;
                mixed                -> raise (ambiguous shape).
      2. tuple — convert to list, recurse.
      3. dict with "rows"/"data"/"values" key -> recurse on that value.
      4. None or empty-string -> return [].
      5. str -> json.loads on entire value; recurse on success.
      6. str -> ast.literal_eval on entire value; recurse on success.
      7. str -> strip markdown fences, retry 5+6.
      8. str -> splitlines, parse each non-blank line via literal_eval
               (then JSON as fallback), accumulate lists that parsed.
               Handles the DEMO5.2 multi-line shape.
      9. anything else -> raise ValueError with a clear type hint.
    """
    # 1. list
    if isinstance(data, list):
        if not data:
            return []
        has_seq = any(isinstance(row, (list, tuple)) for row in data)
        all_seq = all(isinstance(row, (list, tuple)) for row in data)
        if has_seq and not all_seq:
            raise ValueError(
                "data must be a 2D list OR a 1D list of scalars — "
                "received a mixed list (some rows are sequences, others scalars)."
            )
        if all_seq:
            return [list(row) for row in data]
        # 1D promoted to single-row 2D
        return [list(data)]
    # 2. tuple
    if isinstance(data, tuple):
        return _coerce_rows(list(data))
    # 3. dict wrapper
    if isinstance(data, dict):
        for key in ("rows", "data", "values"):
            if key in data:
                return _coerce_rows(data[key])
        raise ValueError(
            f"dict input to _coerce_rows must have a 'rows', 'data', or "
            f"'values' key; got keys {list(data.keys())}"
        )
    # 4. None / empty
    if data is None:
        return []
    # String strategies
    if isinstance(data, str):
        stripped = data.strip()
        if not stripped:
            return []
        # 5. JSON
        parsed = _try_json_for_rows(stripped)
        if parsed is not None:
            return _coerce_rows(parsed)
        # 6. literal_eval
        parsed = _try_literal_eval_for_rows(stripped)
        if parsed is not None:
            return _coerce_rows(parsed)
        # 7. markdown-fence strip + retry
        fenced = _strip_md_fences(stripped)
        if fenced and fenced != stripped:
            parsed = _try_json_for_rows(fenced)
            if parsed is None:
                parsed = _try_literal_eval_for_rows(fenced)
            if parsed is not None:
                return _coerce_rows(parsed)
        # 8. splitlines + per-line parse (DEMO5.2 shape)
        rows: List[List[Any]] = []
        for line in stripped.splitlines():
            line = line.strip().rstrip(",")
            if not line:
                continue
            row_val = _try_literal_eval_for_rows(line)
            if row_val is None:
                row_val = _try_json_for_rows(line)
            if isinstance(row_val, (list, tuple)):
                rows.append(list(row_val))
        if rows:
            return rows
        # All strategies exhausted
        sample = data[:200] + ("..." if len(data) > 200 else "")
        raise ValueError(
            "Could not coerce string to 2D rows (tried JSON, literal_eval, "
            f"markdown-fence strip, and per-line split). Input sample: {sample!r}"
        )
    # 9. anything else
    raise ValueError(
        f"data must be a 2D list, 1D list, string, tuple, or dict — "
        f"got {type(data).__name__}"
    )


def _extract_sheet_id(sheet_id_or_url: str) -> str:
    """Extract the spreadsheet ID from a URL or return as-is if already an ID."""
    m = _SHEET_URL_RE.search(sheet_id_or_url)
    if m:
        return m.group(1)
    return sheet_id_or_url.strip()


def _extract_gid(sheet_id_or_url: Any) -> Optional[int]:
    """Extract the `gid=N` tab identifier from a Google Sheets URL.

    Returns the gid as an int when found, or None when the input is
    a raw ID or a URL without a gid. Invariant #13 requires every tool
    that accepts an ID to also accept a full URL; this helper is the
    tab-level extension of that — a URL like
    `/edit?gid=1392110385#gid=1392110385` tells us which tab the user
    meant, without needing a separate `sheet_name` argument.
    """
    s = str(sheet_id_or_url or "")
    m = _GID_URL_RE.search(s)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _resolve_tab_title(
    sheet_id: str,
    gid: Optional[int],
    credentials_dict: Optional[CredentialsDict],
) -> Optional[str]:
    """Resolve a tab title from a spreadsheet ID + optional gid.

    - gid provided, match found: returns that tab's title.
    - gid provided, no match: falls through to the first tab (the gid
      may have been stale or pointed at a deleted tab; the first tab
      is still better than hardcoding "Sheet1").
    - gid absent: returns the first tab's title.
    - Any API failure (auth, network, permission): returns None. Callers
      must treat None as "fall back to the caller's default" — we do NOT
      raise here because this is a soft best-effort lookup.
    """
    if not credentials_dict:
        return None
    try:
        service = create_sheets_service(credentials_dict)
        spreadsheet = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    except Exception:
        return None
    sheets_meta = spreadsheet.get("sheets", []) or []
    if not sheets_meta:
        return None
    if gid is not None:
        for s in sheets_meta:
            props = s.get("properties", {}) or {}
            if props.get("sheetId") == gid:
                title = props.get("title")
                if title:
                    return title
    first_props = (sheets_meta[0].get("properties", {}) or {})
    return first_props.get("title")


def _pick_sheet_name(
    provided_name: Optional[str],
    sheet_id: str,
    gid: Optional[int],
    credentials_dict: Optional[CredentialsDict],
    default: str = _LEGACY_DEFAULT_TAB,
) -> str:
    """Pick the tab name for a generic sheet operation.

    Precedence (strongest to weakest):
      1. An explicit `provided_name` that is NOT the legacy "Sheet1"
         default: honor as-is. The planner / user clearly named a tab.
      2. A gid parsed from the URL: call the Sheets API and resolve it
         to the current tab title.
      3. No gid: resolve to the first tab's title via the same API.
      4. API resolution failed (auth/network/permission): fall back to
         `provided_name` (which is None or "Sheet1" at this point) or
         the hardcoded default. This preserves pre-fix behavior for the
         pathological case where we cannot call the API at all.

    Note: when `provided_name == "Sheet1"` AND the URL has a gid, the gid
    wins — we treat the legacy default as "caller did not specify a tab".
    This is the DEMO5.0 case. A user who genuinely wants the "Sheet1"
    tab on a multi-tab sheet should pass a URL without `gid=` (or pass
    a tab name other than the legacy default).
    """
    if provided_name and provided_name != default:
        return provided_name
    resolved = _resolve_tab_title(sheet_id, gid, credentials_dict)
    if resolved:
        return resolved
    return provided_name or default


def _apply_tab_to_range(
    range_name: Optional[str],
    sheet_id: str,
    gid: Optional[int],
    credentials_dict: Optional[CredentialsDict],
    default: str = _LEGACY_DEFAULT_TAB,
) -> str:
    """Rewrite a `range_name` argument (for read_sheet / clear_sheet /
    update_sheet) so it targets the resolved tab when the caller only
    supplied the legacy default.

    Handled cases:
      - "Sheet1" (legacy default, bare tab name)  -> resolved tab name
      - "Sheet1!A1:D10" (legacy default + prefix) -> "<resolved>!A1:D10"
      - "Orders" / "Orders!A1:D10" (non-default)  -> honored as-is
      - None / ""                                 -> resolved tab name
      - "A1:D10" (bare cell range, no prefix)     -> honored as-is
        (Sheets API will default to the first tab; we do not inject
        the resolved tab here to avoid changing semantics for callers
        that intentionally omit a prefix.)
    """
    raw = (range_name or "").strip()
    if not raw:
        resolved = _resolve_tab_title(sheet_id, gid, credentials_dict)
        return resolved or default
    if raw == default:
        resolved = _resolve_tab_title(sheet_id, gid, credentials_dict)
        return resolved or default
    if "!" in raw:
        tab, sep, cells = raw.partition("!")
        if tab.strip() == default:
            resolved = _resolve_tab_title(sheet_id, gid, credentials_dict)
            if resolved:
                return f"{resolved}{sep}{cells}"
    return raw


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


def _build_rows_from_orders(
    parsed_orders: List[Dict[str, Any]],
    tab_names: List[str],
) -> Tuple[
    Dict[str, List[List[str]]],
    Dict[str, List[Dict[str, Any]]],
    List[Dict[str, Any]],
    List[str],
]:
    """Translate `parsed_orders` into the intermediate state that both
    `preview_delivery_order_insertion` and `write_delivery_order_data`
    need:

      * `tab_rows` — `{tab_name: [[col0, col1, ...], ...]}`, the actual
        8-column rows the Sheets API will append.
      * `tab_row_meta` — parallel to `tab_rows`, carrying per-row
        `{file, page, reference_number}` so duplicate detection can
        attribute a skipped row back to its source file/page.
      * `orders_summary` — one entry per order (one per PDF page after
        the mapping-agent per-page refactor) with `file`, `page`,
        `reference_number`, `category`, `requested_by`, `tab`,
        `item_count`, and up to 3 `sample_rows`. The response template
        renders this as the per-PDF block the user asked for.
      * `warnings` — routing / missing-field warnings collected while
        building rows.

    Extracted into a shared helper so preview and write stay in lock-
    step; otherwise drift between the two (e.g. preview counts differ
    from write counts) makes the approval pause feel dishonest.
    """
    tab_rows: Dict[str, List[List[str]]] = {}
    tab_row_meta: Dict[str, List[Dict[str, Any]]] = {}
    orders_summary: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for order in parsed_orders:
        header = order.get("header", {}) or {}
        raw_category = header.get("category") or ""
        actual_tab, route_warning = _resolve_tab_for_category(raw_category, tab_names)

        if not actual_tab:
            warnings.append(
                f"{route_warning} (order {header.get('reference_number', '?')})"
            )
            continue

        source_file = order.get("file") or "(unknown)"
        source_page = order.get("page")
        date_val = header.get("date", "")
        ref = header.get("reference_number", "")
        requested_by = header.get("requested_by", "")
        header_cb_date = header.get("cb_date", "")
        line_items = order.get("line_items", []) or []

        sample_rows: List[Dict[str, Any]] = []

        for item in line_items:
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
            tab_row_meta.setdefault(actual_tab, []).append({
                "file": source_file,
                "page": source_page,
                "reference_number": ref,
            })

            if len(sample_rows) < 3:
                sample_rows.append({
                    "item_code": item.get("item_code", ""),
                    "item_description": item.get("item_description", ""),
                    "qty": item.get("qty", ""),
                    "uom": item.get("uom", ""),
                })

            if not item.get("item_code"):
                warnings.append(
                    f"Missing Item Code in row: {str(item.get('item_description', '?'))[:40]}"
                )
            if not item.get("qty") and item.get("qty") != 0:
                warnings.append(
                    f"Missing QTY for {item.get('item_code', '?')}"
                )

        orders_summary.append({
            "file": source_file,
            "page": source_page,
            "reference_number": ref,
            "category": raw_category,
            "requested_by": requested_by,
            "tab": actual_tab,
            "item_count": len(line_items),
            "sample_rows": sample_rows,
        })

    return tab_rows, tab_row_meta, orders_summary, warnings


def _aggregate_files_summary(orders_summary: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse the per-order summary into one entry per source file,
    preserving insertion order. Used by the response-template formatters
    to render a per-PDF block (one block per input file, listing every
    page under it).
    """
    by_file: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for entry in orders_summary:
        fname = entry.get("file") or "(unknown)"
        if fname not in by_file:
            by_file[fname] = {
                "file": fname,
                "pages": [],
                "total_items": 0,
                "references": [],
                "requested_bys": [],
                "tabs": [],
            }
            order.append(fname)
        rec = by_file[fname]
        page = entry.get("page")
        if page is not None and page not in rec["pages"]:
            rec["pages"].append(page)
        rec["total_items"] += int(entry.get("item_count") or 0)
        for key_pair in (
            ("reference_number", "references"),
            ("requested_by", "requested_bys"),
            ("tab", "tabs"),
        ):
            val = entry.get(key_pair[0])
            if val and val not in rec[key_pair[1]]:
                rec[key_pair[1]].append(val)
    return [by_file[f] for f in order]


def _tally_duplicates_by_file(
    duplicate_entries: List[Dict[str, Any]],
) -> Dict[str, int]:
    """Count duplicate rows per source file. The entries must already
    carry a `file` key (stamped by the duplicate-detection pass, which
    reads it from `tab_row_meta`)."""
    by_file: Dict[str, int] = {}
    for entry in duplicate_entries:
        fname = entry.get("file") or "(unknown)"
        by_file[fname] = by_file.get(fname, 0) + 1
    return by_file


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

        tab_rows, tab_row_meta, orders_summary, warnings = _build_rows_from_orders(
            parsed_orders, tab_names
        )

        all_preview_rows: List[Dict[str, Any]] = []
        for tab_name, rows in tab_rows.items():
            for row in rows:
                all_preview_rows.append({"tab": tab_name, "values": row})

        # Duplicate detection using the (Date, Order Reference, Item Code)
        # key. Catches both rows that already exist in the destination tab
        # AND rows that are duplicated WITHIN the same preview batch (e.g.
        # the same PDF was passed to parse_delivery_order_pdfs twice in
        # one call). The preview and the write paths share the same
        # helper `_row_dedup_key` so the user sees exactly the rows the
        # write will skip. We also attach `file`/`page` metadata from the
        # parallel `tab_row_meta` index so downstream rendering can show
        # which PDF produced each duplicate.
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
                for idx, row in enumerate(new_rows):
                    meta = tab_row_meta.get(tab_name, [{}])[idx] if idx < len(tab_row_meta.get(tab_name, [])) else {}
                    key = _row_dedup_key(row)
                    if key in existing_keys:
                        duplicates.append({
                            "tab": tab_name,
                            "file": meta.get("file"),
                            "page": meta.get("page"),
                            "reason": "already in sheet",
                            "date": row[0] if len(row) > 0 else "",
                            "order_reference": row[1] if len(row) > 1 else "",
                            "item_code": row[2] if len(row) > 2 else "",
                        })
                    elif key in batch_keys:
                        duplicates.append({
                            "tab": tab_name,
                            "file": meta.get("file"),
                            "page": meta.get("page"),
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
        files_summary = _aggregate_files_summary(orders_summary)
        duplicates_by_file = _tally_duplicates_by_file(duplicates)

        return {
            "success": True,
            "preview_rows": all_preview_rows,
            "total_new_rows": total_new,
            "duplicates": duplicates,
            "duplicate_count": len(duplicates),
            "duplicates_by_file": duplicates_by_file,
            "orders_summary": orders_summary,
            "files_summary": files_summary,
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

        tab_rows, tab_row_meta, orders_summary, skipped_warnings = _build_rows_from_orders(
            parsed_orders, tab_names
        )

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

            # Look up the parallel metadata list so duplicates are
            # attributed back to their source file/page. `meta_list` may
            # be shorter than `rows` in pathological cases (should not
            # happen since they're built together) — we defensively index
            # with `idx < len(meta_list)`.
            meta_list = tab_row_meta.get(tab_name, [])

            for idx, row in enumerate(rows):
                meta = meta_list[idx] if idx < len(meta_list) else {}
                key = _row_dedup_key(row)
                if key in existing_keys:
                    duplicates_skipped.append({
                        "tab": tab_name,
                        "file": meta.get("file"),
                        "page": meta.get("page"),
                        "reason": "already in sheet",
                        "date": row[0] if len(row) > 0 else "",
                        "order_reference": row[1] if len(row) > 1 else "",
                        "item_code": row[2] if len(row) > 2 else "",
                    })
                    continue
                if key in batch_keys:
                    duplicates_skipped.append({
                        "tab": tab_name,
                        "file": meta.get("file"),
                        "page": meta.get("page"),
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
        duplicates_by_file = _tally_duplicates_by_file(duplicates_skipped)
        files_summary = _aggregate_files_summary(orders_summary)

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
                "duplicates_by_file": duplicates_by_file,
                "orders_summary": orders_summary,
                "files_summary": files_summary,
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
            "duplicates_by_file": duplicates_by_file,
            # Per-order + per-file breakdown so the supervisor response
            # template can render a per-PDF block with sample rows instead
            # of the one-line "wrote N rows" summary.
            "orders_summary": orders_summary,
            "files_summary": files_summary,
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
    "find_or_create_sheet": {
        "func": find_or_create_sheet,
        "description": (
            "Find an existing Google Spreadsheet by exact title (Drive name="
            " match), or create a new one only when no match exists. "
            "Idempotent — use for duplicate-prevention semantics."
        ),
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
    "add_sheet_tab": {
        "func": add_sheet_tab,
        "description": "Idempotently add a new tab to an existing spreadsheet",
    },
    "mirror_tabs": {
        "func": mirror_tabs,
        "description": "Copy all (or filtered) tabs from a source spreadsheet to a target spreadsheet, creating missing tabs and optionally clearing existing data",
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
    "ensure_headers": {
        "func": ensure_headers,
        "description": "Idempotent header writer/validator — writes row 1 if empty, no-ops if it matches, errors on mismatch unless force=true",
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

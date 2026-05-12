"""
pdf_extractor.py
================
Extract the Item Code / Description / QTY / UOM table from PMRL-style
requisition PDFs (Production Materials Requisition List).

Robustness goals:
- Works across multi-page PDFs where the header is reprinted on each page.
- Works across continuation pages without a header (rare; defensive path).
- Tolerates slight column-name variants ("Qty", "QUANTITY", "UOM", "U/M"...).
- Extracts the VRMSD... pallet identifier and collapses `-N` page suffixes.
- Falls back to a line-by-line regex if pdfplumber finds no tables.

Public entrypoint: `extract(pdf_bytes: bytes) -> dict`.
"""

from __future__ import annotations

import io
import re
from collections import Counter
from typing import Any, Dict, List, Optional

import pdfplumber

# Canonical column roles and the cell-text synonyms we accept for each.
# A table whose header row matches >= _MIN_ROLES_MATCHED of these roles is
# considered "our" item table.
_COL_SYNONYMS: Dict[str, List[str]] = {
    "item_code": [
        "item code", "item no", "item number", "code", "sku",
        "material code", "material no", "part no", "part number",
    ],
    "description": [
        "item description", "description", "item desc", "product",
        "particulars", "details", "item name", "product description",
    ],
    "qty": [
        "qty", "quantity", "qty.", "amount", "count",
        "qty ordered", "order qty",
    ],
    "uom": [
        "uom", "unit", "u.o.m", "u/m", "unit of measure", "uom.",
    ],
}

_MIN_ROLES_MATCHED = 3  # Item Code + Qty + UOM (or Description) is enough

# Pallet identifier: VRMSD... possibly followed by `-N` page suffix
_PALLET_ID_RE = re.compile(r"VRMSD[A-Z0-9]+(?:-\d+)?", re.IGNORECASE)

# Item-code shape used to recognize continuation rows on header-less pages
_ITEM_CODE_RE = re.compile(r"^[A-Z]{2,5}\d{6,}$")

# Fallback row regex: ITEMCODE DESCRIPTION... QTY UOM DATE
_FALLBACK_ROW_RE = re.compile(
    r"^([A-Z]{2,5}\d{6,})\s+(.+?)\s+(\d+(?:\.\d+)?)\s+(\S+)\s+\d{1,2}/\d{1,2}/\d{2,4}\s*$",
    re.MULTILINE,
)


def _norm(value: Any) -> str:
    """Lowercase, strip non-alphanumeric, collapse spaces. Used for header
    matching: 'Qty.' -> 'qty', 'U.O.M' -> 'uom'."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", str(value).lower())).strip()


def _match_header_row(header: List[Any]) -> Optional[Dict[str, int]]:
    """Map each role to a column index in `header` using `_COL_SYNONYMS`.

    Returns `{role: col_index}` if at least `_MIN_ROLES_MATCHED` roles match,
    else `None`.
    """
    role_to_idx: Dict[str, int] = {}
    norm_synonyms = {
        role: {_norm(s) for s in syns} for role, syns in _COL_SYNONYMS.items()
    }
    for idx, cell in enumerate(header):
        token = _norm(cell)
        if not token:
            continue
        for role, syns in norm_synonyms.items():
            if role in role_to_idx:
                continue
            if token in syns:
                role_to_idx[role] = idx
                break
    return role_to_idx if len(role_to_idx) >= _MIN_ROLES_MATCHED else None


def _coerce_qty(value: Any) -> Optional[float]:
    """Parse strings like '10.00', '1,200', '12'. Returns `None` for empty
    or non-numeric input (footer/blank rows)."""
    if value is None:
        return None
    s = str(value).strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _clean_cell(value: Any) -> str:
    """Strip and collapse internal newlines. pdfplumber sometimes wraps long
    cells with embedded '\\n' from the visual line break."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\n", " ")).strip()


def _extract_rows_from_table(
    table: List[List[Any]],
    column_map: Dict[str, int],
    skip_header: bool = True,
) -> List[Dict[str, Any]]:
    """Yield item dicts for each row that has a numeric qty. Skips blanks
    and footer rows."""
    out: List[Dict[str, Any]] = []
    iter_rows = table[1:] if skip_header else table
    for row in iter_rows:
        if not row:
            continue

        def cell(role: str) -> Any:
            idx = column_map.get(role)
            if idx is None or idx >= len(row):
                return None
            return row[idx]

        qty = _coerce_qty(cell("qty"))
        if qty is None:
            continue  # not a data row

        item_code = _clean_cell(cell("item_code"))
        description = _clean_cell(cell("description"))
        uom = _clean_cell(cell("uom"))

        if not item_code and not description:
            continue  # entirely empty data row

        out.append({
            "itemCode": item_code,
            "description": description,
            "qty": qty,
            "uom": uom,
        })
    return out


def _extract_pallet_id(full_text: str) -> Optional[str]:
    """Scan all text for VRMSD codes, strip '-N' page suffixes, and return
    the most common prefix (handles multi-page docs cleanly)."""
    matches = _PALLET_ID_RE.findall(full_text or "")
    if not matches:
        return None
    stripped = [re.sub(r"-\d+$", "", m).upper() for m in matches]
    return Counter(stripped).most_common(1)[0][0]


def _fallback_text_regex(text: str, warnings: List[str]) -> List[Dict[str, Any]]:
    """Last-resort parser when pdfplumber finds no tables. Looks for lines
    shaped like `ITEMCODE DESCRIPTION QTY UOM DATE`."""
    rows: List[Dict[str, Any]] = []
    for m in _FALLBACK_ROW_RE.finditer(text or ""):
        qty_val = _coerce_qty(m.group(3))
        if qty_val is None:
            continue
        rows.append({
            "itemCode": m.group(1),
            "description": m.group(2).strip(),
            "qty": qty_val,
            "uom": m.group(4),
        })
    if rows:
        warnings.append("Used text-regex fallback because no tables were detected")
    return rows


def extract(pdf_bytes: bytes) -> Dict[str, Any]:
    """Extract items + pallet ID from a single PMRL-style PDF.

    Args:
        pdf_bytes: Raw PDF file bytes.

    Returns:
        {
            "success":  True if >=1 item was extracted,
            "palletId": "VRMSDSF26427" or None,
            "pages":    int,
            "items":    list of {itemCode, description, qty, uom},
            "warnings": list of human-readable warning strings,
            "rawText":  the full extracted text (used by the fallback path),
        }
    """
    warnings: List[str] = []
    items: List[Dict[str, Any]] = []
    full_text_parts: List[str] = []
    page_count = 0

    prev_col_count: Optional[int] = None
    prev_column_map: Optional[Dict[str, int]] = None

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            text = page.extract_text() or ""
            full_text_parts.append(text)

            tables = page.extract_tables() or []
            page_had_match = False

            for table in tables:
                if not table or not table[0]:
                    continue

                column_map = _match_header_row(table[0])
                if column_map:
                    items.extend(_extract_rows_from_table(table, column_map, skip_header=True))
                    prev_col_count = len(table[0])
                    prev_column_map = column_map
                    page_had_match = True
                    continue

                # Header-less continuation table: same column count as the
                # last accepted table, and the first cell of the first row
                # already looks like an item code.
                if (
                    prev_column_map
                    and prev_col_count
                    and len(table[0]) == prev_col_count
                ):
                    code_idx = prev_column_map.get("item_code", 0)
                    first_cell = _clean_cell(table[0][code_idx] if code_idx < len(table[0]) else "")
                    if _ITEM_CODE_RE.match(first_cell):
                        items.extend(_extract_rows_from_table(
                            table, prev_column_map, skip_header=False,
                        ))
                        page_had_match = True

            if not page_had_match:
                warnings.append(
                    f"No item table detected on page {page.page_number}"
                )

    full_text = "\n".join(full_text_parts)

    if not items:
        items = _fallback_text_regex(full_text, warnings)

    pallet_id = _extract_pallet_id(full_text)

    return {
        "success": len(items) > 0,
        "palletId": pallet_id,
        "pages": page_count,
        "items": items,
        "warnings": warnings,
        "rawText": full_text,
    }

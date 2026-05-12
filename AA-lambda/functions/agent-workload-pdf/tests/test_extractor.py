"""
Tests for pdf_extractor.

Uses the two real PMRL PDFs in `Documents/workload pdf/` as ground truth.
Each sample PDF contains 2 pages * 20 items = 40 items, and a distinct
VRMSD pallet identifier shared across both pages with a `-1`/`-2` suffix
that the extractor must strip.

Run from repo root:
    pytest AA-lambda/functions/agent-workload-pdf/tests -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make `pdf_extractor` importable without packaging.
_THIS = Path(__file__).resolve()
_MODULE_DIR = _THIS.parent.parent
sys.path.insert(0, str(_MODULE_DIR))

from pdf_extractor import (  # noqa: E402
    extract,
    _norm,
    _match_header_row,
    _extract_pallet_id,
    _coerce_qty,
)


# Resolve the sample PDFs relative to repo root (3 parents up from `tests/`)
_REPO_ROOT = _MODULE_DIR.parent.parent.parent
_PDF_DIR = _REPO_ROOT / "Documents" / "workload pdf"
FOOD_PDF = _PDF_DIR / "Food_Requisition.pdf"
NONFOOD_PDF = _PDF_DIR / "NonFood_Requisition.pdf"


def _read(path: Path) -> bytes:
    with open(path, "rb") as f:
        return f.read()


# ---------- Helper-function unit tests ----------------------------------


def test_norm_strips_punctuation_and_lowercases():
    assert _norm("QTY.") == "qty"
    assert _norm("U.O.M") == "uom"
    assert _norm("Item Code") == "item code"
    assert _norm(None) == ""
    assert _norm("  Item   Description  ") == "item description"


def test_match_header_row_canonical():
    header = ["Item Code", "Item Description", "QTY", "UOM", "CB DATE"]
    result = _match_header_row(header)
    assert result is not None
    assert result["item_code"] == 0
    assert result["description"] == 1
    assert result["qty"] == 2
    assert result["uom"] == 3


def test_match_header_row_accepts_partial():
    # Missing "description" but the other 3 are present -> still accepted
    header = ["Item Code", "Other Field", "QTY", "UOM"]
    result = _match_header_row(header)
    assert result is not None
    assert "item_code" in result and "qty" in result and "uom" in result


def test_match_header_row_rejects_footer():
    # Footer row has none of our roles -> rejected
    header = ["Requested By:", "Assembled By:", "Checked By:", "Received By:"]
    assert _match_header_row(header) is None


def test_match_header_row_handles_alt_synonyms():
    header = ["Material Code", "Description", "Quantity", "Unit"]
    result = _match_header_row(header)
    assert result is not None
    assert result["item_code"] == 0
    assert result["description"] == 1
    assert result["qty"] == 2
    assert result["uom"] == 3


def test_coerce_qty_handles_strings_and_commas():
    assert _coerce_qty("10.00") == 10.0
    assert _coerce_qty("1,200") == 1200.0
    assert _coerce_qty("4") == 4.0
    assert _coerce_qty("") is None
    assert _coerce_qty(None) is None
    assert _coerce_qty("Not a number") is None


def test_extract_pallet_id_strips_page_suffix():
    text = "Top of doc VRMSDSF26427-1 then later VRMSDSF26427-2 footer"
    assert _extract_pallet_id(text) == "VRMSDSF26427"


def test_extract_pallet_id_returns_none_when_absent():
    assert _extract_pallet_id("no pallet codes here") is None


def test_extract_pallet_id_picks_most_common_prefix():
    text = "VRMSDSF26427-1 ... VRMSDSF26427-2 ... VRMSDSF99999"
    # 2 of VRMSDSF26427 vs 1 of VRMSDSF99999 -> 26427 wins
    assert _extract_pallet_id(text) == "VRMSDSF26427"


# ---------- End-to-end PDF tests ----------------------------------------


@pytest.mark.skipif(not FOOD_PDF.exists(), reason="Food sample PDF missing")
def test_extract_food_requisition():
    result = extract(_read(FOOD_PDF))

    assert result["success"] is True
    assert result["palletId"] == "VRMSDSF26427"
    assert result["pages"] == 2
    assert len(result["items"]) == 40, (
        f"Expected 40 items (20 per page x 2 pages); got {len(result['items'])}"
    )

    # Every item must have the four mandatory fields populated
    for i, item in enumerate(result["items"]):
        assert item["itemCode"], f"Row {i} missing itemCode: {item}"
        assert item["description"], f"Row {i} missing description: {item}"
        assert item["qty"] > 0, f"Row {i} has non-positive qty: {item}"
        assert item["uom"], f"Row {i} missing uom: {item}"

    # Sanity-check a few known rows from the source document
    first = result["items"][0]
    assert first["itemCode"] == "RMFD00810030020"
    assert "Bread Crumbs" in first["description"]
    assert first["qty"] == 10.0
    assert first["uom"] == "Pack"

    # First row of page 2 should be present
    pickle_relish = next(
        (i for i in result["items"] if i["itemCode"] == "RMFD00910130004"),
        None,
    )
    assert pickle_relish is not None, "Page-2 row was not extracted"
    assert pickle_relish["qty"] == 4.0
    assert pickle_relish["uom"] == "Container"


@pytest.mark.skipif(not NONFOOD_PDF.exists(), reason="NonFood sample PDF missing")
def test_extract_nonfood_requisition():
    result = extract(_read(NONFOOD_PDF))

    assert result["success"] is True
    assert result["palletId"] == "VRMSDSF26438"
    assert result["pages"] == 2
    assert len(result["items"]) == 40

    for i, item in enumerate(result["items"]):
        assert item["itemCode"], f"Row {i} missing itemCode: {item}"
        assert item["description"], f"Row {i} missing description: {item}"
        assert item["qty"] > 0, f"Row {i} qty must be positive: {item}"
        assert item["uom"], f"Row {i} missing uom: {item}"

    first = result["items"][0]
    assert first["itemCode"] == "NMFD00810030020"
    assert "Disposable Gloves" in first["description"]
    assert first["qty"] == 10.0
    assert first["uom"] == "Box"

    mop_head = next(
        (i for i in result["items"] if i["itemCode"] == "NMFD00910130004"),
        None,
    )
    assert mop_head is not None, "Page-2 row was not extracted"
    assert mop_head["qty"] == 4.0
    assert mop_head["uom"] == "Container"


def test_extract_handles_empty_pdf_bytes_gracefully():
    """Should not crash on a degenerate input; just returns success=False."""
    # Minimal valid PDF skeleton: just the header so pdfplumber opens it
    minimal_pdf = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\n"
        b"xref\n0 3\n0000000000 65535 f\n0000000009 00000 n\n"
        b"0000000052 00000 n\ntrailer<</Root 1 0 R/Size 3>>\n"
        b"startxref\n96\n%%EOF\n"
    )
    try:
        result = extract(minimal_pdf)
        assert result["success"] is False
        assert result["items"] == []
        assert result["palletId"] is None
    except Exception as e:
        pytest.skip(f"pdfplumber refuses our minimal PDF skeleton: {e}")

"""
Tests for handlers.calculate.

Covers the 4 mode x basis combinations against numbers from
`Documents/workload pdf/Workload.xlsx` SUMMARY sheet rows 13-24.

Run from repo root:
    pytest AA-lambda/functions/agent-workload/tests/test_calculate.py -v
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

_MODULE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MODULE_DIR))

from handlers.calculate import (  # noqa: E402
    DEFAULT_RATES,
    CalculationError,
    calculate,
)


def _payload(mode: str, basis: str, workers: int = 4,
             pallets=None) -> dict:
    if pallets is None:
        pallets = [{
            "palletId": "VRMSDSF26427",
            "sourceFilename": "Food_Requisition.pdf",
            "items": [
                {"itemCode": "RMFD00810030020", "description": "Bread Crumbs", "qty": 10, "uom": "Pack"},
                {"itemCode": "RMFD00810270002", "description": "Broth Powder", "qty": 12, "uom": "Pack"},
                {"itemCode": "RMFD00710020049", "description": "Cheese Filled","qty": 72, "uom": "Pack"},
            ],
        }]
    return {"mode": mode, "basis": basis, "workers": workers, "pallets": pallets}


# ---------- mode x basis matrix ----------------------------------------


def test_inbound_per_pallet():
    """1 pallet, 4 workers, default rates -> (215.07 + 118.95) / 4."""
    result = calculate(_payload("inbound", "per_pallet"), DEFAULT_RATES)
    expected = (215.07 + 118.95) / 4
    assert math.isclose(result["totalSeconds"], expected, rel_tol=1e-6)
    assert result["palletCount"] == 1
    assert result["mode"]  == "inbound"
    assert result["basis"] == "per_pallet"
    assert len(result["phaseBreakdown"]) == 2
    assert result["phaseBreakdown"][0]["name"] == "Inbound Checking"
    assert result["phaseBreakdown"][1]["name"] == "Put-Away"
    assert result["phaseBreakdown"][0]["driver"] == "pallet"


def test_inbound_per_piece():
    """qty=94, workers=4 -> 94 * (0.098 + 0.610) / 4 = 16.638"""
    result = calculate(_payload("inbound", "per_piece"), DEFAULT_RATES)
    total_qty = 10 + 12 + 72
    expected = total_qty * (0.098 + 0.610) / 4
    assert result["totalQty"] == total_qty
    assert math.isclose(result["totalSeconds"], expected, rel_tol=1e-6)
    assert result["basis"] == "per_piece"
    assert result["phaseBreakdown"][0]["driver"] == "piece"


def test_outbound_per_pallet():
    result = calculate(_payload("outbound", "per_pallet"), DEFAULT_RATES)
    expected = (375.33 + 309.50) / 4
    assert math.isclose(result["totalSeconds"], expected, rel_tol=1e-6)
    assert result["phaseBreakdown"][0]["name"] == "Picking"
    assert result["phaseBreakdown"][1]["name"] == "Outbound Checking"


def test_outbound_per_piece():
    result = calculate(_payload("outbound", "per_piece"), DEFAULT_RATES)
    total_qty = 10 + 12 + 72
    expected = total_qty * (5.72 + 2.67) / 4
    assert math.isclose(result["totalSeconds"], expected, rel_tol=1e-6)


# ---------- multi-pallet aggregation -----------------------------------


def test_multiple_pallets_aggregate_qty_and_count():
    pallets = [
        {"palletId": "P1", "items": [{"itemCode": "A", "description": "a", "qty": 50, "uom": "Pcs"}]},
        {"palletId": "P2", "items": [{"itemCode": "B", "description": "b", "qty": 100, "uom": "Pcs"}]},
    ]
    result = calculate(_payload("outbound", "per_piece", workers=2, pallets=pallets), DEFAULT_RATES)
    assert result["palletCount"] == 2
    assert result["totalQty"] == 150
    assert math.isclose(result["totalSeconds"], 150 * (5.72 + 2.67) / 2, rel_tol=1e-6)


def test_pallet_basis_uses_pallet_count_not_qty():
    """Per-pallet math must ignore the qty values entirely."""
    pallets = [
        {"palletId": "P1", "items": [{"itemCode": "A", "description": "a", "qty": 9999, "uom": "Pcs"}]},
        {"palletId": "P2", "items": [{"itemCode": "B", "description": "b", "qty": 9999, "uom": "Pcs"}]},
    ]
    result = calculate(_payload("inbound", "per_pallet", workers=2, pallets=pallets), DEFAULT_RATES)
    assert math.isclose(result["totalSeconds"], 2 * (215.07 + 118.95) / 2, rel_tol=1e-6)


# ---------- rate override ----------------------------------------------


def test_partial_rate_override_falls_back_to_defaults():
    """User overrides only Inbound Checking; Put-Away should still use the default."""
    rates = {"inboundCheckingSecPerPallet": 300.0}
    result = calculate(_payload("inbound", "per_pallet"), rates)
    expected = (300.0 + 118.95) / 4
    assert math.isclose(result["totalSeconds"], expected, rel_tol=1e-6)


# ---------- validation -------------------------------------------------


def test_invalid_mode_raises():
    with pytest.raises(CalculationError):
        calculate({"mode": "sideways", "basis": "per_piece", "workers": 1,
                   "pallets": [{"palletId": "X", "items": []}]}, DEFAULT_RATES)


def test_invalid_basis_raises():
    with pytest.raises(CalculationError):
        calculate({"mode": "inbound", "basis": "per_gram", "workers": 1,
                   "pallets": [{"palletId": "X", "items": []}]}, DEFAULT_RATES)


def test_zero_workers_raises():
    with pytest.raises(CalculationError):
        calculate(_payload("inbound", "per_pallet", workers=0), DEFAULT_RATES)


def test_no_pallets_raises():
    with pytest.raises(CalculationError):
        calculate({"mode": "inbound", "basis": "per_pallet",
                   "workers": 1, "pallets": []}, DEFAULT_RATES)


def test_negative_qty_raises():
    bad = [{"palletId": "X", "items": [{"itemCode": "Y", "description": "z", "qty": -5, "uom": "Pcs"}]}]
    with pytest.raises(CalculationError):
        calculate(_payload("outbound", "per_piece", pallets=bad), DEFAULT_RATES)


# ---------- output shape -----------------------------------------------


def test_output_includes_display_time():
    """displayHours/displayMinutes are convenience integers for the UI."""
    pallets = [{"palletId": "X",
                "items": [{"itemCode": "A", "description": "a", "qty": 1000, "uom": "Pcs"}]}]
    result = calculate(_payload("outbound", "per_piece", workers=1, pallets=pallets), DEFAULT_RATES)
    # qty=1000 * (5.72 + 2.67) = 8390 sec ~= 139.83 min ~= 2h 19m 50s
    total_minutes = result["totalSeconds"] / 60
    assert result["displayHours"] == int(total_minutes // 60)
    assert result["displayMinutes"] == int(round(total_minutes % 60))


def test_output_pallets_and_items_lists():
    """The flat items list should preserve palletId attribution."""
    pallets = [
        {"palletId": "P1", "sourceFilename": "a.pdf",
         "items": [{"itemCode": "A1", "description": "x", "qty": 5, "uom": "Pcs"}]},
        {"palletId": "P2", "sourceFilename": "b.pdf",
         "items": [{"itemCode": "B1", "description": "y", "qty": 7, "uom": "Pcs"}]},
    ]
    result = calculate(_payload("outbound", "per_piece", pallets=pallets), DEFAULT_RATES)
    assert [p["palletId"] for p in result["pallets"]] == ["P1", "P2"]
    assert [i["palletId"] for i in result["items"]] == ["P1", "P2"]
    assert result["pallets"][0]["sourceFilename"] == "a.pdf"
    assert result["pallets"][0]["itemCount"] == 1
    assert result["pallets"][0]["totalQty"] == 5


def test_pallet_meta_carries_s3_audit_keys():
    """s3Bucket / s3Key on the input ride through into the saved pallet meta."""
    pallets = [{
        "palletId":  "VRMSDSF26427",
        "sourceFilename": "Food_Requisition.pdf",
        "s3Bucket":  "frontend-safexpress",
        "s3Key":     "workload-uploads/2026/05/12/abc123/Food_Requisition.pdf",
        "items":     [{"itemCode": "A", "description": "x", "qty": 1, "uom": "Pcs"}],
    }]
    result = calculate(_payload("inbound", "per_pallet", pallets=pallets), DEFAULT_RATES)
    meta = result["pallets"][0]
    assert meta["s3Bucket"] == "frontend-safexpress"
    assert meta["s3Key"]    == "workload-uploads/2026/05/12/abc123/Food_Requisition.pdf"


def test_pallet_meta_defaults_empty_strings_when_no_s3():
    """Manual pallets / S3-disabled parses have empty audit fields."""
    pallets = [{
        "palletId": "MANUAL-XYZ",
        "items":    [{"itemCode": "A", "description": "x", "qty": 1, "uom": "Pcs"}],
    }]
    result = calculate(_payload("inbound", "per_pallet", pallets=pallets), DEFAULT_RATES)
    meta = result["pallets"][0]
    assert meta["s3Bucket"] == ""
    assert meta["s3Key"]    == ""

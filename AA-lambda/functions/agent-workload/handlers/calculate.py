"""
calculate.py
============
Pure-function workload calculator. Shared between the Lambda runtime and
the local Flask dev shim.

Inputs (from the frontend `Calculate` button):
- mode:    "inbound" | "outbound"   (tab the user is on)
- basis:   "per_pallet" | "per_piece" (basis toggle inside the tab)
- workers: int >= 1
- pallets: list of {palletId, sourceFilename?, items: [{itemCode, description, qty, uom}]}
- rates:   {inboundCheckingSecPerPallet, inboundCheckingSecPerPiece, ...}
           (8 keys; usually fetched from `workload-config`)

Output:
- {totalSeconds, totalMinutes, totalHours, displayHours, displayMinutes,
   palletCount, totalQty, numberOfWorkers, mode, basis, phaseBreakdown,
   items, pallets}

`phaseBreakdown` is a list of dicts the frontend's results panel renders:
    [
        {"name": "Inbound Checking",
         "driver": "pallet" | "piece",
         "driverValue": <int>,
         "ratePerUnit": <float seconds>,
         "timeSeconds": <float>},
        ...
    ]

The math is deliberately simple and easy to audit against the Workload.xlsx
SUMMARY sheet: `time = (driver_value * rate) / workers` per phase, then the
phase totals are summed for the tab's grand total.
"""

from __future__ import annotations

from typing import Any, Dict, List

# Phase definitions keyed by mode + basis. The rate_key fields point into
# the 8-key config blob written by handlers/config.py.
_PHASE_SETS: Dict[str, Dict[str, List[Dict[str, str]]]] = {
    "inbound": {
        "per_pallet": [
            {"name": "Inbound Checking", "rate_key": "inboundCheckingSecPerPallet"},
            {"name": "Put-Away",          "rate_key": "putAwaySecPerPallet"},
        ],
        "per_piece": [
            {"name": "Inbound Checking", "rate_key": "inboundCheckingSecPerPiece"},
            {"name": "Put-Away",          "rate_key": "putAwaySecPerPiece"},
        ],
    },
    "outbound": {
        "per_pallet": [
            {"name": "Picking",            "rate_key": "pickingSecPerPallet"},
            {"name": "Outbound Checking",  "rate_key": "outboundCheckingSecPerPallet"},
        ],
        "per_piece": [
            {"name": "Picking",            "rate_key": "pickingSecPerPiece"},
            {"name": "Outbound Checking",  "rate_key": "outboundCheckingSecPerPiece"},
        ],
    },
}

# Defaults pulled from Documents/workload pdf/Workload.xlsx SUMMARY rows
# 13-24. Standard time = normal time * (1 + 5% allowance). Stored centrally
# so both `calculate.py` and the seed script agree on the canonical numbers.
DEFAULT_RATES: Dict[str, float] = {
    "inboundCheckingSecPerPallet":  215.07,
    "inboundCheckingSecPerPiece":     0.098,
    "putAwaySecPerPallet":          118.95,
    "putAwaySecPerPiece":             0.610,
    "pickingSecPerPallet":          375.33,
    "pickingSecPerPiece":             5.72,
    "outboundCheckingSecPerPallet": 309.50,
    "outboundCheckingSecPerPiece":    2.67,
    "allowanceFactor":                0.05,
}


class CalculationError(ValueError):
    """Raised when the input shape or values are invalid."""


def _validate_mode(mode: str) -> str:
    mode = (mode or "").lower().strip()
    if mode not in _PHASE_SETS:
        raise CalculationError(
            f"Invalid mode {mode!r}; expected one of {list(_PHASE_SETS)}"
        )
    return mode


def _validate_basis(basis: str) -> str:
    basis = (basis or "").lower().strip()
    if basis not in ("per_pallet", "per_piece"):
        raise CalculationError(
            f"Invalid basis {basis!r}; expected per_pallet or per_piece"
        )
    return basis


def _coerce_pos_int(value: Any, name: str) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError) as e:
        raise CalculationError(f"{name} must be an integer, got {value!r}") from e
    if v < 1:
        raise CalculationError(f"{name} must be >= 1, got {v}")
    return v


def _coerce_pos_float(value: Any, name: str) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as e:
        raise CalculationError(f"{name} must be a number, got {value!r}") from e
    if v < 0:
        raise CalculationError(f"{name} must be >= 0, got {v}")
    return v


def _summarize_pallets(pallets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Collapse the pallet list into the aggregates the calculator needs:
    pallet count, total qty across all items, flat items list."""
    pallet_count = len(pallets)
    total_qty = 0.0
    flat_items: List[Dict[str, Any]] = []
    pallet_meta: List[Dict[str, Any]] = []

    for pallet in pallets:
        pid = pallet.get("palletId") or "MANUAL"
        items = pallet.get("items") or []
        item_qty = 0.0
        for item in items:
            qty = _coerce_pos_float(item.get("qty", 0), "items[].qty")
            item_qty += qty
            flat_items.append({
                "itemCode":    str(item.get("itemCode", "") or ""),
                "description": str(item.get("description", "") or ""),
                "qty":         qty,
                "uom":         str(item.get("uom", "") or ""),
                "palletId":    pid,
            })
        total_qty += item_qty
        # Preserve the s3 audit-trail handle when the parse Lambda uploaded
        # the PDF. Stored as plain strings so the workload-history record
        # carries a stable reference even after the 1-day lifecycle rule
        # eventually deletes the object.
        pallet_meta.append({
            "palletId":       pid,
            "sourceFilename": pallet.get("sourceFilename") or "",
            "itemCount":      len(items),
            "totalQty":       item_qty,
            "s3Bucket":       str(pallet.get("s3Bucket") or ""),
            "s3Key":          str(pallet.get("s3Key") or ""),
        })

    return {
        "palletCount": pallet_count,
        "totalQty":    total_qty,
        "items":       flat_items,
        "pallets":     pallet_meta,
    }


def calculate(payload: Dict[str, Any], rates: Dict[str, Any]) -> Dict[str, Any]:
    """Run the workload math against a request payload + a rates blob.

    Args:
        payload: The frontend's request body. Required keys: `mode`, `basis`,
            `workers`, `pallets`. Optional: `notes`, `createdBy`.
        rates:   A dict with at least the 8 rate keys from `DEFAULT_RATES`.
            Missing keys fall back to `DEFAULT_RATES` so the calculator
            still works on a partial config.

    Returns:
        A serializable dict (see module docstring).
    """
    mode    = _validate_mode(payload.get("mode"))
    basis   = _validate_basis(payload.get("basis"))
    workers = _coerce_pos_int(payload.get("workers"), "workers")
    pallets = payload.get("pallets") or []
    if not isinstance(pallets, list):
        raise CalculationError("pallets must be a list")
    if not pallets:
        raise CalculationError("at least one pallet (PDF or manual) is required")

    summary  = _summarize_pallets(pallets)
    phaseset = _PHASE_SETS[mode][basis]

    # Pick the driver value once: pallets if per-pallet, qty if per-piece.
    if basis == "per_pallet":
        driver_value = float(summary["palletCount"])
        driver_label = "pallet"
    else:
        driver_value = float(summary["totalQty"])
        driver_label = "piece"

    # Merge user-supplied rates over the defaults so a partial config still
    # works. Frontend can also pass per-call rate overrides via the same dict.
    effective_rates = {**DEFAULT_RATES, **(rates or {})}

    phase_breakdown: List[Dict[str, Any]] = []
    total_seconds = 0.0
    for phase in phaseset:
        rate = _coerce_pos_float(effective_rates.get(phase["rate_key"], 0), phase["rate_key"])
        seconds = (driver_value * rate) / workers
        total_seconds += seconds
        phase_breakdown.append({
            "name":          phase["name"],
            "driver":        driver_label,
            "driverValue":   driver_value,
            "ratePerUnit":   rate,
            "rateKey":       phase["rate_key"],
            "timeSeconds":   seconds,
            "timeMinutes":   seconds / 60.0,
        })

    total_minutes = total_seconds / 60.0
    total_hours   = total_minutes / 60.0
    display_hours   = int(total_minutes // 60)
    display_minutes = int(round(total_minutes % 60))

    return {
        "mode":             mode,
        "basis":            basis,
        "numberOfWorkers":  workers,
        "palletCount":      summary["palletCount"],
        "totalQty":         summary["totalQty"],
        "totalSeconds":     total_seconds,
        "totalMinutes":     total_minutes,
        "totalHours":       total_hours,
        "displayHours":     display_hours,
        "displayMinutes":   display_minutes,
        "phaseBreakdown":   phase_breakdown,
        "pallets":          summary["pallets"],
        "items":            summary["items"],
    }

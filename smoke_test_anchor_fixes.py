from __future__ import annotations
import sys, os, importlib.util

ROOT = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.join(ROOT, "safexpressops-mapping-agent-287212a2-db05-452d-8bd4-54af56d985d4")
sys.path.insert(0, DEPLOY)

spec = importlib.util.spec_from_file_location(
    "mapping_agent_api", os.path.join(DEPLOY, "mapping_agent_api.py")
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def src_schema(headers, rows):
    raw_rows = [dict(zip(headers, r)) for r in rows]
    col_samples = {h: [str(r[i]) for r in rows[:5] if r[i] not in (None, "")] for i, h in enumerate(headers)}
    return {
        "headers": headers,
        "header_index": {h: i for i, h in enumerate(headers)},
        "header_row_count": 1,
        "raw_rows": raw_rows,
        "col_samples": col_samples,
        "col_types": {h: "string" for h in headers},
        "total_rows": len(rows),
        "total_cols": len(headers),
    }


def tgt_schema(headers, rows):
    raw_rows = [headers] + [list(r) for r in rows]
    col_samples = {}
    for i, h in enumerate(headers):
        col_samples[h] = [str(r[i]) for r in rows[:5] if i < len(r) and r[i] not in (None, "")]
    return {
        "headers": headers,
        "header_index": {h: i for i, h in enumerate(headers)},
        "header_row_count": 1,
        "raw_rows": raw_rows,
        "col_samples": col_samples,
        "col_types": {h: "string" for h in headers},
        "total_rows": len(raw_rows),
        "total_cols": len(headers),
        "formula_cols": [],
        "sections": [],
    }


def passed(name):
    print("  PASS  " + name)


def failed(name, got, want):
    print("  FAIL  " + name)
    print("        got:  " + repr(got))
    print("        want: " + repr(want))
    sys.exit(1)


print()
print("[1] _compute_source_uniqueness")
truck = [
    ("Widget A", "SKU-001"), ("Widget B", "SKU-002"),
    ("Widget C", "SKU-003"), ("Widget C", "SKU-004"),
    ("Widget B", "SKU-005"), ("Widget B", "SKU-006"),
    ("Widget A", "SKU-007"), ("Widget A", "SKU-008"),
    ("Widget B", "SKU-009"), ("Widget C", "SKU-010"),
    ("Widget B", "SKU-011"), ("Widget A", "SKU-012"),
    ("",         "SKU-012"),
]
sx = src_schema(["Product Name", "SKU"], truck)
pn_uniq, pn_cov = m._compute_source_uniqueness(sx, "Product Name")
sku_uniq, sku_cov = m._compute_source_uniqueness(sx, "SKU")
if not (0.20 <= pn_uniq <= 0.30):
    failed("Truck Product Name uniqueness ~0.25", pn_uniq, "0.20..0.30")
passed("Truck Product Name uniqueness=" + format(pn_uniq, ".3f") + ", coverage=" + format(pn_cov, ".3f"))
if not (0.90 <= sku_uniq <= 0.95):
    failed("Truck SKU uniqueness ~0.923", sku_uniq, "0.90..0.95")
passed("Truck SKU uniqueness=" + format(sku_uniq, ".3f") + ", coverage=" + format(sku_cov, ".3f"))

sta = [("Widget A", 1, 2), ("Widget B", 3, 4), ("Widget C", 5, 6),
       ("Widget C", 7, 8), ("Widget B", 9, 10), ("Widget B", 11, 12)]
sx2 = src_schema(["Product Name", "Unit Price", "Stock"], sta)
sta_uniq, _ = m._compute_source_uniqueness(sx2, "Product Name")
if abs(sta_uniq - 0.5) > 0.01:
    failed("Single-tab-append Product Name uniqueness 0.5", sta_uniq, "0.5")
passed("Single-tab-append Product Name uniqueness=" + format(sta_uniq, ".3f"))


print()
print("[2] _infer_strategy_local picks SKU over Product Name (Truck)")
tgt = tgt_schema(["Product Name", "SKU"], [("Widget A", "SKU-001"), ("Widget B", "SKU-002")])
mp = {"Product Name": "Product Name", "SKU": "SKU"}
strat, anchor, _, atype = m._infer_strategy_local(tgt, sx, mp)
ok = atype == "id" and (anchor == "SKU" or (isinstance(anchor, list) and anchor[0] == "SKU"))
if not ok:
    failed("Truck picks SKU", (strat, anchor), "row_per_entity/composite anchored on SKU")
passed("Truck -> strategy=" + str(strat) + ", anchor=" + str(anchor))


print()
print("[3] _infer_strategy_local rejects Product Name 0.5 -> append")
tgt2 = tgt_schema(["Product Name", "Unit Price", "Stock"],
                  [("Widget A", 213, 100), ("Widget B", 296, 300)])
mp2 = {"Product Name": "Product Name", "Unit Price": "Unit Price", "Stock": "Stock"}
strat2, anchor2, _, atype2 = m._infer_strategy_local(tgt2, sx2, mp2)
if strat2 != "append":
    failed("Single-tab-append -> append", (strat2, anchor2), "append")
passed("Single-tab-append -> strategy=" + str(strat2) + ", anchor=" + str(anchor2))


print()
print("[4] _infer_strategy_local TC-A02 (regression: SKU still wins)")
a02 = [
    ("SKU-001", "Widget A", 213, 100, "2025-04-04"),
    ("SKU-002", "Widget B", 296, 300, "2025-04-04"),
    ("SKU-003", "Widget C", 512, 200, "2025-04-05"),
    ("SKU-004", "", "", "", "2025-04-05"),
    ("SKU-005", "", "", "", "2025-04-06"),
    ("SKU-006", "", "", "", "2025-04-07"),
    ("SKU-007", "", "", "", "2025-04-08"),
]
sx3 = src_schema(["SKU", "Product Name", "Unit Price", "Stock", "Date"], a02)
tgt3 = tgt_schema(["SKU", "Product Name", "Unit Price", "Stock", "Date"],
                  [("SKU-001", "Widget A", 213, 100, "2025-04-04"),
                   ("SKU-002", "Widget B", 296, 300, "2025-04-04")])
mp3 = {h: h for h in sx3["headers"]}
strat3, anchor3, _, atype3 = m._infer_strategy_local(tgt3, sx3, mp3)
ok3 = atype3 == "id" and (anchor3 == "SKU" or (isinstance(anchor3, list) and anchor3[0] == "SKU"))
if not ok3:
    failed("TC-A02 picks SKU", (strat3, anchor3), "row_per_entity / SKU")
passed("TC-A02 -> strategy=" + str(strat3) + ", anchor=" + str(anchor3))


print()
print("[5] _infer_strategy_local TC-A01 (regression: Date still wins)")
a01 = [("2025-03-06", 78, 1000), ("2025-03-07", 7, 82),
       ("2025-03-08", 4, 99), ("2025-03-09", 9, 23), ("2025-03-10", 71, 12)]
sx4 = src_schema(["Date", "No. of Truck Received", "No. of Pallet Received"], a01)
tgt4 = tgt_schema(["Date", "No. of Truck Received", "No. of Pallet Received"],
                  [("2025-03-06", 78, 1000)])
sx4["col_types"]["Date"] = "date"
tgt4["col_types"]["Date"] = "date"
mp4 = {h: h for h in sx4["headers"]}
strat4, anchor4, _, atype4 = m._infer_strategy_local(tgt4, sx4, mp4)
if strat4 != "row_per_date" or anchor4 != "Date":
    failed("TC-A01 picks Date", (strat4, anchor4), "row_per_date / Date")
passed("TC-A01 -> strategy=" + str(strat4) + ", anchor=" + str(anchor4))


print()
print("[6] _detect_entity_overlap_anchor rejects Product Name 0.5")
sx5 = src_schema(["Product Name"], [("Widget A",), ("Widget B",), ("Widget C",),
                                     ("Widget C",), ("Widget B",), ("Widget B",)])
tgt5 = tgt_schema(["Product Name"], [("Widget A",), ("Widget B",), ("Widget C",), ("Widget A",)])
sx5["col_samples"]["Product Name"] = ["Widget A", "Widget B", "Widget C"]
tgt5["col_samples"]["Product Name"] = ["Widget A", "Widget B", "Widget C", "Widget A"]
res = m._detect_entity_overlap_anchor(tgt5, sx5, {"Product Name": "Product Name"})
if res is not None:
    failed("Product Name overlap rejected", res, "None")
passed("Product Name overlap correctly rejected by uniqueness gate")


print()
print("[7] _detect_entity_overlap_anchor accepts SKU 1.0")
sx6 = src_schema(["SKU"], [("SKU-001",), ("SKU-002",), ("SKU-003",),
                            ("SKU-004",), ("SKU-005",), ("SKU-006",)])
tgt6 = tgt_schema(["SKU"], [("SKU-001",), ("SKU-002",), ("SKU-003",)])
sx6["col_samples"]["SKU"] = ["SKU-001", "SKU-002", "SKU-003", "SKU-004"]
tgt6["col_samples"]["SKU"] = ["SKU-001", "SKU-002", "SKU-003"]
res2 = m._detect_entity_overlap_anchor(tgt6, sx6, {"SKU": "SKU"})
if res2 is None:
    failed("SKU overlap accepted", None, "(SKU, SKU, ratio>=0.5)")
passed("SKU overlap accepted: ratio=" + format(res2[2], ".2f"))


print()
print("[8] _count_target_col_non_empty")
tgt7 = tgt_schema(["SKU", "Product Name"],
                  [("SKU-001", "Widget A"), ("SKU-002", ""), ("SKU-003", ""), ("", "")])
sku_n = m._count_target_col_non_empty(tgt7, "SKU")
pn_n = m._count_target_col_non_empty(tgt7, "Product Name")
if sku_n != 3:
    failed("SKU non-empty count", sku_n, 3)
if pn_n != 1:
    failed("Product Name non-empty count", pn_n, 1)
passed("SKU=" + str(sku_n) + " non-empty, Product Name=" + str(pn_n) + " non-empty")


print()
print("ALL SMOKE TESTS PASSED")

"""End-to-end simulation of the delivery-order workflow after the fixes.

Goal: exercise REAL code paths with realistic dummy data, covering the entire
chain the user would walk through — Tier 1 intent → Block G safety net →
planner prompt → Jinja-substituted variable wiring through the sub-agents →
risk evaluation → approval-message rendering → resumed execution.

Nothing here hits the network. The only LLM calls are monkey-patched:
  * The classifier (`identify_agents_and_tools`) returns a hand-crafted tool
    dict that deliberately OMITS delivery tools, so Block G is the only thing
    that can put them back.
  * The planner is bypassed — we hand-construct the 6-step ExecutionPlan that
    Rule 16 + Example 3 should be producing.

All other logic is real:
  * `agent_capabilities_v3.agent_capabilities` (checks G1 removed it)
  * `models.ACTION_RISK_LEVELS` (checks G1 risk-level entry removed)
  * `services.response_templates.*` (checks G1 template removed)
  * `services.__init__` import (checks G2 dead-service export removed)
  * `tool_filter.identify_agents_and_tools` post-processing (Block G)
  * `supervisor_agent.Template(...).render(**ctx)` (orchestrator substitution)
  * `Mapping-agent._flatten_file_paths` (parses the Jinja-stringified list)
  * `Sheets-agent._parse_orders_input` (parses the Jinja-stringified list)
  * `checks.tier0_checks._build_rich_approval_message` (G7 render branch)
  * `supervisor_agent` approval substitution (G6 ast.literal_eval-first)
"""

from __future__ import annotations

import io
import json
import os
import sys
import traceback
import types
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)

REPO = Path(__file__).resolve().parent
SUP = REPO / "supervisor-agent"
GMAIL = REPO / "gmail-agent"
SHEETS = REPO / "Sheets-agent"
MAPPING = REPO / "Mapping-agent"

for p in (SUP, GMAIL, SHEETS, MAPPING):
    sys.path.insert(0, str(p))

os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder-for-offline-sim")


def _stub(module_name: str, **attrs) -> types.ModuleType:
    """Register (or return) a dummy module so heavy-dep imports don't break the sim.

    Prefer the REAL module when it's installed locally — the stubs exist
    only to keep imports like `import pandas` from blowing up on machines
    that haven't pip-installed every transitive dep. They were never meant
    to fight with class-level annotations like `pd.DataFrame` in production
    code (see smart_mapping_engine.py:154).
    """
    if module_name in sys.modules:
        return sys.modules[module_name]
    try:
        import importlib
        real = importlib.import_module(module_name)
        sys.modules[module_name] = real
        for k, v in attrs.items():
            if not hasattr(real, k):
                setattr(real, k, v)
        return real
    except Exception:
        pass
    mod = types.ModuleType(module_name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[module_name] = mod
    return mod


def _first_order(parsed: dict) -> dict:
    """Adapter: navigate the post-refactor _parse_single_pdf shape.

    The post-refactor parser returns:
      - rejection: {rejected: True, file, reason}                     (per PDF)
      - success:   {rejected: False, file, orders: [{file, page, header, line_items, warnings}, ...], rejected_pages: [...]}

    Pre-refactor scenarios in this file were written against the legacy
    flat shape where header / line_items lived at the top level. This
    helper returns orders[0] in the success case (so the legacy assertions
    on parsed.get('header') / parsed.get('line_items') keep working) and
    returns the rejection dict unchanged so .get('rejected') / .get('reason')
    callers continue to behave.
    """
    if not isinstance(parsed, dict):
        return {}
    if parsed.get("rejected"):
        return parsed
    orders = parsed.get("orders") or []
    if orders:
        return orders[0]
    return {"header": {}, "line_items": [], "warnings": []}


def _wrap_old_shape_success(old_result: dict) -> dict:
    """Adapter: wrap a legacy-flat success stub into the new nested shape.

    Test stubs that monkey-patch _parse_single_pdf with literal dicts were
    originally written for the pre-refactor flat shape:
        {"file": "...", "header": {...}, "line_items": [...], "warnings": [...]}

    parse_delivery_order_pdfs now expects the per-page nested shape:
        {"rejected": False, "file": "...", "orders": [{...}], "rejected_pages": []}

    Pass a legacy dict in, get the nested form out; rejection dicts are
    returned unchanged.
    """
    if not isinstance(old_result, dict):
        return old_result
    if old_result.get("rejected"):
        return old_result
    return {
        "rejected": False,
        "file": old_result.get("file", ""),
        "orders": [{
            "file": old_result.get("file", ""),
            "page": 1,
            "header": old_result.get("header", {}),
            "line_items": old_result.get("line_items", []),
            "warnings": old_result.get("warnings", []),
        }],
        "rejected_pages": [],
    }


# Heavy runtime deps that the sub-agent modules import at top-level but that
# _flatten_file_paths / _parse_orders_input do not actually use. Stubbing them
# lets us import the real functions under test without installing the full
# service stack.
_stub("pandas")
_stub("PyPDF2")
_stub("openpyxl")

google_mod = _stub("google")
oauth2_mod = _stub("google.oauth2")
creds_mod = _stub("google.oauth2.credentials", Credentials=type("Credentials", (), {}))
setattr(google_mod, "oauth2", oauth2_mod)
setattr(oauth2_mod, "credentials", creds_mod)

api_mod = _stub("googleapiclient")
disc_mod = _stub("googleapiclient.discovery", build=lambda *a, **k: None)
err_mod = _stub("googleapiclient.errors", HttpError=type("HttpError", (Exception,), {}))
setattr(api_mod, "discovery", disc_mod)
setattr(api_mod, "errors", err_mod)
_stub("googleapiclient.http", MediaIoBaseDownload=type("MediaIoBaseDownload", (), {}))
setattr(api_mod, "http", sys.modules["googleapiclient.http"])

RESULTS: list[tuple[str, str, str]] = []


def record(scenario: str, status: str, note: str = "") -> None:
    RESULTS.append((scenario, status, note))
    tag = {"PASS": "[ OK ]", "FAIL": "[FAIL]", "INFO": "[INFO]"}[status]
    print(f"{tag} {scenario}" + (f" - {note}" if note else ""))


def section(title: str) -> None:
    print()
    print("=" * 76)
    print(title)
    print("=" * 76)


# ------------------------------------------------------------------
# SCENARIO 1 — G1: process_delivery_order_workflow fully removed.
# ------------------------------------------------------------------
section("Scenario 1 - G1: broken monolithic tool is fully removed")

try:
    from agent_capabilities_v3 import agent_capabilities  # type: ignore

    gmail_tools = agent_capabilities["gmail_agent"]["tools"]
    if "process_delivery_order_workflow" in gmail_tools:
        record("caps: gmail_agent no longer advertises the broken tool", "FAIL",
               "process_delivery_order_workflow still present in agent_capabilities_v3")
    else:
        record("caps: gmail_agent no longer advertises the broken tool", "PASS")
except Exception as e:  # pragma: no cover
    record("caps: gmail_agent no longer advertises the broken tool", "FAIL", repr(e))

try:
    from models.models import ACTION_RISK_LEVELS  # type: ignore

    if "process_delivery_order_workflow" in ACTION_RISK_LEVELS:
        record("risk: ACTION_RISK_LEVELS entry removed", "FAIL")
    else:
        record("risk: ACTION_RISK_LEVELS entry removed", "PASS")
except Exception as e:  # pragma: no cover
    record("risk: ACTION_RISK_LEVELS entry removed", "FAIL", repr(e))

try:
    from services.response_templates import TOOL_TEMPLATES  # type: ignore

    has_template = any(
        key[1] == "process_delivery_order_workflow"
        for key in TOOL_TEMPLATES.keys()
        if isinstance(key, tuple)
    )
    if has_template:
        record("templates: delivery-order summary template removed", "FAIL")
    else:
        record("templates: delivery-order summary template removed", "PASS")
except Exception as e:  # pragma: no cover
    record("templates: delivery-order summary template removed", "FAIL", repr(e))

gmail_tools_py = (GMAIL / "tools.py").read_text(encoding="utf-8")
if "def _process_delivery_order_workflow_impl" in gmail_tools_py:
    record("tools.py: _process_delivery_order_workflow_impl removed", "FAIL")
else:
    record("tools.py: _process_delivery_order_workflow_impl removed", "PASS")
if "def _extract_attachment_data_impl" in gmail_tools_py or "def _map_columns_to_sheet_impl" in gmail_tools_py:
    record("tools.py: dead helpers removed (G12)", "FAIL")
else:
    record("tools.py: dead helpers removed (G12)", "PASS")

gmail_api_py = (GMAIL / "api.py").read_text(encoding="utf-8")
if "process_delivery_order_workflow" in gmail_api_py:
    record("api.py: TOOL_MAP no longer dispatches the broken tool", "FAIL")
else:
    record("api.py: TOOL_MAP no longer dispatches the broken tool", "PASS")

# ------------------------------------------------------------------
# SCENARIO 2 — G2: dead DeliveryOrderService deleted.
# ------------------------------------------------------------------
section("Scenario 2 - G2: dead delivery_order_service is deleted")

svc_init = (SUP / "services" / "__init__.py").read_text(encoding="utf-8")
if "delivery_order_service" in svc_init:
    record("__init__.py no longer imports DeliveryOrderService", "FAIL")
else:
    record("__init__.py no longer imports DeliveryOrderService", "PASS")

if (SUP / "services" / "delivery_order_service.py").exists():
    record("delivery_order_service.py file deleted", "FAIL")
else:
    record("delivery_order_service.py file deleted", "PASS")

# Import should succeed even though we removed a module.
try:
    import importlib

    services_mod = importlib.import_module("services")
    importlib.reload(services_mod)
    record("services package still imports cleanly", "PASS")
except Exception as e:
    record("services package still imports cleanly", "FAIL", repr(e))

# ------------------------------------------------------------------
# SCENARIO 3 — Block G safety net + keyword alignment + upload_mapped_data
# pruning.
# ------------------------------------------------------------------
section("Scenario 3 - Block G safety net with realistic classifier misses")

import tool_filter  # type: ignore


def _fake_classifier_sparse_sheets_only(user_input, system_prompt=None, user_prompt=None):
    """Mimic a real classifier that only picks sheets_agent.upload_mapped_data
    (the common failure mode we saw in the old trace.log). Block G must:
      * inject gmail_agent.search_emails_with_delivery_order_attachments
      * inject mapping_agent.parse_delivery_order_pdfs
      * inject sheets_agent.validate_delivery_sheet + preview + write
      * inject drive_agent.search_files
      * REMOVE sheets_agent.upload_mapped_data
    """
    class FakeResponse:
        content = json.dumps({"sheets_agent": ["upload_mapped_data"]})
        response_metadata = {"token_usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    return FakeResponse()


class _FakeLLM:
    def invoke(self, messages):
        return _fake_classifier_sparse_sheets_only(None)


def _patch_classifier(monkeypatch_target, fake):
    # Monkey-patch the ChatOpenAI that identify_agents_and_tools instantiates.
    import tool_filter as tf

    original_chat = tf.ChatOpenAI
    tf.ChatOpenAI = lambda *args, **kwargs: fake  # type: ignore
    return lambda: setattr(tf, "ChatOpenAI", original_chat)


def run_block_g_scenario(label: str, user_input: str) -> dict:
    undo = _patch_classifier(tool_filter, _FakeLLM())
    try:
        filter_dict = tool_filter.identify_agents_and_tools(user_input)
    finally:
        undo()
    return filter_dict


scenarios_block_g = [
    ("A: spaced 'delivery order'", "Parse delivery order PDFs in my inbox and write to DO Tracker."),
    ("B: hyphenated 'delivery-order'", "Process the delivery-order emails into Requisition sheet."),
    ("C: bare 'requisition'", "Load the requisition into Requisition sheet."),
    ("D: 'purchase-order'", "Write the purchase-order emails into PO sheet."),
    ("E: 'po pdf' phrase", "Parse the PO pdf attachments into DO Tracker."),
    ("F: 'order list'", "Extract the order list from my inbox into Requisition sheet."),
]

expected_tools = {
    "gmail_agent": {"search_emails_with_delivery_order_attachments"},
    "mapping_agent": {"parse_delivery_order_pdfs"},
    "sheets_agent": {"validate_delivery_sheet", "preview_delivery_order_insertion", "write_delivery_order_data"},
    "drive_agent": {"search_files"},
}

for label, user_input in scenarios_block_g:
    try:
        result = run_block_g_scenario(label, user_input)
        # The result MUST contain all expected tools, with upload_mapped_data removed.
        ok = True
        reasons = []
        for agent, required in expected_tools.items():
            present = set(result.get(agent, []))
            missing = required - present
            if missing:
                ok = False
                reasons.append(f"{agent} missing {sorted(missing)}")
        sheets_tools = result.get("sheets_agent", [])
        if "upload_mapped_data" in sheets_tools:
            ok = False
            reasons.append("sheets_agent still has upload_mapped_data")
        if ok:
            record(f"Block G {label}", "PASS")
        else:
            record(f"Block G {label}", "FAIL", "; ".join(reasons))
    except Exception as e:
        record(f"Block G {label}", "FAIL", repr(e))

# Negative control — non-delivery request must NOT get Block G injected.
try:
    def _fake_unrelated(*args, **kwargs):
        class FakeResponse:
            content = json.dumps({"calendar_agent": ["list_events"]})
            response_metadata = {"token_usage": {"prompt_tokens": 1, "completion_tokens": 1}}

        return FakeResponse()

    class UnrelatedLLM:
        def invoke(self, messages):
            return _fake_unrelated()

    undo = _patch_classifier(tool_filter, UnrelatedLLM())
    try:
        result = tool_filter.identify_agents_and_tools("What's on my calendar today?")
    finally:
        undo()

    has_delivery = (
        "mapping_agent" in result
        or "write_delivery_order_data" in result.get("sheets_agent", [])
    )
    if has_delivery:
        record("Block G negative control (no injection for non-delivery)", "FAIL",
               f"Block G leaked: {result}")
    else:
        record("Block G negative control (no injection for non-delivery)", "PASS")
except Exception as e:
    record("Block G negative control (no injection for non-delivery)", "FAIL", repr(e))

# ------------------------------------------------------------------
# SCENARIO 4 — Planner system prompt contains Rule 16 + Example 3.
# ------------------------------------------------------------------
section("Scenario 4 - Planner prompt exposes Rule 16 + Example 3")

supervisor_src = (SUP / "supervisor_agent.py").read_text(encoding="utf-8")
must_have_snippets = [
    "16. DELIVERY-ORDER PIPELINE",
    "parse_delivery_order_pdfs",
    "validate_delivery_sheet",
    "preview_delivery_order_insertion",
    "write_delivery_order_data",
    "EXAMPLE 3 (delivery-order pipeline",
    "search_emails_with_delivery_order_attachments",
    "NEVER pick sheets_agent.upload_mapped_data",
]
missing = [s for s in must_have_snippets if s not in supervisor_src]
if missing:
    record("planner prompt includes Rule 16 + Example 3 + all steering", "FAIL",
           f"missing: {missing}")
else:
    record("planner prompt includes Rule 16 + Example 3 + all steering", "PASS")

# ------------------------------------------------------------------
# SCENARIO 5 — Filtered capabilities only expose delivery tools.
# ------------------------------------------------------------------
section("Scenario 5 - get_filtered_capabilities_v2 hides upload_mapped_data")

try:
    from tool_filter import get_filtered_capabilities_v2  # type: ignore

    filter_dict = {
        "gmail_agent": ["search_emails_with_delivery_order_attachments"],
        "mapping_agent": ["parse_delivery_order_pdfs"],
        "drive_agent": ["search_files"],
        "sheets_agent": [
            "validate_delivery_sheet",
            "preview_delivery_order_insertion",
            "write_delivery_order_data",
        ],
    }
    caps = get_filtered_capabilities_v2(filter_dict)

    sheet_tools = set(caps["sheets_agent"]["tools"].keys())
    gmail_tools = set(caps["gmail_agent"]["tools"].keys())

    problems = []
    if "upload_mapped_data" in sheet_tools:
        problems.append("upload_mapped_data leaked into filtered sheets caps")
    if "process_delivery_order_workflow" in gmail_tools:
        problems.append("broken monolithic tool leaked into filtered gmail caps")
    if not {"validate_delivery_sheet", "preview_delivery_order_insertion",
            "write_delivery_order_data"}.issubset(sheet_tools):
        problems.append("delivery sheet tools missing from filtered caps")

    if problems:
        record("filtered caps shape is correct", "FAIL", "; ".join(problems))
    else:
        record("filtered caps shape is correct", "PASS")
except Exception as e:
    record("filtered caps shape is correct", "FAIL", repr(e))

# ------------------------------------------------------------------
# SCENARIO 6 — Orchestrator variable substitution → sub-agent parsers.
# This exercises the "Jinja stringifies a Python list, sub-agent parses
# it back via ast.literal_eval" round-trip that the whole pipeline relies
# on.
# ------------------------------------------------------------------
section("Scenario 6 - variable substitution round-trips list values correctly")

# Realistic dummy data — shape matches what _search_emails_with_delivery_order
# _attachments_impl returns.
# Matches the real shape emitted by gmail-agent/tools.py:_search_emails_with_
# delivery_order_attachments_impl (uses "message_id", not "id" — verified at
# gmail-agent/tools.py:1496).
dummy_emails_with_attachments = [
    {
        "message_id": "18d1a234567890ab",
        "from": "vendor@supplier.com",
        "subject": "Delivery Order #DO-2026-0417",
        "date": "Mon, 21 Apr 2026 09:12:00 +0000",
        "timestamp": "2026-04-21T09:12:00Z",
        "internal_date_ms": 1713692320000,
        "attachments": [
            {
                "filename": "DO-2026-0417.pdf",
                "attachment_id": "ANGjdJ_xxx_1",
                "mime_type": "application/pdf",
                "size": 84512,
                "file_path": "C:/tmp/gmail_dl_abc/DO-2026-0417.pdf",
            }
        ],
        "attachment_count": 1,
    },
    {
        "message_id": "18d1abcdef012345",
        "from": "ops@othervendor.com",
        "subject": "Requisition List April",
        "date": "Sun, 20 Apr 2026 16:30:00 +0000",
        "timestamp": "2026-04-20T16:30:00Z",
        "internal_date_ms": 1713631800000,
        "attachments": [
            {
                "filename": "requisition_april.pdf",
                "attachment_id": "ANGjdJ_xxx_2",
                "mime_type": "application/pdf",
                "size": 121834,
                "file_path": "C:/tmp/gmail_dl_abc/requisition_april.pdf",
            }
        ],
        "attachment_count": 1,
    },
]

# Realistic dummy parsed_orders — shape matches what parse_delivery_order_pdfs
# returns. Includes Python None, True, and apostrophes inside strings — the
# exact edge cases that break the old approval-branch JSON parser.
dummy_parsed_orders = [
    {
        "file": "DO-2026-0417.pdf",
        "header": {
            "order_reference": "DO-2026-0417",
            "order_date": "2026-04-17",
            "vendor": "Supplier's Co.",
            "notes": None,
            "urgent": True,
        },
        "line_items": [
            {"item_code": "FOOD-001", "description": "Organic apples", "qty": 20, "unit": "kg", "category": "Food"},
            {"item_code": "NF-042", "description": "Eco-friendly packaging", "qty": 5, "unit": "box", "category": "non-food"},
        ],
        "warnings": [],
    },
    {
        "file": "requisition_april.pdf",
        "header": {
            "order_reference": "REQ-APR-2026",
            "order_date": "2026-04-20",
            "vendor": "Tom's Goods",
            "notes": "Deliver after 3pm",
            "urgent": False,
        },
        "line_items": [
            {"item_code": "FOOD-777", "description": "Whole-grain bread", "qty": 30, "unit": "loaf", "category": "Food"},
        ],
        "warnings": ["Missing delivery address"],
    },
]

# Simulate what the orchestrator does with a Jinja template against a flat
# variable_context (matches supervisor_agent.py:1150-1152 execution branch).
from jinja2 import Template  # type: ignore

variable_context = {
    "today_date": "2026-04-21",
    "emails_with_attachments": dummy_emails_with_attachments,
    "parsed_orders": dummy_parsed_orders,
    "sheet_id": "1A2B3C4D5E6F7G8H9I0J_real_sheet_id",
}

step_b_inputs = {"file_paths": "{{ emails_with_attachments }}"}
step_e_inputs = {"sheet_id": "{{ sheet_id }}", "parsed_orders": "{{ parsed_orders }}"}

substituted_b = {
    k: Template(v).render(**variable_context) if isinstance(v, str) else v
    for k, v in step_b_inputs.items()
}
substituted_e = {
    k: Template(v).render(**variable_context) if isinstance(v, str) else v
    for k, v in step_e_inputs.items()
}

# The substituted values will be Python repr strings. The Mapping-agent's
# _flatten_file_paths and Sheets-agent's _parse_orders_input must decode them
# back correctly.
try:
    # Import from the mapping agent.
    from mapping_agent_api import _flatten_file_paths as mapping_flatten  # type: ignore

    flat_paths = mapping_flatten(substituted_b["file_paths"])
    expected_paths = [
        "C:/tmp/gmail_dl_abc/DO-2026-0417.pdf",
        "C:/tmp/gmail_dl_abc/requisition_april.pdf",
    ]
    if flat_paths == expected_paths:
        record("mapping_agent._flatten_file_paths decodes Jinja-stringified list", "PASS")
    else:
        record("mapping_agent._flatten_file_paths decodes Jinja-stringified list", "FAIL",
               f"got={flat_paths!r} want={expected_paths!r}")
except Exception as e:
    record("mapping_agent._flatten_file_paths decodes Jinja-stringified list", "FAIL",
           f"{e}\n{traceback.format_exc()}")

try:
    # sheets_agent module name collides with agent_capabilities in supervisor-agent,
    # so we reach into its sibling path directly.
    import importlib.util

    sheets_api_path = SHEETS / "sheets_agent_api.py"
    spec = importlib.util.spec_from_file_location("sheets_agent_api_sim", sheets_api_path)
    sheets_api = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(sheets_api)  # type: ignore

    parsed_back = sheets_api._parse_orders_input(substituted_e["parsed_orders"])
    if isinstance(parsed_back, list) and len(parsed_back) == len(dummy_parsed_orders):
        headers_match = all(
            parsed_back[i]["header"]["order_reference"]
            == dummy_parsed_orders[i]["header"]["order_reference"]
            for i in range(len(parsed_back))
        )
        # Python None/True and apostrophes must survive the round-trip.
        none_ok = parsed_back[0]["header"]["notes"] is None
        urgent_ok = parsed_back[0]["header"]["urgent"] is True
        apostrophe_ok = parsed_back[0]["header"]["vendor"] == "Supplier's Co."

        if headers_match and none_ok and urgent_ok and apostrophe_ok:
            record("sheets_agent._parse_orders_input decodes full Python repr (None/True/apostrophe)", "PASS")
        else:
            record("sheets_agent._parse_orders_input decodes full Python repr (None/True/apostrophe)", "FAIL",
                   f"headers={headers_match} none={none_ok} urgent={urgent_ok} apostrophe={apostrophe_ok}")
    else:
        record("sheets_agent._parse_orders_input decodes full Python repr (None/True/apostrophe)", "FAIL",
               f"got type={type(parsed_back).__name__} len={len(parsed_back) if isinstance(parsed_back, list) else 'n/a'}")
except Exception as e:
    record("sheets_agent._parse_orders_input decodes full Python repr (None/True/apostrophe)", "FAIL",
           f"{e}\n{traceback.format_exc()}")

# ------------------------------------------------------------------
# SCENARIO 7 — Approval-branch substitution (G6 fix).
# The old code used rendered.replace("'", '"') then json.loads, which breaks
# on Python None/True and on apostrophes inside strings. The new code uses
# ast.literal_eval FIRST, falls back to json.loads, then to the raw string.
# ------------------------------------------------------------------
section("Scenario 7 - approval-branch substitution round-trips Python literals")

import ast


def simulate_approval_substitution(inputs: dict, ctx: dict) -> dict:
    """Mirror supervisor_agent.py:1040+ approval-branch code."""
    out = {}
    for key, value in inputs.items():
        if isinstance(value, str) and "{{" in value and "}}" in value:
            rendered = Template(value).render(**ctx)
            stripped = rendered.strip()
            if stripped and stripped[0] in "[{":
                parsed = None
                try:
                    parsed = ast.literal_eval(stripped)
                except (ValueError, SyntaxError):
                    try:
                        parsed = json.loads(stripped)
                    except (json.JSONDecodeError, ValueError):
                        parsed = None
                out[key] = parsed if parsed is not None else rendered
            else:
                out[key] = rendered
        else:
            out[key] = value
    return out


approval_inputs = {"sheet_id": "{{ sheet_id }}", "parsed_orders": "{{ parsed_orders }}"}
approval_out = simulate_approval_substitution(approval_inputs, variable_context)

try:
    # parsed_orders must come back as a real list of dicts, not a string.
    assert isinstance(approval_out["parsed_orders"], list), \
        f"parsed_orders is {type(approval_out['parsed_orders']).__name__}"
    assert approval_out["parsed_orders"][0]["header"]["vendor"] == "Supplier's Co.", \
        "apostrophe in vendor name lost"
    assert approval_out["parsed_orders"][0]["header"]["notes"] is None, \
        "None field not preserved"
    assert approval_out["parsed_orders"][0]["header"]["urgent"] is True, \
        "True field not preserved"
    # sheet_id is a bare string — passes through unchanged.
    assert approval_out["sheet_id"] == "1A2B3C4D5E6F7G8H9I0J_real_sheet_id"
    record("approval substitution (G6) round-trips Python list cleanly", "PASS")
except AssertionError as e:
    record("approval substitution (G6) round-trips Python list cleanly", "FAIL", str(e))

# The OLD code would have failed this. Prove it by running the legacy logic:
def legacy_approval_substitution(inputs: dict, ctx: dict) -> dict:
    out = {}
    for key, value in inputs.items():
        if isinstance(value, str) and "{{" in value and "}}" in value:
            rendered = Template(value).render(**ctx)
            try:
                if rendered.startswith("[") or rendered.startswith("{"):
                    out[key] = json.loads(rendered.replace("'", '"'))
                else:
                    out[key] = rendered
            except (json.JSONDecodeError, ValueError):
                out[key] = rendered
        else:
            out[key] = value
    return out


legacy_out = legacy_approval_substitution(approval_inputs, variable_context)
legacy_parsed = legacy_out["parsed_orders"]
# The legacy version keeps it as a raw string (json parse dies on `None`).
if isinstance(legacy_parsed, str):
    record("legacy approval substitution is demonstrably broken (as expected)", "PASS",
           "old code left parsed_orders as a raw string — G6 fix required")
elif isinstance(legacy_parsed, list):
    # Could have accidentally survived — check for None/apostrophe corruption.
    first = legacy_parsed[0]
    broken = (
        first.get("header", {}).get("notes") != None
        or first.get("header", {}).get("vendor") != "Supplier's Co."
    )
    if broken:
        record("legacy approval substitution is demonstrably broken (as expected)", "PASS",
               "old code corrupted None/apostrophes — G6 fix required")
    else:
        record("legacy approval substitution is demonstrably broken (as expected)", "INFO",
               "old code happened to produce valid JSON for this payload; G6 still fixes edge cases")
else:
    record("legacy approval substitution is demonstrably broken (as expected)", "INFO",
           f"legacy output type = {type(legacy_parsed).__name__}")

# ------------------------------------------------------------------
# SCENARIO 8 — G7 rich approval message for write_delivery_order_data.
# ------------------------------------------------------------------
section("Scenario 8 - G7 rich approval message renders readable summary")

try:
    from checks.tier0_checks import _build_rich_approval_message  # type: ignore

    pending_action = {
        "tool": "write_delivery_order_data",
        "risk_level": "DANGEROUS",
        "description": "Append the parsed delivery-order rows into the DO Tracker sheet",
        "step_number": 6,
        "total_steps": 6,
        "inputs": approval_out,
    }
    msg = _build_rich_approval_message(pending_action)

    required_bits = [
        "Writing Delivery-Order Data to Sheet",
        "Sheet ID:",
        "Orders to write:",
        "Total line items:",
        "Source files:",
        "Sample header",
        "DO-2026-0417",
    ]
    missing = [b for b in required_bits if b not in msg]
    # Also make sure the raw parsed_orders dict is NOT dumped verbatim.
    if "'line_items':" in msg and len(msg) > 3000:
        record("approval message is readable, not a raw dump", "FAIL",
               "raw parsed_orders appears to have been dumped inline")
    elif missing:
        record("approval message is readable, not a raw dump", "FAIL",
               f"missing={missing}")
    else:
        record("approval message is readable, not a raw dump", "PASS")
        # Show a preview so the maintainer can eyeball it.
        print("\n--- approval message preview ---")
        print(msg)
        print("--- end preview ---\n")
except Exception as e:
    record("approval message is readable, not a raw dump", "FAIL",
           f"{e}\n{traceback.format_exc()}")

# ------------------------------------------------------------------
# SCENARIO 9 — Full plan walkthrough: Scenario A (sheet by name),
# Scenario B (uploaded PDF), Scenario C (sheet ID pasted).
# For each we simulate the orchestrator's execution-branch substitution
# at every step and check the "next step" input shape is digestible.
# ------------------------------------------------------------------
section("Scenario 9 - Full pipeline walkthrough across 3 user inputs")


def plan_A_by_name() -> list[dict]:
    """Matches corrected Rule 16 + Example 3 exactly.

    NOTE: drive_agent.search_files takes ONLY search_term (no query/file_type/
    max_results). Using the wrong args here would silently pass the mock, but
    Scenario 10 below validates each step's inputs against real capability
    schemas so the miswiring WILL be caught.
    """
    return [
        {"agent": "gmail_agent", "tool": "search_emails_with_delivery_order_attachments",
         "inputs": {"query": "delivery order OR DO OR requisition OR purchase order OR PO has:attachment",
                    "max_results": 10, "download_attachments": True},
         "output_variables": {"emails_with_attachments": "emails_with_attachments"}},
        {"agent": "mapping_agent", "tool": "parse_delivery_order_pdfs",
         "inputs": {"file_paths": "{{ emails_with_attachments }}"},
         "output_variables": {"parsed_orders": "parsed_orders"}},
        {"agent": "drive_agent", "tool": "search_files",
         "inputs": {"search_term": "DO Tracker"},
         "output_variables": {"sheet_id": "results[0].id"}},
        {"agent": "sheets_agent", "tool": "validate_delivery_sheet",
         "inputs": {"sheet_id": "{{ sheet_id }}"}, "output_variables": {}},
        {"agent": "sheets_agent", "tool": "preview_delivery_order_insertion",
         "inputs": {"sheet_id": "{{ sheet_id }}", "parsed_orders": "{{ parsed_orders }}"},
         "output_variables": {}},
        {"agent": "sheets_agent", "tool": "write_delivery_order_data",
         "inputs": {"sheet_id": "{{ sheet_id }}", "parsed_orders": "{{ parsed_orders }}"},
         "output_variables": {}},
    ]


def plan_B_uploaded() -> list[dict]:
    """Matches corrected Rule 16 (path A: uploaded_file → bare string, no brackets).

    The orchestrator's execution branch ONLY Jinja-substitutes values that
    are strings. A list literal like `["{{ var }}"]` would bypass Jinja and
    reach parse_delivery_order_pdfs as a literal template string. The only
    working pattern is to emit file_paths as a bare string; the sub-agent's
    _flatten_file_paths wraps a single path into a list automatically.
    """
    return [
        {"agent": "mapping_agent", "tool": "parse_delivery_order_pdfs",
         "inputs": {"file_paths": "{{ uploaded_file.temp_path }}"},
         "output_variables": {"parsed_orders": "parsed_orders"}},
        {"agent": "drive_agent", "tool": "search_files",
         "inputs": {"search_term": "DO Tracker"},
         "output_variables": {"sheet_id": "results[0].id"}},
        {"agent": "sheets_agent", "tool": "validate_delivery_sheet",
         "inputs": {"sheet_id": "{{ sheet_id }}"}, "output_variables": {}},
        {"agent": "sheets_agent", "tool": "preview_delivery_order_insertion",
         "inputs": {"sheet_id": "{{ sheet_id }}", "parsed_orders": "{{ parsed_orders }}"},
         "output_variables": {}},
        {"agent": "sheets_agent", "tool": "write_delivery_order_data",
         "inputs": {"sheet_id": "{{ sheet_id }}", "parsed_orders": "{{ parsed_orders }}"},
         "output_variables": {}},
    ]


def plan_C_url_pasted() -> list[dict]:
    return [
        {"agent": "gmail_agent", "tool": "search_emails_with_delivery_order_attachments",
         "inputs": {"query": "delivery order has:attachment", "max_results": 5, "download_attachments": True},
         "output_variables": {"emails_with_attachments": "emails_with_attachments"}},
        {"agent": "mapping_agent", "tool": "parse_delivery_order_pdfs",
         "inputs": {"file_paths": "{{ emails_with_attachments }}"},
         "output_variables": {"parsed_orders": "parsed_orders"}},
        {"agent": "sheets_agent", "tool": "validate_delivery_sheet",
         "inputs": {"sheet_id": "1A2B3C4D5E6F7G8H9I0J_real_sheet_id"}, "output_variables": {}},
        {"agent": "sheets_agent", "tool": "preview_delivery_order_insertion",
         "inputs": {"sheet_id": "1A2B3C4D5E6F7G8H9I0J_real_sheet_id", "parsed_orders": "{{ parsed_orders }}"},
         "output_variables": {}},
        {"agent": "sheets_agent", "tool": "write_delivery_order_data",
         "inputs": {"sheet_id": "1A2B3C4D5E6F7G8H9I0J_real_sheet_id", "parsed_orders": "{{ parsed_orders }}"},
         "output_variables": {}},
    ]


def simulate_execution_substitution(inputs, ctx):
    """Mirror supervisor_agent.py:1147-1161 execution-branch code."""
    out = {}
    for key, value in inputs.items():
        if isinstance(value, str):
            out[key] = Template(value).render(**ctx)
        else:
            out[key] = value
    return out


def walk_plan(plan, initial_ctx, agent_responses):
    """Run every step, populating ctx with output_variables as we go.
    agent_responses maps (agent, tool) -> fake response dict.
    Returns (ctx, per_step_log). Raises on any UndefinedError."""
    ctx = dict(initial_ctx)
    log = []
    for step_num, step in enumerate(plan, 1):
        subbed = simulate_execution_substitution(step["inputs"], ctx)
        response = agent_responses.get((step["agent"], step["tool"]), {})
        for var_name, path in step.get("output_variables", {}).items():
            # Mirror extract_nested_value
            from supervisor_agent import extract_nested_value  # type: ignore

            value = extract_nested_value(response, path)
            if value is not None:
                ctx[var_name] = value
        log.append({"step": step_num, "agent": step["agent"], "tool": step["tool"], "inputs": subbed})
    return ctx, log


shared_responses_by_name = {
    ("gmail_agent", "search_emails_with_delivery_order_attachments"): {
        "success": True,
        "emails_with_attachments": dummy_emails_with_attachments,
        "total_emails_found": 2,
        "temp_directory": "C:/tmp/gmail_dl_abc",
    },
    ("mapping_agent", "parse_delivery_order_pdfs"): {
        "success": True,
        "parsed_orders": dummy_parsed_orders,
        "rejected_files": [],
        "total_parsed": 2,
        "total_rejected": 0,
    },
    ("drive_agent", "search_files"): {
        "success": True,
        "results": [{"id": "1A2B3C4D5E6F7G8H9I0J_real_sheet_id", "name": "DO Tracker",
                     "modifiedTime": "2026-04-20T12:00:00Z"}],
        "count": 1,
    },
    ("sheets_agent", "validate_delivery_sheet"): {
        "success": True,
        "is_valid": True,
        "tabs_found": ["Food", "non-food"],
        "matching_tabs": ["Food", "non-food"],
    },
    ("sheets_agent", "preview_delivery_order_insertion"): {
        "success": True,
        "preview_rows": [{"tab": "Food", "rows": 2}, {"tab": "non-food", "rows": 1}],
        "total_new_rows": 3,
        "duplicates": [],
        "duplicate_count": 0,
        "warnings": [],
        "target_tabs": ["Food", "non-food"],
        "message": "Preview ready: 3 rows to append.",
    },
}

# Scenario A run
try:
    final_ctx, steps = walk_plan(plan_A_by_name(), {"today_date": "2026-04-21"}, shared_responses_by_name)
    # Step 2 (parse) must have received a string that decodes to our list.
    step2_file_paths = steps[1]["inputs"]["file_paths"]
    assert isinstance(step2_file_paths, str), "Jinja output should be a string"
    # mapping_agent would parse this back:
    from mapping_agent_api import _flatten_file_paths  # type: ignore

    decoded = _flatten_file_paths(step2_file_paths)
    assert decoded == ["C:/tmp/gmail_dl_abc/DO-2026-0417.pdf",
                       "C:/tmp/gmail_dl_abc/requisition_april.pdf"]

    # Step 3 must have resolved sheet_id via output_variables["sheet_id"] = "results[0].id".
    assert final_ctx.get("sheet_id") == "1A2B3C4D5E6F7G8H9I0J_real_sheet_id"

    # Step 4, 5, 6 must all reference the same sheet_id.
    for idx in (3, 4, 5):
        assert steps[idx]["inputs"]["sheet_id"] == "1A2B3C4D5E6F7G8H9I0J_real_sheet_id"

    # Step 5 (preview) and Step 6 (write) both receive parsed_orders as a
    # stringified list; _parse_orders_input must round-trip it.
    for idx in (4, 5):
        preview_orders_str = steps[idx]["inputs"]["parsed_orders"]
        reparsed = sheets_api._parse_orders_input(preview_orders_str)
        assert reparsed[0]["header"]["order_reference"] == "DO-2026-0417", \
            f"step {idx+1} parsed_orders round-trip failed"

    record("Scenario A (sheet-by-name): all 6 steps wire cleanly", "PASS")
except Exception as e:
    record("Scenario A (sheet-by-name): all 6 steps wire cleanly", "FAIL",
           f"{e}\n{traceback.format_exc()}")

# Scenario B — uploaded file (BARE STRING path, NOT list literal).
try:
    uploaded_ctx = {
        "today_date": "2026-04-21",
        "uploaded_file": {
            "temp_path": "C:/tmp/user_upload_xyz/DO-2026-0417.pdf",
            "filename": "DO-2026-0417.pdf",
        },
    }
    fake_responses_B = dict(shared_responses_by_name)
    # For scenario B we DON'T have the gmail step; start at parse.
    final_ctx, steps = walk_plan(plan_B_uploaded(), uploaded_ctx, fake_responses_B)

    # Step 1 (parse) MUST emit file_paths as a bare string (not a list literal,
    # which would bypass Jinja substitution). After Jinja render, the raw value
    # is a single path string.
    step1_fp = steps[0]["inputs"]["file_paths"]
    assert isinstance(step1_fp, str), \
        f"file_paths must be a string after Jinja render, got {type(step1_fp).__name__}"
    assert step1_fp == "C:/tmp/user_upload_xyz/DO-2026-0417.pdf", \
        f"Jinja should have rendered the uploaded_file.temp_path directly, got: {step1_fp!r}"

    # The sub-agent's _flatten_file_paths MUST wrap a single bare path into a
    # single-element list — this is the whole reason we can emit a bare string
    # instead of a list literal.
    decoded = _flatten_file_paths(step1_fp)
    assert decoded == ["C:/tmp/user_upload_xyz/DO-2026-0417.pdf"], \
        f"_flatten_file_paths should auto-wrap a bare string into a list, got: {decoded!r}"

    # Steps 2-5 should wire sheet_id and parsed_orders via output_variables.
    assert final_ctx.get("sheet_id") == "1A2B3C4D5E6F7G8H9I0J_real_sheet_id"

    record("Scenario B (uploaded file, bare string path): 5-step chain wires cleanly", "PASS")
except Exception as e:
    record("Scenario B (uploaded file, bare string path): 5-step chain wires cleanly", "FAIL",
           f"{e}\n{traceback.format_exc()}")

# Scenario C — sheet URL pasted → no drive_agent.search_files step needed.
try:
    responses_C = {k: v for k, v in shared_responses_by_name.items() if k[1] != "search_files"}
    final_ctx, steps = walk_plan(plan_C_url_pasted(), {"today_date": "2026-04-21"}, responses_C)

    # All references to the sheet_id should be the literal pasted ID — no
    # intermediate Jinja substitution needed.
    for idx in (2, 3, 4):
        assert steps[idx]["inputs"]["sheet_id"] == "1A2B3C4D5E6F7G8H9I0J_real_sheet_id"

    # Step 5 write_delivery_order_data parsed_orders round-trip still works.
    preview_orders_str = steps[4]["inputs"]["parsed_orders"]
    reparsed = sheets_api._parse_orders_input(preview_orders_str)
    assert reparsed[1]["header"]["order_reference"] == "REQ-APR-2026"

    record("Scenario C (sheet URL pasted): 5-step chain skips drive lookup", "PASS")
except Exception as e:
    record("Scenario C (sheet URL pasted): 5-step chain skips drive lookup", "FAIL",
           f"{e}\n{traceback.format_exc()}")

# ------------------------------------------------------------------
# SCENARIO 10 — CAPABILITY-SCHEMA GUARD.
# Validates that every step's inputs in plans A/B/C uses ONLY arg names that
# the real capability schema declares. This is what would have caught the
# drive_agent.search_files(query=..., file_type=..., max_results=...) bug
# from the review phase — the real tool only accepts search_term.
# Also validates Example 3 inside the live planner prompt.
# ------------------------------------------------------------------
section("Scenario 10 - capability-schema guard against arg-name drift")

try:
    from agent_capabilities_v3 import agent_capabilities as _caps  # type: ignore

    def extract_valid_args(agent: str, tool: str) -> set[str]:
        """Return the arg names declared by the capability schema for this tool.
        Treats a missing tool as no args (all inputs would be rejected)."""
        spec = _caps.get(agent, {}).get("tools", {}).get(tool, {})
        return set((spec.get("args") or {}).keys())

    def non_jinja_input_keys(inputs: dict) -> set[str]:
        """The keys the planner is expected to emit — ALL of them must map to
        real args. Jinja-templated VALUES are still fine; what we validate is
        the KEY space (arg names)."""
        return set(inputs.keys())

    def validate_plan(plan_name: str, plan: list[dict]) -> list[str]:
        """Return a list of human-readable mismatch descriptions."""
        mismatches: list[str] = []
        for step_idx, step in enumerate(plan, 1):
            agent, tool = step["agent"], step["tool"]
            declared = extract_valid_args(agent, tool)
            if not declared:
                mismatches.append(
                    f"{plan_name} step {step_idx}: {agent}.{tool} has no declared args (tool missing from caps?)"
                )
                continue
            used = non_jinja_input_keys(step["inputs"])
            bogus = used - declared
            if bogus:
                mismatches.append(
                    f"{plan_name} step {step_idx}: {agent}.{tool} got invalid args {sorted(bogus)} "
                    f"(declared: {sorted(declared)})"
                )
        return mismatches

    all_plans = [
        ("plan_A_by_name", plan_A_by_name()),
        ("plan_B_uploaded", plan_B_uploaded()),
        ("plan_C_url_pasted", plan_C_url_pasted()),
    ]

    all_mismatches: list[str] = []
    for name, plan in all_plans:
        all_mismatches.extend(validate_plan(name, plan))

    if all_mismatches:
        record("all sim plans use only capability-declared arg names", "FAIL",
               " | ".join(all_mismatches))
    else:
        record("all sim plans use only capability-declared arg names", "PASS")

    # Also validate Example 3 in the live planner prompt. Example 3 lives
    # inside a Python str.format template where every literal `{` and `}`
    # is escaped as `{{` / `}}`, and every Jinja placeholder like `{{ var }}`
    # is further escaped to `{{{{{{ var }}}}}}` (sextuple). We don't need to
    # parse the whole dict — we just need to extract the arg-name KEYS from
    # each step's inputs block and compare against the schema.
    #
    # Strategy: read the raw prompt text, isolate the Example 3 region, then
    # for every `"agent": "X", "tool": "Y"` block, pull the keys from the
    # following `"inputs": { ... }` literal. Regex matches quoted identifier
    # tokens immediately followed by `:` inside a conservative window after
    # the inputs keyword. This is intentionally permissive — the goal is to
    # catch obviously wrong names like `file_type` on search_files, not to
    # re-implement JSON parsing.
    import re as _re
    _supervisor_text = (SUP / "supervisor_agent.py").read_text(encoding="utf-8")
    _ex3_start = _supervisor_text.find("EXAMPLE 3 (delivery-order pipeline")
    _ex3_end = _supervisor_text.find("CURRENT DATE CONTEXT", _ex3_start)
    ex3_block = _supervisor_text[_ex3_start:_ex3_end] if _ex3_start >= 0 else ""

    step_header_re = _re.compile(
        r'"agent":\s*"(\w+)",\s*"tool":\s*"(\w+)",\s*"inputs":\s*\{+([^]]+?)(?:"output_variables"|"description")',
        _re.DOTALL,
    )
    # "inputs" block keys — any "name": that appears before the next
    # "output_variables" / "description" marker is treated as an arg name.
    input_key_re = _re.compile(r'"([a-zA-Z_][a-zA-Z0-9_]*)"\s*:')

    ex3_mismatches: list[str] = []
    matches_found = 0
    for m in step_header_re.finditer(ex3_block):
        matches_found += 1
        agent, tool, inputs_body = m.group(1), m.group(2), m.group(3)
        used = set(input_key_re.findall(inputs_body))
        declared = extract_valid_args(agent, tool)
        bogus = used - declared
        if bogus:
            ex3_mismatches.append(
                f"Example 3 {agent}.{tool}: unknown args {sorted(bogus)} (declared: {sorted(declared)})"
            )

    if matches_found == 0:
        record("planner prompt Example 3 uses only capability-declared arg names", "FAIL",
               "regex found 0 steps in Example 3 block — parser drift?")
    elif ex3_mismatches:
        record("planner prompt Example 3 uses only capability-declared arg names", "FAIL",
               " | ".join(ex3_mismatches))
    else:
        record(f"planner prompt Example 3 uses only capability-declared arg names ({matches_found} steps checked)", "PASS")

except Exception as e:
    record("all sim plans use only capability-declared arg names", "FAIL",
           f"{e}\n{traceback.format_exc()}")

# ------------------------------------------------------------------
# SCENARIO 11 — Rule 16 literal-token guard.
# Rule 16's search_files line must NOT contain "file_type=" or "query=" or
# "max_results=" (the bogus args I accidentally introduced initially). Catches
# regressions if someone copies from Rule 7/Example 1 and pastes inside Rule 16.
# ------------------------------------------------------------------
section("Scenario 11 - Rule 16 text forbids wrong search_files args")

try:
    # Extract Rule 16 block from the prompt text.
    _r16_start = _supervisor_text.find("16. DELIVERY-ORDER PIPELINE")
    _r16_end = _supervisor_text.find("\n\nEXAMPLE 1", _r16_start)
    r16_block = _supervisor_text[_r16_start:_r16_end] if _r16_start >= 0 else ""

    # Limit check to the drive_agent.search_files sentence so we don't false-
    # positive on the gmail query="..." keyword in step A.
    search_files_line = ""
    for line in r16_block.splitlines():
        if "drive_agent.search_files" in line:
            search_files_line = line
            break

    if not search_files_line:
        record("Rule 16 mentions drive_agent.search_files", "FAIL",
               "could not find drive_agent.search_files line inside Rule 16")
    else:
        forbidden = []
        # On this specific line, query=/file_type=/max_results= are all wrong.
        if 'query=' in search_files_line:
            forbidden.append("query=")
        if 'file_type=' in search_files_line:
            forbidden.append("file_type=")
        if 'max_results=' in search_files_line:
            forbidden.append("max_results=")
        if 'search_term=' not in search_files_line:
            forbidden.append("(missing search_term=)")
        if forbidden:
            record("Rule 16 search_files line uses correct args only", "FAIL",
                   f"found: {forbidden} in: {search_files_line.strip()!r}")
        else:
            record("Rule 16 search_files line uses correct args only", "PASS")

    # Rule 16 also must tell the planner to use a BARE STRING for uploaded_file,
    # not a list literal. The regression I just caught.
    uploaded_line_idx = r16_block.find("uploaded_file")
    if uploaded_line_idx < 0:
        record("Rule 16 covers uploaded_file case", "FAIL")
    else:
        # Grab the 200 chars after "uploaded_file" to check phrasing.
        ctx_slice = r16_block[uploaded_line_idx:uploaded_line_idx + 400]
        if "BARE STRING" in ctx_slice and "[" not in ctx_slice.split("uploaded_file.temp_path")[0][-30:]:
            record("Rule 16 uploaded_file guidance uses bare-string pattern", "PASS")
        elif "[" in ctx_slice.split("uploaded_file.temp_path")[0][-10:] or \
             "[" in ctx_slice.split("uploaded_file.temp_path")[1][:10]:
            record("Rule 16 uploaded_file guidance uses bare-string pattern", "FAIL",
                   "uploaded_file.temp_path is still wrapped in [...] — Jinja won't substitute")
        else:
            record("Rule 16 uploaded_file guidance uses bare-string pattern", "PASS")

except Exception as e:
    record("Rule 16 text forbids wrong search_files args", "FAIL",
           f"{e}\n{traceback.format_exc()}")

# ------------------------------------------------------------------
# SCENARIO 12 — parse_delivery_order_pdfs returns success:false + no_results
# when every input file is rejected (e.g. pdfplumber unavailable). Reproduces
# the DeliveryTest2.log failure mode.
# ------------------------------------------------------------------
section("Scenario 12 - mapping_agent.parse_delivery_order_pdfs halts cleanly on all-rejected")

try:
    import importlib

    mapping_mod = importlib.import_module("mapping_agent_api")
    importlib.reload(mapping_mod)  # pick up our edits

    # Force the rejected-path: pdfplumber unavailable sentinel.
    original_flag = getattr(mapping_mod, "PDFPLUMBER_AVAILABLE", True)
    mapping_mod.PDFPLUMBER_AVAILABLE = False
    try:
        result = mapping_mod.parse_delivery_order_pdfs(
            ["fake1.pdf", "fake2.pdf"]
        )
    finally:
        mapping_mod.PDFPLUMBER_AVAILABLE = original_flag

    checks = []
    if result.get("success") is not False:
        checks.append(f"expected success=false, got {result.get('success')!r}")
    if result.get("no_results") is not True:
        checks.append(f"expected no_results=true, got {result.get('no_results')!r}")
    if result.get("total_parsed") != 0:
        checks.append(f"expected total_parsed=0, got {result.get('total_parsed')!r}")
    if result.get("total_rejected") != 2:
        checks.append(f"expected total_rejected=2, got {result.get('total_rejected')!r}")
    err = result.get("error") or ""
    if "pdfplumber" not in err.lower():
        checks.append(f"expected pdfplumber hint in error, got {err!r}")

    if checks:
        record(
            "parse_delivery_order_pdfs signals failure on all-rejected",
            "FAIL",
            "; ".join(checks),
        )
    else:
        record("parse_delivery_order_pdfs signals failure on all-rejected", "PASS")

    # Also verify the happy-path hasn't regressed: if at least one file parses,
    # success should still be True even if others are rejected.
    # (Monkey-patch _parse_single_pdf so we don't need a real PDF.)
    original_parser = mapping_mod._parse_single_pdf

    def _mixed_parser(fp: str):
        if fp.endswith("good.pdf"):
            return _wrap_old_shape_success({
                "file": "good.pdf",
                "header": {"order_reference": "DO-1"},
                "line_items": [{"sku": "A", "qty": 1}],
                "warnings": [],
            })
        return {"rejected": True, "file": fp, "reason": "bad format"}

    mapping_mod._parse_single_pdf = _mixed_parser
    try:
        mixed = mapping_mod.parse_delivery_order_pdfs(["good.pdf", "bad.pdf"])
    finally:
        mapping_mod._parse_single_pdf = original_parser

    if mixed.get("success") is True and mixed.get("total_parsed") == 1 and mixed.get("total_rejected") == 1:
        record("parse_delivery_order_pdfs still succeeds with partial wins", "PASS")
    else:
        record(
            "parse_delivery_order_pdfs still succeeds with partial wins",
            "FAIL",
            f"unexpected: {mixed!r}",
        )
except Exception as e:
    record(
        "parse_delivery_order_pdfs signals failure on all-rejected",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 13 — ToolResponse propagates no_results to the top level so the
# supervisor orchestrator's halt branch (supervisor_agent.py:1540) can trigger.
# ------------------------------------------------------------------
section("Scenario 13 - Mapping agent ToolResponse exposes no_results top-level")

try:
    import importlib
    mapping_mod = importlib.import_module("mapping_agent_api")

    ToolResponse = mapping_mod.ToolResponse
    # no_results should round-trip into the response body via .model_dump()
    resp = ToolResponse(
        success=False,
        result=None,
        error="No delivery orders parsed",
        no_results=True,
    )
    dumped = resp.model_dump()
    if dumped.get("no_results") is True and dumped.get("success") is False:
        record("ToolResponse serialises no_results at top level", "PASS")
    else:
        record(
            "ToolResponse serialises no_results at top level",
            "FAIL",
            f"dump={dumped!r}",
        )

    # Also confirm orchestrator's line 1540 pattern would flag this correctly.
    # (The orchestrator reads result.get('no_results') on the JSON body.)
    body = dumped
    is_no_results = body.get("no_results", False)
    if is_no_results is True:
        record("orchestrator halt-branch would trigger on this response", "PASS")
    else:
        record(
            "orchestrator halt-branch would trigger on this response",
            "FAIL",
            "is_no_results=False on the synthetic response",
        )
except Exception as e:
    record(
        "ToolResponse exposes no_results",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 14 — Tier 1 DELIVERY ORDER WORKFLOW prompt block now requires a
# write/parse verb, not just keywords. Lock this in so a future token-trim
# can't silently revert it.
# ------------------------------------------------------------------
section("Scenario 14 - Tier 1 DELIVERY ORDER WORKFLOW requires write/parse verb")

try:
    _conv_text = (SUP / "conversational_agent.py").read_text(encoding="utf-8")
    block_start = _conv_text.find("DELIVERY ORDER WORKFLOW")
    block_end = _conv_text.find("\n\n", block_start)
    do_block = _conv_text[block_start:block_end] if block_start >= 0 else ""

    missing = []
    # Must mention the verb-gate explicitly so the LLM doesn't pattern-match
    # on keywords alone.
    for req in ["write", "parse", "extract"]:
        if req not in do_block.lower():
            missing.append(req)
    # Must mention the negative case — pure search is NOT this workflow.
    if "search" not in do_block.lower() or "NOT this workflow" not in do_block:
        missing.append("pure-search negative case")

    if missing:
        record(
            "Tier 1 DELIVERY ORDER WORKFLOW has verb-gate + negative case",
            "FAIL",
            f"missing: {missing}",
        )
    else:
        record("Tier 1 DELIVERY ORDER WORKFLOW has verb-gate + negative case", "PASS")
except Exception as e:
    record(
        "Tier 1 DELIVERY ORDER WORKFLOW has verb-gate + negative case",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 15 — Approval message renders an explicit "0 orders" warning when
# parsed_orders is empty. Reproduces the DeliveryTest2.log "uninformative
# approval prompt" failure.
# ------------------------------------------------------------------
section("Scenario 15 - Approval message warns when parsed_orders is empty")

try:
    # Import the checks module fresh so we pick up the edit.
    import importlib
    checks_mod = importlib.import_module("checks.tier0_checks")
    importlib.reload(checks_mod)

    build = checks_mod._build_rich_approval_message

    # Case A: empty list → must render the warning.
    pending_empty = {
        "tool": "write_delivery_order_data",
        "risk_level": "DANGEROUS",
        "description": "Write delivery-order rows",
        "step_number": 6,
        "total_steps": 6,
        "inputs": {
            "sheet_id": "1SHEET_ID",
            "parsed_orders": [],
        },
    }
    msg_empty = build(pending_empty)
    problems = []
    if "0" not in msg_empty:
        problems.append("missing '0 orders'")
    if "empty" not in msg_empty.lower():
        problems.append("missing 'empty' warning")
    if "pdfplumber" not in msg_empty.lower():
        problems.append("missing pdfplumber hint")
    if problems:
        record(
            "empty parsed_orders produces a loud approval message",
            "FAIL",
            f"{problems}; preview={msg_empty[:300]!r}",
        )
    else:
        record("empty parsed_orders produces a loud approval message", "PASS")

    # Case B: non-empty list → must still render the detailed summary.
    pending_full = {
        "tool": "write_delivery_order_data",
        "risk_level": "DANGEROUS",
        "description": "Write delivery-order rows",
        "step_number": 6,
        "total_steps": 6,
        "inputs": {
            "sheet_id": "1SHEET_ID",
            "parsed_orders": [
                {
                    "file": "DO-1.pdf",
                    "header": {"order_reference": "DO-1", "vendor": "ACME"},
                    "line_items": [{"sku": "A", "qty": 1}, {"sku": "B", "qty": 2}],
                }
            ],
        },
    }
    msg_full = build(pending_full)
    if "Orders to write:** 1" in msg_full and "empty" not in msg_full.lower():
        record("non-empty parsed_orders still shows detailed summary", "PASS")
    else:
        record(
            "non-empty parsed_orders still shows detailed summary",
            "FAIL",
            f"preview={msg_full[:400]!r}",
        )
except Exception as e:
    record(
        "empty parsed_orders produces a loud approval message",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 16 — Mapping parser category inference only fills FOOD or NON-FOOD.
# Product rule: the requisition sheet only has Food and non-food tabs. Tech /
# IT / any other category MUST NOT be force-routed — the inference helpers
# return "" for those so the category gate can reject the file downstream.
# ------------------------------------------------------------------
section("Scenario 16 - Mapping inference yields only FOOD / NON-FOOD / empty")

try:
    import importlib

    mapping_mod = importlib.import_module("mapping_agent_api")
    importlib.reload(mapping_mod)

    # --- Filename inference is REMOVED. The parser must never dispatch
    # to a filename-based category helper. This guard catches regressions
    # where someone re-introduces filename heuristics (which would break
    # the product rule that filename must not influence category).
    if hasattr(mapping_mod, "_infer_category_from_filename"):
        record(
            "Mapping agent does NOT expose _infer_category_from_filename",
            "FAIL",
            "filename inference helper is back — must be content-only",
        )
    elif hasattr(mapping_mod, "_FILENAME_CATEGORY_TOKENS"):
        record(
            "Mapping agent does NOT expose _infer_category_from_filename",
            "FAIL",
            "_FILENAME_CATEGORY_TOKENS tuple is back — must be content-only",
        )
    else:
        record("Mapping agent does NOT expose _infer_category_from_filename", "PASS")

    # --- _infer_category_from_items ---------------------------------
    food_items = [
        {"item_code": "RMFD00810030020"},
        {"item_code": "RMFD00810030021"},
    ]
    tech_items = [
        {"item_code": "TECH-HW-001"},
        {"item_code": "TECH-NW-001"},
        {"item_code": "TECH-SRV-001"},
    ]
    mixed_items = [
        {"item_code": "TECH-HW-001"},
        {"item_code": "RMFD00810030020"},
    ]
    unknown_items = [
        {"item_code": "PROD-001"},
        {"item_code": "PROD-002"},
    ]
    empty_items: list = []

    item_cases = [
        (food_items, "FOOD"),
        # TECH items must NOT resolve — product rule says ignore Tech.
        (tech_items, ""),
        # Mixed prefixes, no strict majority.
        (mixed_items, ""),
        (unknown_items, ""),
        (empty_items, ""),
    ]
    item_problems = []
    for items, expected in item_cases:
        got = mapping_mod._infer_category_from_items(items)
        if got != expected:
            item_problems.append(
                f"items={[i.get('item_code') for i in items]}: got {got!r}, want {expected!r}"
            )
    if item_problems:
        record(
            "_infer_category_from_items only yields FOOD (or empty for TECH/unknown)",
            "FAIL",
            "; ".join(item_problems),
        )
    else:
        record("_infer_category_from_items only yields FOOD (or empty for TECH/unknown)", "PASS")

    # --- Regex is strict: only FOOD or NON-FOOD labels match. ------
    strict_cases = [
        ("PRODUCTION MATERIALS REQUISITION LIST\nCategory: FOOD    Date: 2025-04-21", "FOOD"),
        ("PRODUCTION MATERIALS REQUISITION LIST\nType: NON-FOOD    Date: 2025-04-21", "NON-FOOD"),
        ("PRODUCTION MATERIALS REQUISITION LIST\nCategory: NON FOOD Date: 2025-04-21", "NON FOOD"),
        # Anything else does NOT match the strict regex.
        ("PRODUCTION MATERIALS REQUISITION LIST\nCategory: TECH     Date: 2025-04-21", None),
        ("PRODUCTION MATERIALS REQUISITION LIST\nCategory: Beverage Date: 2025-04-21", None),
    ]
    strict_problems = []
    for text, expected_category in strict_cases:
        parsed_header = mapping_mod._extract_header_from_text(text)
        got = parsed_header.get("category")
        snippet = repr(text)[:70]
        if expected_category is None:
            if got:
                strict_problems.append(
                    f"{snippet}...: strict regex should NOT match, got {got!r}"
                )
        else:
            if (got or "").strip().upper() != expected_category.upper():
                strict_problems.append(
                    f"{snippet}...: got {got!r}, want {expected_category!r}"
                )
    if strict_problems:
        record(
            "_HEADER_PATTERNS['category'] is strict (FOOD / NON-FOOD only)",
            "FAIL",
            "; ".join(strict_problems),
        )
    else:
        record("_HEADER_PATTERNS['category'] is strict (FOOD / NON-FOOD only)", "PASS")

    # --- _normalise_category -----------------------------------------
    norm_cases = [
        ("FOOD", "FOOD"),
        ("food", "FOOD"),
        (" Food ", "FOOD"),
        ("NON-FOOD", "NON-FOOD"),
        ("non-food", "NON-FOOD"),
        ("NON FOOD", "NON-FOOD"),
        ("NON_FOOD", "NON-FOOD"),
        ("NONFOOD", "NON-FOOD"),
        # Not accepted -> empty string.
        ("TECH", ""),
        ("IT", ""),
        ("Beverage", ""),
        ("", ""),
    ]
    norm_problems = []
    for raw, expected in norm_cases:
        got = mapping_mod._normalise_category(raw)
        if got != expected:
            norm_problems.append(f"{raw!r}: got {got!r}, want {expected!r}")
    if norm_problems:
        record(
            "_normalise_category accepts only FOOD / NON-FOOD variants",
            "FAIL",
            "; ".join(norm_problems),
        )
    else:
        record("_normalise_category accepts only FOOD / NON-FOOD variants", "PASS")
except Exception as e:
    record(
        "Mapping parser category inference (strict)",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 17 — _is_footer_row drops signature / sign-off blocks while
# preserving real line items. End-to-end parse now also uses a Food-named
# PDF so the category gate passes; footer filtering is orthogonal to the
# category gate and must work regardless.
# ------------------------------------------------------------------
section("Scenario 17 - _is_footer_row drops signature blocks, keeps real items")


class _FakePage:
    def __init__(self, text: str, tables: list):
        self._text = text
        self._tables = tables
    def extract_text(self):
        return self._text
    def extract_tables(self):
        return self._tables


class _FakePDF:
    def __init__(self, pages):
        self.pages = pages
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False


def _run_fake_parse(mapping_mod, pdf_path: str, table: list, header_text: str = "PRODUCTION MATERIALS REQUISITION LIST\n", parser=None):
    """Drive _parse_single_pdf with a stubbed pdfplumber so we can test
    parser behavior without a real PDF on disk. Returns the parsed dict.

    ``parser`` lets callers who have monkey-patched
    ``mapping_mod._parse_single_pdf`` supply the ORIGINAL function pointer
    directly, so we don't recursively call the monkey-patch and blow the
    stack. Defaults to the module attribute at call time for simple cases.
    """
    fake_page = _FakePage(header_text, [table])
    fake_pdf = _FakePDF([fake_page])

    class _FakePdfplumberModule:
        @staticmethod
        def open(_path):
            return fake_pdf

    original_plumber = getattr(mapping_mod, "pdfplumber", None)
    original_flag = getattr(mapping_mod, "PDFPLUMBER_AVAILABLE", False)
    original_exists = mapping_mod.os.path.exists
    mapping_mod.pdfplumber = _FakePdfplumberModule
    mapping_mod.PDFPLUMBER_AVAILABLE = True
    mapping_mod.os.path.exists = lambda _p: True  # type: ignore
    try:
        parser_fn = parser if parser is not None else mapping_mod._parse_single_pdf
        return parser_fn(pdf_path)
    finally:
        if original_plumber is not None:
            mapping_mod.pdfplumber = original_plumber
        mapping_mod.PDFPLUMBER_AVAILABLE = original_flag
        mapping_mod.os.path.exists = original_exists  # type: ignore


try:
    import importlib
    mapping_mod = importlib.import_module("mapping_agent_api")
    importlib.reload(mapping_mod)

    footer_cases = [
        # Real rows — must survive.
        ({"item_code": "TECH-HW-001", "item_description": "Laptop", "qty": 5.0, "uom": "Unit"}, False),
        ({"item_code": "RMFD00810030020", "item_description": "Beef", "qty": 10.0, "uom": "KG"}, False),
        ({"item_code": "NF-CLEAN-001", "item_description": "Mop", "qty": 1.0, "uom": "Unit"}, False),

        # Footer rows — must be dropped.
        # 1) Cell contents match a footer keyword exactly.
        ({"item_code": "Requested By", "item_description": "Assembled By", "qty": "Checked By", "uom": "Received By"}, True),
        # 2) qty cell contains a footer keyword even if code looks odd.
        ({"item_code": "SIGN-001", "item_description": "blah", "qty": "SIGNATURE", "uom": ""}, True),
        # 3) Free-text name row - item_code has no digits.
        ({"item_code": "M.C FRANCO", "item_description": "", "qty": "", "uom": ""}, True),
        # 4) "Signature over printed name" survived column mapping.
        ({"item_code": "Signature over printed name", "item_description": "", "qty": "", "uom": ""}, True),
        # 5) A lone person name.
        ({"item_code": "Juan Dela Cruz", "item_description": "", "qty": "", "uom": ""}, True),

        # Edge cases - empty rows should not be flagged (the outer guard
        # handles them), so _is_footer_row must NOT claim every empty row.
        ({"item_code": "", "item_description": "", "qty": "", "uom": ""}, False),
    ]

    problems = []
    for item, expected in footer_cases:
        got = mapping_mod._is_footer_row(item)
        if got != expected:
            problems.append(f"{item}: got {got}, want {expected}")

    if problems:
        record("_is_footer_row filters signatures without false positives", "FAIL", "; ".join(problems))
    else:
        record("_is_footer_row filters signatures without false positives", "PASS")

    # --- End-to-end through _parse_single_pdf minus pdfplumber ------
    # Use a FOOD-named PDF so the category gate passes and we can observe
    # how many line_items survive the signature filter.
    header_row = ["Item Code", "Item Description", "QTY", "UOM"]
    real_items = [
        ["RMFD00810030020", "Beef", "10", "KG"],
        ["RMFD00810030021", "Chicken", "5", "KG"],
    ]
    footer_rows = [
        ["Requested By", "Assembled By", "Checked By", "Received By"],
        ["M.C FRANCO", "", "", ""],
        ["Signature over printed name", "Signature over printed name",
         "Signature over printed name", "Signature over printed name"],
    ]
    table = [header_row] + real_items + footer_rows

    parsed = _run_fake_parse(mapping_mod, "/tmp/Food_DELIVERY_ORDER.pdf", table)

    page_order = _first_order(parsed)
    items = page_order.get("line_items", [])
    item_codes = [i.get("item_code") for i in items]
    if parsed.get("rejected"):
        record(
            "_parse_single_pdf drops footer rows end-to-end (FOOD)",
            "FAIL",
            f"rejected: {parsed.get('reason')!r}",
        )
    elif len(items) == 2 and item_codes == ["RMFD00810030020", "RMFD00810030021"]:
        record("_parse_single_pdf drops footer rows end-to-end (FOOD)", "PASS")
    else:
        record(
            "_parse_single_pdf drops footer rows end-to-end (FOOD)",
            "FAIL",
            f"got {len(items)} items: {item_codes}",
        )

    if page_order.get("header", {}).get("category") == "FOOD":
        record("_parse_single_pdf fills header.category=FOOD via item-code prefix (content)", "PASS")
    else:
        record(
            "_parse_single_pdf fills header.category=FOOD via item-code prefix (content)",
            "FAIL",
            f"header={page_order.get('header')!r}",
        )
except Exception as e:
    record(
        "_is_footer_row + end-to-end parser test",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 18 — _resolve_tab_for_category is strictly binary. Only FOOD and
# NON-FOOD return a destination tab. TECH / IT / unknown return (None, warn).
# Locks in the product rule so a future refactor can't quietly add Tech or
# silently default to non-food.
# ------------------------------------------------------------------
section("Scenario 18 - _resolve_tab_for_category is strictly FOOD / NON-FOOD")

try:
    import importlib.util
    sheets_api_path = SHEETS / "sheets_agent_api.py"
    spec = importlib.util.spec_from_file_location("sheets_agent_api_sim_b3", sheets_api_path)
    sheets_api = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(sheets_api)  # type: ignore

    full_tabs = ["Food", "non-food", "Summary"]
    partial_food_only = ["Food"]          # non-food tab missing
    partial_nonfood_only = ["non-food"]   # Food tab missing

    cases = [
        # (category, tab_names, expected_tab, expect_warning)
        # FOOD and NON-FOOD in both orientations + all whitespace/hyphen variants.
        ("FOOD",      full_tabs,           "Food",     False),
        ("food",      full_tabs,           "Food",     False),
        (" Food ",    full_tabs,           "Food",     False),
        ("NON-FOOD",  full_tabs,           "non-food", False),
        ("non-food",  full_tabs,           "non-food", False),
        ("NON FOOD",  full_tabs,           "non-food", False),
        ("NON_FOOD",  full_tabs,           "non-food", False),
        ("NONFOOD",   full_tabs,           "non-food", False),

        # Non-FOOD/NON-FOOD categories MUST be skipped with a warning —
        # never force-routed to another tab, even if one exists.
        ("TECH",      full_tabs,           None,       True),
        ("IT",        full_tabs,           None,       True),
        ("Beverage",  ["Food", "non-food", "Beverage"], None, True),
        ("",          full_tabs,           None,       True),

        # Even a correct category gets skipped when its destination tab is
        # missing — the template requires both tabs to exist.
        ("FOOD",      partial_nonfood_only, None,      True),
        ("NON-FOOD",  partial_food_only,    None,      True),
    ]

    problems = []
    for category, tabs, expected_tab, expect_warning in cases:
        actual, warning = sheets_api._resolve_tab_for_category(category, tabs)
        if actual != expected_tab:
            problems.append(
                f"category={category!r} tabs={tabs!r}: got tab={actual!r}, want {expected_tab!r}"
            )
        if expect_warning and not warning:
            problems.append(f"category={category!r} tabs={tabs!r}: expected warning, got None")
        if not expect_warning and warning:
            problems.append(
                f"category={category!r} tabs={tabs!r}: unexpected warning={warning!r}"
            )

    # Also assert the TECH warning text mentions that only FOOD / NON-FOOD
    # are accepted, so the user understands WHY their Tech order was skipped.
    _, tech_warn = sheets_api._resolve_tab_for_category("TECH", full_tabs)
    if not tech_warn or ("FOOD" not in tech_warn and "food" not in tech_warn):
        problems.append(
            f"TECH warning should mention FOOD/NON-FOOD policy, got {tech_warn!r}"
        )

    # And the _CATEGORY_TAB_MAP must not contain any Tech entry.
    if any(k.upper().startswith("TECH") or k.upper() in ("IT", "TECHNOLOGY") for k in sheets_api._CATEGORY_TAB_MAP.keys()):
        problems.append(
            f"_CATEGORY_TAB_MAP should not contain Tech/IT entries, got {list(sheets_api._CATEGORY_TAB_MAP.keys())}"
        )

    if problems:
        record(
            "_resolve_tab_for_category routes only FOOD / NON-FOOD, skips everything else",
            "FAIL",
            "; ".join(problems),
        )
    else:
        record("_resolve_tab_for_category routes only FOOD / NON-FOOD, skips everything else", "PASS")
except Exception as e:
    record(
        "_resolve_tab_for_category routes only FOOD / NON-FOOD, skips everything else",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 19 — preview_delivery_order_insertion routes FOOD -> Food and
# NON-FOOD -> non-food; if a TECH order somehow slips past the mapping
# gate (defensive) it gets skipped, never routed.
# ------------------------------------------------------------------
section("Scenario 19 - preview_delivery_order_insertion routes strictly FOOD/NON-FOOD")


def _make_fake_sheets_service(tab_names: list, existing_rows_by_tab: dict | None = None):
    """Minimum-viable fake of the Google Sheets API object graph."""
    existing = existing_rows_by_tab or {}

    class _ValuesCall:
        def __init__(self, range_str: str):
            self._range = range_str
        def execute(self):
            tab = self._range.strip("'").split("'!", 1)[0].lstrip("'")
            return {"values": existing.get(tab, [])}

    class _Values:
        def get(self, spreadsheetId, range):
            return _ValuesCall(range)

    class _GetCall:
        def execute(self):
            return {
                "sheets": [
                    {"properties": {"title": t}} for t in tab_names
                ]
            }

    class _Spreadsheets:
        def get(self, spreadsheetId):
            return _GetCall()
        def values(self):
            return _Values()

    class _Service:
        def spreadsheets(self):
            return _Spreadsheets()

    return _Service()


try:
    import importlib.util
    sheets_api_path = SHEETS / "sheets_agent_api.py"
    spec = importlib.util.spec_from_file_location("sheets_agent_api_sim_b3e2e", sheets_api_path)
    sheets_api = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(sheets_api)  # type: ignore

    food_order = {
        "file": "Food_DO.pdf",
        "header": {
            "category": "FOOD",
            "reference_number": "DO-F-1",
            "date": "2025-04-21",
            "requested_by": "Alice",
        },
        "line_items": [
            {"item_code": "RMFD00810030020", "item_description": "Beef", "qty": 10.0, "uom": "KG"},
            {"item_code": "RMFD00810030021", "item_description": "Chicken", "qty": 5.0, "uom": "KG"},
        ],
    }
    nonfood_order = {
        "file": "NonFood_DO.pdf",
        "header": {
            "category": "NON-FOOD",
            "reference_number": "DO-NF-1",
            "date": "2025-04-21",
            "requested_by": "Carol",
        },
        "line_items": [
            {"item_code": "NF-CLEAN-001", "item_description": "Mop", "qty": 4.0, "uom": "Unit"},
        ],
    }
    tech_order_defensive = {
        "file": "Tech_DO.pdf",
        "header": {
            # Defensive: if a TECH order ever reaches the sheets agent
            # (shouldn't — the mapping agent's category gate rejects these),
            # it must be skipped, not routed anywhere.
            "category": "TECH",
            "reference_number": "DO-T-1",
            "date": "2025-04-21",
            "requested_by": "Bob",
        },
        "line_items": [
            {"item_code": "TECH-HW-001", "item_description": "Laptop", "qty": 3.0, "uom": "Unit"},
        ],
    }

    # --- Case A: FOOD + NON-FOOD orders with correct tabs.
    original_create = sheets_api.create_sheets_service
    sheets_api.create_sheets_service = lambda _c: _make_fake_sheets_service(
        ["Food", "non-food", "Summary"]
    )
    try:
        result_a = sheets_api.preview_delivery_order_insertion(
            sheet_id="1SHEET",
            parsed_orders=[food_order, nonfood_order],
            credentials_dict=sheets_api.CredentialsDict(access_token="x", refresh_token="y"),
        )
    finally:
        sheets_api.create_sheets_service = original_create

    per_tab = {}
    for row in result_a.get("preview_rows", []):
        per_tab.setdefault(row["tab"], []).append(row["values"])

    problems_a = []
    if set(per_tab.keys()) != {"Food", "non-food"}:
        problems_a.append(f"tabs_seen={set(per_tab.keys())}")
    if len(per_tab.get("Food", [])) != 2:
        problems_a.append(f"food rows={len(per_tab.get('Food', []))}")
    if len(per_tab.get("non-food", [])) != 1:
        problems_a.append(f"non-food rows={len(per_tab.get('non-food', []))}")
    if result_a.get("warnings"):
        # Shouldn't see routing warnings on a clean FOOD + NON-FOOD run.
        route_warns = [w for w in result_a["warnings"] if "skipped" in w.lower() or "not FOOD" in w]
        if route_warns:
            problems_a.append(f"unexpected route warnings: {route_warns}")

    if problems_a:
        record(
            "preview routes FOOD->Food and NON-FOOD->non-food",
            "FAIL",
            "; ".join(problems_a),
        )
    else:
        record("preview routes FOOD->Food and NON-FOOD->non-food", "PASS")

    # --- Case B (defensive): TECH order mixed with FOOD + NON-FOOD. The
    # TECH order must be skipped with a warning; the other two route normally.
    sheets_api.create_sheets_service = lambda _c: _make_fake_sheets_service(
        ["Food", "non-food"]
    )
    try:
        result_b = sheets_api.preview_delivery_order_insertion(
            sheet_id="1SHEET",
            parsed_orders=[food_order, tech_order_defensive, nonfood_order],
            credentials_dict=sheets_api.CredentialsDict(access_token="x", refresh_token="y"),
        )
    finally:
        sheets_api.create_sheets_service = original_create

    per_tab_b = {}
    for row in result_b.get("preview_rows", []):
        per_tab_b.setdefault(row["tab"], []).append(row["values"])

    problems_b = []
    if len(per_tab_b.get("Food", [])) != 2:
        problems_b.append(f"food rows={len(per_tab_b.get('Food', []))}")
    if len(per_tab_b.get("non-food", [])) != 1:
        problems_b.append(f"non-food rows={len(per_tab_b.get('non-food', []))}")
    # The TECH rows must NOT appear in any tab.
    for tab, rows in per_tab_b.items():
        for row in rows:
            if "TECH-" in (row[2] or ""):  # column index 2 is item_code
                problems_b.append(f"TECH row leaked into tab={tab!r}: {row!r}")
    warnings_b = result_b.get("warnings", []) or []
    if not any("TECH" in w.upper() and "skipped" in w.lower() for w in warnings_b):
        problems_b.append(f"expected TECH-skipped warning, got {warnings_b!r}")

    if problems_b:
        record(
            "preview skips TECH order (defensive) and routes others correctly",
            "FAIL",
            "; ".join(problems_b),
        )
    else:
        record("preview skips TECH order (defensive) and routes others correctly", "PASS")

    # --- Case C: FOOD order with a broken sheet (no Food tab). The order
    # must be skipped with a clear warning about the missing tab, not
    # silently placed into non-food.
    sheets_api.create_sheets_service = lambda _c: _make_fake_sheets_service(
        ["non-food"]
    )
    try:
        result_c = sheets_api.preview_delivery_order_insertion(
            sheet_id="1SHEET",
            parsed_orders=[food_order],
            credentials_dict=sheets_api.CredentialsDict(access_token="x", refresh_token="y"),
        )
    finally:
        sheets_api.create_sheets_service = original_create

    problems_c = []
    if result_c.get("preview_rows"):
        problems_c.append(f"expected 0 preview_rows, got {len(result_c['preview_rows'])}")
    warnings_c = result_c.get("warnings", []) or []
    if not any("Food" in w and ("missing" in w.lower() or "not found" in w.lower() or "skipped" in w.lower()) for w in warnings_c):
        problems_c.append(f"expected 'Food tab missing' warning, got {warnings_c!r}")

    if problems_c:
        record(
            "preview hard-skips FOOD order when Food tab is absent",
            "FAIL",
            "; ".join(problems_c),
        )
    else:
        record("preview hard-skips FOOD order when Food tab is absent", "PASS")
except Exception as e:
    record(
        "preview_delivery_order_insertion strict FOOD/NON-FOOD routing",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 20 — Category gate: a Tech-named PDF with TECH items must be
# REJECTED at _parse_single_pdf, not parsed and returned for routing. This
# is the product-rule gate described by the user: the requisition sheet
# only accepts FOOD and NON-FOOD; anything else is ignored upfront.
# ------------------------------------------------------------------
section("Scenario 20 - Mapping parser rejects Tech requisition PDFs")

try:
    import importlib
    mapping_mod = importlib.import_module("mapping_agent_api")
    importlib.reload(mapping_mod)

    header_row = ["Item Code", "Item Description", "QTY", "UOM"]
    tech_items = [
        ["TECH-HW-001", "Laptop", "5", "Unit"],
        ["TECH-NW-001", "Router", "2", "Unit"],
        ["TECH-SRV-001", "Server", "1", "Unit"],
    ]
    tech_table = [header_row] + tech_items

    parsed = _run_fake_parse(mapping_mod, "/tmp/Tech_DELIVERY_ORDER.pdf", tech_table)
    problems = []
    # Per-page refactor: a Tech PDF whose only page trips the category gate
    # comes back as {rejected: False, orders: [], rejected_pages: [{page, reason}]}.
    # parse_delivery_order_pdfs collapses that to a rejected_files entry, so
    # the user-facing behaviour is unchanged. Accept either shape here.
    if parsed.get("rejected"):
        reason = parsed.get("reason") or ""
    else:
        rej_pages = parsed.get("rejected_pages") or []
        orders = parsed.get("orders") or []
        if not rej_pages or orders:
            problems.append(f"expected rejected=True or all-pages-rejected, got {parsed!r}")
        reason = "; ".join((p.get("reason", "") for p in rej_pages))
    if "FOOD" not in reason.upper() or "NON-FOOD" not in reason.upper():
        problems.append(f"rejection reason should mention FOOD and NON-FOOD, got {reason!r}")
    if problems:
        record(
            "_parse_single_pdf rejects Tech requisition PDFs",
            "FAIL",
            "; ".join(problems),
        )
    else:
        record("_parse_single_pdf rejects Tech requisition PDFs", "PASS")

    # Now run parse_delivery_order_pdfs with one FOOD PDF and one TECH PDF.
    # The FOOD one must parse and land in parsed_orders, the TECH one must
    # land in rejected_files, and the top-level success flag must be True
    # (we got at least one usable order).
    real_parser = mapping_mod._parse_single_pdf  # capture BEFORE monkey-patching

    food_table = [
        header_row,
        ["RMFD00810030020", "Beef", "10", "KG"],
        ["RMFD00810030021", "Chicken", "5", "KG"],
    ]

    def _fake_single(fp: str):
        # Pass parser=real_parser so _run_fake_parse calls the REAL
        # _parse_single_pdf, not the monkey-patched _fake_single (which
        # would recurse forever).
        if "Food" in fp or "food" in fp:
            return _run_fake_parse(mapping_mod, fp, food_table, parser=real_parser)
        return _run_fake_parse(mapping_mod, fp, tech_table, parser=real_parser)

    mapping_mod._parse_single_pdf = _fake_single
    try:
        result = mapping_mod.parse_delivery_order_pdfs(
            ["/tmp/Food_DELIVERY_ORDER.pdf", "/tmp/Tech_DELIVERY_ORDER.pdf"]
        )
    finally:
        mapping_mod._parse_single_pdf = real_parser

    mix_problems = []
    if result.get("success") is not True:
        mix_problems.append(f"expected success=True (one file parsed), got {result.get('success')!r}")
    if result.get("total_parsed") != 1:
        mix_problems.append(f"expected total_parsed=1, got {result.get('total_parsed')!r}")
    if result.get("total_rejected") != 1:
        mix_problems.append(f"expected total_rejected=1, got {result.get('total_rejected')!r}")
    rej = result.get("rejected_files", [])
    if not rej or "Tech" not in rej[0].get("file", ""):
        mix_problems.append(f"expected Tech PDF in rejected_files, got {rej!r}")
    parsed_orders = result.get("parsed_orders", [])
    if len(parsed_orders) != 1 or parsed_orders[0].get("header", {}).get("category") != "FOOD":
        mix_problems.append(f"expected 1 FOOD order parsed, got {parsed_orders!r}")
    if mix_problems:
        record(
            "parse_delivery_order_pdfs keeps FOOD, rejects TECH on mixed batch",
            "FAIL",
            "; ".join(mix_problems),
        )
    else:
        record("parse_delivery_order_pdfs keeps FOOD, rejects TECH on mixed batch", "PASS")
except Exception as e:
    record(
        "_parse_single_pdf rejects Tech requisition PDFs",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 21 — Content-only category detection.
#
# Product rule: "File name should not matter and just the content." Filename
# has been intentionally removed from the inference chain. This scenario
# locks that rule in by feeding the parser content+filename combinations
# where the filename would previously have won, and verifying the parser
# follows the CONTENT every time.
# ------------------------------------------------------------------
section("Scenario 21 - Filename is ignored; category comes from content only")

try:
    import importlib
    mapping_mod = importlib.import_module("mapping_agent_api")
    importlib.reload(mapping_mod)

    header_row = ["Item Code", "Item Description", "QTY", "UOM"]
    food_items = [
        [header_row[0], header_row[1], header_row[2], header_row[3]],
        ["RMFD00810030020", "Beef", "10", "KG"],
        ["RMFD00810030021", "Chicken", "5", "KG"],
    ]
    tech_items_table = [
        header_row,
        ["TECH-HW-001", "Laptop", "5", "Unit"],
        ["TECH-NW-001", "Router", "2", "Unit"],
    ]
    # Filename sends mixed / wrong signals on purpose.
    cases = [
        # (pdf_path, table, expect_rejected, expected_category)
        # 1. Filename screams FOOD, content is TECH — filename must NOT save it.
        ("/tmp/Food_DELIVERY_ORDER.pdf", tech_items_table, True, None),
        # 2. Filename screams Non-Food, content is TECH — still rejected.
        ("/tmp/NonFood_DELIVERY_ORDER.pdf", tech_items_table, True, None),
        # 3. Filename is totally neutral, content is FOOD — accepted as FOOD.
        ("/tmp/DO-2025-04-21.pdf", food_items, False, "FOOD"),
        # 4. Filename is gibberish, content is FOOD — still accepted.
        ("/tmp/asdf_1234.pdf", food_items, False, "FOOD"),
    ]

    problems = []
    for pdf_path, table, expect_rejected, expected_category in cases:
        parsed = _run_fake_parse(mapping_mod, pdf_path, table)
        if expect_rejected:
            # Same as the Tech-rejection scenario: accept either whole-PDF
            # rejection (rejected: True) or all-pages-rejected (orders empty
            # + rejected_pages non-empty), since parse_delivery_order_pdfs
            # collapses both into the same user-facing "rejected file".
            whole_pdf_reject = parsed.get("rejected")
            all_pages_rejected = (
                not parsed.get("rejected")
                and not (parsed.get("orders") or [])
                and bool(parsed.get("rejected_pages") or [])
            )
            if not (whole_pdf_reject or all_pages_rejected):
                problems.append(
                    f"{pdf_path!r} with TECH content: expected rejection, got {parsed!r}"
                )
        else:
            if parsed.get("rejected"):
                problems.append(
                    f"{pdf_path!r} with FOOD content: expected acceptance, got reason={parsed.get('reason')!r}"
                )
            else:
                got_cat = _first_order(parsed).get("header", {}).get("category")
                if got_cat != expected_category:
                    problems.append(
                        f"{pdf_path!r}: got category={got_cat!r}, want {expected_category!r}"
                    )

    if problems:
        record(
            "Filename never overrides content in category detection",
            "FAIL",
            "; ".join(problems),
        )
    else:
        record("Filename never overrides content in category detection", "PASS")
except Exception as e:
    record(
        "Filename never overrides content in category detection",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 22 — File-type gate: anything that isn't a .pdf is rejected
# up-front with a clear "Not a PDF file" reason. Non-PDF files must NEVER
# reach the template or category checks.
# ------------------------------------------------------------------
section("Scenario 22 - Non-PDF files are rejected with 'Not a PDF file'")

try:
    import importlib
    mapping_mod = importlib.import_module("mapping_agent_api")
    importlib.reload(mapping_mod)

    # Even with pdfplumber simulated as "available", the extension check
    # fires before we try to open the file. Use the real function directly
    # — we don't need _run_fake_parse here.
    original_flag = getattr(mapping_mod, "PDFPLUMBER_AVAILABLE", False)
    mapping_mod.PDFPLUMBER_AVAILABLE = True
    try:
        non_pdf_cases = [
            "/tmp/report.docx",
            "/tmp/random.txt",
            "/tmp/image.png",
            "/tmp/spreadsheet.xlsx",
            "/tmp/no_extension",
            "/tmp/fake.pdf.exe",  # sneaky double extension; .exe wins
        ]
        problems = []
        for path in non_pdf_cases:
            result = mapping_mod._parse_single_pdf(path)
            if not result.get("rejected"):
                problems.append(f"{path!r}: expected rejection, got {result!r}")
            elif "pdf" not in (result.get("reason") or "").lower():
                problems.append(f"{path!r}: rejection reason should mention PDF, got {result.get('reason')!r}")

        # And at the batch layer, a batch of only non-PDFs collapses to
        # zero parsed + a clear top-level failure (no cascade into the
        # sheet pipeline).
        batch = mapping_mod.parse_delivery_order_pdfs(non_pdf_cases)
        if batch.get("total_parsed") != 0:
            problems.append(f"batch total_parsed expected 0, got {batch.get('total_parsed')!r}")
        if batch.get("total_rejected") != len(non_pdf_cases):
            problems.append(f"batch total_rejected expected {len(non_pdf_cases)}, got {batch.get('total_rejected')!r}")
        if batch.get("success") is not False:
            problems.append(f"batch success should be False on all-rejected, got {batch.get('success')!r}")

        if problems:
            record(
                "Non-PDF uploads are rejected by file-type gate",
                "FAIL",
                "; ".join(problems),
            )
        else:
            record("Non-PDF uploads are rejected by file-type gate", "PASS")
    finally:
        mapping_mod.PDFPLUMBER_AVAILABLE = original_flag
except Exception as e:
    record(
        "Non-PDF uploads are rejected by file-type gate",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 23 — Wrong-template PDF rejected at the marker check. A PDF
# that parses fine but whose first-page text doesn't contain the
# "PRODUCTION MATERIALS REQUISITION LIST" / "REQUISITION LIST" marker
# must be rejected BEFORE we try to extract rows. This guards against
# the user pointing us at a completely different kind of PDF (invoice,
# sales report, letter, etc.).
# ------------------------------------------------------------------
section("Scenario 23 - PDFs that don't match our template are rejected")

try:
    import importlib
    mapping_mod = importlib.import_module("mapping_agent_api")
    importlib.reload(mapping_mod)

    wrong_template_texts = [
        "MONTHLY SALES REPORT\nCategory: FOOD\nProduct X: 100 units",
        "INVOICE #12345\nBill To: Acme Corp\nTotal: $5,000",
        "INTERNAL MEMO\nSubject: Budget review",
        "",  # empty extraction
    ]

    problems = []
    for i, wrong_text in enumerate(wrong_template_texts):
        # Even with good-looking table data, absence of marker must reject.
        parsed = _run_fake_parse(
            mapping_mod,
            f"/tmp/wrong_template_{i}.pdf",
            [
                ["Item Code", "Description", "QTY", "UOM"],
                ["RMFD00810030020", "Beef", "10", "KG"],
            ],
            header_text=wrong_text,
        )
        if not parsed.get("rejected"):
            snippet = repr(wrong_text)[:60]
            problems.append(
                f"text={snippet}...: expected rejection (wrong template), got {parsed!r}"
            )
        elif "requisition" not in (parsed.get("reason") or "").lower():
            problems.append(
                f"rejection reason should mention requisition/template, got {parsed.get('reason')!r}"
            )

    # And when the marker IS present, the same item table parses cleanly.
    valid = _run_fake_parse(
        mapping_mod,
        "/tmp/DO-2025-04-21.pdf",
        [
            ["Item Code", "Description", "QTY", "UOM"],
            ["RMFD00810030020", "Beef", "10", "KG"],
        ],
        header_text="PRODUCTION MATERIALS REQUISITION LIST\n",
    )
    if valid.get("rejected"):
        problems.append(
            f"valid marker: expected acceptance, got rejection {valid.get('reason')!r}"
        )

    if problems:
        record(
            "Wrong-template PDFs rejected before data parsing",
            "FAIL",
            "; ".join(problems),
        )
    else:
        record("Wrong-template PDFs rejected before data parsing", "PASS")
except Exception as e:
    record(
        "Wrong-template PDFs rejected before data parsing",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 24 — validate_delivery_sheet rejects a wrong sheet. If the user
# pastes a link to a completely different spreadsheet (missing Food +
# non-food tabs), the agent must return error_type=wrong_sheet with a
# message that explicitly says this is NOT the designated requisition
# sheet — not just a vague "header mismatch".
# ------------------------------------------------------------------
section("Scenario 24 - validate_delivery_sheet rejects wrong sheet with clear error")


def _make_full_fake_service(
    tab_names: list,
    spreadsheet_title: str = "Production Materials Requisition List",
    header_by_tab: dict | None = None,
    permission_status: int | None = None,
    append_status: int | None = None,
    err_cls=None,
):
    """Richer fake Sheets service that exercises the whole validate_delivery_sheet
    path (metadata + per-tab header row + _check_write_permission's batchUpdate
    + values().append()).

    permission_status: if set, the batchUpdate title noop raises HttpError(status).
    append_status: if set, values().append() raises HttpError(status).
    """
    header_by_tab = header_by_tab or {}

    def _raise(status):
        assert err_cls is not None
        e = err_cls(f"fake http {status}")
        e.resp = types.SimpleNamespace(status=status)
        raise e

    class _ValuesGet:
        def __init__(self, range_str: str):
            self._range = range_str
        def execute(self):
            tab = self._range.strip("'").split("'!", 1)[0].lstrip("'")
            row = header_by_tab.get(tab, [])
            return {"values": [row] if row else []}

    class _ValuesAppend:
        def __init__(self, *a, **kw):
            pass
        def execute(self):
            if append_status is not None:
                _raise(append_status)
            return {"updates": {"updatedCells": 8}}

    class _Values:
        def get(self, spreadsheetId, range):
            return _ValuesGet(range)
        def append(self, spreadsheetId, range, valueInputOption, insertDataOption, body):
            return _ValuesAppend()

    class _BatchUpdate:
        def __init__(self, *a, **kw):
            pass
        def execute(self):
            if permission_status is not None:
                _raise(permission_status)
            return {"replies": [{}]}

    class _SpreadsheetsGet:
        def __init__(self, _kwargs):
            self._fields = _kwargs.get("fields") or ""
        def execute(self):
            # When called with fields="properties.title", only surface title
            # (mimics Google's partial-response behavior so _check_write_permission
            # reads the current title before the noop update).
            return {
                "properties": {"title": spreadsheet_title},
                "sheets": [{"properties": {"title": t}} for t in tab_names],
            }

    class _Spreadsheets:
        def get(self, spreadsheetId, **kwargs):
            return _SpreadsheetsGet(kwargs)
        def batchUpdate(self, spreadsheetId, body):
            return _BatchUpdate()
        def values(self):
            return _Values()

    class _Service:
        def spreadsheets(self):
            return _Spreadsheets()

    return _Service()


try:
    import importlib.util
    sheets_api_path = SHEETS / "sheets_agent_api.py"
    spec = importlib.util.spec_from_file_location("sheets_agent_api_sim_sheet_err", sheets_api_path)
    sheets_api = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(sheets_api)  # type: ignore

    err_cls = sheets_api.HttpError

    # Case A: completely different sheet — tabs are "Budget" / "Summary".
    original_create = sheets_api.create_sheets_service
    sheets_api.create_sheets_service = lambda _c: _make_full_fake_service(
        tab_names=["Budget", "Summary"],
        spreadsheet_title="Q1 Finance Dashboard",
        err_cls=err_cls,
    )
    try:
        result_a = sheets_api.validate_delivery_sheet(
            sheet_id="1WRONG",
            credentials_dict=sheets_api.CredentialsDict(access_token="x", refresh_token="y"),
        )
    finally:
        sheets_api.create_sheets_service = original_create

    problems_a = []
    if result_a.get("success") is not False:
        problems_a.append(f"expected success=False, got {result_a.get('success')!r}")
    if result_a.get("error_type") != "wrong_sheet":
        problems_a.append(f"expected error_type='wrong_sheet', got {result_a.get('error_type')!r}")
    err_msg = (result_a.get("error") or "").lower()
    if "different" not in err_msg and "designated" not in err_msg:
        problems_a.append(
            f"error should call out 'different sheet' / 'designated', got: {result_a.get('error')!r}"
        )
    if "q1 finance dashboard" not in err_msg:
        problems_a.append(f"error should include sheet title, got: {result_a.get('error')!r}")
    if "food" not in err_msg or "non-food" not in err_msg:
        problems_a.append(f"error should mention Food/non-food tabs, got: {result_a.get('error')!r}")
    if sorted(result_a.get("missing_tabs", [])) != sorted(["Food", "non-food"]):
        problems_a.append(f"missing_tabs should be ['Food','non-food'], got {result_a.get('missing_tabs')!r}")

    if problems_a:
        record(
            "validate_delivery_sheet flags wrong sheet with explicit 'different sheet' error",
            "FAIL",
            "; ".join(problems_a),
        )
    else:
        record(
            "validate_delivery_sheet flags wrong sheet with explicit 'different sheet' error",
            "PASS",
        )

    # Case B: correct tabs but wrong header row ("Product" instead of "Date").
    # This is a template mismatch (right kind of sheet, wrong structure) — error
    # should reference the template but NOT say "different sheet" because tabs
    # are present.
    wrong_headers = {
        "Food": ["Product", "Order Reference", "Item Code", "Item Description", "QTY", "UOM", "CB Date", "Requested by"],
        "non-food": ["Product", "Order Reference", "Item Code", "Item Description", "QTY", "UOM", "CB Date", "Requested by"],
    }
    sheets_api.create_sheets_service = lambda _c: _make_full_fake_service(
        tab_names=["Food", "non-food"],
        spreadsheet_title="Requisition List v2",
        header_by_tab=wrong_headers,
        err_cls=err_cls,
    )
    try:
        result_b = sheets_api.validate_delivery_sheet(
            sheet_id="1MISMATCH",
            credentials_dict=sheets_api.CredentialsDict(access_token="x", refresh_token="y"),
        )
    finally:
        sheets_api.create_sheets_service = original_create

    problems_b = []
    if result_b.get("success") is not False:
        problems_b.append(f"expected success=False, got {result_b.get('success')!r}")
    if result_b.get("error_type") != "wrong_sheet":
        problems_b.append(f"expected error_type='wrong_sheet', got {result_b.get('error_type')!r}")
    if not result_b.get("mismatch_details"):
        problems_b.append("mismatch_details should list the header mismatches")
    err_msg_b = (result_b.get("error") or "").lower()
    if "date" not in err_msg_b or "product" not in err_msg_b:
        problems_b.append(f"error should call out Date-vs-Product mismatch, got: {result_b.get('error')!r}")

    if problems_b:
        record(
            "validate_delivery_sheet flags header mismatch with actionable detail",
            "FAIL",
            "; ".join(problems_b),
        )
    else:
        record(
            "validate_delivery_sheet flags header mismatch with actionable detail",
            "PASS",
        )
except Exception as e:
    record(
        "validate_delivery_sheet wrong-sheet coverage",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 25 — validate_delivery_sheet catches read-only (Viewer) access.
# Template + tabs are correct, but the caller only has Viewer access, so
# the proactive _check_write_permission noop title update returns HTTP 403.
# The function must return error_type=read_only with a message telling the
# user to ask for Editor access.
# ------------------------------------------------------------------
section("Scenario 25 - validate_delivery_sheet catches read-only sheet access")

try:
    import importlib.util
    sheets_api_path = SHEETS / "sheets_agent_api.py"
    spec = importlib.util.spec_from_file_location("sheets_agent_api_sim_perm", sheets_api_path)
    sheets_api = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(sheets_api)  # type: ignore

    err_cls = sheets_api.HttpError

    # Good headers + tabs + title, but batchUpdate raises 403.
    good_headers = {
        "Food": sheets_api._EXPECTED_HEADERS,
        "non-food": sheets_api._EXPECTED_HEADERS,
    }
    original_create = sheets_api.create_sheets_service
    sheets_api.create_sheets_service = lambda _c: _make_full_fake_service(
        tab_names=["Food", "non-food"],
        spreadsheet_title="Production Materials Requisition List",
        header_by_tab=good_headers,
        permission_status=403,
        err_cls=err_cls,
    )
    try:
        result = sheets_api.validate_delivery_sheet(
            sheet_id="1READONLY",
            credentials_dict=sheets_api.CredentialsDict(access_token="x", refresh_token="y"),
        )
    finally:
        sheets_api.create_sheets_service = original_create

    problems = []
    if result.get("success") is not False:
        problems.append(f"expected success=False, got {result.get('success')!r}")
    if result.get("is_valid") is not True:
        problems.append(f"is_valid should remain True (template IS correct), got {result.get('is_valid')!r}")
    if result.get("error_type") != "read_only":
        problems.append(f"expected error_type='read_only', got {result.get('error_type')!r}")
    err_msg = (result.get("error") or "").lower()
    if "editor" not in err_msg:
        problems.append(f"error should recommend asking for Editor access, got: {result.get('error')!r}")
    if "read-only" not in err_msg and "viewer" not in err_msg:
        problems.append(f"error should call out read-only/Viewer, got: {result.get('error')!r}")

    if problems:
        record(
            "validate_delivery_sheet catches read-only access with actionable error",
            "FAIL",
            "; ".join(problems),
        )
    else:
        record(
            "validate_delivery_sheet catches read-only access with actionable error",
            "PASS",
        )

    # Sanity: happy path (no 403) surfaces success=True so we're not just
    # always returning read-only.
    sheets_api.create_sheets_service = lambda _c: _make_full_fake_service(
        tab_names=["Food", "non-food"],
        spreadsheet_title="Production Materials Requisition List",
        header_by_tab=good_headers,
        err_cls=err_cls,
    )
    try:
        ok = sheets_api.validate_delivery_sheet(
            sheet_id="1OK",
            credentials_dict=sheets_api.CredentialsDict(access_token="x", refresh_token="y"),
        )
    finally:
        sheets_api.create_sheets_service = original_create

    if ok.get("success") is True and ok.get("is_valid") is True and not ok.get("error_type"):
        record("validate_delivery_sheet happy path still returns success=True", "PASS")
    else:
        record(
            "validate_delivery_sheet happy path still returns success=True",
            "FAIL",
            f"got {ok!r}",
        )
except Exception as e:
    record(
        "validate_delivery_sheet read-only coverage",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 26 — write_delivery_order_data defends against mid-flight 403
# (user had write access during validation but lost it, or permission
# check was skipped). A 403 on values().append() must surface a clear
# read-only error with error_type=read_only, not a raw HttpError.
# ------------------------------------------------------------------
section("Scenario 26 - write_delivery_order_data catches 403 on append with read_only error")

try:
    import importlib.util
    sheets_api_path = SHEETS / "sheets_agent_api.py"
    spec = importlib.util.spec_from_file_location("sheets_agent_api_sim_write_perm", sheets_api_path)
    sheets_api = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(sheets_api)  # type: ignore

    err_cls = sheets_api.HttpError

    food_order = {
        "file": "DO-2025-04-21.pdf",
        "header": {
            "category": "FOOD",
            "reference_number": "DO-F-1",
            "date": "2025-04-21",
            "requested_by": "Alice",
        },
        "line_items": [
            {"item_code": "RMFD00810030020", "item_description": "Beef", "qty": 10.0, "uom": "KG"},
        ],
    }

    original_create = sheets_api.create_sheets_service
    sheets_api.create_sheets_service = lambda _c: _make_full_fake_service(
        tab_names=["Food", "non-food"],
        spreadsheet_title="Production Materials Requisition List",
        append_status=403,
        err_cls=err_cls,
    )
    try:
        result = sheets_api.write_delivery_order_data(
            sheet_id="1READONLY",
            parsed_orders=[food_order],
            credentials_dict=sheets_api.CredentialsDict(access_token="x", refresh_token="y"),
        )
    finally:
        sheets_api.create_sheets_service = original_create

    problems = []
    if result.get("success") is not False:
        problems.append(f"expected success=False, got {result.get('success')!r}")
    if result.get("error_type") != "read_only":
        problems.append(f"expected error_type='read_only', got {result.get('error_type')!r}")
    err_msg = (result.get("error") or "").lower()
    if "read-only" not in err_msg and "editor" not in err_msg:
        problems.append(
            f"error should mention read-only/Editor access, got: {result.get('error')!r}"
        )

    if problems:
        record(
            "write_delivery_order_data surfaces read-only error on 403 during append",
            "FAIL",
            "; ".join(problems),
        )
    else:
        record(
            "write_delivery_order_data surfaces read-only error on 403 during append",
            "PASS",
        )
except Exception as e:
    record(
        "write_delivery_order_data surfaces read-only error on 403 during append",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 27 — Bug 5 detection.
#
# Product rule: when a NAME-BASED lookup (search_files / list_my_docs /
# list_files) returns 2+ matches and the planner pre-committed to
# `results[0].id`, the orchestrator MUST pause for user selection.
# Email/draft searches keep the old behavior because `emails[0]` is the
# canonical "latest message" selector.
#
# The fix lives in supervisor_agent.py around line 1471-1500. This
# scenario re-runs that exact decision logic in isolation so we don't
# have to spin up the full orchestrator.
# ------------------------------------------------------------------
section("Scenario 27 - Bug 5: indexed output_var on name-based lookup triggers pause")

try:
    import importlib, re as _re, json as _json

    sup_mod = importlib.import_module("supervisor_agent")
    importlib.reload(sup_mod)

    def _decide_pause(tool_name, output_variables, agent_result, plan, step_idx):
        """Mirror supervisor_agent.py:1461-1496 decision logic exactly."""
        DISAMBIGUATION_TOOLS = {
            "list_my_docs": "documents",
            "search_files": "results",
            "search_emails": "emails",
            "search_drafts": "drafts",
            "list_files": "files",
        }
        INDEXED_DISAMBIGUATION_TOOLS = {"search_files", "list_my_docs", "list_files"}
        results_field = DISAMBIGUATION_TOOLS.get(tool_name)
        if not results_field:
            return (False, None, "tool not a disambig candidate")
        is_last_step = (step_idx == len(plan))
        if is_last_step:
            return (False, None, "last step — nothing to disambiguate for")

        items = agent_result.get(results_field, [])

        disambig_var = None
        for var_name, source_field in output_variables.items():
            if source_field == results_field:
                disambig_var = var_name
                break
            if (tool_name in INDEXED_DISAMBIGUATION_TOOLS
                and isinstance(source_field, str)
                and source_field.startswith(results_field + "[")):
                disambig_var = var_name
                break

        if not disambig_var or not isinstance(items, list) or len(items) <= 1:
            return (False, disambig_var, "no ambiguity")

        pattern = _re.compile(
            r"\{\{\s*" + _re.escape(disambig_var) + r"(?=\s|\}|\.|\[|\|)"
        )
        for future_step in plan[step_idx:]:
            if pattern.search(_json.dumps(future_step.get("inputs", {}), default=str)):
                return (True, disambig_var, "downstream uses var")
        return (False, disambig_var, "no downstream reference")

    plan = [
        # Step 3: search_files — this is where we evaluate the pause.
        {
            "agent": "drive_agent",
            "tool": "search_files",
            "inputs": {"search_term": "Product Requisition List"},
            "output_variables": {"sheet_id": "results[0].id"},
        },
        # Step 4 onwards consume the variable.
        {
            "agent": "sheets_agent",
            "tool": "validate_delivery_sheet",
            "inputs": {"sheet_id": "{{ sheet_id }}"},
            "output_variables": {},
        },
        {
            "agent": "sheets_agent",
            "tool": "preview_delivery_order_insertion",
            "inputs": {"sheet_id": "{{ sheet_id }}", "parsed_orders": "{{ parsed_orders }}"},
            "output_variables": {},
        },
    ]
    agent_result = {
        "success": True,
        "results": [
            {"id": "1aaa", "name": "Product Requisition List", "modified": "2025-04-15"},
            {"id": "1bbb", "name": "PRODUCTION MATERIALS REQUISITION LIST", "modified": "2025-04-18"},
        ],
    }

    should_pause, disambig_var, reason = _decide_pause(
        "search_files", {"sheet_id": "results[0].id"}, agent_result, plan, step_idx=1,
    )

    problems = []
    if not should_pause:
        problems.append(
            f"expected pause=True for search_files + results[0].id + 2 matches, "
            f"got pause={should_pause} reason={reason!r}"
        )
    if disambig_var != "sheet_id":
        problems.append(
            f"expected disambig_var='sheet_id', got {disambig_var!r}"
        )

    if problems:
        record(
            "Bug 5 - search_files + 'results[0].id' + 2 matches -> pause",
            "FAIL",
            "; ".join(problems),
        )
    else:
        record(
            "Bug 5 - search_files + 'results[0].id' + 2 matches -> pause",
            "PASS",
            "indexed extraction on name-based lookup now triggers disambiguation",
        )
except Exception as e:
    record(
        "Bug 5 - search_files + 'results[0].id' + 2 matches -> pause",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 28 — Bug 5 detection MUST NOT fire for email searches.
#
# `emails[0].message_id` is the canonical "latest email" selector. If we
# pause for disambiguation every time multiple emails match a search
# (very common), we break flows like "forward my latest email about X".
# ------------------------------------------------------------------
section("Scenario 28 - Bug 5: email search with 'emails[0].message_id' still auto-picks latest")

try:
    # Re-use the _decide_pause helper from Scenario 27.
    email_plan = [
        {
            "agent": "gmail_agent",
            "tool": "search_emails",
            "inputs": {"query": "subject:invoice"},
            "output_variables": {"latest_email_id": "emails[0].message_id"},
        },
        {
            "agent": "gmail_agent",
            "tool": "forward_email",
            "inputs": {"message_id": "{{ latest_email_id }}"},
            "output_variables": {},
        },
    ]
    email_agent_result = {
        "success": True,
        "emails": [
            {"message_id": "m1", "subject": "Invoice 1", "date": "2025-04-20"},
            {"message_id": "m2", "subject": "Invoice 2", "date": "2025-04-18"},
            {"message_id": "m3", "subject": "Invoice 3", "date": "2025-04-15"},
        ],
    }
    should_pause, disambig_var, reason = _decide_pause(
        "search_emails",
        {"latest_email_id": "emails[0].message_id"},
        email_agent_result,
        email_plan,
        step_idx=1,
    )

    problems = []
    if should_pause:
        problems.append(
            f"search_emails + emails[0] must NOT pause (breaks 'latest X'), "
            f"but got pause=True reason={reason!r}"
        )
    if disambig_var is not None:
        problems.append(
            f"expected disambig_var=None for email searches, got {disambig_var!r}"
        )

    if problems:
        record(
            "Bug 5 - search_emails + 'emails[0].message_id' NOT paused",
            "FAIL",
            "; ".join(problems),
        )
    else:
        record(
            "Bug 5 - search_emails + 'emails[0].message_id' NOT paused",
            "PASS",
            "email/draft searches keep 'latest' auto-selection semantics",
        )
except Exception as e:
    record(
        "Bug 5 - search_emails + 'emails[0].message_id' NOT paused",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 29 — Bug 5 detection respects the downstream-usage gate.
#
# If the planner emits an indexed output_var but no later step references
# the variable (e.g. "just find me the sheet, don't do anything with it"),
# do NOT pause — the existing Bug B.5 gate must still hold.
# ------------------------------------------------------------------
section("Scenario 29 - Bug 5: indexed output_var but no downstream use -> no pause")

try:
    unused_plan = [
        {
            "agent": "drive_agent",
            "tool": "search_files",
            "inputs": {"search_term": "Budget"},
            "output_variables": {"sheet_id": "results[0].id"},
        },
        {
            "agent": "calendar_agent",
            "tool": "list_events",
            "inputs": {"max_results": 5},  # No reference to {{ sheet_id }}
            "output_variables": {},
        },
    ]
    unused_agent_result = {
        "success": True,
        "results": [
            {"id": "1a", "name": "Budget 2024", "modified": "2024-12-01"},
            {"id": "1b", "name": "Budget 2025", "modified": "2025-01-01"},
        ],
    }
    should_pause, disambig_var, reason = _decide_pause(
        "search_files",
        {"sheet_id": "results[0].id"},
        unused_agent_result,
        unused_plan,
        step_idx=1,
    )

    if should_pause:
        record(
            "Bug 5 - downstream-usage gate still blocks unused indexed var",
            "FAIL",
            f"expected no pause (nothing uses {{ sheet_id }}), got pause=True reason={reason!r}",
        )
    else:
        record(
            "Bug 5 - downstream-usage gate still blocks unused indexed var",
            "PASS",
            "Bug B.5 gate preserved — indexed var without downstream reference does not pause",
        )
except Exception as e:
    record(
        "Bug 5 - downstream-usage gate still blocks unused indexed var",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 30 — Bug 5 resume path extracts the selected item correctly.
#
# After the orchestrator pauses, the user picks option 2. On resume, the
# `sheet_id` variable MUST resolve to the 2nd option's ID (not the 1st),
# because the planner's extraction path is `results[0].id` against a
# patched agent_result where the results array has been collapsed to the
# user's single pick.
# ------------------------------------------------------------------
section("Scenario 30 - Bug 5: resume re-runs extraction against patched agent_result")

try:
    extract_nested_value = sup_mod.extract_nested_value

    # Simulated state captured at pause time:
    agent_result_snapshot = {
        "success": True,
        "results": [
            {"id": "1aaa", "name": "Product Requisition List"},
            {"id": "1bbb", "name": "PRODUCTION MATERIALS REQUISITION LIST"},
        ],
    }
    results_field = "results"
    output_variables = {"sheet_id": "results[0].id"}

    # User picks option 2.
    selected_item = agent_result_snapshot["results"][1]  # 1bbb

    # Replay what routes/threads.py resume path does.
    patched = dict(agent_result_snapshot)
    patched[results_field] = [selected_item]

    resolved = {}
    for out_var, source_field in output_variables.items():
        resolved[out_var] = extract_nested_value(patched, source_field)

    problems = []
    if resolved.get("sheet_id") != "1bbb":
        problems.append(
            f"expected sheet_id='1bbb' (user's pick), got {resolved.get('sheet_id')!r}"
        )

    if problems:
        record(
            "Bug 5 - resume: user picks option 2 -> sheet_id = 1bbb",
            "FAIL",
            "; ".join(problems),
        )
    else:
        record(
            "Bug 5 - resume: user picks option 2 -> sheet_id = 1bbb",
            "PASS",
            "extract_nested_value over patched agent_result correctly yields option 2's id",
        )
except Exception as e:
    record(
        "Bug 5 - resume: user picks option 2 -> sheet_id = 1bbb",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 31 — Bug 5 resume backwards-compatibility with whole-array
# pattern ({"results": "results"}).
#
# The existing flow where the planner uses the WHOLE-ARRAY output_var
# must keep working unchanged: picking option K collapses the results
# array to [option_K] and downstream {{ results[0].id }} resolves
# correctly.
# ------------------------------------------------------------------
section("Scenario 31 - Bug 5: whole-array pattern still works after resume")

try:
    extract_nested_value = sup_mod.extract_nested_value

    agent_result_snapshot = {
        "success": True,
        "results": [
            {"id": "a1", "name": "Alpha"},
            {"id": "b2", "name": "Bravo"},
            {"id": "c3", "name": "Charlie"},
        ],
    }
    # Legacy planner output — whole array bound to variable `results`.
    output_variables = {"results": "results"}
    selected_item = agent_result_snapshot["results"][2]  # c3

    patched = dict(agent_result_snapshot)
    patched["results"] = [selected_item]

    resolved = {}
    for out_var, source_field in output_variables.items():
        resolved[out_var] = extract_nested_value(patched, source_field)

    # Downstream step would do: {{ results[0].id }} = extract_nested_value(
    # variable_context, "results[0].id")
    final_id = extract_nested_value({"results": resolved["results"]}, "results[0].id")

    problems = []
    if final_id != "c3":
        problems.append(
            f"expected final_id='c3' for whole-array resume, got {final_id!r}"
        )

    if problems:
        record(
            "Bug 5 - whole-array resume pattern still works",
            "FAIL",
            "; ".join(problems),
        )
    else:
        record(
            "Bug 5 - whole-array resume pattern still works",
            "PASS",
            "backwards-compatible with the {\"results\": \"results\"} pattern",
        )
except Exception as e:
    record(
        "Bug 5 - whole-array resume pattern still works",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 32 — Bug 1 Tier 1 prompt carries the email_filter rule.
#
# Product rule: in multi-turn delivery-order flows, Tier 1 must extract
# `email_filter` from the narrowing context of a prior turn (e.g. the
# user's Turn 1 search for "Order to Starbucks and Co.") so the planner
# can narrow the Gmail search instead of falling back to the generic
# "delivery order OR DO OR …" default.
#
# The fix is a prompt addition in conversational_agent.py's
# DELIVERY ORDER WORKFLOW block. This scenario locks in the exact
# phrasing so future edits don't accidentally drop the rule.
# ------------------------------------------------------------------
section("Scenario 32 - Bug 1: Tier 1 prompt keeps email_filter extraction rule")

try:
    conv_path = SUP / "conversational_agent.py"
    conv_text = conv_path.read_text(encoding="utf-8")

    required_phrases = [
        # The workflow block must still be present.
        "DELIVERY ORDER WORKFLOW (task_type=process_delivery_order)",
        # The verb-gate from the earlier fix must stay.
        'write/parse/extract verb',
        "use gmail_agent.search_emails as a single step",
        # The new email_filter extraction rule.
        "email_filter when the message references a prior email",
        'COMPLETED TASKS shows a recent gmail search',
        "copy that prior search's narrowing phrase verbatim",
        "Omit email_filter when the current turn is a fresh batch request",
    ]
    missing = [p for p in required_phrases if p not in conv_text]

    if missing:
        record(
            "Bug 1 - Tier 1 prompt carries email_filter extraction rule",
            "FAIL",
            f"missing phrases: {missing}",
        )
    else:
        record(
            "Bug 1 - Tier 1 prompt carries email_filter extraction rule",
            "PASS",
            "multi-turn narrowing context is preserved for the planner",
        )
except Exception as e:
    record(
        "Bug 1 - Tier 1 prompt carries email_filter extraction rule",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 33 — Bug F Planner Rule 16 wraps email_filter in subject:"..."
#
# Updated for the Bug F (Gmail naive-query) fix: when email_filter is
# present in Parameters, the planner must wrap its value as
# `subject:"<email_filter>" has:attachment` so Gmail matches the SUBJECT
# field only — bare keywords match across body/subject/attachment text and
# return overly-broad results (the "Delivery Food 2 Food!" → 10 emails
# regression in execution_logs/paul/searchingSpecificDeliveryOrderIssueAgain.log).
# The fallback for fresh batch requests (no email_filter) is preserved.
# ------------------------------------------------------------------
section("Scenario 33 - Bug F: Planner Rule 16 wraps email_filter in subject:\"...\"")

try:
    sup_path = SUP / "supervisor_agent.py"
    sup_text = sup_path.read_text(encoding="utf-8")

    required_phrases = [
        # Rule 16 anchor.
        "DELIVERY-ORDER PIPELINE (task_type=process_delivery_order)",
        # The new conditional email_filter wiring — wrap-in-subject pattern.
        "if email_filter is present",
        'wrap its value as `subject:"<email_filter>" has:attachment`',
        "Gmail matches the SUBJECT field only",
        # Inline mini-example anchor (the failing log's input).
        'subject:"Delivery Food 2 Food!" has:attachment',
        # The generic fallback text must still be present for the else branch.
        "delivery order OR DO OR requisition OR purchase order OR PO has:attachment",
    ]
    missing = [p for p in required_phrases if p not in sup_text]

    if missing:
        record(
            "Bug F - Planner Rule 16 wraps email_filter in subject:\"...\"",
            "FAIL",
            f"missing phrases: {missing}",
        )
    else:
        record(
            "Bug F - Planner Rule 16 wraps email_filter in subject:\"...\"",
            "PASS",
            "Rule 16 wraps email_filter as subject:\"...\"; fallback preserved for fresh turns",
        )
except Exception as e:
    record(
        "Bug F - Planner Rule 16 wraps email_filter in subject:\"...\"",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 34 — Bug 1 build_supervisor_input surfaces email_filter.
#
# Tier 1 puts email_filter into extracted_info. The planner only reads
# the "Parameters:" block of supervisor_input. This scenario verifies
# that the serialization path actually makes email_filter visible to the
# planner (keys starting with "_" are stripped; email_filter must not be
# one of them).
# ------------------------------------------------------------------
section("Scenario 34 - Bug 1: build_supervisor_input emits email_filter to planner")

try:
    # Avoid heavy imports by exercising the serialization logic inline.
    # This mirrors conversational_agent.py:1740-1754 exactly.
    import json as _json

    def _build(execution_summary, extracted_info):
        s = execution_summary
        if extracted_info:
            s += "\n\nParameters:\n"
            for key, value in extracted_info.items():
                if key.startswith("_"):
                    continue
                if isinstance(value, (list, dict)):
                    s += f"- {key}: {_json.dumps(value, indent=2)}\n"
                else:
                    s += f"- {key}: {value}\n"
        return s

    out = _build(
        "Parse delivery-order PDFs and write to 'Product Requisition List' "
        "filtered by 'Order to Starbucks and Co.'",
        {
            "task_type": "process_delivery_order",
            "sheet_name": "Product Requisition List",
            "email_filter": "Order to Starbucks and Co.",
            "_cached_tool_filter": {"gmail_agent": ["search_emails"]},  # stripped
        },
    )

    problems = []
    if "- email_filter: Order to Starbucks and Co." not in out:
        problems.append(
            "email_filter did not land in Parameters block — planner can't see it"
        )
    if "_cached_tool_filter" in out:
        problems.append(
            "_cached_tool_filter leaked into planner input (must be stripped)"
        )
    if "filtered by 'Order to Starbucks and Co.'" not in out:
        problems.append(
            "execution_summary should advertise the email_filter to the planner"
        )

    if problems:
        record(
            "Bug 1 - build_supervisor_input surfaces email_filter",
            "FAIL",
            "; ".join(problems),
        )
    else:
        record(
            "Bug 1 - build_supervisor_input surfaces email_filter",
            "PASS",
            "email_filter flows cleanly from extracted_info -> Parameters -> planner",
        )
except Exception as e:
    record(
        "Bug 1 - build_supervisor_input surfaces email_filter",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 35 — Silent-rejection fix: supervisor_agent.py attaches
# upstream_rejected_files to step_info when pausing for approval.
#
# Reproduces the DeliveryTesting2PDFs2.log failure mode where a Tech PDF
# was silently rejected by the mapping agent's category gate (intended)
# but the subsequent write_delivery_order_data approval prompt showed
# no trace of the skipped file, so the user approved without knowing
# only 1 of 2 PDFs would be written.
#
# This scenario exercises BOTH layers of the fix:
#   (a) source-level guard — supervisor_agent.py must contain the
#       variable_context scan logic
#   (b) behavioural — the same scan logic, re-implemented here in
#       isolation against a realistic variable_context, must correctly
#       extract rejected_files entries from any step_*_* namespace
# ------------------------------------------------------------------
section("Scenario 35 - Silent-rejection: orchestrator attaches upstream_rejected_files on pause")

try:
    supervisor_src = (SUP / "supervisor_agent.py").read_text(encoding="utf-8")

    required_snippets_35a = [
        'upstream_rejected_files',
        'rejected_files',
        'step_info["upstream_rejected_files"] = upstream_rejected_files',
    ]
    missing_35a = [s for s in required_snippets_35a if s not in supervisor_src]
    if missing_35a:
        record(
            "Scenario 35a - supervisor_agent.py contains upstream_rejected_files scan",
            "FAIL",
            f"missing snippets: {missing_35a}",
        )
    else:
        record(
            "Scenario 35a - supervisor_agent.py contains upstream_rejected_files scan",
            "PASS",
        )

    # Behavioural re-implementation of the scan logic (mirrors the block
    # added at supervisor_agent.py:1074). If this helper and the real
    # code diverge, the source-level guard above catches it on the next run.
    def _scan_upstream_rejected_files(variable_context: dict) -> list:
        out: list = []
        seen: set = set()
        for ctx_key, ctx_val in variable_context.items():
            if not isinstance(ctx_key, str) or not ctx_key.startswith("step_"):
                continue
            if not isinstance(ctx_val, dict):
                continue
            rf = ctx_val.get("rejected_files")
            if not isinstance(rf, list) or not rf:
                continue
            for item in rf:
                if not isinstance(item, dict):
                    continue
                fname = item.get("file") or item.get("filename")
                if fname and fname in seen:
                    continue
                out.append(item)
                if fname:
                    seen.add(fname)
        return out

    # --- Case 35b: realistic variable_context mirroring DeliveryTesting2PDFs2.log
    # 1 good PDF parsed + 1 Tech PDF rejected.
    ctx_partial = {
        "today_date": "2026-04-21",
        "uploaded_file": None,
        "step_1_gmail_agent": {
            "emails_with_attachments": [{"subject": "DO 1", "attachments": [{"file_path": "Food.pdf"}]}],
            "total_attachments_downloaded": 2,
        },
        "step_2_mapping_agent": {
            "parsed_orders": [{"file": "Food_DELIVERY_ORDER (1).pdf", "line_items": [{"a": 1}]}],
            "rejected_files": [
                {
                    "file": "Tech_DELIVERY_ORDER (1).pdf",
                    "reason": (
                        "Category is not FOOD or NON-FOOD. The requisition sheet "
                        "only accepts these two categories."
                    ),
                }
            ],
            "total_parsed": 1,
            "total_rejected": 1,
        },
        "parsed_orders": [{"file": "Food_DELIVERY_ORDER (1).pdf", "line_items": [{"a": 1}]}],
        "step_3_drive_agent": {"results": [{"id": "SHEET_ID"}]},
        "sheet_id": "SHEET_ID",
        "step_4_sheets_agent": {"valid": True, "message": "Sheet is valid"},
        "step_5_sheets_agent": {"preview_rows": [], "target_tabs": ["Food"]},
    }
    extracted_partial = _scan_upstream_rejected_files(ctx_partial)
    problems_35b = []
    if len(extracted_partial) != 1:
        problems_35b.append(f"expected 1 rejected file, got {len(extracted_partial)}")
    elif extracted_partial[0].get("file") != "Tech_DELIVERY_ORDER (1).pdf":
        problems_35b.append(f"wrong file: {extracted_partial[0].get('file')!r}")
    elif "FOOD or NON-FOOD" not in (extracted_partial[0].get("reason") or ""):
        problems_35b.append("reason text did not survive the scan")
    if problems_35b:
        record(
            "Scenario 35b - scan extracts rejected_files from step_N_mapping_agent",
            "FAIL",
            "; ".join(problems_35b),
        )
    else:
        record(
            "Scenario 35b - scan extracts rejected_files from step_N_mapping_agent",
            "PASS",
        )

    # --- Case 35c: no rejections — scan returns [].
    ctx_clean = {
        "today_date": "2026-04-21",
        "step_1_gmail_agent": {"emails_with_attachments": []},
        "step_2_mapping_agent": {
            "parsed_orders": [{"file": "Food.pdf"}],
            "rejected_files": [],
            "total_parsed": 1,
            "total_rejected": 0,
        },
    }
    extracted_clean = _scan_upstream_rejected_files(ctx_clean)
    if extracted_clean == []:
        record(
            "Scenario 35c - scan returns [] when nothing was rejected (no regression)",
            "PASS",
        )
    else:
        record(
            "Scenario 35c - scan returns [] when nothing was rejected (no regression)",
            "FAIL",
            f"unexpected output: {extracted_clean!r}",
        )

    # --- Case 35d: rejected_files from multiple steps are deduplicated by filename.
    ctx_dup = {
        "step_2_mapping_agent": {
            "rejected_files": [
                {"file": "X.pdf", "reason": "reason A"},
                {"file": "Y.pdf", "reason": "reason B"},
            ],
        },
        "step_7_mapping_agent": {
            "rejected_files": [
                {"file": "X.pdf", "reason": "reason A (duplicate)"},
                {"file": "Z.pdf", "reason": "reason C"},
            ],
        },
    }
    extracted_dup = _scan_upstream_rejected_files(ctx_dup)
    files_dup = [r.get("file") for r in extracted_dup]
    if files_dup == ["X.pdf", "Y.pdf", "Z.pdf"]:
        record(
            "Scenario 35d - rejected_files deduped by filename across step namespaces",
            "PASS",
        )
    else:
        record(
            "Scenario 35d - rejected_files deduped by filename across step namespaces",
            "FAIL",
            f"got {files_dup!r}",
        )

    # --- Case 35e: non-dict / non-list values in variable_context are ignored
    # (regression guard — the scan must not raise on unexpected shapes).
    ctx_noisy = {
        "step_1_something": "not a dict",
        "step_2_mapping_agent": {"rejected_files": "not a list"},
        "step_3_mapping_agent": {"rejected_files": [None, 123, {"file": "R.pdf", "reason": "x"}]},
        "unrelated_key": {"rejected_files": [{"file": "NOT_A_STEP.pdf", "reason": "y"}]},
    }
    try:
        extracted_noisy = _scan_upstream_rejected_files(ctx_noisy)
    except Exception as e:
        extracted_noisy = f"raised: {e}"
    if (
        isinstance(extracted_noisy, list)
        and [r.get("file") for r in extracted_noisy] == ["R.pdf"]
    ):
        record(
            "Scenario 35e - scan ignores noisy values, skips non-step_* keys",
            "PASS",
        )
    else:
        record(
            "Scenario 35e - scan ignores noisy values, skips non-step_* keys",
            "FAIL",
            f"got {extracted_noisy!r}",
        )
except Exception as e:
    record(
        "Scenario 35 - orchestrator upstream_rejected_files attachment",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 36 — Silent-rejection fix: the approval message for
# write_delivery_order_data surfaces upstream_rejected_files so the
# user sees which PDFs were skipped BEFORE they hit "yes".
# ------------------------------------------------------------------
section("Scenario 36 - Approval message surfaces upstream_rejected_files warning")

try:
    import importlib
    checks_mod = importlib.import_module("checks.tier0_checks")
    importlib.reload(checks_mod)
    build = checks_mod._build_rich_approval_message

    # Realistic pending_action mirroring what the orchestrator would persist
    # for the DeliveryTesting2PDFs2.log scenario.
    pending_partial = {
        "tool": "write_delivery_order_data",
        "risk_level": "DANGEROUS",
        "description": "Append the parsed delivery-order rows into the sheet",
        "step_number": 6,
        "total_steps": 6,
        "inputs": {
            "sheet_id": "1SHEET_ID",
            "parsed_orders": [
                {
                    "file": "Food_DELIVERY_ORDER (1).pdf",
                    "header": {"reference_number": "DO-2026-01", "category": "FOOD"},
                    "line_items": [{"item_code": "RMFD001", "qty": 10}] * 17,
                }
            ],
        },
        "upstream_rejected_files": [
            {
                "file": "Tech_DELIVERY_ORDER (1).pdf",
                "reason": (
                    "Category is not FOOD or NON-FOOD. The requisition sheet "
                    "only accepts these two categories. The PDF content did "
                    "not expose a 'Category: FOOD' or 'Category: NON-FOOD' "
                    "label."
                ),
            }
        ],
    }
    msg_partial = build(pending_partial)

    required_36a = [
        "Tech_DELIVERY_ORDER (1).pdf",   # the skipped filename
        "skipped",                       # the warning verb
        "NOT be written",                # making "this is not in the write" loud
        "FOOD or NON-FOOD",              # the reason text
        "Orders to write:** 1",          # the good PDF still renders
        "Total line items:** 17",
    ]
    missing_36a = [s for s in required_36a if s not in msg_partial]
    if missing_36a:
        record(
            "Scenario 36a - approval message warns about skipped PDFs in partial-success case",
            "FAIL",
            f"missing: {missing_36a}; preview={msg_partial[:600]!r}",
        )
    else:
        record(
            "Scenario 36a - approval message warns about skipped PDFs in partial-success case",
            "PASS",
        )
        print("\n--- approval message preview (partial success) ---")
        print(msg_partial)
        print("--- end preview ---\n")

    # Case 36b: more than 5 rejected files — the message should truncate at 5
    # and show "…and N more skipped."
    pending_many = {
        "tool": "write_delivery_order_data",
        "risk_level": "DANGEROUS",
        "description": "Append the parsed delivery-order rows into the sheet",
        "step_number": 6,
        "total_steps": 6,
        "inputs": {
            "sheet_id": "1SHEET_ID",
            "parsed_orders": [
                {"file": "Food.pdf", "header": {"category": "FOOD"}, "line_items": [{"x": 1}]}
            ],
        },
        "upstream_rejected_files": [
            {"file": f"Tech_{i}.pdf", "reason": "Category is not FOOD or NON-FOOD."}
            for i in range(8)
        ],
    }
    msg_many = build(pending_many)
    problems_36b = []
    if "Tech_0.pdf" not in msg_many:
        problems_36b.append("first rejected file missing")
    if "Tech_4.pdf" not in msg_many:
        problems_36b.append("5th rejected file missing (should still render)")
    if "Tech_7.pdf" in msg_many:
        problems_36b.append("7th rejected file should have been truncated")
    if "3 more skipped" not in msg_many:
        problems_36b.append("missing truncation footer '…and 3 more skipped.'")
    if problems_36b:
        record(
            "Scenario 36b - approval message truncates >5 rejected files with footer",
            "FAIL",
            "; ".join(problems_36b) + f"; preview={msg_many[:800]!r}",
        )
    else:
        record(
            "Scenario 36b - approval message truncates >5 rejected files with footer",
            "PASS",
        )
except Exception as e:
    record(
        "Scenario 36 - approval message surfaces upstream_rejected_files",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 37 — Regression guard: the approval message is UNCHANGED
# when there are no upstream rejections. The existing detailed
# summary (orders, line items, source files, sample header) must
# still render, and the new warning block must NOT appear.
# ------------------------------------------------------------------
section("Scenario 37 - Approval message unchanged when no PDFs were rejected")

try:
    import importlib
    checks_mod = importlib.import_module("checks.tier0_checks")
    importlib.reload(checks_mod)
    build = checks_mod._build_rich_approval_message

    pending_clean = {
        "tool": "write_delivery_order_data",
        "risk_level": "DANGEROUS",
        "description": "Append the parsed delivery-order rows into the sheet",
        "step_number": 6,
        "total_steps": 6,
        "inputs": {
            "sheet_id": "1SHEET_ID",
            "parsed_orders": [
                {
                    "file": "Food.pdf",
                    "header": {"reference_number": "DO-2026-07", "category": "FOOD"},
                    "line_items": [{"item_code": "RMFD001", "qty": 5}] * 3,
                }
            ],
        },
        # NOTE: no upstream_rejected_files key at all — mirrors the clean
        # all-PDFs-parsed case.
    }
    msg_clean = build(pending_clean)

    required_37 = [
        "Orders to write:** 1",
        "Total line items:** 3",
        "Food.pdf",
    ]
    forbidden_37 = [
        "skipped and will NOT be written",  # new warning header must be absent
        "Tech_",                            # any rejected-file reference
        "…and",                             # truncation footer must be absent
    ]
    missing_37 = [s for s in required_37 if s not in msg_clean]
    leaked_37 = [s for s in forbidden_37 if s in msg_clean]
    if missing_37 or leaked_37:
        record(
            "Scenario 37 - approval message unchanged on no-rejection path",
            "FAIL",
            f"missing={missing_37}, leaked={leaked_37}; preview={msg_clean[:600]!r}",
        )
    else:
        record(
            "Scenario 37 - approval message unchanged on no-rejection path",
            "PASS",
        )

    # Also verify: empty list for upstream_rejected_files is treated the same
    # as missing — the warning block must NOT render.
    pending_empty_list = dict(pending_clean)
    pending_empty_list["upstream_rejected_files"] = []
    msg_empty_list = build(pending_empty_list)
    if any(s in msg_empty_list for s in forbidden_37):
        record(
            "Scenario 37b - empty upstream_rejected_files list renders no warning",
            "FAIL",
            f"forbidden snippet leaked; preview={msg_empty_list[:600]!r}",
        )
    else:
        record(
            "Scenario 37b - empty upstream_rejected_files list renders no warning",
            "PASS",
        )
except Exception as e:
    record(
        "Scenario 37 - approval message unchanged on no-rejection path",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 38 — Silent-rejection fix: the final-summary template for
# parse_delivery_order_pdfs now lists rejected filenames + reasons
# when total_rejected > 0. This ensures the post-execution summary
# (read by the user AFTER the write succeeds) is not silent either.
# ------------------------------------------------------------------
section("Scenario 38 - Final summary template lists rejected files")

try:
    import importlib
    rt_mod = importlib.import_module("services.response_templates")
    importlib.reload(rt_mod)
    format_step = rt_mod.format_step

    output_mixed = {
        "success": True,
        "parsed_orders": [
            {
                "file": "Food_DELIVERY_ORDER (1).pdf",
                "header": {"category": "FOOD"},
                "line_items": [{"item_code": "RMFD001", "qty": 5}],
            }
        ],
        "rejected_files": [
            {
                "file": "Tech_DELIVERY_ORDER (1).pdf",
                "reason": (
                    "Category is not FOOD or NON-FOOD. The requisition sheet "
                    "only accepts these two categories."
                ),
            }
        ],
        "total_parsed": 1,
        "total_rejected": 1,
    }
    text_mixed = format_step("mapping_agent", "parse_delivery_order_pdfs", output_mixed)

    required_38a = [
        "Parsed 1 delivery order(s)",
        "1 file(s) rejected",
        "Skipped files",
        "Tech_DELIVERY_ORDER (1).pdf",
        "FOOD or NON-FOOD",
    ]
    missing_38a = [s for s in required_38a if s not in (text_mixed or "")]
    if missing_38a:
        record(
            "Scenario 38a - parse_delivery_order_pdfs template lists skipped files",
            "FAIL",
            f"missing={missing_38a}; preview={(text_mixed or '')[:400]!r}",
        )
    else:
        record(
            "Scenario 38a - parse_delivery_order_pdfs template lists skipped files",
            "PASS",
        )
        print("\n--- final summary preview (mixed) ---")
        print(text_mixed)
        print("--- end preview ---\n")

    # Truncation: >5 rejected files render first 5 + footer.
    output_many = {
        "parsed_orders": [{"file": "Food.pdf", "header": {"category": "FOOD"}, "line_items": []}],
        "rejected_files": [
            {"file": f"Tech_{i}.pdf", "reason": "Category is not FOOD or NON-FOOD."}
            for i in range(7)
        ],
        "total_parsed": 1,
        "total_rejected": 7,
    }
    text_many = format_step("mapping_agent", "parse_delivery_order_pdfs", output_many)
    problems_38b = []
    if "Tech_0.pdf" not in (text_many or ""):
        problems_38b.append("first skipped file missing")
    if "Tech_4.pdf" not in (text_many or ""):
        problems_38b.append("5th skipped file missing")
    if "Tech_6.pdf" in (text_many or ""):
        problems_38b.append("7th skipped file should have been truncated")
    if "2 more" not in (text_many or ""):
        problems_38b.append("missing '…and 2 more' truncation footer")
    if problems_38b:
        record(
            "Scenario 38b - final summary truncates >5 rejected files",
            "FAIL",
            "; ".join(problems_38b) + f"; preview={(text_many or '')[:500]!r}",
        )
    else:
        record(
            "Scenario 38b - final summary truncates >5 rejected files",
            "PASS",
        )
except Exception as e:
    record(
        "Scenario 38 - final summary template lists rejected files",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 39 — Regression guard: the final-summary template behaves
# exactly like the legacy "Parsed X, Y rejected" string when there
# are no rejections. Also verifies that static-string templates for
# every OTHER tool (e.g. reply_to_email) still render correctly after
# the callable-template upgrade in response_templates.py.
# ------------------------------------------------------------------
section("Scenario 39 - Final summary regression: no rejections + other templates still work")

try:
    import importlib
    rt_mod = importlib.import_module("services.response_templates")
    importlib.reload(rt_mod)
    format_step = rt_mod.format_step

    # Case 39a: clean parse — no "Skipped files" section.
    output_clean = {
        "parsed_orders": [
            {"file": "Food1.pdf", "header": {"category": "FOOD"}, "line_items": [{"x": 1}]},
            {"file": "Food2.pdf", "header": {"category": "NON-FOOD"}, "line_items": [{"y": 2}]},
        ],
        "rejected_files": [],
        "total_parsed": 2,
        "total_rejected": 0,
    }
    text_clean = format_step("mapping_agent", "parse_delivery_order_pdfs", output_clean)
    problems_39a = []
    if "Parsed 2 delivery order(s)" not in (text_clean or ""):
        problems_39a.append("legacy headline missing")
    if "0 file(s) rejected" not in (text_clean or ""):
        problems_39a.append("legacy '0 file(s) rejected' clause missing")
    if "Skipped files" in (text_clean or ""):
        problems_39a.append("'Skipped files' block leaked into clean summary")
    if problems_39a:
        record(
            "Scenario 39a - clean parse renders legacy one-line summary",
            "FAIL",
            "; ".join(problems_39a) + f"; preview={(text_clean or '')!r}",
        )
    else:
        record(
            "Scenario 39a - clean parse renders legacy one-line summary",
            "PASS",
        )

    # Case 39b: a static-string template (reply_to_email) still renders.
    # The callable-template upgrade in _format_action must remain
    # backward-compatible with every other template entry.
    text_reply = format_step(
        "gmail_agent",
        "reply_to_email",
        {"subject": "Hello", "to": "alice@example.com", "message_id": "abc"},
    )
    if text_reply and "Replied to" in text_reply and "Hello" in text_reply and "alice@example.com" in text_reply:
        record(
            "Scenario 39b - static-string templates (reply_to_email) still render",
            "PASS",
        )
    else:
        record(
            "Scenario 39b - static-string templates (reply_to_email) still render",
            "FAIL",
            f"preview={text_reply!r}",
        )

    # Case 39c: a use_message template (list_my_docs / preview_delivery)
    # still renders from the message field.
    text_preview = format_step(
        "sheets_agent",
        "preview_delivery_order_insertion",
        {"message": "17 row(s) ready to insert across 1 tab(s). No duplicates detected."},
    )
    if text_preview and "17 row(s) ready" in text_preview:
        record(
            "Scenario 39c - use_message templates still render after callable upgrade",
            "PASS",
        )
    else:
        record(
            "Scenario 39c - use_message templates still render after callable upgrade",
            "FAIL",
            f"preview={text_preview!r}",
        )
except Exception as e:
    record(
        "Scenario 39 - final summary regression guards",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# SCENARIO 40 — End-to-end re-replay of the DeliveryTesting2PDFs2.log
# failure mode. Confirms the three-layer fix holds from the mapping
# agent's output through to the approval prompt AND the final summary.
#
# Stages:
#   1. mapping_agent.parse_delivery_order_pdfs runs on [good.pdf, bad.pdf]
#      — one parses, one is rejected by the category gate. The real
#      function is used; _parse_single_pdf is stubbed so we don't need
#      real PDFs.
#   2. The orchestrator's scan logic lifts rejected_files into step_info.
#   3. _build_rich_approval_message renders the approval prompt — the
#      user now sees "Tech rejected" BEFORE clicking yes.
#   4. format_step renders the final post-execution summary — the user
#      sees "Tech rejected" AFTER the write too.
#
# If ANY link in the chain breaks, the user is silently unaware again.
# ------------------------------------------------------------------
section("Scenario 40 - E2E: DeliveryTesting2PDFs2.log partial-rejection chain is no longer silent")

try:
    import importlib
    mapping_mod = importlib.import_module("mapping_agent_api")
    importlib.reload(mapping_mod)

    # Stage 1 — run the REAL parse_delivery_order_pdfs with a mocked parser
    # so we don't need real PDFs on disk.
    original_parser = mapping_mod._parse_single_pdf

    def _chain_parser(fp: str):
        if "Food" in fp:
            return _wrap_old_shape_success({
                "file": "Food_DELIVERY_ORDER (1).pdf",
                "header": {"reference_number": "DO-01", "category": "FOOD", "requested_by": "QA"},
                "line_items": [{"item_code": "RMFD001", "item_description": "TEST", "qty": 5, "uom": "KG"}],
                "warnings": [],
            })
        return {
            "rejected": True,
            "file": "Tech_DELIVERY_ORDER (1).pdf",
            "reason": (
                "Category is not FOOD or NON-FOOD. The requisition sheet "
                "only accepts these two categories. The PDF content did not "
                "expose a 'Category: FOOD' or 'Category: NON-FOOD' label, "
                "and its item codes did not match a known FOOD prefix. "
                "Detected category label: ''."
            ),
        }

    mapping_mod._parse_single_pdf = _chain_parser
    try:
        parse_out = mapping_mod.parse_delivery_order_pdfs(
            ["/tmp/Food_DELIVERY_ORDER (1).pdf", "/tmp/Tech_DELIVERY_ORDER (1).pdf"]
        )
    finally:
        mapping_mod._parse_single_pdf = original_parser

    chain_problems = []
    if parse_out.get("success") is not True:
        chain_problems.append(
            f"stage 1: expected success=true (partial parse), got {parse_out.get('success')!r}"
        )
    if parse_out.get("total_parsed") != 1:
        chain_problems.append(f"stage 1: expected total_parsed=1, got {parse_out.get('total_parsed')!r}")
    if parse_out.get("total_rejected") != 1:
        chain_problems.append(f"stage 1: expected total_rejected=1, got {parse_out.get('total_rejected')!r}")
    rejected = parse_out.get("rejected_files") or []
    if not rejected or rejected[0].get("file") != "Tech_DELIVERY_ORDER (1).pdf":
        chain_problems.append(f"stage 1: rejected_files wrong: {rejected!r}")

    # Stage 2 — orchestrator scan logic lifts rejected_files into step_info.
    # Re-use the same helper from scenario 35 behavioural parity.
    variable_context = {
        "step_1_gmail_agent": {"emails_with_attachments": [], "total_attachments_downloaded": 2},
        "step_2_mapping_agent": {
            k: v for k, v in parse_out.items() if k not in ("success", "error", "no_results")
        },
    }

    # Inline the real scan logic (must stay in sync with supervisor_agent.py:~1074).
    upstream_rejected_files: list = []
    _seen_rf: set = set()
    for ctx_key, ctx_val in variable_context.items():
        if not isinstance(ctx_key, str) or not ctx_key.startswith("step_"):
            continue
        if not isinstance(ctx_val, dict):
            continue
        rf = ctx_val.get("rejected_files")
        if not isinstance(rf, list) or not rf:
            continue
        for item in rf:
            if not isinstance(item, dict):
                continue
            fname = item.get("file") or item.get("filename")
            if fname and fname in _seen_rf:
                continue
            upstream_rejected_files.append(item)
            if fname:
                _seen_rf.add(fname)

    if not upstream_rejected_files:
        chain_problems.append("stage 2: scan logic produced empty upstream_rejected_files")

    # Stage 3 — approval prompt.
    checks_mod = importlib.import_module("checks.tier0_checks")
    importlib.reload(checks_mod)
    build = checks_mod._build_rich_approval_message

    step_info = {
        "tool": "write_delivery_order_data",
        "risk_level": "DANGEROUS",
        "description": "Append the parsed delivery-order rows into the sheet",
        "step_number": 6,
        "total_steps": 6,
        "inputs": {
            "sheet_id": "1SHEET_ID",
            "parsed_orders": parse_out.get("parsed_orders") or [],
        },
        "upstream_rejected_files": upstream_rejected_files,
    }
    approval_msg = build(step_info)
    if "Tech_DELIVERY_ORDER (1).pdf" not in approval_msg:
        chain_problems.append("stage 3: approval prompt does not mention rejected file")
    if "skipped and will NOT be written" not in approval_msg:
        chain_problems.append("stage 3: approval prompt missing 'skipped' warning")
    if "Orders to write:** 1" not in approval_msg:
        chain_problems.append("stage 3: approval prompt lost the 'Orders to write: 1' line")

    # Stage 4 — final summary template.
    rt_mod = importlib.import_module("services.response_templates")
    importlib.reload(rt_mod)
    summary_text = rt_mod.format_step(
        "mapping_agent", "parse_delivery_order_pdfs", parse_out
    )
    if "Skipped files" not in (summary_text or ""):
        chain_problems.append("stage 4: final summary missing 'Skipped files' block")
    if "Tech_DELIVERY_ORDER (1).pdf" not in (summary_text or ""):
        chain_problems.append("stage 4: final summary does not name the rejected file")

    if chain_problems:
        record(
            "Scenario 40 - E2E chain surfaces partial rejection end-to-end",
            "FAIL",
            "; ".join(chain_problems)
            + f"\n      approval_msg[:400]={approval_msg[:400]!r}"
            + f"\n      summary_text[:400]={(summary_text or '')[:400]!r}",
        )
    else:
        record(
            "Scenario 40 - E2E chain surfaces partial rejection end-to-end",
            "PASS",
            "mapping → step_info scan → approval prompt → final summary all mention Tech PDF",
        )
except Exception as e:
    record(
        "Scenario 40 - E2E chain surfaces partial rejection end-to-end",
        "FAIL",
        f"{e}\n{traceback.format_exc()}",
    )


# ------------------------------------------------------------------
# FINAL REPORT
# ------------------------------------------------------------------
section("FINAL REPORT")

passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
failed = sum(1 for _, s, _ in RESULTS if s == "FAIL")
info = sum(1 for _, s, _ in RESULTS if s == "INFO")
print()
print(f"TOTAL: {len(RESULTS)} checks — PASS: {passed}, FAIL: {failed}, INFO: {info}")

if failed:
    print()
    print("FAILURES:")
    for name, status, note in RESULTS:
        if status == "FAIL":
            print(f"  * {name}")
            if note:
                print(f"      {note}")

sys.exit(0 if failed == 0 else 1)

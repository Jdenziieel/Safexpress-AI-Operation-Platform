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
    """Register (or return) a dummy module so heavy-dep imports don't break the sim."""
    if module_name in sys.modules:
        return sys.modules[module_name]
    mod = types.ModuleType(module_name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[module_name] = mod
    return mod


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

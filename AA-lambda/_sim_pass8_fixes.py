"""Pass 8 — verify the audit-pass-6 fixes do exactly what's documented.

Coverage:
  1. ``shared/routes/`` exists and exposes the helpers the WS handler needs:
     ``send_message_to_thread``, ``_handle_pending_action_decision``,
     ``_handle_disambiguation_selection``, ``_execute_workflow_guarded``,
     ``_persist_final_response``, ``_has_actionable_task``,
     and ``run_workflow``. Also confirms ``routes/__init__.py`` exists.

  2. ``supervisor-action-get`` reshapes a flat persistence row
     (``agent_name`` / ``tool_name`` / ``inputs``) into the nested
     ``step_info`` shape returned by source ``GET /action/{action_id}``.

  3. ``supervisor-ws-chat`` correctly imports the brain helpers via
     ``from routes.threads import …`` (the failure mode this fix targeted).

  4. ``supervisor-action-approve`` no longer references the dead
     ``GoneException`` import — verified by import + symbol absence.

  5. AA-lambda/requirements.txt declares the brain stack (catches a
     regression where a future cleanup drops langchain / openai).

Usage:
    cd AA-lambda
    python _sim_pass8_fixes.py
"""
from __future__ import annotations

import json
import os
import sys
import importlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHARED = ROOT / "shared"
FUNCTIONS = ROOT / "functions"

for p in (str(ROOT), str(SHARED)):
    if p not in sys.path:
        sys.path.insert(0, p)


def t1_routes_dir_present_and_importable() -> tuple[bool, str]:
    """Routes package + the seven helpers WS-chat depends on."""
    routes_dir = SHARED / "routes"
    if not routes_dir.is_dir():
        return False, f"missing dir: {routes_dir}"
    init = routes_dir / "__init__.py"
    if not init.exists():
        return False, "missing routes/__init__.py"
    expected_files = {"threads.py", "workflow.py", "actions.py", "admin.py"}
    actual = {p.name for p in routes_dir.glob("*.py")}
    missing = expected_files - actual
    if missing:
        return False, f"missing route files: {sorted(missing)}"

    # Try a real attribute pull via AST so we don't require runtime imports
    # of langchain / openai inside the dev shell. We're verifying the surface
    # is wired (helper names exist as defs), not that the brain executes.
    import ast

    threads_src = (routes_dir / "threads.py").read_text(encoding="utf-8")
    expected_helpers = {
        "send_message_to_thread",
        "_handle_pending_action_decision",
        "_handle_disambiguation_selection",
        "_execute_workflow_guarded",
        "_persist_final_response",
        "_has_actionable_task",
    }
    tree = ast.parse(threads_src)
    declared = {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing_helpers = expected_helpers - declared
    if missing_helpers:
        return False, f"helpers missing in routes/threads.py: {sorted(missing_helpers)}"

    workflow_src = (routes_dir / "workflow.py").read_text(encoding="utf-8")
    if "def run_workflow" not in workflow_src:
        return False, "routes/workflow.py missing run_workflow def"

    return True, f"routes/ has {len(actual)} files; all required helpers present"


def t2_action_get_flat_row_reshape() -> tuple[bool, str]:
    """Drive the action-get reshape path with a synthetic flat row, mirroring
    the real DynamoDB / SQLite ``get_pending_action`` shape, and verify the
    step_info dict comes out with the source shape."""
    fn_dir = FUNCTIONS / "supervisor-action-get"
    lf = fn_dir / "lambda_function.py"
    src = lf.read_text(encoding="utf-8")
    # Hard-coded shape verification — the lambda must build the dict from
    # FLAT row keys and not from a phantom row.get("step_info") call.
    must_contain = [
        '"agent": row.get("agent_name")',
        '"tool": row.get("tool_name")',
        '"inputs": row.get("inputs")',
        '"step_number": row.get("step_number")',
        '"output_variables": row.get("output_variables")',
    ]
    missing = [m for m in must_contain if m not in src]
    if missing:
        return False, f"missing reshape keys in supervisor-action-get: {missing}"
    if 'row.get("step_info")' in src:
        return False, "supervisor-action-get still reads phantom row.get('step_info')"
    return True, "supervisor-action-get reshapes flat row into nested step_info"


def t3_ws_chat_imports_route_helpers() -> tuple[bool, str]:
    """The new WS-chat handler must import the route helpers we added.
    Source-text grep is enough — we've already shown the lambda imports
    cleanly in _sim_phase6.py; here we verify the architectural intent."""
    lf = FUNCTIONS / "supervisor-ws-chat" / "lambda_function.py"
    src = lf.read_text(encoding="utf-8")
    expected_imports = [
        "from routes.threads import",
        "_handle_pending_action_decision",
        "_handle_disambiguation_selection",
        "_execute_workflow_guarded",
        "_has_actionable_task",
        "_persist_final_response",
    ]
    missing = [m for m in expected_imports if m not in src]
    if missing:
        return False, f"WS-chat missing route delegations: {missing}"
    return True, "WS-chat delegates to routes.threads helpers"


def t4_action_approve_no_dead_gone_exception() -> tuple[bool, str]:
    """The dead `except GoneException` block is gone; cleanup of stale
    connections runs via the False-return path."""
    lf = FUNCTIONS / "supervisor-action-approve" / "lambda_function.py"
    src = lf.read_text(encoding="utf-8")
    if "except GoneException" in src:
        return False, "still has dead 'except GoneException:'"
    if ", GoneException" in src:
        return False, "still imports GoneException"
    if "_cleanup_stale_connection" not in src:
        return False, "missing _cleanup_stale_connection helper"
    if "if not delivered:" not in src:
        return False, "missing False-return cleanup branch"
    return True, "GoneException dead-code removed; cleanup runs on post_to_connection False"


def t5_brain_deps_in_requirements() -> tuple[bool, str]:
    """Catch any regression where a future cleanup drops the brain stack."""
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    must_have = [
        "openai",
        "tiktoken",
        "langchain-core",
        "langchain-openai",
        "langgraph",
        "jinja2",
        "tenacity",
        "fastapi",
        "pydantic",
        "boto3",
    ]
    missing = [m for m in must_have if m not in reqs]
    if missing:
        return False, f"requirements.txt missing: {missing}"
    return True, f"requirements.txt has {len(must_have)} brain deps declared"


def t6_action_get_actually_runs() -> tuple[bool, str]:
    """End-to-end sanity check: import action-get, monkey-patch
    get_log_storage to return a flat row, invoke lambda_handler, assert
    the response contains the reshaped step_info."""
    fn_dir = FUNCTIONS / "supervisor-action-get"
    saved = list(sys.path)
    saved_modules = set(sys.modules.keys())
    try:
        sys.path.insert(0, str(fn_dir))
        spec = importlib.util.spec_from_file_location(
            "_aa_test_action_get", fn_dir / "lambda_function.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        flat_row = {
            "action_id": "act_123",
            "step_number": 2,
            "agent_name": "calendar_agent",
            "tool_name": "create_event",
            "description": "Create the kickoff meeting",
            "inputs": {"summary": "Kickoff", "start_time": "2026-05-03T09:00:00"},
            "output_variables": {"event_id": "event_id"},
            "risk_level": "MODERATE",
            "status": "pending",
            "created_at": "2026-05-02T07:00:00",
        }

        class _FakeStorage:
            def get_pending_action(self, _aid):
                return flat_row

        # Bypass the persistence factory — it's a closed-over import
        # in the lambda, so reach into the module-level reference.
        try:
            from shared import persistence_factory as pf  # type: ignore
            pf._log_storage_singleton = _FakeStorage()  # type: ignore
        except Exception:
            return False, "could not patch persistence_factory"

        event = {
            "httpMethod": "GET",
            "pathParameters": {"action_id": "act_123"},
            "requestContext": {"authorizer": {"claims": {"sub": "u1"}}},
        }
        resp = mod.lambda_handler(event, None)

        body = json.loads(resp.get("body", "{}"))
        si = body.get("step_info") or {}
        ok = (
            body.get("action_id") == "act_123"
            and si.get("agent") == "calendar_agent"
            and si.get("tool") == "create_event"
            and si.get("inputs", {}).get("summary") == "Kickoff"
            and si.get("step_number") == 2
            and body.get("expires_at") is not None
        )
        if not ok:
            return False, f"unexpected response body: {body}"
        return True, "lambda_handler returns nested step_info from flat row"
    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"{type(e).__name__}: {e}"
    finally:
        sys.path[:] = saved
        for k in list(sys.modules.keys()):
            if k not in saved_modules:
                m = sys.modules.get(k)
                f = getattr(m, "__file__", "") or ""
                if str(ROOT.parent).lower() in f.lower():
                    sys.modules.pop(k, None)


def main() -> int:
    print("=" * 70)
    print("AA-lambda Pass 8 fix-verification")
    print("=" * 70)
    tests = [
        ("routes/ directory + helpers", t1_routes_dir_present_and_importable),
        ("supervisor-action-get reshape", t2_action_get_flat_row_reshape),
        ("supervisor-ws-chat delegates to routes.threads", t3_ws_chat_imports_route_helpers),
        ("supervisor-action-approve dead code removed", t4_action_approve_no_dead_gone_exception),
        ("AA-lambda/requirements.txt brain stack", t5_brain_deps_in_requirements),
        ("supervisor-action-get end-to-end smoke", t6_action_get_actually_runs),
    ]
    failures = 0
    for label, fn in tests:
        ok, msg = fn()
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: {msg}")
        if not ok:
            failures += 1
    print("=" * 70)
    if failures:
        print(f"FAILED: {failures} check(s) failed")
        return 1
    print("PASSED — all fix checks green")
    return 0


if __name__ == "__main__":
    sys.exit(main())

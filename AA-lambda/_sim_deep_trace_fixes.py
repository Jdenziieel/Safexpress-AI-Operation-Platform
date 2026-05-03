"""
AA-lambda deep-trace fix-verification suite.

Run AFTER the deep-trace audit edits land. Verifies:
  1. supervisor-delete-thread now calls delete_thread(hard_delete=False) → status="deleted"
     instead of archive_thread() → status="archived" (matches source).
  2. supervisor-create-thread runs _execute_workflow_guarded inline when
     ready_for_execution=True (matches source create_thread lines 1262-1297).
  3. supervisor-create-thread-upload runs _execute_workflow_guarded inline.
  4. supervisor-create-thread imports llm_error_response (LLM error fidelity).
  5. supervisor-workflow imports llm_error_response.
  6. supervisor-ws-chat error event spreads is_llm_error structure.
  7. lambda_helpers.llm_error_response exists and shapes responses correctly.
  8. agent-sheets wraps creds in CredentialsDict before calling tool funcs.
  9. agent-drive wraps creds in CredentialsDict before calling tool funcs.
 10. supervisor-actions-pending and supervisor-health have explicit sys.path setup.

Each check is independent and prints ok/FAIL with a diagnostic. Exit code 0
on success, 1 on any failure.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# ----------------------------------------------------------------------
# Setup: keep stdout encoding-safe under ``cp1252``.
# ----------------------------------------------------------------------
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
FUNC = ROOT / "functions"
SHARED = ROOT / "shared"

results: list[tuple[bool, str, str]] = []


def check(label: str, predicate, detail: str = "") -> None:
    try:
        ok = bool(predicate())
    except Exception as e:
        ok = False
        detail = f"raised {type(e).__name__}: {e}"
    results.append((ok, label, detail))


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


# ----------------------------------------------------------------------
# 1. delete-thread: source preserves status="deleted"
# ----------------------------------------------------------------------
src1 = read(FUNC / "supervisor-delete-thread" / "lambda_function.py")
check(
    "supervisor-delete-thread uses delete_thread(hard_delete=False)",
    lambda: "tm.delete_thread(thread_id, hard_delete=False)" in src1
            and "tm.archive_thread(" not in src1,
    detail="Must call delete_thread(hard_delete=False) so status='deleted' (source parity).",
)


# ----------------------------------------------------------------------
# 2-3. create-thread {plain, upload}: workflow runs inline if ready
# ----------------------------------------------------------------------
src2 = read(FUNC / "supervisor-create-thread" / "lambda_function.py")
check(
    "supervisor-create-thread runs _execute_workflow_guarded inline",
    lambda: "_execute_workflow_guarded" in src2
            and "_persist_final_response" in src2
            and "_has_actionable_task" in src2,
    detail="Source create_thread (lines 1262-1297) calls these helpers when ready.",
)

src3 = read(FUNC / "supervisor-create-thread-upload" / "lambda_function.py")
check(
    "supervisor-create-thread-upload runs _execute_workflow_guarded inline",
    lambda: "_execute_workflow_guarded" in src3
            and "_persist_final_response" in src3
            and "cleanup_file=uploaded_file" in src3,
    detail="Source create_thread_with_upload (lines 1419-1437) chains these helpers.",
)


# ----------------------------------------------------------------------
# 4-5. LLM error structured-response shape
# ----------------------------------------------------------------------
check(
    "supervisor-create-thread imports llm_error_response",
    lambda: "llm_error_response" in src2 and "LLMServiceException" in src2,
)
check(
    "supervisor-create-thread-upload imports llm_error_response",
    lambda: "llm_error_response" in src3 and "LLMServiceException" in src3,
)
src4 = read(FUNC / "supervisor-workflow" / "lambda_function.py")
check(
    "supervisor-workflow imports llm_error_response + handle_llm_error",
    lambda: "llm_error_response" in src4
            and "handle_llm_error" in src4
            and "is_llm_error" in src4,
)


# ----------------------------------------------------------------------
# 6. ws-chat error event spreads is_llm_error
# ----------------------------------------------------------------------
src5 = read(FUNC / "supervisor-ws-chat" / "lambda_function.py")
check(
    "supervisor-ws-chat error event spreads structured payload",
    lambda: "extra = e.to_dict()" in src5
            and "_push(pusher, \"error\"" in src5
            and "**extra" in src5,
    detail="Must spread exc.to_dict() into the WS error event so the FE LLMErrorModal renders.",
)


# ----------------------------------------------------------------------
# 7. lambda_helpers.llm_error_response exists
# ----------------------------------------------------------------------
src6 = read(SHARED / "lambda_helpers.py")
check(
    "shared/lambda_helpers.py exposes llm_error_response",
    lambda: "def llm_error_response" in src6
            and "to_dict()" in src6,
)


# ----------------------------------------------------------------------
# 8-9. Sub-agent Pydantic credential wrapping
# ----------------------------------------------------------------------
src7 = read(FUNC / "agent-sheets" / "lambda_function.py")
check(
    "agent-sheets wraps creds in CredentialsDict",
    lambda: "from sheets_agent_api import TOOL_REGISTRY, CredentialsDict" in src7
            and "CredentialsDict(**creds)" in src7,
    detail="Source tools use credentials_dict.access_token (attribute access).",
)

src8 = read(FUNC / "agent-drive" / "lambda_function.py")
check(
    "agent-drive wraps creds in CredentialsDict",
    lambda: "from api import DRIVE_TOOLS, CredentialsDict" in src8
            and "CredentialsDict(**creds)" in src8
            and "tool_func(inputs, creds_obj)" in src8,
    detail="Source drive tool funcs use credentials_dict.access_token / .client_id.",
)


# ----------------------------------------------------------------------
# 10. sys.path setup added for the two stragglers
# ----------------------------------------------------------------------
src9 = read(FUNC / "supervisor-actions-pending" / "lambda_function.py")
check(
    "supervisor-actions-pending has sys.path setup",
    lambda: "_HERE = os.path.dirname" in src9 and "sys.path.insert" in src9,
)
src10 = read(FUNC / "supervisor-health" / "lambda_function.py")
check(
    "supervisor-health has sys.path setup",
    lambda: "_HERE = os.path.dirname" in src10 and "sys.path.insert" in src10,
)


# ----------------------------------------------------------------------
# 11. End-to-end smoke: llm_error_response shapes correctly
# ----------------------------------------------------------------------
def _llm_smoke():
    sys.path.insert(0, str(SHARED))
    from lambda_helpers import llm_error_response  # type: ignore

    class FakeLLMErr(Exception):
        status_code = 429
        def to_dict(self):
            return {
                "is_llm_error": True,
                "error_type": "rate_limit",
                "user_message": "Slow down",
                "status_code": 429,
            }

    resp = llm_error_response(FakeLLMErr())
    import json
    body = json.loads(resp["body"])
    return (
        resp["statusCode"] == 429
        and body.get("is_llm_error") is True
        and body.get("error_type") == "rate_limit"
        and "Content-Type" in resp["headers"]
    )


check("llm_error_response shapes 429 + is_llm_error correctly", _llm_smoke)


# ----------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------
print("=" * 72)
print("AA-lambda deep-trace fix-verification")
print("=" * 72)

passed = 0
failed = 0
for ok, label, detail in results:
    marker = "ok  " if ok else "FAIL"
    suffix = f": {detail}" if detail else ""
    print(f"  {marker}  {label}{suffix}")
    if ok:
        passed += 1
    else:
        failed += 1

print("=" * 72)
if failed:
    print(f"FAILED \u2014 {failed} of {passed + failed} checks failed")
    sys.exit(1)
print(f"PASSED \u2014 all {passed} deep-trace fix checks green")
sys.exit(0)

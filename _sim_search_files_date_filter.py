"""
Simulation: verify created_after / created_before on drive_agent.search_files
actually reach the Drive query string correctly, with no live API calls.

Strategy:
  - Mock the googleapiclient Drive service's files().list(q=...).execute() chain.
  - Capture the `q` kwarg the implementation built.
  - Assert the clause shape matches what Drive expects:
      * always: "name contains '<term>' and trashed=false"
      * when created_after:  "createdTime >= '<iso>'"
      * when created_before: "createdTime < '<iso>'"
  - Cover: bare-date normalization, full datetime pass-through, malformed input,
    quote-escaping in search_term, empty-result formatting, capability parity.

Run:
    python _sim_search_files_date_filter.py
"""

from __future__ import annotations

import io
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


REPO_ROOT = Path(__file__).resolve().parent
GDRIVE = REPO_ROOT / "gdrive-agent"
SUPERVISOR = REPO_ROOT / "supervisor-agent"
for p in (GDRIVE, SUPERVISOR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# UTF-8 stdout so em-dashes in diagnostic prints don't die on Windows cp1252
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Stub Google API imports so gdrive-agent/tools.py loads in an isolated venv.
# tools.py imports google_auth_oauthlib, googleapiclient, and google.* at the
# top. In live deployment these come from the sub-agent's own venv. The tests
# here never exercise real Google code — they pass a MagicMock as `service`
# and assert on the query string the impl built — so empty shim modules are
# sufficient. Keep this block BEFORE any `from tools import ...`.
# ---------------------------------------------------------------------------
def _stub_module(fullname: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(fullname)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[fullname] = mod
    return mod


_GOOGLE_STUBS = [
    ("google", {}),
    ("google.auth", {}),
    ("google.auth.transport", {}),
    ("google.auth.transport.requests", {"Request": MagicMock()}),
    ("google.oauth2", {}),
    ("google.oauth2.credentials", {"Credentials": MagicMock()}),
    ("google_auth_oauthlib", {}),
    ("google_auth_oauthlib.flow", {"InstalledAppFlow": MagicMock()}),
    ("googleapiclient", {}),
    ("googleapiclient.discovery", {"build": MagicMock()}),
    ("googleapiclient.http", {
        "MediaFileUpload": MagicMock(),
        "MediaIoBaseUpload": MagicMock(),
        "MediaIoBaseDownload": MagicMock(),
    }),
]
for name, attrs in _GOOGLE_STUBS:
    if name not in sys.modules:
        _stub_module(name, **attrs)


def _header(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def _mock_drive_service(return_files=None):
    """Build a MagicMock that imitates enough of the googleapiclient Drive
    service for search_files_in_safeexpress_impl to call files().list(...)
    and have us capture the `q` kwarg it passed."""
    svc = MagicMock()
    exec_mock = MagicMock()
    exec_mock.execute.return_value = {"files": list(return_files or [])}
    svc.files.return_value.list.return_value = exec_mock
    return svc


def _captured_query(svc) -> str:
    return svc.files.return_value.list.call_args.kwargs["q"]


def test_backward_compat_no_bounds():
    _header("TEST 1 — backward compat: no date args, query unchanged shape")
    from tools import search_files_in_safeexpress_impl
    svc = _mock_drive_service()
    result = search_files_in_safeexpress_impl(svc, "Delivery")
    assert result["success"] is True, result
    q = _captured_query(svc)
    assert "name contains 'Delivery'" in q, q
    assert "trashed=false" in q, q
    assert "createdTime" not in q, f"expected no createdTime clause, got: {q!r}"
    print(f"  ok  : query = {q!r}")


def test_both_bounds_month_window():
    _header("TEST 2 — 'April 2026' half-open window: both bounds present")
    from tools import search_files_in_safeexpress_impl
    svc = _mock_drive_service()
    result = search_files_in_safeexpress_impl(
        svc, "Delivery",
        created_after="2026-04-01",
        created_before="2026-05-01",
    )
    assert result["success"] is True, result
    q = _captured_query(svc)
    assert "createdTime >= '2026-04-01T00:00:00'" in q, q
    assert "createdTime < '2026-05-01T00:00:00'" in q, q
    # Order doesn't strictly matter but document what we got:
    assert q.count("createdTime") == 2, f"expected 2 createdTime clauses, got: {q!r}"
    print(f"  ok  : query = {q!r}")
    print(f"        message suffix = {result['message']!r}")


def test_lower_bound_only_passthrough_iso_datetime():
    _header("TEST 3 — lower bound only, full ISO datetime with Z passed through")
    from tools import search_files_in_safeexpress_impl
    svc = _mock_drive_service()
    result = search_files_in_safeexpress_impl(
        svc, "POD", created_after="2026-01-01T00:00:00Z",
    )
    assert result["success"] is True, result
    q = _captured_query(svc)
    assert "createdTime >= '2026-01-01T00:00:00Z'" in q, q
    assert "createdTime <" not in q, f"expected no upper-bound clause, got: {q!r}"
    print(f"  ok  : query = {q!r}")


def test_upper_bound_only():
    _header("TEST 4 — upper bound only")
    from tools import search_files_in_safeexpress_impl
    svc = _mock_drive_service()
    result = search_files_in_safeexpress_impl(
        svc, "Manifest", created_before="2026-03-01",
    )
    assert result["success"] is True, result
    q = _captured_query(svc)
    assert "createdTime < '2026-03-01T00:00:00'" in q, q
    assert "createdTime >=" not in q, f"expected no lower-bound clause, got: {q!r}"
    print(f"  ok  : query = {q!r}")


def test_malformed_date_returns_failure_dict():
    _header("TEST 5 — malformed date surfaces structured failure (success=False)")
    from tools import search_files_in_safeexpress_impl
    svc = _mock_drive_service()
    result = search_files_in_safeexpress_impl(
        svc, "Delivery", created_after="last month",
    )
    assert result["success"] is False, result
    assert "ISO-8601" in result["error"], result
    assert "last month" in result["error"], result
    # Drive should never have been called when the bound failed to normalize
    svc.files.return_value.list.assert_not_called()
    print(f"  ok  : error = {result['error']!r}")
    print(f"  ok  : Drive API was NOT called (short-circuited correctly)")


def test_search_term_quote_escaping_intact():
    _header("TEST 6 — quote-escaping in search_term still works with bounds")
    from tools import search_files_in_safeexpress_impl
    svc = _mock_drive_service()
    result = search_files_in_safeexpress_impl(
        svc, "O'Brien", created_after="2026-04-01",
    )
    assert result["success"] is True
    q = _captured_query(svc)
    assert "name contains 'O\\'Brien'" in q, q
    assert "createdTime >= '2026-04-01T00:00:00'" in q, q
    print(f"  ok  : query = {q!r}")


def test_empty_result_message_has_window_suffix():
    _header("TEST 7 — empty-result message documents the window")
    from tools import search_files_in_safeexpress_impl
    svc = _mock_drive_service(return_files=[])
    result = search_files_in_safeexpress_impl(
        svc, "Invoice",
        created_after="2026-04-01",
        created_before="2026-05-01",
    )
    assert result["success"] is True
    assert result["count"] == 0
    assert "[2026-04-01T00:00:00, 2026-05-01T00:00:00)" in result["message"], result["message"]
    print(f"  ok  : message = {result['message']!r}")


def test_normalizer_unit_cases():
    _header("TEST 8 — _normalize_drive_rfc3339 unit cases")
    from tools import _normalize_drive_rfc3339

    # None / empty → None
    assert _normalize_drive_rfc3339(None, "x") is None
    assert _normalize_drive_rfc3339("", "x") is None
    print(f"  ok  : None/empty → None")

    # Bare date → start-of-day
    assert _normalize_drive_rfc3339("2026-04-01", "x") == "2026-04-01T00:00:00"
    print(f"  ok  : '2026-04-01' → '2026-04-01T00:00:00'")

    # Full datetime variants pass through
    for iso in [
        "2026-04-01T00:00:00",
        "2026-04-01T12:34:56Z",
        "2026-04-01T12:34:56+05:30",
    ]:
        assert _normalize_drive_rfc3339(iso, "x") == iso, iso
    print(f"  ok  : ISO datetimes pass through unchanged")

    # Bad input raises
    for bad in ["last month", "2026/04/01", "April 1 2026", "xx-xx-xx"]:
        try:
            _normalize_drive_rfc3339(bad, "created_after")
            raise AssertionError(f"expected ValueError for {bad!r}")
        except ValueError as ve:
            assert "ISO-8601" in str(ve)
            assert "created_after" in str(ve)
    print(f"  ok  : malformed inputs raise ValueError with clear message")


def test_legacy_wrapper_still_works():
    _header("TEST 9 — legacy wrapper 'search_files_in_safeexpress' still callable both ways")
    from tools import search_files_in_safeexpress
    svc = _mock_drive_service(return_files=[
        {"id": "1", "name": "foo.pdf", "mimeType": "application/pdf"},
    ])
    # Old 2-arg call shape
    files = search_files_in_safeexpress(svc, "foo")
    assert files == [{"id": "1", "name": "foo.pdf", "mimeType": "application/pdf"}]
    # New 4-arg call shape
    files2 = search_files_in_safeexpress(
        svc, "foo", created_after="2026-04-01", created_before="2026-05-01"
    )
    assert files2 == files
    q = _captured_query(svc)
    assert "createdTime >= '2026-04-01T00:00:00'" in q, q
    print(f"  ok  : 2-arg call shape preserved; 4-arg shape threads bounds through")


def test_capability_declares_new_args():
    _header("TEST 10 — capability declares created_after / created_before")
    from agent_capabilities_v3 import agent_capabilities
    sf = agent_capabilities["drive_agent"]["tools"]["search_files"]
    for key in ("search_term", "created_after", "created_before"):
        assert key in sf["args"], f"{key} missing from args"
    assert "ISO-8601" in sf["args"]["created_after"]
    assert "ISO-8601" in sf["args"]["created_before"]
    assert "INCLUSIVE" in sf["args"]["created_after"]
    assert "EXCLUSIVE" in sf["args"]["created_before"]
    assert sf.get("note"), "capability should have a note warning about natural-language parsing"
    assert "today_date" in sf["note"], "note should reference today_date"
    assert "NOT" in sf["note"] and "natural" in sf["note"].lower()
    print(f"  ok  : args declared, note names today_date and warns off natural-language dates")


def test_capability_reaches_planner_prompt():
    _header("TEST 11 — planner-facing JSON carries the new args + note")
    import json
    from tool_filter import get_filtered_capabilities_v2
    filtered = get_filtered_capabilities_v2({"drive_agent": ["search_files"]})
    rendered = json.dumps(filtered, indent=2)
    assert '"created_after"' in rendered, "created_after missing from rendered prompt"
    assert '"created_before"' in rendered, "created_before missing from rendered prompt"
    assert "ISO-8601" in rendered
    assert "today_date" in rendered
    print(f"  ok  : drive_agent.search_files JSON block carries the new args (~{len(rendered)//4} tokens)")


def main() -> int:
    tests = [
        test_backward_compat_no_bounds,
        test_both_bounds_month_window,
        test_lower_bound_only_passthrough_iso_datetime,
        test_upper_bound_only,
        test_malformed_date_returns_failure_dict,
        test_search_term_quote_escaping_intact,
        test_empty_result_message_has_window_suffix,
        test_normalizer_unit_cases,
        test_legacy_wrapper_still_works,
        test_capability_declares_new_args,
        test_capability_reaches_planner_prompt,
    ]
    failures: list[tuple[str, str]] = []
    for fn in tests:
        try:
            fn()
        except AssertionError as e:
            failures.append((fn.__name__, str(e)))
            print(f"  FAIL: {e}")
        except Exception as e:
            failures.append((fn.__name__, f"{type(e).__name__}: {e}"))
            print(f"  ERROR: {type(e).__name__}: {e}")

    _header("SUMMARY")
    if failures:
        for name, err in failures:
            print(f"  FAIL {name}: {err}")
        return 1
    print(f"  all {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

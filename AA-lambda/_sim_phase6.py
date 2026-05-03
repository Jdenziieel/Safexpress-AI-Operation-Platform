"""Phase 6 smoke test — validates the AA-lambda port without deploying.

Coverage:
  1. Every Lambda's `lambda_function.py` imports cleanly (catches syntax / sys.path bugs).
  2. `shared.persistence_factory.get_thread_manager()` returns the SQLite impl when
     `PERSISTENCE_BACKEND` is unset, the DynamoDB impl when set to ``dynamodb``.
  3. `shared.utils._inject_quota_context` correctly threads ``user_id``, ``jwt``,
     and ``request_id`` from `logging_config` into the sub-agent payload's
     ``credentials_dict`` (Phase 2.5.A invariant).
  4. `shared.lambda_helpers.install_persistence_backend()` swaps `sys.modules`
     entries for ``thread_manager`` and ``log_storage`` only when
     ``PERSISTENCE_BACKEND=dynamodb``.

Usage::

    cd AA-lambda
    python _sim_phase6.py

Prints a table of passes/failures and exits 0 on success, 1 otherwise.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path

try:
    import boto3  # noqa: F401  (presence indicates AWS SDK is installed locally)

    _HAS_BOTO3 = True
except Exception:
    _HAS_BOTO3 = False

ROOT = Path(__file__).resolve().parent
SHARED = ROOT / "shared"
FUNCTIONS = ROOT / "functions"

# Make `shared` and individual function dirs importable.
for p in (str(ROOT), str(SHARED)):
    if p not in sys.path:
        sys.path.insert(0, p)


@contextmanager
def env_overrides(**kwargs):
    saved = {k: os.environ.get(k) for k in kwargs}
    try:
        for k, v in kwargs.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ----------------------------------------------------------------------
# Test 1 — every Lambda imports cleanly
# ----------------------------------------------------------------------


def _import_lambda(fn_dir: Path) -> tuple[bool, str]:
    """Try to import a Lambda's `lambda_function.py`.

    Returns (ok, message). Treats ``ModuleNotFoundError: boto3``,
    ``langchain``, ``langgraph``, ``openai``, ``pydantic``, ``httpx``, etc.
    as "skipped" since those resolve at deploy time inside the Lambda image,
    not in the local dev shell.
    """
    name = fn_dir.name
    lf = fn_dir / "lambda_function.py"
    if not lf.exists():
        return False, "missing lambda_function.py"

    saved_path = list(sys.path)
    saved_modules = set(sys.modules.keys())
    try:
        sys.path.insert(0, str(fn_dir))
        spec = importlib.util.spec_from_file_location(
            f"_aa_lambda_test_{name.replace('-', '_')}", lf
        )
        if not spec or not spec.loader:
            return False, "no module spec"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not hasattr(mod, "lambda_handler"):
            return False, "no lambda_handler"
        return True, "ok"
    except ModuleNotFoundError as e:
        # Heavy / runtime-only deps are expected to be missing in dev shell.
        runtime_only = {
            "boto3", "botocore",
            "langchain", "langchain_core", "langchain_openai",
            "langgraph",
            "openai", "tiktoken",
            "httpx",
            "weaviate",
            "pdfplumber", "fitz",
            "pandas", "numpy",
            "google", "google.auth", "google.oauth2", "googleapiclient",
            "pydantic",
            "pytz", "dateutil", "python-dateutil",
            "dotenv", "python-dotenv",
        }
        missing = (e.name or "").split(".")[0]
        if missing in runtime_only:
            return True, f"skipped (no {missing} locally)"
        return False, f"ModuleNotFoundError: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        sys.path[:] = saved_path
        # Drop modules that came from THIS project (Lambda-local `api.py`,
        # `tools.py`, brain copies under shared/, etc.), but NEVER drop
        # site-packages modules — re-initializing PyO3-compiled C extensions
        # like `cryptography._rust` raises ImportError after the first time.
        proj_root = str(ROOT.parent).lower()
        for mod_name in list(sys.modules.keys()):
            if mod_name in saved_modules:
                continue
            mod = sys.modules.get(mod_name)
            mod_file = getattr(mod, "__file__", None) or ""
            if not mod_file:
                # Built-in / namespace package — keep.
                continue
            if mod_file.lower().startswith(proj_root):
                sys.modules.pop(mod_name, None)


def test_all_lambdas_import() -> dict:
    results: dict = {"passed": [], "failed": []}
    for fn_dir in sorted(FUNCTIONS.iterdir()):
        if not fn_dir.is_dir():
            continue
        ok, msg = _import_lambda(fn_dir)
        (results["passed"] if ok else results["failed"]).append((fn_dir.name, msg))
    return results


# ----------------------------------------------------------------------
# Test 2 — persistence_factory dispatch
# ----------------------------------------------------------------------


def test_persistence_factory_default() -> tuple[bool, str]:
    try:
        from shared import persistence_factory  # type: ignore

        persistence_factory.reset_singletons()
        with env_overrides(PERSISTENCE_BACKEND=None):
            tm = persistence_factory.get_thread_manager()
        cls_module = type(tm).__module__
        if "dynamodb" in cls_module:
            return False, f"unexpectedly DDB: {cls_module}"
        return True, f"sqlite: {cls_module}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        try:
            persistence_factory.reset_singletons()  # type: ignore
        except Exception:
            pass


def test_persistence_factory_dynamodb() -> tuple[bool, str]:
    try:
        from shared import persistence_factory  # type: ignore

        persistence_factory.reset_singletons()
        with env_overrides(PERSISTENCE_BACKEND="dynamodb"):
            try:
                tm = persistence_factory.get_thread_manager()
            except Exception as e:
                return False, f"DDB ctor: {type(e).__name__}: {e}"
        cls_module = type(tm).__module__
        if "dynamodb" not in cls_module:
            return False, f"got {cls_module} not DDB"
        return True, f"dynamodb: {cls_module}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        try:
            persistence_factory.reset_singletons()  # type: ignore
        except Exception:
            pass


# ----------------------------------------------------------------------
# Test 3 — _inject_quota_context (Phase 2.5.A invariant)
# ----------------------------------------------------------------------


def test_inject_quota_context() -> tuple[bool, str]:
    try:
        sys.path.insert(0, str(SHARED))
        try:
            import logging_config as lc  # type: ignore
            import utils as u  # type: ignore
        finally:
            sys.path.pop(0)

        rid = lc.set_request_context(
            request_id="req_123",
            user_id="user_abc",
            jwt="jwt_xyz",
        )
        try:
            payload = {
                "tool": "list_events",
                "inputs": {"max_results": 5},
                "credentials_dict": {"access_token": "atok"},
            }
            shaped = u._inject_quota_context(payload)
            creds = shaped.get("credentials_dict") or {}
            ok = (
                creds.get("_user_id") == "user_abc"
                and creds.get("_jwt") == "jwt_xyz"
                and creds.get("_request_id") == "req_123"
                and creds.get("access_token") == "atok"
                and rid == "req_123"
            )
            if not ok:
                return False, f"creds={creds}"
            return True, "user_id+jwt+request_id propagated"
        finally:
            lc.clear_request_context()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ----------------------------------------------------------------------
# Test 4 — install_persistence_backend swaps sys.modules
# ----------------------------------------------------------------------


# ----------------------------------------------------------------------
# Test 5 — quota_check / quota_report behaviors (Phase 2.5)
# ----------------------------------------------------------------------


def _quota_with_fake(monkey_response, fn):
    """Run ``fn`` while ``urllib.request.urlopen`` is replaced with
    ``monkey_response`` (a callable that returns a context-manager-yielding
    object or raises an exception).

    Always uses ``shared.lambda_helpers`` (the same module that the Lambda
    handlers themselves use) so we exercise the deployed code path, not
    a freshly-loaded duplicate that would have its own stale globals.
    """
    sys.path.insert(0, str(ROOT))
    try:
        import urllib.request as ur
        from shared import lambda_helpers as lh  # type: ignore

        lh.QUOTA_BASE = os.environ.get("QUOTA_SERVICE_URL", "").rstrip("/")
        lh.QUOTA_ENABLED = (
            os.environ.get("QUOTA_ENABLED", "true").lower() == "true"
        )

        saved = ur.urlopen
        ur.urlopen = monkey_response  # type: ignore[assignment]
        try:
            return fn(lh)
        finally:
            ur.urlopen = saved
    finally:
        sys.path.pop(0)


class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def read(self) -> bytes:
        return self._body


def test_quota_check_disabled_skips() -> tuple[bool, str]:
    try:
        with env_overrides(
            QUOTA_ENABLED="false",
            QUOTA_SERVICE_URL="https://q.example.com",
        ):
            sys.path.insert(0, str(ROOT))
            try:
                from shared import lambda_helpers as lh  # type: ignore

                lh.QUOTA_ENABLED = False
                lh.QUOTA_BASE = "https://q.example.com"
                allowed, body = lh.quota_check("u1", "jwt", 100, "tool_call")
            finally:
                sys.path.pop(0)
        return (allowed is True and body == {}, f"allowed={allowed} body={body}")
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def test_quota_check_no_user_skips() -> tuple[bool, str]:
    try:
        with env_overrides(
            QUOTA_ENABLED="true",
            QUOTA_SERVICE_URL="https://q.example.com",
        ):
            sys.path.insert(0, str(ROOT))
            try:
                from shared import lambda_helpers as lh  # type: ignore

                lh.QUOTA_ENABLED = True
                lh.QUOTA_BASE = "https://q.example.com"
                allowed, body = lh.quota_check(None, "jwt", 100, "tool_call")
            finally:
                sys.path.pop(0)
        return (allowed is True and body == {}, f"allowed={allowed} body={body}")
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def test_quota_check_allowed() -> tuple[bool, str]:
    try:
        with env_overrides(
            QUOTA_ENABLED="true",
            QUOTA_SERVICE_URL="https://q.example.com",
        ):
            captured = {}

            def fake(req, timeout=None):
                captured["url"] = req.full_url
                captured["headers"] = dict(req.header_items())
                captured["body"] = json.loads(req.data.decode("utf-8"))
                return _FakeResp(json.dumps({"allowed": True, "remaining": 9000}).encode())

            allowed, body = _quota_with_fake(
                fake, lambda lh: lh.quota_check("u1", "jwt-abc", 1000, "tool_call")
            )
        if not allowed:
            return False, f"expected allowed, got {allowed} body={body}"
        if "/quota/check" not in captured["url"]:
            return False, f"wrong endpoint: {captured.get('url')}"
        if captured["headers"].get("Authorization") != "Bearer jwt-abc":
            return False, f"missing/wrong Authorization: {captured['headers']}"
        if captured["body"].get("user_id") != "u1":
            return False, f"wrong user_id in payload: {captured['body']}"
        return True, "POST /quota/check w/ Bearer jwt + correct payload"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def test_quota_check_429_blocks() -> tuple[bool, str]:
    """429 → exceeded, NOT fail-open."""
    try:
        with env_overrides(
            QUOTA_ENABLED="true",
            QUOTA_SERVICE_URL="https://q.example.com",
        ):
            import urllib.error as ue

            def fake(req, timeout=None):
                fp = type("fp", (object,), {"read": lambda self: b'{"reason": "monthly limit"}'})()
                err = ue.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
                err.read = lambda: b'{"reason": "monthly limit"}'
                raise err

            allowed, body = _quota_with_fake(
                fake, lambda lh: lh.quota_check("u1", "jwt", 1000, "tool_call")
            )
        if allowed is not False:
            return False, f"expected blocked, got allowed={allowed}"
        if not body.get("quota_exceeded"):
            return False, f"expected quota_exceeded flag, body={body}"
        return True, "429 → blocked + quota_exceeded=True"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def test_quota_check_404_deactivated() -> tuple[bool, str]:
    """404 → user deactivated, NOT fail-open."""
    try:
        with env_overrides(
            QUOTA_ENABLED="true",
            QUOTA_SERVICE_URL="https://q.example.com",
        ):
            import urllib.error as ue

            def fake(req, timeout=None):
                err = ue.HTTPError(req.full_url, 404, "Not Found", {}, None)
                err.read = lambda: b'{"reason": "user deactivated"}'
                raise err

            allowed, body = _quota_with_fake(
                fake, lambda lh: lh.quota_check("u1", "jwt", 1000, "tool_call")
            )
        if allowed is not False:
            return False, f"expected blocked, got allowed={allowed}"
        if not body.get("user_deactivated"):
            return False, f"expected user_deactivated flag, body={body}"
        return True, "404 → blocked + user_deactivated=True"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def test_quota_check_503_failopen() -> tuple[bool, str]:
    """503 / network error → FAIL-OPEN per QUOTA_SERVICE_REFERENCE §2.4."""
    try:
        with env_overrides(
            QUOTA_ENABLED="true",
            QUOTA_SERVICE_URL="https://q.example.com",
        ):
            def fake(req, timeout=None):
                raise OSError("connection refused")

            allowed, body = _quota_with_fake(
                fake, lambda lh: lh.quota_check("u1", "jwt", 1000, "tool_call")
            )
        if allowed is not True:
            return False, f"expected fail-open allowed=True, got {allowed}"
        if body != {}:
            return False, f"expected empty body on fail-open, got {body}"
        return True, "network failure → fail-open allowed=True"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def test_quota_report_payload_shape() -> tuple[bool, str]:
    try:
        with env_overrides(
            QUOTA_ENABLED="true",
            QUOTA_SERVICE_URL="https://q.example.com",
            SERVICE_NAME="supervisor-test",
        ):
            captured = {}

            def fake(req, timeout=None):
                captured["url"] = req.full_url
                captured["headers"] = dict(req.header_items())
                captured["body"] = json.loads(req.data.decode("utf-8"))
                return _FakeResp(b'{"ok": true}')

            ok = _quota_with_fake(
                fake,
                lambda lh: lh.quota_report(
                    user_id="u1",
                    jwt="jwt-xyz",
                    model="gpt-4o-mini",
                    input_tokens=120,
                    output_tokens=85,
                    cached_tokens=40,
                    operation="tool_call",
                    request_id="req-9",
                    duration_ms=350,
                    success=True,
                ),
            )
        if not ok:
            return False, f"reported failure"
        body = captured.get("body", {})
        for k in ("user_id", "service", "operation", "model", "input_tokens",
                  "output_tokens", "cached_tokens", "duration_ms", "success",
                  "request_id"):
            if k not in body:
                return False, f"missing field {k!r} in payload: {body}"
        if body["service"] != "supervisor-test":
            return False, f"SERVICE_NAME not honored: {body['service']}"
        if "/quota/report" not in captured["url"]:
            return False, f"wrong endpoint: {captured.get('url')}"
        return True, "POST /quota/report w/ full schema + service-name discipline"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def test_install_persistence_backend() -> tuple[bool, str]:
    try:
        sys.path.insert(0, str(SHARED))
        try:
            from shared import lambda_helpers as lh  # type: ignore
        finally:
            sys.path.pop(0)
        # Snapshot
        prev_tm = sys.modules.get("thread_manager")
        prev_ls = sys.modules.get("log_storage")

        with env_overrides(PERSISTENCE_BACKEND="dynamodb"):
            lh.install_persistence_backend()
            tm = sys.modules.get("thread_manager")
            ls = sys.modules.get("log_storage")
            ok = (
                tm is not None and "dynamodb" in tm.__name__
                and ls is not None and "dynamodb" in ls.__name__
            )
            if not ok:
                return False, f"tm={tm and tm.__name__} ls={ls and ls.__name__}"
        # Restore previous module bindings to avoid leaking.
        if prev_tm is None:
            sys.modules.pop("thread_manager", None)
        else:
            sys.modules["thread_manager"] = prev_tm
        if prev_ls is None:
            sys.modules.pop("log_storage", None)
        else:
            sys.modules["log_storage"] = prev_ls
        return True, "thread_manager+log_storage rebound to DDB modules"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ----------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------


def main() -> int:
    print("=" * 70)
    print("AA-lambda Phase 6 smoke test")
    print("=" * 70)
    failures = 0

    print("\n[1] Lambda lambda_function.py imports")
    res = test_all_lambdas_import()
    for name, msg in res["passed"]:
        print(f"  ok    {name}")
    for name, msg in res["failed"]:
        print(f"  FAIL  {name} -- {msg}")
    failures += len(res["failed"])
    print(
        f"  Total: {len(res['passed'])} passed, {len(res['failed'])} failed "
        f"(of {len(res['passed']) + len(res['failed'])})"
    )

    print("\n[2] persistence_factory dispatch")
    ok, msg = test_persistence_factory_default()
    print(f"  {'ok  ' if ok else 'FAIL'} default (sqlite): {msg}")
    if not ok:
        failures += 1
    if _HAS_BOTO3:
        ok, msg = test_persistence_factory_dynamodb()
        print(f"  {'ok  ' if ok else 'FAIL'} dynamodb: {msg}")
        if not ok:
            failures += 1
    else:
        print(
            "  skip dynamodb: boto3 not installed locally "
            "(present in Lambda runtime — re-run inside the Docker image to verify)"
        )

    print("\n[3] _inject_quota_context")
    ok, msg = test_inject_quota_context()
    print(f"  {'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        failures += 1

    print("\n[4] install_persistence_backend")
    if _HAS_BOTO3:
        ok, msg = test_install_persistence_backend()
        print(f"  {'ok  ' if ok else 'FAIL'} {msg}")
        if not ok:
            failures += 1
    else:
        print(
            "  skip: boto3 not installed locally "
            "(install_persistence_backend imports dynamodb_thread_manager which "
            "needs boto3; will be present in deployed Lambda)"
        )

    print("\n[5] Quota service integration (Phase 2.5)")
    quota_tests = [
        ("disabled (QUOTA_ENABLED=false) skips & fails open",
         test_quota_check_disabled_skips),
        ("missing user_id skips & fails open", test_quota_check_no_user_skips),
        ("/quota/check happy path (Bearer jwt + payload)",
         test_quota_check_allowed),
        ("/quota/check 429 blocks with quota_exceeded",
         test_quota_check_429_blocks),
        ("/quota/check 404 blocks with user_deactivated",
         test_quota_check_404_deactivated),
        ("/quota/check network error fails open (allowed=True)",
         test_quota_check_503_failopen),
        ("/quota/report payload shape (service name + cached_tokens)",
         test_quota_report_payload_shape),
    ]
    for label, fn in quota_tests:
        ok, msg = fn()
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: {msg}")
        if not ok:
            failures += 1

    print("\n" + "=" * 70)
    if failures:
        print(f"FAILED: {failures} check(s) failed")
        return 1
    print("PASSED — all checks green")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Static-import audit for the 31 LIGHT supervisor Lambda functions.

For each function in the LIGHT_FUNCTIONS list below, walks every .py file
in the function folder + every transitively-imported `shared/` module
referenced by that folder, and confirms NONE of the heavy modules (full
LangChain stack, OpenAI SDK, tiktoken, jinja2, pdfplumber, etc.) are
imported at module top level.

Output:
  [ok]   supervisor-list-threads
  [ok]   supervisor-search-threads
  [fail] supervisor-foo: pulls in `langchain_core` via shared/utils.py

This is a static check — it doesn't actually run the imports — so it's
fast and doesn't need the build/<fn>/ folder to exist. Catches the case
where a developer adds `from shared.utils import call_agent_with_retry`
to a "light" function without realizing utils.py imports langchain.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path


HEAVY_FORBIDDEN = {
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langgraph",
    "langgraph_checkpoint",
    "langgraph_prebuilt",
    "langgraph_sdk",
    "openai",
    "tiktoken",
    "jinja2",
    "MarkupSafe",
    "tenacity",
    "orjson",
    "ormsgpack",
    "regex",
    "pdfplumber",
    "pymupdf",
    "fitz",
    "pandas",
    "numpy",
    "fastapi",
    "starlette",
    "uvicorn",
    "google.auth",
    "google.oauth2",
    "googleapiclient",
}


# Exact list mirroring build-all.ps1's "everything not in $DockerFunctions"
# (i.e. the 31 functions that ship as ZIPs).
LIGHT_FUNCTIONS = [
    "supervisor-list-threads",
    "supervisor-search-threads",
    "supervisor-get-thread",
    "supervisor-get-messages",
    "supervisor-update-thread",
    "supervisor-delete-thread",
    "supervisor-get-progress",
    "supervisor-actions-pending",
    "supervisor-actions-cleanup",
    "supervisor-action-get",
    "supervisor-health",
    "supervisor-admin-activity",
    "supervisor-admin-activity-summary",
    "supervisor-admin-alerts",
    "supervisor-admin-budget-get",
    "supervisor-admin-budget-update",
    "supervisor-admin-health",
    "supervisor-admin-logs",
    "supervisor-admin-metrics",
    "supervisor-admin-metrics-internal",
    "supervisor-admin-pricing-list",
    "supervisor-admin-pricing-update",
    "supervisor-admin-usage-summary",
    "supervisor-agents-metrics",
    "supervisor-logs-list",
    "supervisor-logs-search",
    "supervisor-logs-stats",
    "supervisor-logs-clear",
    "supervisor-logs-by-request",
    "supervisor-post-message",
    "supervisor-post-message-upload",
]


# Specific shared modules we know are heavy and must not be referenced
# by ANY light function.
HEAVY_SHARED_MODULES = {
    "shared.utils",  # imports langchain_openai + tiktoken at top level
    "shared.config",  # imports langchain_openai
    "shared.routes",  # imports the brain
}


def _scan_file(path: Path) -> set[str]:
    """Return the set of fully-qualified module names imported at the
    TOP LEVEL of `path`. Top-level means "not inside any def/class".
    Lazy imports inside function bodies are intentionally ignored —
    they don't run on cold start."""
    try:
        src = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return set()
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return set()

    imports: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    return imports


def _classify(import_name: str) -> str | None:
    """Return the offending heavy module name if `import_name` matches
    any heavy module (or a sub-module of one), else None."""
    parts = import_name.split(".")
    for i in range(1, len(parts) + 1):
        prefix = ".".join(parts[:i])
        if prefix in HEAVY_FORBIDDEN:
            return prefix
    return None


def audit(root: Path) -> int:
    fns_dir = root / "functions"
    shared_dir = root / "shared"
    failures: list[str] = []

    for fn in LIGHT_FUNCTIONS:
        fn_dir = fns_dir / fn
        if not fn_dir.is_dir():
            failures.append(f"{fn}: folder missing")
            continue

        # Collect top-level imports from every .py in the function folder
        # + their transitive `shared/` imports.
        offending: list[tuple[str, str, str]] = []  # (file, import, reason)
        seen_shared: set[str] = set()
        worklist: list[Path] = [p for p in fn_dir.glob("*.py")]

        while worklist:
            path = worklist.pop()
            top_imports = _scan_file(path)

            for imp in top_imports:
                bad = _classify(imp)
                if bad:
                    rel = path.relative_to(root)
                    offending.append((str(rel), imp, bad))

                # Resolve `shared.<mod>` -> shared/<mod>.py and queue it.
                if imp.startswith("shared.") or imp == "shared":
                    sub = imp.removeprefix("shared.").removeprefix("shared")
                    if not sub:
                        continue
                    if sub in HEAVY_SHARED_MODULES or imp in HEAVY_SHARED_MODULES:
                        rel = path.relative_to(root)
                        offending.append((str(rel), imp, "heavy shared module"))
                    candidate_pkg = shared_dir / sub.replace(".", "/") / "__init__.py"
                    candidate_mod = shared_dir / (sub.replace(".", "/") + ".py")
                    for cand in (candidate_mod, candidate_pkg):
                        if cand.is_file() and str(cand) not in seen_shared:
                            seen_shared.add(str(cand))
                            worklist.append(cand)
                # Also follow bare `<mod>` imports that resolve to a file
                # under shared/ (e.g. `from models.models import ...` after
                # the lambda_function adds shared/ to sys.path).
                first = imp.split(".")[0]
                bare_candidate_mod = shared_dir / (imp.replace(".", "/") + ".py")
                bare_candidate_pkg = shared_dir / imp.replace(".", "/") / "__init__.py"
                for cand in (bare_candidate_mod, bare_candidate_pkg):
                    if cand.is_file() and str(cand) not in seen_shared:
                        seen_shared.add(str(cand))
                        worklist.append(cand)

        if offending:
            failures.append(fn)
            print(f"[fail] {fn}")
            for src_file, imp, reason in offending:
                print(f"         {src_file}: imports `{imp}` ({reason})")
        else:
            print(f"[ok]   {fn}")

    print()
    if failures:
        print(f"FAIL: {len(failures)}/{len(LIGHT_FUNCTIONS)} light functions pull heavy deps")
        return 1
    print(f"PASS: all {len(LIGHT_FUNCTIONS)} light functions are clean")
    return 0


if __name__ == "__main__":
    import sys

    root = Path(__file__).resolve().parent.parent
    sys.exit(audit(root))

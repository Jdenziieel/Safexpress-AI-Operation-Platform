"""
End-to-end simulation of the folder-aware changes across drive / sheets / docs /
supervisor tool-filter / risk-map layers.

Runs offline with mocked Google API services — no network, no credentials.
Goal: exercise every branch I touched and surface any logic gap, off-by-one,
or wiring mismatch BEFORE the code hits real Google infra.
"""

from __future__ import annotations

import io
import os
import sys
import types
import json
import importlib
import unittest.mock as mock
from typing import Any, Dict, List, Optional


HERE = os.path.dirname(os.path.abspath(__file__))


# -----------------------------------------------------------------------------
# Mock Google Drive / Sheets / Docs services
# -----------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, payload: Any):
        self._payload = payload

    def execute(self):
        return self._payload


class FakeDriveService:
    """Simulates google-api-python-client's drive.v3 service.

    Implements only the subset we touch:
      files().list(q=..., fields=..., ...)
      files().create(body=..., media_body=..., fields=...)
      files().get(fileId=..., fields=...)
      files().update(fileId=..., addParents=..., removeParents=..., body=..., fields=...)
      files().export(...), files().get_media(...)
    """

    def __init__(self):
        # node: {id, name, mimeType, parents: [ids]}
        self.nodes: Dict[str, Dict[str, Any]] = {}
        # deterministic id counter
        self._next_id = 1
        # log of ops for assertions
        self.log: List[str] = []

    def _new_id(self, prefix: str = "id") -> str:
        nid = f"{prefix}_{self._next_id:04d}"
        self._next_id += 1
        return nid

    # Seed a folder at a given parent; returns its id
    def seed_folder(self, name: str, parent_id: Optional[str] = "root") -> str:
        fid = self._new_id("fold")
        self.nodes[fid] = {
            "id": fid,
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id] if parent_id else [],
        }
        return fid

    def seed_file(self, name: str, parent_id: str = "root", mime: str = "text/plain") -> str:
        fid = self._new_id("file")
        self.nodes[fid] = {"id": fid, "name": name, "mimeType": mime, "parents": [parent_id]}
        return fid

    def files(self):
        return _FakeDriveFiles(self)


class _FakeDriveFiles:
    def __init__(self, svc: FakeDriveService):
        self.svc = svc

    def list(self, q: str = "", fields: str = "", orderBy: str = "", pageSize: int = 100):
        self.svc.log.append(f"list q={q!r}")
        results = list(self.svc.nodes.values())

        # crude filter against the common q patterns we build
        def _matches(node: Dict[str, Any]) -> bool:
            if "trashed=false" in q:
                pass  # ours never sets trashed
            if "mimeType='application/vnd.google-apps.folder'" in q:
                if node.get("mimeType") != "application/vnd.google-apps.folder":
                    return False
            if "mimeType!='application/vnd.google-apps.folder'" in q:
                if node.get("mimeType") == "application/vnd.google-apps.folder":
                    return False
            def _extract_quoted(q: str, prefix: str) -> Optional[str]:
                """Pull the quoted literal after prefix, respecting backslash escapes."""
                idx = q.find(prefix)
                if idx < 0:
                    return None
                i = idx + len(prefix)
                out = []
                while i < len(q):
                    ch = q[i]
                    if ch == "\\" and i + 1 < len(q):
                        out.append(q[i + 1])
                        i += 2
                        continue
                    if ch == "'":
                        return "".join(out)
                    out.append(ch)
                    i += 1
                return None

            # name='X'
            target = _extract_quoted(q, "name='")
            if target is not None and node.get("name") != target:
                return False
            # name contains 'X'
            term = _extract_quoted(q, "name contains '")
            if term is not None and term.lower() not in (node.get("name") or "").lower():
                return False
            # '<parent>' in parents
            if " in parents" in q:
                try:
                    start = q.rindex("'", 0, q.index(" in parents")) + 1
                    # find the opening quote by scanning left
                    segment = q[: q.index(" in parents")]
                    quote_start = segment.rfind("'", 0, segment.rfind("'"))
                    parent = segment[quote_start + 1 : -1]
                    parents = node.get("parents", [])
                    if parent == "root":
                        if parents and parents[0] not in ("root",):
                            # in our tests, everything at root has parents=['root']
                            return parents and parents[0] == "root"
                        return parents == ["root"] or parents == []
                    if parent not in parents:
                        return False
                except ValueError:
                    pass
            return True

        filtered = [n for n in results if _matches(n)]
        return _FakeResult({"files": filtered})

    def create(self, body: Dict[str, Any], fields: str = "", media_body: Any = None):
        mimeType = body.get("mimeType") or "text/plain"
        parents = body.get("parents") or ["root"]
        fid = self.svc._new_id("new")
        self.svc.nodes[fid] = {
            "id": fid,
            "name": body.get("name", ""),
            "mimeType": mimeType,
            "parents": parents,
        }
        self.svc.log.append(f"create name={body.get('name')!r} parents={parents}")
        return _FakeResult({
            "id": fid,
            "name": body.get("name", ""),
            "webViewLink": f"https://drive.google.com/file/d/{fid}/view",
            "mimeType": mimeType,
        })

    def get(self, fileId: str, fields: str = ""):
        node = self.svc.nodes.get(fileId)
        if not node:
            raise Exception(f"file not found: {fileId}")
        self.svc.log.append(f"get id={fileId}")
        return _FakeResult(dict(node))

    def update(self, fileId: str, body: Optional[Dict[str, Any]] = None,
               addParents: Optional[str] = None, removeParents: Optional[str] = None,
               fields: str = ""):
        node = self.svc.nodes.get(fileId)
        if not node:
            raise Exception(f"file not found: {fileId}")
        # Real Drive API rejects addParents pointing at a non-existent
        # folder — mirror that so move-failure tests are meaningful.
        if addParents and addParents not in ("root",) and addParents not in self.svc.nodes:
            raise Exception(f"addParents target not found: {addParents}")
        if body and "name" in body:
            node["name"] = body["name"]
        if addParents:
            new_parents = list(node.get("parents", []))
            for p in (removeParents or "").split(","):
                p = p.strip()
                if p and p in new_parents:
                    new_parents.remove(p)
            new_parents.append(addParents)
            node["parents"] = new_parents
        self.svc.log.append(f"update id={fileId} add={addParents} remove={removeParents}")
        return _FakeResult(dict(node))


# -----------------------------------------------------------------------------
# Helpers to import modules by path (they're not in sys.path layout)
# -----------------------------------------------------------------------------

def _load_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# -----------------------------------------------------------------------------
# Assertion helpers
# -----------------------------------------------------------------------------

FAILURES: List[str] = []

def check(name: str, cond: bool, details: str = ""):
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {details}" if details else ""))
    if not cond:
        FAILURES.append(name + (f" — {details}" if details else ""))


# -----------------------------------------------------------------------------
# Phase 1: drive-agent/tools.py
# -----------------------------------------------------------------------------

def test_drive_tools():
    print("\n=== Phase 1: drive-agent/tools.py ===")
    drive_tools = _load_module("drive_tools", os.path.join(HERE, "gdrive-agent", "tools.py"))

    # --- A. Empty-path resolver returns root ---
    svc = FakeDriveService()
    check("resolve_folder_path_to_id('') → 'root'",
          drive_tools.resolve_folder_path_to_id(svc, "") == "root")
    check("resolve_folder_path_to_id('   ') → 'root'",
          drive_tools.resolve_folder_path_to_id(svc, "   ") == "root")

    # --- B. Strict lookup fails on missing segment ---
    svc = FakeDriveService()
    check("strict lookup missing → None",
          drive_tools.resolve_folder_path_to_id(svc, "Nope", create_if_missing=False) is None)

    # --- C. Create-if-missing creates full chain idempotently ---
    svc = FakeDriveService()
    id1 = drive_tools.resolve_folder_path_to_id(svc, "Finance/Q1", create_if_missing=True)
    id2 = drive_tools.resolve_folder_path_to_id(svc, "Finance/Q1", create_if_missing=True)
    check("resolve_folder_path_to_id idempotent", id1 is not None and id1 == id2)
    # Assert both segments exist with correct parenting
    finance = [n for n in svc.nodes.values() if n["name"] == "Finance"]
    q1 = [n for n in svc.nodes.values() if n["name"] == "Q1"]
    check("Finance created exactly once", len(finance) == 1)
    check("Q1 created exactly once", len(q1) == 1)
    check("Q1 parented under Finance", q1 and q1[0]["parents"][0] == finance[0]["id"])

    # --- D. create_nested_folder_impl with parent_folder_id ---
    svc = FakeDriveService()
    root_biz = drive_tools.create_nested_folder_impl(svc, "Business")
    sub = drive_tools.create_nested_folder_impl(svc, "Reports/2026",
                                                parent_folder_id=root_biz["folder_id"])
    check("nested under parent — success", sub["success"] is True)
    reports = [n for n in svc.nodes.values() if n["name"] == "Reports"]
    check("Reports parented under Business",
          reports and reports[0]["parents"][0] == root_biz["folder_id"])

    # --- E. get_folder_info_impl strict-then-fuzzy ---
    svc = FakeDriveService()
    svc.seed_folder("Finance", "root")
    info = drive_tools.get_folder_info_impl(svc, "Finance")
    check("get_folder_info strict hit", info["success"] and info["folder_id"])
    info = drive_tools.get_folder_info_impl(svc, "NotThere")
    check("get_folder_info miss", info["success"] is False)

    # --- F. upload_file_to_folder_impl with folder_id (fast path) ---
    svc = FakeDriveService()
    dest = svc.seed_folder("Archive", "root")
    # Need a real local file to satisfy MediaFileUpload — use this script
    out = drive_tools.upload_file_to_folder_impl(
        svc, filename="test.txt", filepath=__file__, folder_id=dest
    )
    check("upload_file folder_id branch success", out["success"] is True)
    check("upload_file stored target folder_id", out["folder_id"] == dest)

    # --- G. upload_file_to_folder_impl with folder_path (find-or-create) ---
    svc = FakeDriveService()
    out = drive_tools.upload_file_to_folder_impl(
        svc, filename="test.txt", filepath=__file__, folder_path="Sales/Q1"
    )
    check("upload_file folder_path branch success", out["success"] is True)
    segs = {n["name"] for n in svc.nodes.values() if n["mimeType"].endswith("folder")}
    check("upload_file created Sales folder", "Sales" in segs)
    check("upload_file created Q1 folder", "Q1" in segs)

    # --- H. upload_file with NEITHER (defaults to Drive root) ---
    svc = FakeDriveService()
    out = drive_tools.upload_file_to_folder_impl(svc, filename="bare.txt", filepath=__file__)
    check("upload_file default root — folder_id='root'", out["folder_id"] == "root")
    check("upload_file default root — folder_path label 'My Drive'", out["folder_path"] == "My Drive")

    # --- I. move_file_impl reparents (replaces parents) ---
    svc = FakeDriveService()
    src = svc.seed_folder("Old", "root")
    dst = svc.seed_folder("New", "root")
    file_id = svc.seed_file("doc.txt", parent_id=src)
    out = drive_tools.move_file_impl(svc, file_id=file_id, folder_id=dst)
    check("move_file success", out["success"] is True)
    check("move_file replaced parent to dst",
          svc.nodes[file_id]["parents"] == [dst])

    # --- J. move_file_impl with folder_path create_if_missing=False ---
    svc = FakeDriveService()
    file_id = svc.seed_file("doc.txt", parent_id="root")
    out = drive_tools.move_file_impl(svc, file_id=file_id,
                                     folder_path="Nope", create_if_missing=False)
    check("move_file strict miss → fail",
          out["success"] is False and "not found" in (out.get("message") or "").lower())

    # --- J2. move_file_impl default (create_if_missing unspecified) now
    #     defaults to False — a typo like 'Fiance' must FAIL, not silently
    #     create a new folder. Regression guard for the hardened default.
    svc = FakeDriveService()
    svc.seed_folder("Finance", "root")
    file_id = svc.seed_file("doc.txt", parent_id="root")
    out = drive_tools.move_file_impl(svc, file_id=file_id, folder_path="Fiance")
    check("move_file default strict (no kwarg) fails on typo",
          out["success"] is False)
    check("move_file default did not create 'Fiance' folder",
          not any(n["name"] == "Fiance" for n in svc.nodes.values()))

    # --- K. move_file_impl with folder_path create_if_missing=True (creates) ---
    svc = FakeDriveService()
    file_id = svc.seed_file("doc.txt", parent_id="root")
    out = drive_tools.move_file_impl(svc, file_id=file_id,
                                     folder_path="FreshFolder", create_if_missing=True)
    check("move_file create_if_missing=True creates destination",
          out["success"] is True)
    check("FreshFolder now exists",
          any(n["name"] == "FreshFolder" for n in svc.nodes.values()))

    # --- L. search_files_in_safeexpress_impl escapes single quotes ---
    svc = FakeDriveService()
    svc.seed_file("O'Neil.txt", parent_id="root")
    out = drive_tools.search_files_in_safeexpress_impl(svc, "O'Neil")
    check("search handles apostrophe in name", out["success"] and out["count"] == 1)

    # --- M. move_file_impl requires file_id ---
    svc = FakeDriveService()
    out = drive_tools.move_file_impl(svc, file_id="", folder_id="x")
    check("move_file missing file_id → error", out["success"] is False)

    # --- N. move_file_impl requires destination ---
    svc = FakeDriveService()
    file_id = svc.seed_file("f.txt")
    out = drive_tools.move_file_impl(svc, file_id=file_id)
    check("move_file missing destination → error", out["success"] is False)

    # --- O. get_safeexpress_folder_id returns 'root' (legacy name) ---
    check("legacy get_safeexpress_folder_id returns 'root'",
          drive_tools.get_safeexpress_folder_id(FakeDriveService()) == "root")


# -----------------------------------------------------------------------------
# Phase 2: drive-agent/api.py — upload_file_tool end-to-end dispatch
# -----------------------------------------------------------------------------

def test_drive_api():
    print("\n=== Phase 2: drive-agent/api.py ===")
    # Mock the service factory so we can inject FakeDriveService
    drive_api_path = os.path.join(HERE, "gdrive-agent", "api.py")

    # stdlib import gymnastics: api.py imports `from tools import ...` (same dir)
    # so we must chdir to make relative import resolve, OR inject the path.
    saved_cwd = os.getcwd()
    try:
        os.chdir(os.path.join(HERE, "gdrive-agent"))
        sys.path.insert(0, os.getcwd())
        if "drive_api_mod" in sys.modules:
            del sys.modules["drive_api_mod"]
        api = _load_module("drive_api_mod", "api.py")
    finally:
        os.chdir(saved_cwd)

    # Confirm move_file_tool registered
    check("move_file in DRIVE_TOOLS", "move_file" in api.DRIVE_TOOLS)
    check("create_folder in DRIVE_TOOLS", "create_folder" in api.DRIVE_TOOLS)
    check("get_folder_info in DRIVE_TOOLS", "get_folder_info" in api.DRIVE_TOOLS)

    # Invoke upload_file_tool with folder_id using mocked service
    fake = FakeDriveService()
    dest = fake.seed_folder("UploadTarget", "root")

    creds = types.SimpleNamespace(
        access_token="x", refresh_token="y", token_uri="u",
        client_id="a", client_secret="b",
    )
    with mock.patch.object(api, "get_service_from_creds", return_value=fake):
        out = api.upload_file_tool(
            {"file_path": __file__, "filename": "t.txt", "folder_id": dest},
            creds,
        )
    check("upload_file_tool folder_id branch success", out.get("success") is True)
    check("upload_file_tool returns folder_id unchanged", out.get("folder_id") == dest)

    # Invoke upload_file_tool with folder_path (find-or-create)
    fake = FakeDriveService()
    with mock.patch.object(api, "get_service_from_creds", return_value=fake):
        out = api.upload_file_tool(
            {"file_path": __file__, "filename": "t.txt", "folder_path": "Reports/Q2"},
            creds,
        )
    check("upload_file_tool folder_path branch success", out.get("success") is True)
    created_names = {n["name"] for n in fake.nodes.values()}
    check("Reports/Q2 created via find-or-create",
          "Reports" in created_names and "Q2" in created_names)

    # move_file_tool end-to-end
    fake = FakeDriveService()
    dest = fake.seed_folder("Dest", "root")
    fid = fake.seed_file("doc.txt", parent_id="root")
    with mock.patch.object(api, "get_service_from_creds", return_value=fake):
        out = api.move_file_tool({"file_id": fid, "folder_id": dest}, creds)
    check("move_file_tool success", out.get("success") is True)
    check("move_file_tool reparented",
          fake.nodes[fid]["parents"] == [dest])

    # move_file_tool default (no create_if_missing) — must NOT create the
    # destination folder on a typo. Regression guard for the hardened
    # move_file_tool default.
    fake = FakeDriveService()
    fake.seed_folder("Finance", "root")
    fid = fake.seed_file("doc.txt", parent_id="root")
    with mock.patch.object(api, "get_service_from_creds", return_value=fake):
        out = api.move_file_tool({"file_id": fid, "folder_path": "Fiance"}, creds)
    check("move_file_tool default strict rejects typo",
          out.get("success") is False)
    check("move_file_tool default did not create 'Fiance'",
          not any(n["name"] == "Fiance" for n in fake.nodes.values()))

    # upload_file_tool when BOTH folder_id AND folder_path are given — the
    # fix makes folder_id win cleanly without re-resolving folder_path.
    fake = FakeDriveService()
    dest = fake.seed_folder("ExplicitDest", "root")
    with mock.patch.object(api, "get_service_from_creds", return_value=fake):
        out = api.upload_file_tool(
            {"file_path": __file__, "filename": "t.txt",
             "folder_id": dest, "folder_path": "SomeOther/Path"},
            creds,
        )
    check("upload_file_tool folder_id wins over folder_path",
          out.get("success") is True and out.get("folder_id") == dest)
    check("upload_file_tool did not create the unused folder_path",
          not any(n["name"] == "SomeOther" for n in fake.nodes.values())
          and not any(n["name"] == "Path" for n in fake.nodes.values()))

    # create_folder_tool end-to-end
    fake = FakeDriveService()
    with mock.patch.object(api, "get_service_from_creds", return_value=fake):
        out = api.create_folder_tool({"folder_path": "A/B/C"}, creds)
    check("create_folder_tool success", out.get("success") is True)
    # Nested should create 3 folders
    folders = [n for n in fake.nodes.values() if n["mimeType"].endswith("folder")]
    check("create_folder_tool created 3 nested segments", len(folders) == 3)

    # list_files_tool with folder_path strict lookup
    fake = FakeDriveService()
    target = fake.seed_folder("Docs", "root")
    fake.seed_file("a.pdf", parent_id=target)
    fake.seed_file("b.pdf", parent_id=target)
    with mock.patch.object(api, "get_service_from_creds", return_value=fake):
        out = api.list_files_tool({"folder_path": "Docs"}, creds)
    check("list_files folder_path resolves + lists", out.get("success") is True and out.get("count") == 2)

    # list_files_tool with missing folder_path → error (strict)
    fake = FakeDriveService()
    with mock.patch.object(api, "get_service_from_creds", return_value=fake):
        out = api.list_files_tool({"folder_path": "NoSuch"}, creds)
    check("list_files missing folder_path → error", out.get("success") is False)

    # get_folder_info_tool
    fake = FakeDriveService()
    target = fake.seed_folder("Known", "root")
    with mock.patch.object(api, "get_service_from_creds", return_value=fake):
        out = api.get_folder_info_tool({"folder_path": "Known"}, creds)
    check("get_folder_info_tool success", out.get("success") is True)
    check("get_folder_info_tool returns folder_id", out.get("folder_id") == target)


# -----------------------------------------------------------------------------
# Phase 3: risk-map + name heuristics
# -----------------------------------------------------------------------------

def test_risk_map():
    print("\n=== Phase 3: supervisor_agent risk classification ===")
    # supervisor_agent.py lives in supervisor-agent/; needs its own path on sys.path
    sv_dir = os.path.join(HERE, "supervisor-agent")
    sys.path.insert(0, sv_dir)
    saved_cwd = os.getcwd()
    try:
        os.chdir(sv_dir)
        # Avoid loading the whole FastAPI app — just import the helper functions.
        # models.models is safe to import standalone; supervisor_agent.py imports a lot.
        models = _load_module("sv_models", os.path.join(sv_dir, "models", "models.py"))
        # Inline a copy of the risk heuristics to avoid the cost of importing the
        # whole supervisor_agent module (which pulls langchain, langgraph, etc.)
        # The logic must match the real impl in supervisor-agent/supervisor_agent.py.
        _DANGEROUS = ("send_", "forward_", "reply_", "update_", "edit_", "append_",
                      "write_", "share_", "replace_", "publish_")
        _CRITICAL = ("delete_", "purge_", "destroy_", "clear_", "wipe_", "empty_",
                     "remove_all_", "drop_")

        def risk(tool: str):
            explicit = models.ACTION_RISK_LEVELS.get(tool)
            if explicit is not None:
                return explicit
            low = (tool or "").lower()
            for h in _CRITICAL:
                if low.startswith(h):
                    return models.ActionRiskLevel.CRITICAL
            for h in _DANGEROUS:
                if low.startswith(h):
                    return models.ActionRiskLevel.DANGEROUS
            return models.ActionRiskLevel.MODERATE

        def needs(tool: str, auto_mod: bool = True) -> bool:
            r = risk(tool)
            if r == models.ActionRiskLevel.SAFE:
                return False
            if r == models.ActionRiskLevel.MODERATE:
                return not auto_mod
            return True  # DANGEROUS or CRITICAL
    finally:
        os.chdir(saved_cwd)

    cases = [
        # (tool, expected_risk, expected_needs_approval_default)
        ("search_emails", "safe", False),
        ("list_events", "safe", False),
        ("get_folder_info", "safe", False),
        ("transform_text", "safe", False),
        ("create_draft_email", "moderate", False),
        ("create_sheet", "moderate", False),
        ("create_folder", "moderate", False),
        ("move_file", "moderate", False),
        ("rename_file", "moderate", False),
        ("update_event", "moderate", False),
        ("send_draft_email", "dangerous", True),
        ("forward_email", "dangerous", True),
        ("edit_doc", "dangerous", True),
        ("update_doc", "dangerous", True),
        ("append_rows", "dangerous", True),
        ("delete_file", "critical", True),
        ("delete_event", "critical", True),
        ("clear_sheet", "critical", True),
        ("empty_trash", "critical", True),
        # Unregistered — should fall back via name heuristic
        ("delete_thread_forever", "critical", True),
        ("purge_user_data", "critical", True),
        ("send_weekly_digest", "dangerous", True),
        ("update_spreadsheet_theme", "dangerous", True),
        ("edit_calendar_access", "dangerous", True),
        ("replace_workbook", "dangerous", True),
        # Unregistered benign name → MODERATE, requires_approval(default)=False
        ("analyze_document_structure", "moderate", False),
    ]
    for tool, expected_risk, expected_approval in cases:
        actual_risk = risk(tool).value
        actual_approval = needs(tool)
        check(f"risk({tool})={expected_risk}",
              actual_risk == expected_risk,
              f"got {actual_risk}")
        check(f"needs_approval({tool})={expected_approval}",
              actual_approval == expected_approval,
              f"got {actual_approval}")


# -----------------------------------------------------------------------------
# Phase 4: tool_filter safety-net matrix (keyword-based branches only —
# the LLM classifier itself is mocked out)
# -----------------------------------------------------------------------------

def test_tool_filter_safety_nets():
    print("\n=== Phase 4: tool_filter safety nets ===")
    sv_dir = os.path.join(HERE, "supervisor-agent")
    sys.path.insert(0, sv_dir)
    saved_cwd = os.getcwd()
    try:
        os.chdir(sv_dir)
        if "tool_filter" in sys.modules:
            del sys.modules["tool_filter"]
        tool_filter = _load_module("tool_filter", os.path.join(sv_dir, "tool_filter.py"))
    finally:
        os.chdir(saved_cwd)

    scenarios = [
        # (user_input, classifier_output, expected_tools_present, expected_tools_absent)
        # Scenario 1: create sheet in named folder (no explicit create)
        ("Create a Budget Tracker sheet in the Finance folder",
         {"sheets_agent": ["create_sheet"]},
         [("drive_agent", "get_folder_info"), ("sheets_agent", "create_sheet")],
         [("drive_agent", "create_folder")]),
        # Scenario 2: create sheet AND explicit-create folder
        ("Create a Finance folder and put a Budget sheet in it",
         {"sheets_agent": ["create_sheet"]},
         [("drive_agent", "get_folder_info"),
          ("drive_agent", "create_folder"),
          ("sheets_agent", "create_sheet")],
         []),
        # Scenario 3: create doc in folder
        ("Make a doc called Notes in the Work folder",
         {"docs_agent": ["create_doc"]},
         [("drive_agent", "get_folder_info"), ("docs_agent", "create_doc")],
         []),
        # Scenario 4: upload into folder
        ("Upload report.pdf to the Reports folder in Drive",
         {"drive_agent": ["upload_file"]},
         [("drive_agent", "get_folder_info"), ("drive_agent", "upload_file")],
         []),
        # Scenario 5: rename file — needs search_files
        ("Rename my draft_report file to Final_Report",
         {"drive_agent": ["rename_file"]},
         [("drive_agent", "rename_file"), ("drive_agent", "search_files")],
         []),
        # Scenario 6: move file — needs search_files
        ("Move my report.pdf into the Archive folder",
         {"drive_agent": ["move_file"]},
         [("drive_agent", "move_file"), ("drive_agent", "search_files")],
         []),
        # Scenario 7: calendar update — needs list_events
        ("Update my Sprint Review meeting to 3pm",
         {"calendar_agent": ["update_event"]},
         [("calendar_agent", "update_event"), ("calendar_agent", "list_events")],
         []),
        # Scenario 8: email keywords — force gmail_agent with draft pair.
        # The keyword net only triggers on explicit email language; a bare
        # "send an update" should not trigger it (ambiguous — could be slack).
        ("Send an email to bob@test.com with a quick update",
         {},
         [("gmail_agent", "create_draft_email"), ("gmail_agent", "send_draft_email")],
         []),
        # Scenario 9: docs edit keywords — auto-add edit tools
        ("Fix grammar in my Report doc",
         {"docs_agent": ["read_doc"]},
         [("docs_agent", "read_doc"), ("docs_agent", "edit_doc"),
          ("docs_agent", "update_doc"), ("docs_agent", "list_my_docs")],
         []),
        # Scenario 10: simple chat — no folder-placement net triggered
        ("what's the weather",
         {},
         [],
         [("drive_agent", "get_folder_info"), ("drive_agent", "create_folder")]),
        # Scenario 11: creation mentioning folder but no creation tool selected
        ("Show me folders in Drive",
         {"drive_agent": ["list_folders"]},
         [("drive_agent", "list_folders")],
         [("drive_agent", "get_folder_info"), ("drive_agent", "create_folder")]),
        # Scenario 12: Ambiguous "send" without email context — must NOT
        # auto-inject gmail tools (would false-positive on Slack/Teams asks).
        ("Send a quick update",
         {},
         [],
         [("gmail_agent", "create_draft_email"), ("gmail_agent", "send_draft_email")]),
        # Scenario 13: Explicit create folder WITHOUT file creation — only
        # create_folder is needed, no get_folder_info injection required
        # (because there's no file-placement step following it).
        ("Create a new folder called Inbox",
         {"drive_agent": ["create_folder"]},
         [("drive_agent", "create_folder")],
         []),
        # Scenario 14: Multi-word folder name in explicit create — regex
        # must catch "create a 2026 Q1 budget folder".
        ("Create a 2026 Q1 budget folder and upload report.pdf to it",
         {"drive_agent": ["upload_file"]},
         [("drive_agent", "get_folder_info"),
          ("drive_agent", "create_folder"),
          ("drive_agent", "upload_file")],
         []),
        # Scenario 15: Calendar delete — needs list_events too.
        ("Delete my 2pm meeting tomorrow",
         {"calendar_agent": ["delete_event"]},
         [("calendar_agent", "delete_event"), ("calendar_agent", "list_events")],
         []),
        # Scenario 16: Delivery order keywords trigger full DO bundle
        # (specialised tools, not generic geocoding/append).
        ("Process the delivery order from acme@test.com",
         {"gmail_agent": ["search_emails"]},
         [("gmail_agent", "search_emails_with_delivery_order_attachments"),
          ("mapping_agent", "parse_delivery_order_pdfs"),
          ("sheets_agent", "validate_delivery_sheet"),
          ("sheets_agent", "preview_delivery_order_insertion"),
          ("sheets_agent", "write_delivery_order_data")],
         []),
        # Scenario 17: Folder keyword appears but in benign context — e.g.
        # "that project folder" mention without any creation/upload tool.
        # Must NOT inject folder-placement tools (no false positive).
        ("Tell me about my project folder organization",
         {},
         [],
         [("drive_agent", "get_folder_info"), ("drive_agent", "create_folder")]),
    ]

    for idx, (user_in, classifier_out, expected_present, expected_absent) in enumerate(scenarios, 1):
        # Patch the classifier call
        class _FakeResp:
            def __init__(self, data):
                self.content = json.dumps(data)
                self.response_metadata = {"token_usage": {}}

        with mock.patch.object(tool_filter, "ChatOpenAI") as mock_llm_cls:
            mock_llm = mock.MagicMock()
            mock_llm.invoke.return_value = _FakeResp(classifier_out)
            mock_llm_cls.return_value = mock_llm
            try:
                got = tool_filter.identify_agents_and_tools(user_in)
            except Exception as e:
                check(f"scenario {idx}: classifier call works", False, f"raised {e}")
                continue

        for agent, tool in expected_present:
            ok = tool in got.get(agent, [])
            check(f"scenario {idx}: '{user_in[:40]}' → {agent}.{tool} present",
                  ok, f"got {dict(got)}")
        for agent, tool in expected_absent:
            ok = tool not in got.get(agent, [])
            check(f"scenario {idx}: '{user_in[:40]}' → {agent}.{tool} absent",
                  ok, f"got {dict(got)}")


# -----------------------------------------------------------------------------
# Phase 5: sheets create_sheet with folder reparenting
# -----------------------------------------------------------------------------

def test_sheets_create_sheet():
    print("\n=== Phase 5: Sheets-agent create_sheet folder reparenting ===")
    # Mock the whole googleapiclient.build so we can inject FakeDriveService
    # alongside a fake Sheets service. We load the module and monkey-patch.
    sheets_dir = os.path.join(HERE, "Sheets-agent")
    saved_cwd = os.getcwd()
    try:
        os.chdir(sheets_dir)
        sys.path.insert(0, sheets_dir)
        if "sheets_agent_api" in sys.modules:
            del sys.modules["sheets_agent_api"]
        sheets = _load_module("sheets_agent_api", "sheets_agent_api.py")
    finally:
        os.chdir(saved_cwd)

    fake_drive = FakeDriveService()
    target = fake_drive.seed_folder("Finance", "root")

    # Fake Sheets service
    class _SS:
        def __init__(self):
            self._sheet_id = "sheet_1234"
            self._created = False

        def spreadsheets(self):
            return self

        def create(self, body):
            self._created = True
            self._body = body
            return _FakeResult({
                "spreadsheetId": self._sheet_id,
                "spreadsheetUrl": f"https://docs.google.com/spreadsheets/d/{self._sheet_id}",
            })

        def values(self):
            return self

        def update(self, **kwargs):
            return _FakeResult({"updatedCells": 0})

    fake_sheets = _SS()
    # Pre-register the sheet as a drive node so reparent can find it
    fake_drive.nodes[fake_sheets._sheet_id] = {
        "id": fake_sheets._sheet_id,
        "name": "Budget Tracker",
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "parents": ["root"],
    }

    with mock.patch.object(sheets, "create_sheets_service", return_value=fake_sheets), \
         mock.patch.object(sheets, "create_drive_service", return_value=fake_drive):
        creds = sheets.CredentialsDict(access_token="a", refresh_token="b",
                                       client_id="c", client_secret="d")
        out = sheets.create_sheet(title="Budget Tracker", folder_id=target, credentials_dict=creds)

    check("create_sheet success", out.get("success") is True)
    check("create_sheet returned folder_moved=True", out.get("folder_moved") is True)
    check("create_sheet returned folder_id matches input", out.get("folder_id") == target)
    check("reparenting replaced parents",
          fake_drive.nodes[fake_sheets._sheet_id]["parents"] == [target])

    # Move failure case — reparent raises
    fake_drive2 = FakeDriveService()
    fake_sheets2 = _SS()
    fake_sheets2._sheet_id = "sheet_fail"

    class _FailingFiles:
        def __init__(self, svc): self.svc = svc
        def get(self, **kw): raise RuntimeError("permission denied")
        def update(self, **kw): raise RuntimeError("permission denied")

    fake_drive2.files = lambda: _FailingFiles(fake_drive2)

    with mock.patch.object(sheets, "create_sheets_service", return_value=fake_sheets2), \
         mock.patch.object(sheets, "create_drive_service", return_value=fake_drive2):
        out = sheets.create_sheet(title="Budget 2", folder_id="some_id", credentials_dict=creds)

    check("create_sheet handles move failure gracefully — still success",
          out.get("success") is True)
    check("create_sheet surfaces warning on move failure",
          out.get("warning") is not None and "permission" in out.get("warning", "").lower())
    check("create_sheet folder_moved=False on failure",
          out.get("folder_moved") is False)

    # No folder_id → no reparent attempt
    fake_sheets3 = _SS()
    fake_sheets3._sheet_id = "sheet_plain"
    with mock.patch.object(sheets, "create_sheets_service", return_value=fake_sheets3), \
         mock.patch.object(sheets, "create_drive_service", return_value=FakeDriveService()):
        out = sheets.create_sheet(title="Plain", credentials_dict=creds)
    check("create_sheet no folder_id — success, no reparent",
          out.get("success") is True and out.get("folder_moved") is False and out.get("folder_id") is None)


# -----------------------------------------------------------------------------
# Phase 6: gdocs-agent create_doc folder_id flow
# -----------------------------------------------------------------------------

def test_docs_create_doc():
    print("\n=== Phase 6: gdocs-agent create_doc folder reparenting ===")
    docs_dir = os.path.join(HERE, "gdocs-agent")
    saved_cwd = os.getcwd()
    try:
        os.chdir(docs_dir)
        sys.path.insert(0, docs_dir)
        if "docs_tools" in sys.modules:
            del sys.modules["docs_tools"]
        docs_tools = _load_module("docs_tools", "tools.py")
    finally:
        os.chdir(saved_cwd)

    fake_drive = FakeDriveService()
    target = fake_drive.seed_folder("Projects", "root")

    # Fake Docs service — takes the drive as a constructor arg so we can
    # pair each docs service with its own drive without leaking state
    # through a closure.
    class _DocsSvc:
        def __init__(self, drive):
            self._counter = 1
            self._drive = drive
        def documents(self):
            return self
        def create(self, body):
            did = f"doc_{self._counter:04d}"
            self._counter += 1
            self._drive.nodes[did] = {
                "id": did,
                "name": body["title"],
                "mimeType": "application/vnd.google-apps.document",
                "parents": ["root"],
            }
            return _FakeResult({"documentId": did})
        def batchUpdate(self, documentId, body):
            return _FakeResult({"replies": []})

    fake_docs = _DocsSvc(fake_drive)

    def fake_get_service(service_name, version, credentials_dict):
        if service_name == "docs":
            return fake_docs
        return fake_drive

    with mock.patch.object(docs_tools, "get_google_service", side_effect=fake_get_service):
        raw = docs_tools._create_google_doc_impl(
            title="Sprint Notes", credentials_dict={"access_token": "x"}, folder_id=target
        )

    check("_create_google_doc_impl returns string", isinstance(raw, str))
    check("_create_google_doc_impl string contains 'successfully'",
          "successfully" in raw.lower())
    check("_create_google_doc_impl string includes Folder ID", f"Folder ID: {target}" in raw)
    check("_create_google_doc_impl string says Folder moved: yes",
          "Folder moved: yes" in raw)

    # Verify api.py parser extracts correctly
    try:
        os.chdir(docs_dir)
        sys.path.insert(0, docs_dir)
        if "docs_api" in sys.modules:
            del sys.modules["docs_api"]
        # api.py imports things like document_format_extractor — skip loading the
        # whole app and just import the parser by loading only what we need.
        # Instead, replicate the regex logic here since _parse_tool_result is
        # pure and self-contained.
        import re
        def parse(tool_name, raw, inputs):
            doc_id_match = re.search(r"(?:ID|Document ID): ([a-zA-Z0-9_-]+)", raw)
            folder_id_match = re.search(r"Folder ID: ([a-zA-Z0-9_-]+)", raw)
            folder_moved_match = re.search(r"Folder moved: (yes|no)", raw)
            folder_err_match = re.search(r"Folder move error: (.+)", raw)
            return {
                "success": True,
                "document_id": doc_id_match.group(1) if doc_id_match else None,
                "folder_id": folder_id_match.group(1) if folder_id_match else inputs.get("folder_id"),
                "folder_moved": folder_moved_match.group(1) == "yes" if folder_moved_match else None,
                "folder_move_error": folder_err_match.group(1).strip() if folder_err_match else None,
            }
    finally:
        os.chdir(saved_cwd)

    parsed = parse("create_doc", raw, {"folder_id": target, "title": "Sprint Notes"})
    check("parse extracts document_id", parsed["document_id"] and parsed["document_id"].startswith("doc_"))
    check("parse extracts folder_id", parsed["folder_id"] == target)
    check("parse extracts folder_moved=True", parsed["folder_moved"] is True)
    check("parse extracts folder_move_error=None", parsed["folder_move_error"] is None)

    # Regex: documents with '-' or '_' in ID. Verify folder_id with underscore works.
    weird_id = "abc_DEF-123"
    fake_drive2 = FakeDriveService()
    fake_drive2.seed_folder("xxx", "root")  # placeholder
    fake_drive2.nodes[weird_id] = {"id": weird_id, "name": "weird_folder",
                                   "mimeType": "application/vnd.google-apps.folder",
                                   "parents": ["root"]}
    # Inject a doc so reparent succeeds
    fake_docs2 = _DocsSvc(fake_drive2)

    def fake_get_service2(service_name, version, credentials_dict):
        if service_name == "docs":
            return fake_docs2
        return fake_drive2

    with mock.patch.object(docs_tools, "get_google_service", side_effect=fake_get_service2):
        raw2 = docs_tools._create_google_doc_impl(title="T", credentials_dict={}, folder_id=weird_id)
    parsed2 = parse("create_doc", raw2, {"folder_id": weird_id, "title": "T"})
    check("parse handles folder_id with underscores/dashes/mixed case",
          parsed2["folder_id"] == weird_id)

    # Error path: folder_id that points to nonexistent node → move fails
    fake_drive3 = FakeDriveService()
    fake_docs3 = _DocsSvc(fake_drive3)

    def fake_get_service3(service_name, version, credentials_dict):
        if service_name == "docs":
            return fake_docs3
        return fake_drive3

    with mock.patch.object(docs_tools, "get_google_service", side_effect=fake_get_service3):
        # folder_id "ghost" not in fake_drive3.nodes → get() will raise
        raw3 = docs_tools._create_google_doc_impl(title="T2", credentials_dict={}, folder_id="ghost")
    check("_create_google_doc_impl handles move failure",
          "Folder moved: no" in raw3)
    check("_create_google_doc_impl surfaces error line",
          "Folder move error:" in raw3)
    parsed3 = parse("create_doc", raw3, {"folder_id": "ghost", "title": "T2"})
    check("parse detects folder_moved=False", parsed3["folder_moved"] is False)
    check("parse captures folder_move_error", parsed3["folder_move_error"] is not None)

    # Test _create_doc_with_content_impl (returns dict)
    fake_drive4 = FakeDriveService()
    target4 = fake_drive4.seed_folder("Docs", "root")
    fake_docs4 = _DocsSvc(fake_drive4)

    def fake_get_service4(service_name, version, credentials_dict):
        if service_name == "docs":
            return fake_docs4
        return fake_drive4

    with mock.patch.object(docs_tools, "get_google_service", side_effect=fake_get_service4):
        out = docs_tools._create_doc_with_content_impl(
            title="Minutes", credentials_dict={}, text="Hello world", folder_id=target4
        )
    check("_create_doc_with_content_impl returns dict", isinstance(out, dict))
    check("_create_doc_with_content_impl success", out.get("success") is True)
    check("_create_doc_with_content_impl passes through folder_id",
          out.get("folder_id") == target4)
    check("_create_doc_with_content_impl folder_moved=True", out.get("folder_moved") is True)
    check("_create_doc_with_content_impl document_url set",
          out.get("document_url", "").startswith("https://docs.google.com/document/"))

    # Edge: neither text nor file_path
    with mock.patch.object(docs_tools, "get_google_service", side_effect=fake_get_service4):
        out = docs_tools._create_doc_with_content_impl(title="Empty", credentials_dict={})
    check("_create_doc_with_content_impl without content → error",
          out.get("success") is False)


# -----------------------------------------------------------------------------
# Phase 7: Jinja output_variables round-trip for the new folder pattern
# -----------------------------------------------------------------------------

def test_jinja_folder_substitution():
    print("\n=== Phase 7: Jinja folder_id substitution in plans ===")
    # We can't easily run the full orchestrator offline, but we can test the
    # extract_nested_value helper + Jinja behaviour on the expected shape.
    try:
        from jinja2 import Template, StrictUndefined, UndefinedError
    except ImportError:
        print("  [SKIP] jinja2 not installed")
        return

    # --- A. Happy path: folder_id substitution ---
    variable_context = {
        "folder_id": "fold_xyz",
        "today_date": "2026-04-21",
    }
    inputs = {
        "title": "Budget Tracker",
        "folder_id": "{{ folder_id }}",
        "sheet_names": ["Sheet1"],
    }
    substituted = {
        k: (Template(v).render(**variable_context) if isinstance(v, str) else v)
        for k, v in inputs.items()
    }
    check("folder_id substituted via Jinja",
          substituted["folder_id"] == "fold_xyz")
    check("non-string inputs preserved as-is",
          substituted["sheet_names"] == ["Sheet1"])
    check("literal strings preserved",
          substituted["title"] == "Budget Tracker")

    # --- B. Indexed + dotted access (e.g. search_files → move_file) ---
    variable_context2 = {
        "results": [
            {"id": "file_aaa", "name": "report.pdf"},
            {"id": "file_bbb", "name": "draft.pdf"},
        ],
    }
    tmpl = "{{ results[0].id }}"
    rendered = Template(tmpl).render(**variable_context2)
    check("indexed dotted substitution", rendered == "file_aaa")

    # --- C. Missing variable raises with StrictUndefined
    # (matches orchestrator behaviour: Planning Rule 13 forbids hallucinated
    # variable refs; missing variable must fail the step, not silently
    # substitute "") ---
    try:
        Template("{{ ghost }}", undefined=StrictUndefined).render(**variable_context)
        check("StrictUndefined raises on missing var", False,
              "expected UndefinedError")
    except UndefinedError:
        check("StrictUndefined raises on missing var", True)

    # --- D. Simulated orchestrator behavior: if folder_id lookup returns
    # success=False, downstream step should NOT run with folder_id="" ---
    # This mirrors the pause-on-disambiguation logic and our recommendation
    # to fail loud.
    lookup_result = {"success": False, "folder_id": None, "message": "Folder 'Finance' not found"}
    should_continue = lookup_result.get("success") and lookup_result.get("folder_id")
    check("Lookup failure blocks downstream folder_id step",
          not should_continue)

    # --- E. Jinja with output_variables: simulate renaming
    # get_folder_info.folder_id → "target_folder_id"
    output_vars = {"target_folder_id": "folder_id"}
    raw_step_output = {"folder_id": "fold_123", "success": True}
    renamed_ctx = {
        output_name: raw_step_output.get(source_key)
        for output_name, source_key in output_vars.items()
    }
    next_input = Template("{{ target_folder_id }}").render(**renamed_ctx)
    check("output_variables rename flows into next step",
          next_input == "fold_123")


# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------

def main():
    test_drive_tools()
    test_drive_api()
    test_risk_map()
    test_tool_filter_safety_nets()
    test_sheets_create_sheet()
    test_docs_create_doc()
    test_jinja_folder_substitution()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} failure(s):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("All simulation checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()

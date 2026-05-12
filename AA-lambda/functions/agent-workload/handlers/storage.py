"""Storage adapter for the agent-workload Lambda.

Two backends, selected via the `WORKLOAD_STORAGE` env var (default `sqlite`
for local development; deployed Lambda sets `dynamodb`):

- `dynamodb` -> three real tables in AWS (workload-config, workload-history,
  workload-uom). PK = string. See `AA-lambda/infra/workload-dynamodb.yaml`
  for the table definitions and seed data.

- `sqlite`  -> a single local SQLite file (path from `WORKLOAD_SQLITE_PATH`,
  default `./workload.db`). Used by the Flask local-dev shim AND by tests.
  Schema is created on first use.

The two backends expose the same `WorkloadStorage` interface so handlers
don't care which one is active.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

try:  # pragma: no cover - boto3 is only present in the Lambda runtime
    import boto3
    from boto3.dynamodb.conditions import Key
except ImportError:  # noqa: BLE001
    boto3 = None  # type: ignore[assignment]
    Key = None  # type: ignore[assignment]

from .calculate import DEFAULT_RATES


# Default UOM list: union of UOMs seen in the two sample PDFs plus the two
# universal ones from the xlsx (Pcs, Pallet). Admin can add/remove later.
# UOMs are intentionally GLOBAL (operational vocabulary, not user preference).
DEFAULT_UOMS: List[str] = [
    "Pack", "Case", "Can", "Bottle", "Jar", "Pouch", "Block", "Container",
    "Gal", "Tetra", "Box", "Roll", "Canister", "Bar", "Pcs", "Pallet",
]

# Sentinel partition value for the org-wide default rate set. A user with no
# personal config falls back to this row, which itself falls back to the
# hard-coded DEFAULT_RATES if even the sentinel is missing.
DEFAULT_USER_ID = "__default__"


def _coerce_user_id(user_id: Optional[str]) -> str:
    """Treat empty/None as the org-default partition. Anything else (a real
    email or JWT subject) becomes the user's own partition."""
    if not user_id:
        return DEFAULT_USER_ID
    return str(user_id).strip() or DEFAULT_USER_ID


def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ----------------------------------------------------------------------
# SQLite backend
# ----------------------------------------------------------------------


class SqliteStorage:
    """SQLite-backed storage. Stores rates as a single JSON blob to avoid
    schema churn when we add new rate keys."""

    _DEFAULT_PATH = os.environ.get("WORKLOAD_SQLITE_PATH", "workload.db")

    def __init__(self, path: Optional[str] = None):
        self.path = path or self._DEFAULT_PATH
        self._lock = threading.Lock()
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._conn() as conn:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS workload_config (
                    config_key  TEXT PRIMARY KEY,
                    rates_json  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    updated_by  TEXT
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS workload_history (
                    id                  TEXT PRIMARY KEY,
                    user_id             TEXT NOT NULL DEFAULT '__default__',
                    mode                TEXT NOT NULL,
                    basis               TEXT NOT NULL,
                    pallet_count        REAL NOT NULL,
                    total_qty           REAL NOT NULL,
                    number_of_workers   INTEGER NOT NULL,
                    total_seconds       REAL NOT NULL,
                    phase_breakdown     TEXT NOT NULL,
                    pallets             TEXT NOT NULL,
                    items               TEXT NOT NULL,
                    notes               TEXT,
                    created_by          TEXT,
                    created_at          TEXT NOT NULL
                )
            """)
            # Add user_id column to pre-existing tables created before this
            # change (idempotent: ignore "duplicate column" errors).
            try:
                c.execute(
                    "ALTER TABLE workload_history "
                    "ADD COLUMN user_id TEXT NOT NULL DEFAULT '__default__'"
                )
            except sqlite3.OperationalError:
                pass
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_workload_history_user "
                "ON workload_history(user_id, created_at)"
            )
            c.execute("""
                CREATE TABLE IF NOT EXISTS workload_uom (
                    uom  TEXT PRIMARY KEY
                )
            """)
            # Seed the org-default config row on first run. The legacy
            # config_key='current' row is left alone (deprecated, ignored by
            # the per-user lookup) so we never destroy whatever rates were
            # in there.
            c.execute(
                "SELECT 1 FROM workload_config WHERE config_key = ?",
                (DEFAULT_USER_ID,),
            )
            if c.fetchone() is None:
                c.execute(
                    "INSERT INTO workload_config(config_key, rates_json, updated_at, updated_by) "
                    "VALUES (?,?,?,?)",
                    (DEFAULT_USER_ID, json.dumps(DEFAULT_RATES), _now_iso(), "system"),
                )
            for u in DEFAULT_UOMS:
                c.execute("INSERT OR IGNORE INTO workload_uom(uom) VALUES (?)", (u,))
            conn.commit()

    # ----- config (per-user with org-default fallback) -----

    def get_config(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Return the caller's personal rates, or fall back to the org default.

        Lookup order:
          1. workload_config row keyed by `user_id`
          2. workload_config row keyed by DEFAULT_USER_ID ('__default__')
          3. hard-coded DEFAULT_RATES from code

        `userId` is echoed back so the frontend can show whose config this is
        and whether it's the user's own or the inherited org default.
        """
        owner = _coerce_user_id(user_id)
        with self._lock, self._conn() as conn:
            personal = conn.execute(
                "SELECT * FROM workload_config WHERE config_key = ?", (owner,)
            ).fetchone()
            row = personal
            if row is None and owner != DEFAULT_USER_ID:
                row = conn.execute(
                    "SELECT * FROM workload_config WHERE config_key = ?",
                    (DEFAULT_USER_ID,),
                ).fetchone()
        inherited = (owner != DEFAULT_USER_ID) and (personal is None)

        if row is None:
            return {
                "userId":               owner,
                "isDefault":            owner == DEFAULT_USER_ID,
                "inheritedFromDefault": inherited,
                **DEFAULT_RATES,
                "updatedAt": None,
                "updatedBy": None,
            }
        rates = json.loads(row["rates_json"])
        return {
            "userId":               owner,
            "isDefault":            owner == DEFAULT_USER_ID,
            "inheritedFromDefault": inherited,
            **{**DEFAULT_RATES, **rates},
            "updatedAt": row["updated_at"],
            "updatedBy": row["updated_by"],
        }

    def update_config(self, rates: Dict[str, Any],
                      updated_by: Optional[str],
                      user_id: Optional[str] = None) -> Dict[str, Any]:
        """Write the rates into THIS user's row only. Other users are not
        affected. Passing `user_id=None` updates the org default (used by the
        seeder + admin tools)."""
        owner = _coerce_user_id(user_id)
        merged = {**DEFAULT_RATES, **self._sanitize_rates(rates)}
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO workload_config(config_key, rates_json, updated_at, updated_by)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(config_key) DO UPDATE SET
                    rates_json = excluded.rates_json,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (owner, json.dumps(merged), _now_iso(), updated_by),
            )
            conn.commit()
        return self.get_config(user_id)

    def reset_config(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Drop the user's personal row so they fall back to the org default."""
        owner = _coerce_user_id(user_id)
        if owner == DEFAULT_USER_ID:
            return self.get_config(user_id)
        with self._lock, self._conn() as conn:
            conn.execute(
                "DELETE FROM workload_config WHERE config_key = ?", (owner,)
            )
            conn.commit()
        return self.get_config(user_id)

    @staticmethod
    def _sanitize_rates(rates: Dict[str, Any]) -> Dict[str, float]:
        clean: Dict[str, float] = {}
        for key, value in (rates or {}).items():
            if key not in DEFAULT_RATES:
                continue
            try:
                clean[key] = float(value)
            except (TypeError, ValueError):
                continue
        return clean

    # ----- history (scoped to the calling user) -----

    def save_history(self, calc_result: Dict[str, Any],
                     notes: str, created_by: str,
                     user_id: Optional[str] = None) -> Dict[str, Any]:
        owner = _coerce_user_id(user_id)
        history_id = str(uuid.uuid4())
        created_at = _now_iso()
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO workload_history (
                    id, user_id, mode, basis, pallet_count, total_qty,
                    number_of_workers, total_seconds, phase_breakdown,
                    pallets, items, notes, created_by, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    history_id,
                    owner,
                    calc_result["mode"],
                    calc_result["basis"],
                    float(calc_result["palletCount"]),
                    float(calc_result["totalQty"]),
                    int(calc_result["numberOfWorkers"]),
                    float(calc_result["totalSeconds"]),
                    json.dumps(calc_result["phaseBreakdown"]),
                    json.dumps(calc_result["pallets"]),
                    json.dumps(calc_result["items"]),
                    notes,
                    created_by,
                    created_at,
                ),
            )
            conn.commit()
        return {"id": history_id, "createdAt": created_at, "userId": owner}

    def list_history(self, mode: Optional[str], limit: int, offset: int,
                     user_id: Optional[str] = None) -> Dict[str, Any]:
        owner = _coerce_user_id(user_id)
        params: List[Any] = [owner]
        where = "WHERE user_id = ?"
        if mode:
            where += " AND mode = ?"
            params.append(mode)
        with self._lock, self._conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS c FROM workload_history {where}", params
            ).fetchone()["c"]
            rows = conn.execute(
                f"SELECT * FROM workload_history {where} "
                f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return {
            "total":   total,
            "limit":   limit,
            "offset":  offset,
            "records": [self._row_to_record(r) for r in rows],
        }

    def get_history(self, history_id: str,
                    user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Returns the record only if it's owned by `user_id`. Returns None
        either way if the row doesn't exist OR if it's owned by someone else,
        so the handler can serve a single 404 for both cases (no info leak)."""
        owner = _coerce_user_id(user_id)
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM workload_history WHERE id = ? AND user_id = ?",
                (history_id, owner),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def delete_history(self, history_id: str,
                       user_id: Optional[str] = None) -> bool:
        owner = _coerce_user_id(user_id)
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM workload_history WHERE id = ? AND user_id = ?",
                (history_id, owner),
            )
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id":              row["id"],
            "userId":          row["user_id"] if "user_id" in row.keys() else DEFAULT_USER_ID,
            "mode":            row["mode"],
            "basis":           row["basis"],
            "palletCount":     row["pallet_count"],
            "totalQty":        row["total_qty"],
            "numberOfWorkers": row["number_of_workers"],
            "totalSeconds":    row["total_seconds"],
            "phaseBreakdown":  json.loads(row["phase_breakdown"]),
            "pallets":         json.loads(row["pallets"]),
            "items":           json.loads(row["items"]),
            "notes":           row["notes"] or "",
            "createdBy":       row["created_by"] or "",
            "createdAt":       row["created_at"],
        }

    # ----- uom -----

    def list_uoms(self) -> List[str]:
        with self._lock, self._conn() as conn:
            rows = conn.execute("SELECT uom FROM workload_uom ORDER BY uom").fetchall()
        return [r["uom"] for r in rows]

    def add_uom(self, uom: str) -> List[str]:
        uom = (uom or "").strip()
        if not uom:
            return self.list_uoms()
        with self._lock, self._conn() as conn:
            conn.execute("INSERT OR IGNORE INTO workload_uom(uom) VALUES (?)", (uom,))
            conn.commit()
        return self.list_uoms()

    def delete_uom(self, uom: str) -> List[str]:
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM workload_uom WHERE uom = ?", (uom,))
            conn.commit()
        return self.list_uoms()


# ----------------------------------------------------------------------
# DynamoDB backend (used in the deployed Lambda)
# ----------------------------------------------------------------------


class DynamoStorage:
    """DynamoDB-backed implementation of the same interface.

    Table names are read from env vars so the same code works in staging vs
    prod. Defaults match the names in `AA-lambda/infra/workload-dynamodb.yaml`.
    """

    CONFIG_TABLE  = os.environ.get("WORKLOAD_CONFIG_TABLE",  "workload-config")
    HISTORY_TABLE = os.environ.get("WORKLOAD_HISTORY_TABLE", "workload-history")
    UOM_TABLE     = os.environ.get("WORKLOAD_UOM_TABLE",     "workload-uom")

    def __init__(self):
        if boto3 is None:
            raise RuntimeError("boto3 is not installed; cannot use DynamoStorage")
        self._db = boto3.resource("dynamodb")
        self._config  = self._db.Table(self.CONFIG_TABLE)
        self._history = self._db.Table(self.HISTORY_TABLE)
        self._uom     = self._db.Table(self.UOM_TABLE)

    # ----- config (per-user with org-default fallback) -----

    def get_config(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Same semantics as SqliteStorage.get_config — user row -> default
        row -> hard-coded defaults. `inheritedFromDefault` is True whenever
        the caller is a real user but has no personal row of their own, even
        if the explicit '__default__' row is also missing (in which case the
        hard-coded DEFAULT_RATES from calculate.py supplies the values)."""
        owner = _coerce_user_id(user_id)
        personal = (self._config.get_item(Key={"configKey": owner}).get("Item") or {})
        item = personal
        if not personal and owner != DEFAULT_USER_ID:
            item = (self._config.get_item(Key={"configKey": DEFAULT_USER_ID})
                    .get("Item") or {})
        inherited = (owner != DEFAULT_USER_ID) and (not personal)
        return {
            "userId":               owner,
            "isDefault":            owner == DEFAULT_USER_ID,
            "inheritedFromDefault": inherited,
            **{**DEFAULT_RATES,
               **{k: float(v) for k, v in item.items() if k in DEFAULT_RATES}},
            "updatedAt": item.get("updatedAt"),
            "updatedBy": item.get("updatedBy"),
        }

    def update_config(self, rates: Dict[str, Any],
                      updated_by: Optional[str],
                      user_id: Optional[str] = None) -> Dict[str, Any]:
        from decimal import Decimal
        owner = _coerce_user_id(user_id)
        clean = SqliteStorage._sanitize_rates(rates)
        merged = {**DEFAULT_RATES, **clean}
        item = {
            "configKey": owner,
            **{k: Decimal(str(v)) for k, v in merged.items()},
            "updatedAt": _now_iso(),
            "updatedBy": updated_by or "user",
        }
        self._config.put_item(Item=item)
        return self.get_config(user_id)

    def reset_config(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Delete the user's personal row so they go back to the org default."""
        owner = _coerce_user_id(user_id)
        if owner != DEFAULT_USER_ID:
            self._config.delete_item(Key={"configKey": owner})
        return self.get_config(user_id)

    # ----- history (scoped to the calling user) -----

    def save_history(self, calc_result: Dict[str, Any],
                     notes: str, created_by: str,
                     user_id: Optional[str] = None) -> Dict[str, Any]:
        from decimal import Decimal
        owner = _coerce_user_id(user_id)
        history_id = str(uuid.uuid4())
        created_at = _now_iso()
        item = {
            "id":              history_id,
            "userId":          owner,
            "mode":            calc_result["mode"],
            "basis":           calc_result["basis"],
            "palletCount":     Decimal(str(calc_result["palletCount"])),
            "totalQty":        Decimal(str(calc_result["totalQty"])),
            "numberOfWorkers": int(calc_result["numberOfWorkers"]),
            "totalSeconds":    Decimal(str(calc_result["totalSeconds"])),
            # Lists/dicts get JSON-encoded to dodge DynamoDB's no-empty-string rule.
            "phaseBreakdown":  json.dumps(calc_result["phaseBreakdown"]),
            "pallets":         json.dumps(calc_result["pallets"]),
            "items":           json.dumps(calc_result["items"]),
            "notes":           notes or "",
            "createdBy":       created_by or "user",
            "createdAt":       created_at,
        }
        self._history.put_item(Item=item)
        return {"id": history_id, "createdAt": created_at, "userId": owner}

    def list_history(self, mode: Optional[str], limit: int, offset: int,
                     user_id: Optional[str] = None) -> Dict[str, Any]:
        """Scan + in-memory filter by userId. Capstone-scale; a userId GSI
        would be the right next step once the table grows past a few thousand
        rows."""
        owner = _coerce_user_id(user_id)
        filter_expr = None
        if Key is not None:
            filter_expr = Key("userId").eq(owner)
            if mode:
                filter_expr = filter_expr & Key("mode").eq(mode)
        kwargs: Dict[str, Any] = {}
        if filter_expr is not None:
            kwargs["FilterExpression"] = filter_expr
        resp = self._history.scan(**kwargs)
        records = [self._dynamo_to_record(i) for i in resp.get("Items", [])]
        # Tail-defense: rows written before user_id was a column lack the
        # field — treat those as "__default__" so they're invisible to real
        # users.
        records = [r for r in records
                   if (r.get("userId") or DEFAULT_USER_ID) == owner]
        records.sort(key=lambda r: r.get("createdAt") or "", reverse=True)
        total = len(records)
        sliced = records[offset: offset + limit]
        return {"total": total, "limit": limit, "offset": offset, "records": sliced}

    def get_history(self, history_id: str,
                    user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        owner = _coerce_user_id(user_id)
        resp = self._history.get_item(Key={"id": history_id})
        item = resp.get("Item")
        if not item:
            return None
        if (item.get("userId") or DEFAULT_USER_ID) != owner:
            return None  # cross-user access -> single 404
        return self._dynamo_to_record(item)

    def delete_history(self, history_id: str,
                       user_id: Optional[str] = None) -> bool:
        """ConditionExpression makes the delete atomic on ownership: if
        userId doesn't match, DynamoDB rejects the delete and we return
        False (handler serves a 404)."""
        from botocore.exceptions import ClientError
        owner = _coerce_user_id(user_id)
        try:
            self._history.delete_item(
                Key={"id": history_id},
                ConditionExpression="userId = :u",
                ExpressionAttributeValues={":u": owner},
                ReturnValues="ALL_OLD",
            )
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise

    @staticmethod
    def _dynamo_to_record(item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id":              item.get("id"),
            "userId":          item.get("userId") or DEFAULT_USER_ID,
            "mode":            item.get("mode"),
            "basis":           item.get("basis"),
            "palletCount":     float(item.get("palletCount") or 0),
            "totalQty":        float(item.get("totalQty") or 0),
            "numberOfWorkers": int(item.get("numberOfWorkers") or 0),
            "totalSeconds":    float(item.get("totalSeconds") or 0),
            "phaseBreakdown":  json.loads(item.get("phaseBreakdown") or "[]"),
            "pallets":         json.loads(item.get("pallets") or "[]"),
            "items":           json.loads(item.get("items") or "[]"),
            "notes":           item.get("notes") or "",
            "createdBy":       item.get("createdBy") or "",
            "createdAt":       item.get("createdAt"),
        }

    # ----- uom -----

    def list_uoms(self) -> List[str]:
        resp = self._uom.scan()
        uoms = [i["uom"] for i in resp.get("Items", []) if i.get("uom")]
        uoms.sort()
        return uoms

    def add_uom(self, uom: str) -> List[str]:
        uom = (uom or "").strip()
        if uom:
            self._uom.put_item(Item={"uom": uom})
        return self.list_uoms()

    def delete_uom(self, uom: str) -> List[str]:
        self._uom.delete_item(Key={"uom": uom})
        return self.list_uoms()


# ----------------------------------------------------------------------
# Factory
# ----------------------------------------------------------------------


_INSTANCE: Optional[Any] = None


def get_storage():
    """Return a cached `SqliteStorage` or `DynamoStorage` based on env vars.

    Selection logic:
    1. `WORKLOAD_STORAGE=sqlite` -> SQLite.
    2. `WORKLOAD_STORAGE=dynamodb` -> DynamoDB. Falls back to SQLite if boto3
       can't initialize (e.g. running tests without AWS creds).
    3. Default -> SQLite (safer for local dev).
    """
    global _INSTANCE
    if _INSTANCE is not None:
        return _INSTANCE

    backend = os.environ.get("WORKLOAD_STORAGE", "sqlite").lower()
    if backend == "dynamodb":
        try:
            _INSTANCE = DynamoStorage()
        except Exception:  # noqa: BLE001
            _INSTANCE = SqliteStorage()
    else:
        _INSTANCE = SqliteStorage()
    return _INSTANCE


def reset_storage_for_tests(storage_obj: Optional[Any] = None) -> None:
    """Tests inject a fresh storage instance via this hook."""
    global _INSTANCE
    _INSTANCE = storage_obj

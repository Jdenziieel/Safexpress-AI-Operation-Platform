"""
Phase 7.A — One-shot bulk migration: SQLite (supervisor-agent) → DynamoDB (Sup_*).

Reads from:
  supervisor-agent/threads.db  → Sup_Threads, Sup_ThreadStates, Sup_MemoryStates,
                                  Sup_Messages, Sup_ConversationStates
  supervisor-agent/logs.db     → Sup_Logs, Sup_LLMCalls, Sup_AgentCalls,
                                  Sup_RequestSummaries

Deliberately SKIPS (per plan §7.A):
  - pending_actions   → TTL-driven, mostly stale; safer to re-issue
  - model_pricing     → auto-seeds at first cold start of supervisor-admin-pricing-list
  - system_settings   → admin-edited; re-set after cutover via Logs page

Usage::

    cd AA-lambda
    # Dry run — counts rows that WOULD be written, no writes.
    python scripts/migrate_sqlite_to_dynamodb.py --dry-run

    # Live run with default DB paths.
    python scripts/migrate_sqlite_to_dynamodb.py

    # Custom paths.
    python scripts/migrate_sqlite_to_dynamodb.py \
        --threads-db ../supervisor-agent/threads.db \
        --logs-db    ../supervisor-agent/logs.db \
        --region     ap-southeast-1

    # Migrate only a single source table family.
    python scripts/migrate_sqlite_to_dynamodb.py --only threads
    python scripts/migrate_sqlite_to_dynamodb.py --only logs

Idempotent: re-running puts the same items with the same primary keys, so the
target rows are simply overwritten. Messages get fresh `sk` values
(`{created_at}#{message_id}`) preserving order; if you re-run after the source
has grown, you'll get duplicate Sup_Messages rows for the new entries — wipe
the table first or use a fresh range.

DynamoDB BatchWriteItem caps at 25 items per request. We chunk per-table.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError


# ----------------------------------------------------------------------
# Defaults & helpers
# ----------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_THREADS_DB = REPO_ROOT / "supervisor-agent" / "threads.db"
DEFAULT_LOGS_DB = REPO_ROOT / "supervisor-agent" / "logs.db"
DEFAULT_REGION = os.environ.get("AWS_REGION", "ap-southeast-1")

TABLE_NAMES = {
    "threads": os.environ.get("SUP_THREADS_TABLE", "Sup_Threads"),
    "thread_states": os.environ.get("SUP_THREAD_STATES_TABLE", "Sup_ThreadStates"),
    "memory_states": os.environ.get("SUP_MEMORY_STATES_TABLE", "Sup_MemoryStates"),
    "messages": os.environ.get("SUP_MESSAGES_TABLE", "Sup_Messages"),
    "conversation_states": os.environ.get(
        "SUP_CONVERSATION_STATES_TABLE", "Sup_ConversationStates"
    ),
    "logs": os.environ.get("SUP_LOGS_TABLE", "Sup_Logs"),
    "llm_calls": os.environ.get("SUP_LLM_CALLS_TABLE", "Sup_LLMCalls"),
    "agent_calls": os.environ.get("SUP_AGENT_CALLS_TABLE", "Sup_AgentCalls"),
    "request_summaries": os.environ.get(
        "SUP_REQUEST_SUMMARIES_TABLE", "Sup_RequestSummaries"
    ),
}

LOGS_TTL_DAYS = int(os.environ.get("LOGS_TTL_DAYS", "90"))
S3_SPILL_BUCKET = os.environ.get("SUP_THREAD_STATES_BUCKET", "")
S3_SPILL_THRESHOLD = 380 * 1024  # 380KB, same as dynamodb_thread_manager


def _ddb_safe(obj: Any) -> Any:
    """Convert floats → Decimal, drop None values, recurse into dicts/lists."""
    if obj is None:
        return None
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _ddb_safe(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_ddb_safe(v) for v in obj]
    return obj


def _ulid() -> str:
    ts = int(time.time() * 1000)
    rand = uuid.uuid4().hex
    return f"{ts:013x}{rand[:13]}"


def _ttl_epoch(days: int) -> int:
    return int(time.time() + days * 86400)


def _row_dict(cursor: sqlite3.Cursor, row: tuple) -> Dict[str, Any]:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


# ----------------------------------------------------------------------
# Stats accumulator
# ----------------------------------------------------------------------


class Stats:
    def __init__(self) -> None:
        self.read: Dict[str, int] = {}
        self.written: Dict[str, int] = {}
        self.skipped: Dict[str, int] = {}
        self.errors: Dict[str, int] = {}

    def bump_read(self, table: str, n: int = 1) -> None:
        self.read[table] = self.read.get(table, 0) + n

    def bump_written(self, table: str, n: int = 1) -> None:
        self.written[table] = self.written.get(table, 0) + n

    def bump_skipped(self, table: str, n: int = 1) -> None:
        self.skipped[table] = self.skipped.get(table, 0) + n

    def bump_error(self, table: str, n: int = 1) -> None:
        self.errors[table] = self.errors.get(table, 0) + n

    def report(self) -> None:
        all_tables = sorted(set(self.read) | set(self.written) | set(self.skipped) | set(self.errors))
        if not all_tables:
            print("  (no rows processed)")
            return
        col_w = max((len(t) for t in all_tables), default=12)
        print(f"  {'table':<{col_w}}  {'read':>7}  {'written':>7}  {'skipped':>7}  {'errors':>7}")
        print(f"  {'-' * col_w}  {'-' * 7}  {'-' * 7}  {'-' * 7}  {'-' * 7}")
        for t in all_tables:
            print(
                f"  {t:<{col_w}}  "
                f"{self.read.get(t, 0):>7}  "
                f"{self.written.get(t, 0):>7}  "
                f"{self.skipped.get(t, 0):>7}  "
                f"{self.errors.get(t, 0):>7}"
            )


# ----------------------------------------------------------------------
# DynamoDB writer with batch_writer
# ----------------------------------------------------------------------


class DDBBulkWriter:
    """Wraps DynamoDB ``batch_writer`` (auto-batches at 25 items per request).

    The boto3 batch_writer transparently retries unprocessed items.
    We wrap PutItem calls so dry-run mode just counts.
    """

    def __init__(self, dynamodb, table_name: str, *, dry_run: bool):
        self.dynamodb = dynamodb
        self.table_name = table_name
        self.dry_run = dry_run
        self._table = dynamodb.Table(table_name) if not dry_run else None
        self._writer = None

    def __enter__(self):
        if not self.dry_run:
            self._writer = self._table.batch_writer().__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._writer is not None:
            return self._writer.__exit__(exc_type, exc_val, exc_tb)
        return False

    def put(self, item: Dict[str, Any]) -> None:
        if self.dry_run:
            return
        self._writer.put_item(Item=_ddb_safe(item))


# ----------------------------------------------------------------------
# Migrators — threads.db
# ----------------------------------------------------------------------


def migrate_threads(
    threads_db: Path, dynamodb, stats: Stats, dry_run: bool
) -> Dict[str, int]:
    """Migrate threads, thread_states, memory_states, messages, conversation_states."""
    if not threads_db.exists():
        print(f"  [WARN] threads.db not found at {threads_db} — skipping")
        return {}

    conn = sqlite3.connect(str(threads_db))
    conn.row_factory = sqlite3.Row
    try:
        # ---------- threads → Sup_Threads ----------
        cur = conn.execute("SELECT * FROM threads")
        with DDBBulkWriter(dynamodb, TABLE_NAMES["threads"], dry_run=dry_run) as w:
            for row in cur:
                stats.bump_read("threads")
                d = dict(row)
                item = {
                    "thread_id": d["thread_id"],
                    "user_id": d.get("user_id") or "unknown",
                    "created_at": d.get("created_at"),
                    "updated_at": d.get("updated_at"),
                    "title": d.get("title") or "Untitled Conversation",
                    "message_count": int(d.get("message_count") or 0),
                    "status": d.get("status") or "active",
                }
                if d.get("last_message_preview"):
                    item["last_message_preview"] = d["last_message_preview"]
                if d.get("tags"):
                    try:
                        item["tags"] = json.loads(d["tags"])
                    except Exception:
                        item["tags"] = [d["tags"]]
                try:
                    w.put(item)
                    stats.bump_written("threads")
                except Exception as e:
                    print(f"  [ERROR] threads thread_id={d.get('thread_id')!r}: {e}")
                    stats.bump_error("threads")

        # ---------- thread_states → Sup_ThreadStates ----------
        cur = conn.execute("SELECT thread_id, conversation_state FROM thread_states")
        with DDBBulkWriter(
            dynamodb, TABLE_NAMES["thread_states"], dry_run=dry_run
        ) as w:
            for row in cur:
                stats.bump_read("thread_states")
                state_json = row["conversation_state"]
                if state_json is None:
                    stats.bump_skipped("thread_states")
                    continue
                size = len(state_json.encode("utf-8")) if isinstance(state_json, str) else 0
                if size > S3_SPILL_THRESHOLD and S3_SPILL_BUCKET and not dry_run:
                    # Spill to S3 to mirror save_thread_state's behavior.
                    s3 = boto3.client("s3")
                    key = f"thread_states/{row['thread_id']}/{uuid.uuid4().hex}.json"
                    try:
                        s3.put_object(
                            Bucket=S3_SPILL_BUCKET, Key=key,
                            Body=state_json.encode("utf-8"),
                        )
                        item = {
                            "thread_id": row["thread_id"],
                            "s3_pointer": f"s3://{S3_SPILL_BUCKET}/{key}",
                            "stored_at": _now_iso(),
                        }
                    except Exception as e:
                        print(f"  [ERROR] s3 spill for {row['thread_id']!r}: {e}")
                        stats.bump_error("thread_states")
                        continue
                else:
                    item = {
                        "thread_id": row["thread_id"],
                        "state_json": state_json,
                        "stored_at": _now_iso(),
                    }
                try:
                    w.put(item)
                    stats.bump_written("thread_states")
                except Exception as e:
                    print(f"  [ERROR] thread_states {row['thread_id']!r}: {e}")
                    stats.bump_error("thread_states")

        # ---------- memory_states → Sup_MemoryStates ----------
        cur = conn.execute("SELECT thread_id, memory_state FROM memory_states")
        with DDBBulkWriter(
            dynamodb, TABLE_NAMES["memory_states"], dry_run=dry_run
        ) as w:
            for row in cur:
                stats.bump_read("memory_states")
                if row["memory_state"] is None:
                    stats.bump_skipped("memory_states")
                    continue
                item = {
                    "thread_id": row["thread_id"],
                    "memory_json": row["memory_state"],
                    "stored_at": _now_iso(),
                }
                try:
                    w.put(item)
                    stats.bump_written("memory_states")
                except Exception as e:
                    print(f"  [ERROR] memory_states {row['thread_id']!r}: {e}")
                    stats.bump_error("memory_states")

        # ---------- messages → Sup_Messages ----------
        # SQLite messages have AUTOINCREMENT id; DynamoDB uses (thread_id, sk).
        # sk = "{created_at}#{uuid}" preserves chronological ordering.
        cur = conn.execute(
            "SELECT thread_id, role, content, created_at, "
            "file_name, file_type, file_size, message_id FROM messages "
            "ORDER BY thread_id, message_id"
        )
        with DDBBulkWriter(dynamodb, TABLE_NAMES["messages"], dry_run=dry_run) as w:
            for row in cur:
                stats.bump_read("messages")
                d = dict(row)
                created_at = d.get("created_at") or _now_iso()
                msg_uuid = uuid.uuid4().hex
                sk = f"{created_at}#{msg_uuid}"
                item = {
                    "thread_id": d["thread_id"],
                    "sk": sk,
                    "message_id": msg_uuid,
                    "role": d.get("role") or "user",
                    "content": d.get("content") or "",
                    "created_at": created_at,
                }
                if d.get("file_name"):
                    item["file_name"] = d["file_name"]
                if d.get("file_type"):
                    item["file_type"] = d["file_type"]
                if d.get("file_size") is not None:
                    item["file_size"] = int(d["file_size"])
                try:
                    w.put(item)
                    stats.bump_written("messages")
                except Exception as e:
                    print(f"  [ERROR] messages thread_id={d.get('thread_id')!r}: {e}")
                    stats.bump_error("messages")

        # ---------- conversation_states → Sup_ConversationStates ----------
        try:
            cur = conn.execute(
                "SELECT conversation_id, state_json, updated_at FROM conversation_states"
            )
            with DDBBulkWriter(
                dynamodb, TABLE_NAMES["conversation_states"], dry_run=dry_run
            ) as w:
                for row in cur:
                    stats.bump_read("conversation_states")
                    item = {
                        "conversation_id": row["conversation_id"],
                        "state_json": row["state_json"] or "{}",
                        "updated_at": row["updated_at"] or _now_iso(),
                    }
                    try:
                        w.put(item)
                        stats.bump_written("conversation_states")
                    except Exception as e:
                        print(
                            f"  [ERROR] conversation_states {row['conversation_id']!r}: {e}"
                        )
                        stats.bump_error("conversation_states")
        except sqlite3.OperationalError as e:
            print(f"  [WARN] conversation_states table missing — {e}")

    finally:
        conn.close()
    return {}


# ----------------------------------------------------------------------
# Migrators — logs.db
# ----------------------------------------------------------------------


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def migrate_logs(
    logs_db: Path, dynamodb, stats: Stats, dry_run: bool
) -> Dict[str, int]:
    """Migrate logs, llm_calls, agent_calls, request_summaries.

    Skips: pending_actions, model_pricing, system_settings (per plan §7.A).
    """
    if not logs_db.exists():
        print(f"  [WARN] logs.db not found at {logs_db} — skipping")
        return {}

    conn = sqlite3.connect(str(logs_db))
    conn.row_factory = sqlite3.Row
    try:
        # ---------- logs → Sup_Logs ----------
        cur = conn.execute(
            "SELECT timestamp, level, logger, message, request_id, "
            "conversation_id, thread_id, component, operation, data "
            "FROM logs ORDER BY id"
        )
        ttl = _ttl_epoch(LOGS_TTL_DAYS)
        with DDBBulkWriter(dynamodb, TABLE_NAMES["logs"], dry_run=dry_run) as w:
            for row in cur:
                stats.bump_read("logs")
                d = dict(row)
                item = {
                    "log_id": _ulid(),
                    "timestamp": d.get("timestamp") or _now_iso(),
                    "level": (d.get("level") or "INFO").upper(),
                    "logger": d.get("logger") or "unknown",
                    "message": (d.get("message") or "")[:4000],
                    "expires_at": ttl,
                }
                for k in ("request_id", "conversation_id", "thread_id", "component", "operation"):
                    if d.get(k):
                        item[k] = d[k]
                if d.get("data"):
                    item["data"] = (d["data"] or "")[:8000]
                try:
                    w.put(item)
                    stats.bump_written("logs")
                except Exception as e:
                    print(f"  [ERROR] logs ts={d.get('timestamp')!r}: {e}")
                    stats.bump_error("logs")

        # ---------- llm_calls → Sup_LLMCalls ----------
        cur = conn.execute(
            "SELECT timestamp, request_id, conversation_id, user_id, service, "
            "model, tier, operation, input_tokens, output_tokens, total_tokens, "
            "estimated_cost_usd, duration_ms, success, prompt_summary, error, "
            "cumulative_tokens, cumulative_cost_usd, "
            "COALESCE(cached_tokens, 0) AS cached_tokens "
            "FROM llm_calls ORDER BY id"
        )
        with DDBBulkWriter(dynamodb, TABLE_NAMES["llm_calls"], dry_run=dry_run) as w:
            for row in cur:
                stats.bump_read("llm_calls")
                d = dict(row)
                item = {
                    "call_id": _ulid(),
                    "timestamp": d.get("timestamp") or _now_iso(),
                    "model": d.get("model") or "unknown",
                    "input_tokens": int(d.get("input_tokens") or 0),
                    "output_tokens": int(d.get("output_tokens") or 0),
                    "total_tokens": int(d.get("total_tokens") or 0),
                    "cached_tokens": int(d.get("cached_tokens") or 0),
                    "estimated_cost_usd": float(d.get("estimated_cost_usd") or 0.0),
                    "duration_ms": float(d.get("duration_ms") or 0.0),
                    "success": bool(d.get("success") or 0),
                    "service": d.get("service") or "supervisor",
                }
                for k in ("request_id", "conversation_id", "user_id", "tier", "operation",
                          "prompt_summary", "error"):
                    if d.get(k):
                        item[k] = d[k]
                if d.get("cumulative_tokens") is not None:
                    item["cumulative_tokens"] = int(d["cumulative_tokens"])
                if d.get("cumulative_cost_usd") is not None:
                    item["cumulative_cost_usd"] = float(d["cumulative_cost_usd"])
                try:
                    w.put(item)
                    stats.bump_written("llm_calls")
                except Exception as e:
                    print(f"  [ERROR] llm_calls ts={d.get('timestamp')!r}: {e}")
                    stats.bump_error("llm_calls")

        # ---------- agent_calls → Sup_AgentCalls ----------
        cur = conn.execute(
            "SELECT timestamp, request_id, conversation_id, agent_name, tool_name, "
            "step_number, total_steps, inputs, success, duration_ms, output_summary, "
            "error FROM agent_calls ORDER BY id"
        )
        with DDBBulkWriter(dynamodb, TABLE_NAMES["agent_calls"], dry_run=dry_run) as w:
            for row in cur:
                stats.bump_read("agent_calls")
                d = dict(row)
                item = {
                    "call_id": _ulid(),
                    "timestamp": d.get("timestamp") or _now_iso(),
                    "agent_name": d.get("agent_name") or "unknown",
                    "tool_name": d.get("tool_name") or "unknown",
                    "success": bool(d.get("success") or 0),
                    "duration_ms": float(d.get("duration_ms") or 0.0),
                }
                if d.get("step_number") is not None:
                    item["step_number"] = int(d["step_number"])
                if d.get("total_steps") is not None:
                    item["total_steps"] = int(d["total_steps"])
                if d.get("inputs"):
                    item["inputs"] = (d["inputs"] or "")[:4000]
                if d.get("output_summary"):
                    item["output_summary"] = (d["output_summary"] or "")[:1000]
                if d.get("error"):
                    item["error"] = (d["error"] or "")[:1000]
                if d.get("request_id"):
                    item["request_id"] = d["request_id"]
                if d.get("conversation_id"):
                    item["conversation_id"] = d["conversation_id"]
                try:
                    w.put(item)
                    stats.bump_written("agent_calls")
                except Exception as e:
                    print(f"  [ERROR] agent_calls ts={d.get('timestamp')!r}: {e}")
                    stats.bump_error("agent_calls")

        # ---------- request_summaries → Sup_RequestSummaries ----------
        cur = conn.execute(
            "SELECT request_id, conversation_id, thread_id, started_at, completed_at, "
            "total_duration_ms, total_input_tokens, total_output_tokens, total_tokens, "
            "total_cost_usd, llm_call_count, agent_call_count, success, error "
            "FROM request_summaries ORDER BY id"
        )
        with DDBBulkWriter(
            dynamodb, TABLE_NAMES["request_summaries"], dry_run=dry_run
        ) as w:
            for row in cur:
                stats.bump_read("request_summaries")
                d = dict(row)
                if not d.get("request_id"):
                    stats.bump_skipped("request_summaries")
                    continue
                item = {
                    "request_id": d["request_id"],
                    "started_at": d.get("started_at") or _now_iso(),
                    "completed_at": d.get("completed_at") or _now_iso(),
                    "total_duration_ms": float(d.get("total_duration_ms") or 0.0),
                    "total_input_tokens": int(d.get("total_input_tokens") or 0),
                    "total_output_tokens": int(d.get("total_output_tokens") or 0),
                    "total_tokens": int(d.get("total_tokens") or 0),
                    "total_cost_usd": float(d.get("total_cost_usd") or 0.0),
                    "llm_call_count": int(d.get("llm_call_count") or 0),
                    "agent_call_count": int(d.get("agent_call_count") or 0),
                    "success": bool(d.get("success") or 0),
                }
                if d.get("conversation_id"):
                    item["conversation_id"] = d["conversation_id"]
                if d.get("thread_id"):
                    item["thread_id"] = d["thread_id"]
                if d.get("error"):
                    item["error"] = (d["error"] or "")[:1000]
                try:
                    w.put(item)
                    stats.bump_written("request_summaries")
                except Exception as e:
                    print(
                        f"  [ERROR] request_summaries req={d.get('request_id')!r}: {e}"
                    )
                    stats.bump_error("request_summaries")

    finally:
        conn.close()
    return {}


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(
        description="Bulk-migrate supervisor-agent SQLite databases to DynamoDB."
    )
    p.add_argument(
        "--threads-db",
        type=Path,
        default=DEFAULT_THREADS_DB,
        help=f"path to threads.db (default: {DEFAULT_THREADS_DB})",
    )
    p.add_argument(
        "--logs-db",
        type=Path,
        default=DEFAULT_LOGS_DB,
        help=f"path to logs.db (default: {DEFAULT_LOGS_DB})",
    )
    p.add_argument("--region", default=DEFAULT_REGION, help=f"AWS region (default: {DEFAULT_REGION})")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="count rows that would be written without making any DynamoDB calls",
    )
    p.add_argument(
        "--only",
        choices=["threads", "logs", "all"],
        default="all",
        help="restrict migration to one DB family (default: all)",
    )
    args = p.parse_args()

    print("=" * 72)
    print(
        f"AA-lambda Phase 7.A — {'DRY RUN' if args.dry_run else 'LIVE'} migration\n"
        f"  threads.db: {args.threads_db}\n"
        f"  logs.db:    {args.logs_db}\n"
        f"  region:     {args.region}\n"
        f"  only:       {args.only}"
    )
    print("=" * 72)

    if args.dry_run:
        dynamodb = None
    else:
        dynamodb = boto3.resource("dynamodb", region_name=args.region)
        # Quick sanity check — does at least one Sup_* table exist?
        client = boto3.client("dynamodb", region_name=args.region)
        try:
            existing = set(client.list_tables().get("TableNames", []))
        except ClientError as e:
            print(f"[FATAL] cannot list DynamoDB tables: {e}")
            return 2
        missing = [t for t in TABLE_NAMES.values() if t not in existing]
        if missing:
            print(
                f"[FATAL] target tables missing in region {args.region}: {missing}\n"
                f"        Run AA-lambda/infra/provision-phase-0.ps1 first."
            )
            return 2

    stats = Stats()
    if args.only in ("threads", "all"):
        print("\n--- threads.db ---")
        migrate_threads(args.threads_db, dynamodb, stats, args.dry_run)
    if args.only in ("logs", "all"):
        print("\n--- logs.db ---")
        migrate_logs(args.logs_db, dynamodb, stats, args.dry_run)

    print("\n" + "=" * 72)
    print("Result")
    print("=" * 72)
    stats.report()

    error_count = sum(stats.errors.values())
    if error_count:
        print(f"\nFAILED: {error_count} row(s) errored — review log lines above")
        return 1

    if args.dry_run:
        print(
            "\nDry run complete. Re-run without --dry-run to actually write to DynamoDB."
        )
    else:
        print("\nMigration complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

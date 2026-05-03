"""
DynamoDB-backed LogStorage.

Drop-in replacement for `log_storage.LogStorage`. Same public API.

Backed by 7 of the 12 Sup_* tables:
  Sup_Logs              — PK log_id, GSI request_id-timestamp-index, level-timestamp-index, TTL expires_at
  Sup_LLMCalls          — PK call_id, GSI request_id-index, user_id-timestamp-index
  Sup_AgentCalls        — PK call_id, GSI request_id-index
  Sup_RequestSummaries  — PK request_id, GSI conversation_id-index (INSERT OR REPLACE)
  Sup_PendingActions    — PK action_id, GSI thread_id-status-index, TTL expires_at
  Sup_ModelPricing      — PK model
  Sup_SystemSettings    — PK key

Conforms to LOGS_ANALYTICS_MIGRATION_CONTRACT.md §6 invariants:
  - All `service` writes restricted to {supervisor, supervisor-agent-gmail,
    supervisor-agent-docs, supervisor-agent-mapping}.
  - All `tier` writes restricted to {chat, classifier, 0.5, 1, planner,
    transform, summarization}.
  - All `agent_name` writes restricted to {gmail_agent, calendar_agent,
    sheets_agent, mapping_agent, docs_agent, drive_agent}.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Attr, Key

from models.models import LogLevel


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

_TABLE_NAMES = {
    "logs": os.environ.get("SUP_LOGS_TABLE", "Sup_Logs"),
    "llm_calls": os.environ.get("SUP_LLM_CALLS_TABLE", "Sup_LLMCalls"),
    "agent_calls": os.environ.get("SUP_AGENT_CALLS_TABLE", "Sup_AgentCalls"),
    "request_summaries": os.environ.get(
        "SUP_REQUEST_SUMMARIES_TABLE", "Sup_RequestSummaries"
    ),
    "pending_actions": os.environ.get(
        "SUP_PENDING_ACTIONS_TABLE", "Sup_PendingActions"
    ),
    "model_pricing": os.environ.get("SUP_MODEL_PRICING_TABLE", "Sup_ModelPricing"),
    "system_settings": os.environ.get("SUP_SYSTEM_SETTINGS_TABLE", "Sup_SystemSettings"),
}

ALLOWED_SERVICES = {
    "supervisor",
    "supervisor-agent-gmail",
    "supervisor-agent-docs",
    "supervisor-agent-mapping",
}

ALLOWED_TIERS = {
    # Source-of-truth pipeline tiers (per LOGS_ANALYTICS_MIGRATION_CONTRACT §6)
    "chat",
    "classifier",
    "0.5",
    "1",
    "planner",
    "transform",
    "summarization",
    # Additional tiers actually emitted by the brain — whitelisted explicitly
    # so admin "Usage by Tier" stops bucketing them as "Unknown" and the
    # per-tier cost tile reflects reality. Each is a distinct LLM step in
    # the request lifecycle:
    #   - formatter:   conversational_agent.confirmation_formatter (turns the
    #                  planner's execution_summary into a friendly
    #                  "I'll do X — proceed?" prompt before the pause)
    #   - orchestrator: utils.transform_text (mid-workflow data shaping)
    #   - post:        summarization_service._llm_compose (response composer
    #                  fallback when no per-tool template exists)
    #   - enrichment:  content_enrichment.enrich_request (resolves "the doc",
    #                  "that email", etc. against recent context)
    #   - memory:      conversation_memory summarization rollup
    "formatter",
    "orchestrator",
    "post",
    "enrichment",
    "memory",
}

ALLOWED_AGENT_NAMES = {
    "gmail_agent",
    "calendar_agent",
    "sheets_agent",
    "mapping_agent",
    "docs_agent",
    "drive_agent",
}

LOGS_TTL_DAYS = 90  # matches plan §6 "TTL expires_at"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ttl_epoch(days: int) -> int:
    return int((datetime.now(timezone.utc) + timedelta(days=days)).timestamp())


def _ulid() -> str:
    """Cheap ULID-like sortable id without the ulid-py dep."""
    ts = int(time.time() * 1000)
    rand = uuid.uuid4().hex
    return f"{ts:013x}{rand[:13]}"


def _ddb_safe(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _ddb_safe(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_ddb_safe(v) for v in obj]
    return obj


def _from_ddb(obj):
    if isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    if isinstance(obj, dict):
        return {k: _from_ddb(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_ddb(v) for v in obj]
    return obj


def _coerce_log_level(level) -> str:
    if isinstance(level, LogLevel):
        return level.value
    if isinstance(level, str):
        return level.upper()
    return "INFO"


# ----------------------------------------------------------------------
# Class
# ----------------------------------------------------------------------


class LogStorage:
    def __init__(self, db_path: str = "logs.db"):
        # `db_path` ignored — kept for API parity.
        self.db_path = Path(db_path)
        region = os.environ.get("AWS_REGION", "ap-southeast-1")
        endpoint = os.environ.get("DYNAMODB_ENDPOINT_URL")
        kwargs = {"region_name": region}
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        self._ddb = boto3.resource("dynamodb", **kwargs)

        self.t_logs = self._ddb.Table(_TABLE_NAMES["logs"])
        self.t_llm = self._ddb.Table(_TABLE_NAMES["llm_calls"])
        self.t_agent = self._ddb.Table(_TABLE_NAMES["agent_calls"])
        self.t_summary = self._ddb.Table(_TABLE_NAMES["request_summaries"])
        self.t_pending = self._ddb.Table(_TABLE_NAMES["pending_actions"])
        self.t_pricing = self._ddb.Table(_TABLE_NAMES["model_pricing"])
        self.t_settings = self._ddb.Table(_TABLE_NAMES["system_settings"])

    # ------------------------------------------------------------------
    # Inserts
    # ------------------------------------------------------------------

    def insert_log(
        self,
        timestamp: str,
        level,
        logger: str,
        message: str,
        request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        component: Optional[str] = None,
        operation: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> int:
        log_id = _ulid()
        item = {
            "log_id": log_id,
            "timestamp": timestamp or _now_iso(),
            "level": _coerce_log_level(level),
            "logger": logger,
            "message": message[:4000],  # cap to play nice with DynamoDB item size
            "expires_at": _ttl_epoch(LOGS_TTL_DAYS),
        }
        if request_id:
            item["request_id"] = request_id
        if conversation_id:
            item["conversation_id"] = conversation_id
        if thread_id:
            item["thread_id"] = thread_id
        if component:
            item["component"] = component
        if operation:
            item["operation"] = operation
        if data is not None:
            item["data"] = json.dumps(data, default=str)[:8000]
        self.t_logs.put_item(Item=_ddb_safe(item))
        # Legacy callers expected an int autoincrement — return a stable hash.
        return int(log_id[:12], 16)

    def insert_llm_call(
        self,
        timestamp: str,
        model: str,
        operation: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: Optional[int] = None,
        estimated_cost_usd: float = 0.0,
        duration_ms: float = 0.0,
        success: bool = True,
        prompt_summary: Optional[str] = None,
        error: Optional[str] = None,
        request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        service: str = "supervisor",
        tier: Optional[str] = None,
        cumulative_tokens: Optional[int] = None,
        cumulative_cost_usd: Optional[float] = None,
        cached_tokens: int = 0,
    ) -> int:
        # Service-name discipline (Phase 2.5.E)
        if service not in ALLOWED_SERVICES:
            service = "supervisor"
        if tier and tier not in ALLOWED_TIERS:
            tier = None  # drop unknown tier rather than poison analytics

        call_id = _ulid()
        if total_tokens is None:
            total_tokens = int(input_tokens) + int(output_tokens)
        item = {
            "call_id": call_id,
            "timestamp": timestamp or _now_iso(),
            "model": model,
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "total_tokens": int(total_tokens),
            "cached_tokens": int(cached_tokens or 0),
            "estimated_cost_usd": float(estimated_cost_usd or 0.0),
            "duration_ms": float(duration_ms or 0.0),
            "success": bool(success),
            "service": service,
        }
        if operation:
            item["operation"] = operation
        if prompt_summary:
            item["prompt_summary"] = prompt_summary[:1000]
        if error:
            item["error"] = error[:1000]
        if request_id:
            item["request_id"] = request_id
        if conversation_id:
            item["conversation_id"] = conversation_id
        if user_id:
            item["user_id"] = user_id
        if tier:
            item["tier"] = tier
        if cumulative_tokens is not None:
            item["cumulative_tokens"] = int(cumulative_tokens)
        if cumulative_cost_usd is not None:
            item["cumulative_cost_usd"] = float(cumulative_cost_usd)

        self.t_llm.put_item(Item=_ddb_safe(item))
        return int(call_id[:12], 16)

    def insert_agent_call(
        self,
        timestamp: str,
        agent_name: str,
        tool_name: str,
        step_number: Optional[int] = None,
        total_steps: Optional[int] = None,
        inputs: Optional[Dict[str, Any]] = None,
        success: bool = True,
        duration_ms: float = 0.0,
        output_summary: Optional[str] = None,
        error: Optional[str] = None,
        request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> int:
        if agent_name not in ALLOWED_AGENT_NAMES:
            # Don't reject — log it for observability.
            print(f"[LogStorage] WARN: non-canonical agent_name={agent_name!r}")

        call_id = _ulid()
        item = {
            "call_id": call_id,
            "timestamp": timestamp or _now_iso(),
            "agent_name": agent_name,
            "tool_name": tool_name,
            "success": bool(success),
            "duration_ms": float(duration_ms or 0.0),
        }
        if step_number is not None:
            item["step_number"] = int(step_number)
        if total_steps is not None:
            item["total_steps"] = int(total_steps)
        if inputs is not None:
            item["inputs"] = json.dumps(inputs, default=str)[:4000]
        if output_summary:
            item["output_summary"] = output_summary[:1000]
        if error:
            item["error"] = error[:1000]
        if request_id:
            item["request_id"] = request_id
        if conversation_id:
            item["conversation_id"] = conversation_id

        self.t_agent.put_item(Item=_ddb_safe(item))
        return int(call_id[:12], 16)

    def insert_request_summary(
        self,
        request_id: str,
        conversation_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        total_duration_ms: float = 0.0,
        total_input_tokens: int = 0,
        total_output_tokens: int = 0,
        total_tokens: int = 0,
        total_cost_usd: float = 0.0,
        llm_call_count: int = 0,
        agent_call_count: int = 0,
        success: bool = True,
        error: Optional[str] = None,
    ) -> int:
        item = {
            "request_id": request_id,
            "started_at": started_at or _now_iso(),
            "completed_at": completed_at or _now_iso(),
            "total_duration_ms": float(total_duration_ms or 0.0),
            "total_input_tokens": int(total_input_tokens or 0),
            "total_output_tokens": int(total_output_tokens or 0),
            "total_tokens": int(total_tokens or (total_input_tokens + total_output_tokens) or 0),
            "total_cost_usd": float(total_cost_usd or 0.0),
            "llm_call_count": int(llm_call_count or 0),
            "agent_call_count": int(agent_call_count or 0),
            "success": bool(success),
        }
        if conversation_id:
            item["conversation_id"] = conversation_id
        if thread_id:
            item["thread_id"] = thread_id
        if error:
            item["error"] = error[:1000]
        self.t_summary.put_item(Item=_ddb_safe(item))  # PutItem is INSERT OR REPLACE in DDB.
        return int(_ulid()[:12], 16)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_logs(
        self,
        level: Optional[str] = None,
        component: Optional[str] = None,
        request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        search_query: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "timestamp",
        sort_order: str = "DESC",
        # AA-lambda Phase 1 alias parameters (for callers using `since`/`until`)
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> tuple:
        """Same shape as supervisor-agent/log_storage.LogStorage.get_logs.
        Returns (rows, total) tuple. Supports both `start_time`/`end_time`
        (source naming) AND `since`/`until` (legacy aliases).
        """
        start_time = start_time or since
        end_time = end_time or until
        rows = self._scan_logs(
            level=level,
            component=component,
            request_id=request_id,
            conversation_id=conversation_id,
            thread_id=thread_id,
            start_time=start_time,
            end_time=end_time,
            search_query=search_query,
        )
        reverse = (sort_order or "DESC").upper() == "DESC"
        rows.sort(key=lambda r: r.get(sort_by) or r.get("timestamp", ""), reverse=reverse)
        total = len(rows)
        return rows[offset : offset + limit], total

    def _scan_logs(
        self,
        level: Optional[str],
        component: Optional[str],
        request_id: Optional[str],
        conversation_id: Optional[str],
        thread_id: Optional[str],
        start_time: Optional[str],
        end_time: Optional[str],
        search_query: Optional[str],
    ) -> List[Dict[str, Any]]:
        # Use GSI when possible; fall back to Scan for ad-hoc filters.
        if request_id:
            resp = self.t_logs.query(
                IndexName="request_id-timestamp-index",
                KeyConditionExpression=Key("request_id").eq(request_id),
            )
            items = resp.get("Items", [])
        elif level:
            resp = self.t_logs.query(
                IndexName="level-timestamp-index",
                KeyConditionExpression=Key("level").eq(level.upper()),
            )
            items = resp.get("Items", [])
        else:
            items = self._scan_paginated(self.t_logs)

        ql = (search_query or "").lower()
        out = []
        for item in items:
            item = _from_ddb(item)
            if conversation_id and item.get("conversation_id") != conversation_id:
                continue
            if thread_id and item.get("thread_id") != thread_id:
                continue
            if component and item.get("component") != component:
                continue
            if start_time and (item.get("timestamp") or "") < start_time:
                continue
            if end_time and (item.get("timestamp") or "") > end_time:
                continue
            if ql and ql not in (item.get("message") or "").lower():
                continue
            out.append(item)
        return out

    def get_llm_calls(
        self,
        request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        if request_id:
            resp = self.t_llm.query(
                IndexName="request_id-index",
                KeyConditionExpression=Key("request_id").eq(request_id),
            )
            items = resp.get("Items", [])
        elif user_id:
            resp = self.t_llm.query(
                IndexName="user_id-timestamp-index",
                KeyConditionExpression=Key("user_id").eq(user_id),
                ScanIndexForward=False,
            )
            items = resp.get("Items", [])
        else:
            items = self._scan_paginated(self.t_llm)

        items = [_from_ddb(i) for i in items]
        if conversation_id:
            items = [i for i in items if i.get("conversation_id") == conversation_id]
        if since:
            items = [i for i in items if (i.get("timestamp") or "") >= since]
        if until:
            items = [i for i in items if (i.get("timestamp") or "") <= until]
        items.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return items[offset : offset + limit]

    def get_agent_calls(
        self,
        agent_name: Optional[str] = None,
        request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        # legacy aliases
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        start_time = start_time or since
        end_time = end_time or until
        if request_id:
            resp = self.t_agent.query(
                IndexName="request_id-index",
                KeyConditionExpression=Key("request_id").eq(request_id),
            )
            items = resp.get("Items", [])
        else:
            items = self._scan_paginated(self.t_agent)

        items = [_from_ddb(i) for i in items]
        if conversation_id:
            items = [i for i in items if i.get("conversation_id") == conversation_id]
        if agent_name:
            items = [i for i in items if i.get("agent_name") == agent_name]
        if start_time:
            items = [i for i in items if (i.get("timestamp") or "") >= start_time]
        if end_time:
            items = [i for i in items if (i.get("timestamp") or "") <= end_time]
        items.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return items[offset : offset + limit]

    def get_request_summaries(
        self,
        conversation_id: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        if conversation_id:
            resp = self.t_summary.query(
                IndexName="conversation_id-index",
                KeyConditionExpression=Key("conversation_id").eq(conversation_id),
            )
            items = resp.get("Items", [])
        else:
            items = self._scan_paginated(self.t_summary)
        items = [_from_ddb(i) for i in items]
        if since:
            items = [i for i in items if (i.get("started_at") or "") >= since]
        items.sort(key=lambda r: r.get("started_at", ""), reverse=True)
        return items[offset : offset + limit]

    def get_token_usage_stats(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        group_by: str = "day",
        conversation_id: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Per-thread filtering — used by the AI Assistant chat's
        # "Token consumption" modal so admins can see exactly what each
        # conversation cost without scanning the global table. The brain
        # writes both `conversation_id` and `thread_id` onto LLMCalls
        # rows (see logging_config.set_request_context); for single-turn
        # threads they are the same string. We accept either alias and
        # match on the row's `conversation_id` (the more universally
        # populated field) — falling back to `thread_id` only when the
        # row carries no conversation_id (legacy data).
        rows = [_from_ddb(i) for i in self._scan_paginated(self.t_llm)]
        if start_time:
            rows = [r for r in rows if (r.get("timestamp") or "") >= start_time]
        if end_time:
            rows = [r for r in rows if (r.get("timestamp") or "") <= end_time]
        scope = conversation_id or thread_id
        if scope:
            rows = [
                r for r in rows
                if (r.get("conversation_id") == scope or r.get("thread_id") == scope)
            ]

        total_calls = len(rows)
        total_input = sum(int(r.get("input_tokens") or 0) for r in rows)
        total_output = sum(int(r.get("output_tokens") or 0) for r in rows)
        total_tokens = sum(int(r.get("total_tokens") or (int(r.get("input_tokens") or 0) + int(r.get("output_tokens") or 0))) for r in rows)
        total_cost = sum(float(r.get("estimated_cost_usd") or 0.0) for r in rows)
        successful = sum(1 for r in rows if r.get("success"))
        failed = total_calls - successful
        durations = [float(r.get("duration_ms") or 0) for r in rows if r.get("duration_ms") is not None]
        avg_duration_ms = sum(durations) / len(durations) if durations else 0

        totals = {
            "total_calls": total_calls,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
            "avg_duration_ms": avg_duration_ms,
            "successful_calls": successful,
            "failed_calls": failed,
        }

        def _group_by(rows_, key, extra=None):
            buckets: Dict[str, Dict[str, Any]] = {}
            for r in rows_:
                k = r.get(key) or "unknown"
                d = buckets.setdefault(
                    k,
                    {
                        key: k,
                        "calls": 0,
                        "successful_calls": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "tokens": 0,
                        "cost_usd": 0.0,
                        "avg_duration_ms": 0.0,
                        "_dur_sum": 0.0,
                    },
                )
                d["calls"] += 1
                if r.get("success"):
                    d["successful_calls"] += 1
                d["input_tokens"] += int(r.get("input_tokens") or 0)
                d["output_tokens"] += int(r.get("output_tokens") or 0)
                d["tokens"] += int(r.get("total_tokens") or 0)
                d["cost_usd"] += float(r.get("estimated_cost_usd") or 0.0)
                d["_dur_sum"] += float(r.get("duration_ms") or 0)
                if extra:
                    extra(d, r)
            for k, d in buckets.items():
                d["avg_duration_ms"] = d["_dur_sum"] / d["calls"] if d["calls"] else 0
                d.pop("_dur_sum", None)
            return list(buckets.values())

        def _by_op(d, r):
            d.setdefault("models_used", set()).add(r.get("model") or "unknown")
        by_operation = _group_by(rows, "operation", extra=_by_op)
        for d in by_operation:
            d["models_used"] = ",".join(sorted(d["models_used"])) if isinstance(d.get("models_used"), set) else d.get("models_used")

        return {
            "totals": totals,
            "by_model": _group_by(rows, "model"),
            "by_tier": _group_by(rows, "tier"),
            "by_operation": by_operation,
        }

    def get_token_summary(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        conversation_id: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Alias for get_token_usage_stats — matches source signature.
        Optional conversation_id / thread_id forwards to per-thread filter."""
        return self.get_token_usage_stats(
            start_time,
            end_time,
            conversation_id=conversation_id,
            thread_id=thread_id,
        )

    def get_request_analytics(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 50,
        conversation_id: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = [_from_ddb(i) for i in self._scan_paginated(self.t_llm)]
        if start_time:
            rows = [r for r in rows if (r.get("timestamp") or "") >= start_time]
        if end_time:
            rows = [r for r in rows if (r.get("timestamp") or "") <= end_time]
        scope = conversation_id or thread_id
        if scope:
            rows = [
                r for r in rows
                if (r.get("conversation_id") == scope or r.get("thread_id") == scope)
            ]
        # Group by request_id
        buckets: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            rid = r.get("request_id")
            if not rid:
                continue
            d = buckets.setdefault(rid, {
                "request_id": rid,
                "started_at": r.get("timestamp"),
                "ended_at": r.get("timestamp"),
                "llm_calls": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "_models": set(),
            })
            ts = r.get("timestamp") or ""
            if ts:
                if ts < d["started_at"]:
                    d["started_at"] = ts
                if ts > d["ended_at"]:
                    d["ended_at"] = ts
            d["llm_calls"] += 1
            d["total_input_tokens"] += int(r.get("input_tokens") or 0)
            d["total_output_tokens"] += int(r.get("output_tokens") or 0)
            d["total_tokens"] += int(r.get("total_tokens") or 0)
            d["total_cost_usd"] += float(r.get("estimated_cost_usd") or 0.0)
            d["_models"].add(r.get("model") or "unknown")
        out = list(buckets.values())
        for d in out:
            d["models_used"] = ",".join(sorted(d.pop("_models", set())))
        out.sort(key=lambda r: r.get("started_at") or "", reverse=True)
        return out[:limit]

    def get_log_counts(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> Dict[str, int]:
        rows = [_from_ddb(i) for i in self._scan_paginated(self.t_logs)]
        if start_time:
            rows = [r for r in rows if (r.get("timestamp") or "") >= start_time]
        if end_time:
            rows = [r for r in rows if (r.get("timestamp") or "") <= end_time]
        counts: Dict[str, int] = {}
        for r in rows:
            lvl = r.get("level") or "INFO"
            counts[lvl] = counts.get(lvl, 0) + 1
        return counts

    def search_logs(
        self,
        query: str,
        level: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple:
        """Returns (rows, total). Source contract."""
        return self.get_logs(
            level=level,
            search_query=query,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
        )

    def clear_logs(self, before_time: Optional[str] = None) -> int:
        cutoff = before_time or (
            datetime.now(timezone.utc) - timedelta(days=LOGS_TTL_DAYS)
        ).isoformat()
        deleted = 0
        for table_name in (self.t_logs, self.t_llm, self.t_agent, self.t_summary):
            for item in self._scan_paginated(table_name):
                ts = item.get("timestamp") or item.get("started_at")
                if ts and ts < cutoff:
                    pk_attr = next(iter(item.keys() & {"log_id", "call_id", "request_id"}))
                    table_name.delete_item(Key={pk_attr: item[pk_attr]})
                    deleted += 1
        return deleted

    def cleanup_old_logs(self, days_to_keep: int = 30) -> int:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days_to_keep)
        ).isoformat()
        return self.clear_logs(before_time=cutoff)

    def get_avg_response_time(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Returns {"avg_response_time_ms": float, "total_requests": int}.
        Matches source contract."""
        rows = [_from_ddb(i) for i in self._scan_paginated(self.t_summary)]
        if start_time:
            rows = [r for r in rows if (r.get("completed_at") or r.get("started_at") or "") >= start_time]
        if end_time:
            rows = [r for r in rows if (r.get("completed_at") or r.get("started_at") or "") <= end_time]
        durations = [float(r.get("total_duration_ms") or 0) for r in rows if (r.get("total_duration_ms") or 0) > 0]
        if not durations:
            return {"avg_response_time_ms": 0, "total_requests": 0}
        avg = sum(durations) / len(durations)
        return {
            "avg_response_time_ms": round(avg, 0),
            "total_requests": len(durations),
        }

    def get_usage_summary(self) -> Dict[str, Any]:  # noqa: D401
        """Returns {today, this_week, this_month: {conversations, requests}}.
        Source contract."""
        rows = [_from_ddb(i) for i in self._scan_paginated(self.t_summary)]
        now = datetime.now(timezone.utc)
        starts = {
            "today": (now - timedelta(hours=24)).isoformat(),
            "this_week": (now - timedelta(days=7)).isoformat(),
            "this_month": (now - timedelta(days=30)).isoformat(),
        }
        result: Dict[str, Any] = {}
        for label, start in starts.items():
            sliced = [r for r in rows if (r.get("completed_at") or r.get("started_at") or "") >= start]
            convs = {r.get("conversation_id") for r in sliced if r.get("conversation_id")}
            result[label] = {"conversations": len(convs), "requests": len(sliced)}
        return result

    # ------------------------------------------------------------------
    # Model pricing
    # ------------------------------------------------------------------

    def seed_model_pricing(
        self, default_pricing: Dict[str, Dict[str, float]]
    ) -> None:
        """Source contract:
        - missing rows: insert with updated_by='system_seed'
        - existing 'system_seed' rows: refresh rates if defaults changed
        - existing admin-edited rows (updated_by != 'system_seed'): preserve
        """
        for model, rates in default_pricing.items():
            if model == "default":
                continue
            existing = self.t_pricing.get_item(Key={"model": model}).get("Item")
            new_input = float(rates.get("input") or rates.get("input_rate_per_1k", 0) or 0)
            new_output = float(rates.get("output") or rates.get("output_rate_per_1k", 0) or 0)
            new_cached = rates.get("cached_input")
            new_cached_f = float(new_cached) if new_cached is not None else None
            now = _now_iso()
            if existing is None:
                item = {
                    "model": model,
                    "input_rate_per_1k": new_input,
                    "output_rate_per_1k": new_output,
                    "updated_at": now,
                    "updated_by": "system_seed",
                }
                if new_cached_f is not None:
                    item["cached_input_rate_per_1k"] = new_cached_f
                self.t_pricing.put_item(Item=_ddb_safe(item))
                continue
            existing = _from_ddb(existing)
            if existing.get("updated_by") != "system_seed":
                # Preserve admin-edits
                continue
            # Refresh seed rates in place
            updates = {}
            if float(existing.get("input_rate_per_1k") or 0) != new_input:
                updates["input_rate_per_1k"] = new_input
            if float(existing.get("output_rate_per_1k") or 0) != new_output:
                updates["output_rate_per_1k"] = new_output
            existing_cached = existing.get("cached_input_rate_per_1k")
            existing_cached_f = float(existing_cached) if existing_cached is not None else None
            if existing_cached_f != new_cached_f:
                updates["cached_input_rate_per_1k"] = new_cached_f
            if updates:
                expr_names = {f"#k{i}": k for i, k in enumerate(updates.keys())}
                expr_values = {f":v{i}": v for i, v in enumerate(updates.values())}
                set_clauses = [f"{n} = :v{i}" for i, n in enumerate(expr_names.values())]
                set_clauses.append("updated_at = :ts")
                expr_values[":ts"] = now
                self.t_pricing.update_item(
                    Key={"model": model},
                    UpdateExpression="SET " + ", ".join(set_clauses),
                    ExpressionAttributeValues=_ddb_safe(expr_values),
                )

    def get_all_model_pricing(self) -> List[Dict[str, Any]]:
        items = self._scan_paginated(self.t_pricing)
        return [_from_ddb(i) for i in items]

    def get_model_pricing(self, model: str) -> Optional[Dict[str, float]]:
        resp = self.t_pricing.get_item(Key={"model": model})
        item = resp.get("Item")
        if not item:
            return None
        item = _from_ddb(item)
        return {
            "input_rate_per_1k": float(item.get("input_rate_per_1k") or 0.0),
            "output_rate_per_1k": float(item.get("output_rate_per_1k") or 0.0),
            "cached_input_rate_per_1k": item.get("cached_input_rate_per_1k"),
        }

    def update_model_pricing(
        self,
        model: str,
        input_rate: Optional[float] = None,
        output_rate: Optional[float] = None,
        cached_input_rate: Optional[float] = None,
        updated_by: Optional[str] = None,
        # AA-lambda Phase 3 aliases for legacy DynamoDB-only callers
        input_rate_per_1k: Optional[float] = None,
        output_rate_per_1k: Optional[float] = None,
        cached_input_rate_per_1k: Optional[float] = None,
    ) -> bool:
        """Source contract: input_rate / output_rate / cached_input_rate / updated_by.
        DynamoDB-only aliases (input_rate_per_1k etc.) are still accepted."""
        ir = input_rate if input_rate is not None else input_rate_per_1k
        orr = output_rate if output_rate is not None else output_rate_per_1k
        cir = cached_input_rate if cached_input_rate is not None else cached_input_rate_per_1k

        item = {
            "model": model,
            "input_rate_per_1k": float(ir) if ir is not None else 0.0,
            "output_rate_per_1k": float(orr) if orr is not None else 0.0,
            "updated_at": _now_iso(),
            "updated_by": updated_by or "admin",
        }
        if cir is not None:
            item["cached_input_rate_per_1k"] = float(cir)
        self.t_pricing.put_item(Item=_ddb_safe(item))
        return True

    # ------------------------------------------------------------------
    # System settings
    # ------------------------------------------------------------------

    def get_setting(self, key: str) -> Optional[str]:
        resp = self.t_settings.get_item(Key={"key": key})
        item = resp.get("Item")
        return item.get("value") if item else None

    def set_setting(self, key: str, value: str) -> None:
        self.t_settings.put_item(
            Item={"key": key, "value": value, "updated_at": _now_iso()}
        )

    # ------------------------------------------------------------------
    # Pending actions (Phase 1.B authority — LogStorage stays as a passthrough
    # for backwards compat callers that still use log_storage.insert_pending_action)
    # ------------------------------------------------------------------

    def insert_pending_action(
        self,
        action_id: str,
        thread_id: Optional[str],
        conversation_id: Optional[str],
        request_id: Optional[str],
        step_number: Optional[int],
        agent_name: str,
        tool_name: str,
        description: Optional[str],
        inputs: Optional[Dict[str, Any]],
        output_variables: Optional[Dict[str, Any]] = None,
        risk_level: str = "MODERATE",
        expires_at: Optional[str] = None,
        connection_id: Optional[str] = None,
    ) -> int:
        ttl_epoch = None
        if expires_at:
            try:
                ttl_epoch = int(datetime.fromisoformat(expires_at).timestamp())
            except Exception:
                ttl_epoch = _ttl_epoch(7)
        else:
            ttl_epoch = _ttl_epoch(7)

        item = {
            "action_id": action_id,
            "agent_name": agent_name,
            "tool_name": tool_name,
            "status": "pending",
            "risk_level": risk_level,
            "created_at": _now_iso(),
            "expires_at": ttl_epoch,
        }
        if thread_id:
            item["thread_id"] = thread_id
        if conversation_id:
            item["conversation_id"] = conversation_id
        if request_id:
            item["request_id"] = request_id
        if step_number is not None:
            item["step_number"] = int(step_number)
        if description:
            item["description"] = description[:1000]
        if inputs is not None:
            item["inputs"] = json.dumps(inputs, default=str)[:8000]
        if output_variables is not None:
            item["output_variables"] = json.dumps(output_variables, default=str)[:2000]
        if connection_id:
            # Phase 4.C — used by ws-chat to route the resume push back
            item["connection_id"] = connection_id

        self.t_pending.put_item(Item=_ddb_safe(item))
        return int(action_id[:12], 16) if isinstance(action_id, str) else 0

    def get_pending_action(self, action_id: str) -> Optional[Dict[str, Any]]:
        resp = self.t_pending.get_item(Key={"action_id": action_id})
        item = resp.get("Item")
        if not item:
            return None
        item = _from_ddb(item)
        if item.get("inputs"):
            try:
                item["inputs"] = json.loads(item["inputs"])
            except (json.JSONDecodeError, TypeError):
                pass
        if item.get("output_variables"):
            try:
                item["output_variables"] = json.loads(item["output_variables"])
            except (json.JSONDecodeError, TypeError):
                pass
        return item

    def get_pending_actions(
        self,
        thread_id: Optional[str] = None,
        status: str = "pending",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        if thread_id:
            resp = self.t_pending.query(
                IndexName="thread_id-status-index",
                KeyConditionExpression=Key("thread_id").eq(thread_id)
                & Key("status").eq(status),
                Limit=limit,
            )
            items = resp.get("Items", [])
        else:
            items = self._scan_paginated(self.t_pending)
            items = [i for i in items if i.get("status") == status]
            items = items[:limit]

        out: List[Dict[str, Any]] = []
        for item in items:
            item = _from_ddb(item)
            if item.get("inputs"):
                try:
                    item["inputs"] = json.loads(item["inputs"])
                except (json.JSONDecodeError, TypeError):
                    pass
            if item.get("output_variables"):
                try:
                    item["output_variables"] = json.loads(item["output_variables"])
                except (json.JSONDecodeError, TypeError):
                    pass
            out.append(item)
        return out

    def update_pending_action_status(
        self,
        action_id: str,
        status: str,
        decided_by: Optional[str] = None,
        execution_result: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> bool:
        update_expr = ["#s = :s", "decided_at = :d"]
        expr_names = {"#s": "status"}
        expr_values = {
            ":s": status,
            ":d": _now_iso(),
        }
        if decided_by:
            update_expr.append("decided_by = :db")
            expr_values[":db"] = decided_by
        if execution_result is not None:
            update_expr.append("execution_result = :er")
            expr_values[":er"] = json.dumps(execution_result, default=str)[:8000]
        if error:
            update_expr.append("#e = :err")
            expr_names["#e"] = "error"
            expr_values[":err"] = error[:1000]

        try:
            self.t_pending.update_item(
                Key={"action_id": action_id},
                UpdateExpression="SET " + ", ".join(update_expr),
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
                ConditionExpression="attribute_exists(action_id)",
            )
            return True
        except self._ddb.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def delete_pending_action(self, action_id: str) -> bool:
        try:
            self.t_pending.delete_item(
                Key={"action_id": action_id},
                ConditionExpression="attribute_exists(action_id)",
            )
            return True
        except self._ddb.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def cleanup_expired_actions(self) -> int:
        # TTL handles this server-side; provide manual sweep for tests.
        now_epoch = int(datetime.now(timezone.utc).timestamp())
        deleted = 0
        for item in self._scan_paginated(self.t_pending):
            ttl = item.get("expires_at")
            if ttl and int(ttl) < now_epoch:
                self.t_pending.delete_item(Key={"action_id": item["action_id"]})
                deleted += 1
        return deleted

    def cleanup_expired_pending_actions(self, expire_minutes: int = 5) -> int:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=expire_minutes)
        ).isoformat()
        deleted = 0
        for item in self._scan_paginated(self.t_pending):
            if item.get("status") != "pending":
                continue
            created = item.get("created_at")
            if created and created < cutoff:
                self.update_pending_action_status(
                    action_id=item["action_id"],
                    status="expired",
                    error="auto-expired",
                )
                deleted += 1
        return deleted

    # ------------------------------------------------------------------
    # LogsPage admin endpoints (Phase 3.D / contract §4)
    # ------------------------------------------------------------------

    def get_admin_metrics(self, period_hours: int = 24) -> Dict[str, Any]:
        return {
            "tokens": self.get_token_usage_stats(period_hours),
            "requests": self.get_request_analytics(period_hours),
            "log_counts": self.get_log_counts(period_hours),
            "avg_response_time_ms": self.get_avg_response_time(period_hours),
        }

    def get_internal_metrics(self) -> Dict[str, Any]:
        # Currently mirrors get_admin_metrics(period_hours=1); contract §4.7.
        return self.get_admin_metrics(period_hours=1)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _scan_paginated(self, table) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        last_key = None
        while True:
            kwargs = {}
            if last_key is not None:
                kwargs["ExclusiveStartKey"] = last_key
            resp = table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
        return items

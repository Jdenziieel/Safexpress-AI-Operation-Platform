"""
DynamoDB-backed ThreadManager.

Drop-in replacement for `thread_manager.ThreadManager`. Same public API.
Backed by the 5 Sup_* tables provisioned in Phase 0.A:
  - Sup_Threads             (PK: thread_id, GSI: user_id-updated_at-index)
  - Sup_ThreadStates        (PK: thread_id)
  - Sup_MemoryStates        (PK: thread_id)
  - Sup_Messages            (PK: thread_id, SK: sk = "<created_at>#<message_id>")
  - Sup_ConversationStates  (PK: conversation_id, TTL: expires_at)

S3 spillover for `Sup_ThreadStates` rows over ~350KB; pointer is
`{"s3_pointer": "s3://bucket/key"}` in the DynamoDB row, real blob in S3.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Key

from models.models import ThreadMetadata


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

_S3_SPILL_THRESHOLD = 350 * 1024  # 350 KB; DynamoDB hard limit is 400 KB
_TABLE_NAMES = {
    "threads": os.environ.get("SUP_THREADS_TABLE", "Sup_Threads"),
    "thread_states": os.environ.get("SUP_THREAD_STATES_TABLE", "Sup_ThreadStates"),
    "memory_states": os.environ.get("SUP_MEMORY_STATES_TABLE", "Sup_MemoryStates"),
    "messages": os.environ.get("SUP_MESSAGES_TABLE", "Sup_Messages"),
    "conversation_states": os.environ.get(
        "SUP_CONV_STATES_TABLE", "Sup_ConversationStates"
    ),
}

_THREADS_GSI = "user_id-updated_at-index"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ddb_safe(obj):
    """DynamoDB doesn't accept floats; convert to Decimal. Recursively scrubs
    None values inside lists. Top-level None keys are caller's responsibility."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _ddb_safe(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_ddb_safe(v) for v in obj]
    return obj


def _from_ddb(obj):
    """Inverse of _ddb_safe — Decimal -> float / int."""
    if isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    if isinstance(obj, dict):
        return {k: _from_ddb(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_ddb(v) for v in obj]
    return obj


# ----------------------------------------------------------------------
# Class
# ----------------------------------------------------------------------


class ThreadManager:
    """
    DynamoDB-backed thread manager. Identical public surface to the
    SQLite version in `thread_manager.py`.
    """

    def __init__(self, db_path: str = "threads.db"):
        # `db_path` kept for API compatibility; ignored when DynamoDB-backed.
        self.db_path = Path(db_path)
        region = os.environ.get("AWS_REGION", "ap-southeast-1")
        endpoint = os.environ.get("DYNAMODB_ENDPOINT_URL")  # set for DynamoDB Local

        kwargs = {"region_name": region}
        if endpoint:
            kwargs["endpoint_url"] = endpoint

        self._ddb = boto3.resource("dynamodb", **kwargs)
        self._s3 = None  # lazy
        self._s3_bucket = os.environ.get("S3_TEMP_BUCKET", "capstone-kb-files")

        self.t_threads = self._ddb.Table(_TABLE_NAMES["threads"])
        self.t_thread_states = self._ddb.Table(_TABLE_NAMES["thread_states"])
        self.t_memory_states = self._ddb.Table(_TABLE_NAMES["memory_states"])
        self.t_messages = self._ddb.Table(_TABLE_NAMES["messages"])
        self.t_conv_states = self._ddb.Table(_TABLE_NAMES["conversation_states"])

        print(f" DynamoDB thread manager initialized (region={region})")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_s3(self):
        if self._s3 is None:
            self._s3 = boto3.client(
                "s3", region_name=os.environ.get("AWS_REGION", "ap-southeast-1")
            )
        return self._s3

    def _row_to_metadata(self, item: Dict[str, Any]) -> ThreadMetadata:
        item = _from_ddb(item)
        tags = item.get("tags") or []
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                tags = []
        return ThreadMetadata(
            thread_id=item["thread_id"],
            user_id=item["user_id"],
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
            title=item.get("title"),
            message_count=int(item.get("message_count") or 0),
            status=item.get("status") or "active",
            last_message_preview=item.get("last_message_preview"),
            tags=tags,
        )

    # ------------------------------------------------------------------
    # CRUD — threads
    # ------------------------------------------------------------------

    def create_thread(
        self,
        user_id: str,
        thread_id: Optional[str] = None,
        title: Optional[str] = None,
    ) -> ThreadMetadata:
        if thread_id is None:
            thread_id = f"{user_id}_{uuid.uuid4().hex[:8]}"
        now = _now_iso()
        item = {
            "thread_id": thread_id,
            "user_id": user_id,
            "created_at": now,
            "updated_at": now,
            "title": title or "New Conversation",
            "message_count": 0,
            "status": "active",
        }
        self.t_threads.put_item(Item=item)
        print(f" Created thread (DDB): {thread_id} for user: {user_id}")
        return ThreadMetadata(
            thread_id=thread_id,
            user_id=user_id,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
            title=title or "New Conversation",
            message_count=0,
            status="active",
        )

    def get_thread(self, thread_id: str) -> Optional[ThreadMetadata]:
        resp = self.t_threads.get_item(Key={"thread_id": thread_id})
        item = resp.get("Item")
        if not item:
            return None
        return self._row_to_metadata(item)

    def list_threads(
        self,
        user_id: str,
        status: str = "active",
        limit: int = 50,
        offset: int = 0,
    ) -> List[ThreadMetadata]:
        # Query GSI; offset emulated by walking pages.
        kwargs = {
            "IndexName": _THREADS_GSI,
            "KeyConditionExpression": Key("user_id").eq(user_id),
            "ScanIndexForward": False,  # newest first
            "Limit": limit + offset,
        }
        rows: List[ThreadMetadata] = []
        skipped = 0
        last_key = None
        while True:
            if last_key is not None:
                kwargs["ExclusiveStartKey"] = last_key
            resp = self.t_threads.query(**kwargs)
            for item in resp.get("Items", []):
                if item.get("status", "active") != status:
                    continue
                if skipped < offset:
                    skipped += 1
                    continue
                rows.append(self._row_to_metadata(item))
                if len(rows) >= limit:
                    return rows
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
        return rows

    def update_thread(
        self,
        thread_id: str,
        title: Optional[str] = None,
        message_count: Optional[int] = None,
        last_message_preview: Optional[str] = None,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        update_expr = ["#u = :u"]
        expr_names = {"#u": "updated_at"}
        expr_values = {":u": _now_iso()}

        if title is not None:
            update_expr.append("#t = :t")
            expr_names["#t"] = "title"
            expr_values[":t"] = title
        if message_count is not None:
            update_expr.append("#mc = :mc")
            expr_names["#mc"] = "message_count"
            expr_values[":mc"] = int(message_count)
        if last_message_preview is not None:
            update_expr.append("#lmp = :lmp")
            expr_names["#lmp"] = "last_message_preview"
            expr_values[":lmp"] = last_message_preview
        if status is not None:
            update_expr.append("#st = :st")
            expr_names["#st"] = "status"
            expr_values[":st"] = status
        if tags is not None:
            update_expr.append("#tg = :tg")
            expr_names["#tg"] = "tags"
            expr_values[":tg"] = tags

        try:
            self.t_threads.update_item(
                Key={"thread_id": thread_id},
                UpdateExpression="SET " + ", ".join(update_expr),
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
                ConditionExpression="attribute_exists(thread_id)",
            )
            return True
        except self._ddb.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def archive_thread(self, thread_id: str) -> bool:
        return self.update_thread(thread_id, status="archived")

    def delete_thread(self, thread_id: str, hard_delete: bool = False) -> bool:
        if not hard_delete:
            return self.update_thread(thread_id, status="deleted")

        # Hard delete — drop thread + state + memory + ALL messages.
        existed = self.get_thread(thread_id) is not None
        if not existed:
            return False
        self.t_threads.delete_item(Key={"thread_id": thread_id})
        self.t_thread_states.delete_item(Key={"thread_id": thread_id})
        self.t_memory_states.delete_item(Key={"thread_id": thread_id})

        # Page through messages and batch-delete by SK.
        last_key = None
        while True:
            kwargs = {"KeyConditionExpression": Key("thread_id").eq(thread_id)}
            if last_key is not None:
                kwargs["ExclusiveStartKey"] = last_key
            resp = self.t_messages.query(**kwargs)
            with self.t_messages.batch_writer() as bw:
                for item in resp.get("Items", []):
                    bw.delete_item(
                        Key={"thread_id": item["thread_id"], "sk": item["sk"]}
                    )
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
        return True

    def search_threads(
        self,
        user_id: str,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[ThreadMetadata]:
        rows = self.list_threads(user_id=user_id, status="active", limit=200)
        if query:
            ql = query.lower()
            rows = [
                t
                for t in rows
                if (t.title or "").lower().find(ql) >= 0
                or (t.last_message_preview or "").lower().find(ql) >= 0
            ]
        if tags:
            tag_set = set(tags)
            rows = [t for t in rows if tag_set.issubset(set(t.tags or []))]
        return rows[:limit]

    # ------------------------------------------------------------------
    # Thread state / memory state
    # ------------------------------------------------------------------

    def save_thread_state(self, thread_id: str, state: Any) -> None:
        if hasattr(state, "model_dump"):
            state_dict = state.model_dump()
        else:
            state_dict = state
        state_json = json.dumps(state_dict, default=str)

        if len(state_json.encode("utf-8")) > _S3_SPILL_THRESHOLD:
            key = f"thread_states/{thread_id}/{uuid.uuid4().hex}.json"
            self._get_s3().put_object(
                Bucket=self._s3_bucket, Key=key, Body=state_json.encode("utf-8")
            )
            self.t_thread_states.put_item(
                Item={
                    "thread_id": thread_id,
                    "s3_pointer": f"s3://{self._s3_bucket}/{key}",
                    "stored_at": _now_iso(),
                }
            )
            return

        self.t_thread_states.put_item(
            Item={
                "thread_id": thread_id,
                "state_json": state_json,
                "stored_at": _now_iso(),
            }
        )

    def load_thread_state(self, thread_id: str) -> Optional[Dict[str, Any]]:
        resp = self.t_thread_states.get_item(Key={"thread_id": thread_id})
        item = resp.get("Item")
        if not item:
            return None

        if "s3_pointer" in item:
            pointer = item["s3_pointer"]
            assert pointer.startswith("s3://"), pointer
            _, _, rest = pointer.partition("s3://")
            bucket, _, key = rest.partition("/")
            obj = self._get_s3().get_object(Bucket=bucket, Key=key)
            return json.loads(obj["Body"].read())

        raw = item.get("state_json")
        return json.loads(raw) if raw else None

    def save_memory_state(self, thread_id: str, memory: Dict[str, Any]) -> None:
        memory_json = json.dumps(memory, default=str)
        self.t_memory_states.put_item(
            Item={
                "thread_id": thread_id,
                "memory_json": memory_json,
                "stored_at": _now_iso(),
            }
        )

    def load_memory_state(self, thread_id: str) -> Optional[Dict[str, Any]]:
        resp = self.t_memory_states.get_item(Key={"thread_id": thread_id})
        item = resp.get("Item")
        if not item or not item.get("memory_json"):
            return None
        return json.loads(item["memory_json"])

    def save_conversation_state_standalone(
        self, conversation_id: str, state: Any
    ) -> None:
        if hasattr(state, "model_dump"):
            state_dict = state.model_dump()
        else:
            state_dict = state
        self.t_conv_states.put_item(
            Item={
                "conversation_id": conversation_id,
                "state_json": json.dumps(state_dict, default=str),
                "updated_at": _now_iso(),
            }
        )

    def load_conversation_state_standalone(
        self, conversation_id: str
    ) -> Optional[Dict[str, Any]]:
        resp = self.t_conv_states.get_item(Key={"conversation_id": conversation_id})
        item = resp.get("Item")
        if not item or not item.get("state_json"):
            return None
        return json.loads(item["state_json"])

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def add_message(
        self,
        thread_id: str,
        role: str,
        content: str,
        file_name: Optional[str] = None,
        file_type: Optional[str] = None,
        file_size: Optional[int] = None,
    ) -> int:
        now = _now_iso()
        message_id = uuid.uuid4().hex
        sk = f"{now}#{message_id}"
        item = {
            "thread_id": thread_id,
            "sk": sk,
            "message_id": message_id,
            "role": role,
            "content": content,
            "created_at": now,
        }
        if file_name:
            item["file_name"] = file_name
        if file_type:
            item["file_type"] = file_type
        if file_size is not None:
            item["file_size"] = int(file_size)

        preview = content[:100] if len(content) > 100 else content

        # Two sequential resource-level writes (high-level Table API),
        # NOT transact_write_items via meta.client.
        #
        # Why: every attempt to use `meta.client.transact_write_items` from
        # this Lambda failed with `Incorrect operand type for operator …,
        # operand type: M`/`MAP` even though the same payload works via the
        # AWS CLI. The root cause is that low-level AttributeValue dicts
        # (`{"N": "1"}`) get re-serialized by something in this boto3 call
        # path and become `{"M": {"N": {"S": "1"}}}` on the wire, so DDB
        # sees every value as a Map and rejects arithmetic / ADD on them.
        # The high-level `Table.put_item` / `Table.update_item` calls used
        # everywhere else in this file (e.g. `update_thread` line 254) take
        # plain Python values and serialize them correctly.
        #
        # Trade-off: cross-table atomicity is lost. The Put always runs
        # first; if the counter Update fails the message is still persisted
        # and the count is off-by-one until the next add_message — a
        # cosmetic drift, not data loss. The Update is best-effort: any
        # exception is logged and swallowed so a transient counter glitch
        # cannot block the chat flow.
        self.t_messages.put_item(Item=item)
        try:
            self.t_threads.update_item(
                Key={"thread_id": thread_id},
                UpdateExpression="SET last_message_preview = :p, updated_at = :u ADD message_count :one",
                ExpressionAttributeValues={
                    ":one": 1,
                    ":p": preview,
                    ":u": now,
                },
            )
        except Exception as e:
            print(
                f"[dynamodb_thread_manager] add_message: counter/preview "
                f"update failed for thread {thread_id} (non-fatal, message "
                f"is already saved): {e}"
            )
        # message_id is a string ULID-ish; legacy callers expected an int.
        # Hash it to a stable int so downstream code that did `int(...)` still works.
        return int(message_id[:12], 16)

    def replace_last_assistant_message(self, thread_id: str, content: str) -> bool:
        # Query newest assistant row.
        resp = self.t_messages.query(
            KeyConditionExpression=Key("thread_id").eq(thread_id),
            ScanIndexForward=False,
            Limit=20,
        )
        target = None
        for item in resp.get("Items", []):
            if item.get("role") == "assistant":
                target = item
                break
        if not target:
            return False

        self.t_messages.update_item(
            Key={"thread_id": thread_id, "sk": target["sk"]},
            UpdateExpression="SET content = :c",
            ExpressionAttributeValues={":c": content},
        )

        preview = content[:100] if len(content) > 100 else content
        self.t_threads.update_item(
            Key={"thread_id": thread_id},
            UpdateExpression="SET last_message_preview = :p, updated_at = :u",
            ExpressionAttributeValues={":p": preview, ":u": _now_iso()},
        )
        return True

    def get_messages(
        self, thread_id: str, limit: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        resp = self.t_messages.query(
            KeyConditionExpression=Key("thread_id").eq(thread_id),
            ScanIndexForward=True,
            Limit=limit + offset,
        )
        items = resp.get("Items", [])[offset : offset + limit]
        out: List[Dict[str, Any]] = []
        for item in items:
            item = _from_ddb(item)
            msg = {
                "message_id": int(item["message_id"][:12], 16) if isinstance(item.get("message_id"), str) else item.get("message_id"),
                "thread_id": item["thread_id"],
                "role": item["role"],
                "content": item["content"],
                "created_at": item["created_at"],
            }
            if item.get("file_name"):
                msg["file_name"] = item["file_name"]
                msg["file_type"] = item.get("file_type")
                msg["file_size"] = item.get("file_size")
            out.append(msg)
        return out

    def get_message_count(self, thread_id: str) -> int:
        thread = self.get_thread(thread_id)
        return thread.message_count if thread else 0

    def get_thread_count(self, user_id: str, status: str = "active") -> int:
        # Query GSI and count; up to 1000 threads per user is OK.
        count = 0
        last_key = None
        while True:
            kwargs = {
                "IndexName": _THREADS_GSI,
                "KeyConditionExpression": Key("user_id").eq(user_id),
                "Select": "COUNT",
            }
            if last_key is not None:
                kwargs["ExclusiveStartKey"] = last_key
            resp = self.t_threads.query(**kwargs)
            count += resp.get("Count", 0)
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
        return count

    def auto_generate_title(self, first_message: str, max_length: int = 50) -> str:
        title = first_message.strip()
        if len(title) > max_length:
            title = title[:max_length] + "..."
        return title


# Helper: low-level transact_write attribute conversion (DynamoDB JSON).
# Used only inside add_message — keeps the rest of the class on the resource API.
def _ddb_to_attr(item: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in item.items():
        if isinstance(v, bool):
            out[k] = {"BOOL": v}
        elif isinstance(v, int):
            out[k] = {"N": str(v)}
        elif isinstance(v, float):
            out[k] = {"N": str(v)}
        elif isinstance(v, str):
            out[k] = {"S": v}
        elif v is None:
            out[k] = {"NULL": True}
        elif isinstance(v, list):
            out[k] = {"L": [_ddb_to_attr({"_": x})["_"] for x in v]}
        elif isinstance(v, dict):
            out[k] = {"M": _ddb_to_attr(v)}
        else:
            out[k] = {"S": str(v)}
    return out

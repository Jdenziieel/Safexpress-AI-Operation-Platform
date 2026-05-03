"""supervisor-action-approve — POST /action/approve/{action_id}.

Heavy Lambda (Docker, can fire LLMs via _resume_remaining_steps) that:
  1. Loads PendingAction from DynamoDB
  2. Updates status (approve / reject / skip)
  3. On approve: executes the single action via call_agent_with_retry,
     persists status, and (Phase 4.C) pushes the result back over the
     WebSocket if a connection_id is associated with the pending row.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.join(_HERE, "shared")
for p in (_SHARED, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.lambda_helpers import (
    success_response,
    error_response,
    options_response,
    parse_body,
    get_path_param,
    set_request_context_lambda,
    quota_check,
)
from shared.persistence_factory import get_log_storage
from shared.apigw_pusher import post_to_connection
from shared.config import AGENT_ENDPOINTS, get_google_credentials
from shared.utils import call_agent_with_retry


def _cleanup_stale_connection(connection_id: str) -> None:
    """Best-effort delete of a stale connection record. Called when
    ``post_to_connection`` returns False (410 Gone)."""
    if not connection_id:
        return
    try:
        import boto3  # type: ignore

        table_name = os.environ.get("WS_CONNECTIONS_TABLE", "KB_WebSocketConnections")
        region = os.environ.get("AWS_REGION", "ap-southeast-1")
        boto3.resource("dynamodb", region_name=region).Table(table_name).delete_item(
            Key={"connection_id": connection_id}
        )
    except Exception as e:
        print(f"[approve] cleanup_stale_connection({connection_id}) failed: {e}")


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()

    action_id = get_path_param(event, "action_id")
    if not action_id:
        return error_response(400, "action_id is required")

    body = parse_body(event)
    decision = (body.get("decision") or "approve").lower()
    rejection_reason = body.get("rejection_reason")
    modified_inputs = body.get("modified_inputs")

    if decision not in ("approve", "reject", "skip"):
        return error_response(400, "decision must be one of: approve, reject, skip")

    storage = get_log_storage()
    with set_request_context_lambda(event) as ctx:
        user_id = ctx.get("user_id")
        jwt = ctx.get("jwt")
        request_id = ctx.get("request_id")

        # Pre-flight quota check — approval can resume a workflow that
        # fires additional LLM calls (transform_text / summarization).
        if decision == "approve":
            allowed, qdata = quota_check(user_id, jwt, estimated_tokens=2000, operation="action_approve")
            if not allowed:
                return error_response(
                    429 if qdata.get("quota_exceeded") else 403,
                    qdata.get("error", "Quota exceeded"),
                    quota=qdata,
                )

        action_data = storage.get_pending_action(action_id)
        if not action_data:
            return error_response(404, "Action not found")
        if action_data.get("status", "pending") != "pending":
            return error_response(400, f"Action already {action_data.get('status')}")

        # Timeout check (360 minutes per source)
        try:
            created_at = datetime.fromisoformat(action_data["created_at"]) if isinstance(action_data["created_at"], str) else action_data["created_at"]
        except Exception:
            created_at = datetime.utcnow()
        if datetime.utcnow() - created_at > timedelta(minutes=360):
            storage.update_pending_action_status(action_id, "expired", decided_by="system_timeout")
            return error_response(400, "Action approval expired")

        # Reject path
        if decision == "reject":
            storage.update_pending_action_status(action_id, "rejected", decided_by="user", error=rejection_reason)
            return success_response({
                "status": "rejected",
                "action_id": action_id,
                "message": f"Action rejected: {rejection_reason}",
            })

        # Skip path
        if decision == "skip":
            storage.update_pending_action_status(action_id, "skipped", decided_by="user")
            return success_response({
                "status": "skipped",
                "action_id": action_id,
                "message": "Action skipped, workflow will continue to next step",
            })

        # Approve path — mark approved then execute the single tool call.
        storage.update_pending_action_status(action_id, "approved", decided_by="user")

        step_info = {
            "agent": action_data.get("agent_name"),
            "tool": action_data.get("tool_name"),
            "inputs": modified_inputs or action_data.get("inputs") or {},
        }

        try:
            agent = step_info["agent"]
            tool = step_info["tool"]
            inputs = step_info["inputs"]
            agent_target = AGENT_ENDPOINTS.get(agent)
            if not agent_target:
                raise ValueError(f"No endpoint for agent: {agent}")
            result = call_agent_with_retry(
                agent_url=agent_target,
                request_payload={
                    "tool": tool,
                    "inputs": inputs,
                    "credentials_dict": get_google_credentials(),
                },
                max_retries=3,
            )
            if not result:
                raise ValueError("Agent call failed after retries")
            storage.update_pending_action_status(
                action_id, "completed", decided_by="user", execution_result=result
            )
            try:
                storage.delete_pending_action(action_id)
            except Exception:
                pass

            # Phase 4.C — push back over WS if there's a connection_id stash
            connection_id = action_data.get("connection_id")
            if connection_id:
                try:
                    delivered = post_to_connection(
                        connection_id,
                        {
                            "type": "complete",
                            "thread_id": action_data.get("thread_id"),
                            "action_id": action_id,
                            "result": result,
                        },
                    )
                    if not delivered:
                        # Connection went 410 Gone between pause and approve;
                        # clean up the stale record so the next $disconnect
                        # doesn't double-delete.
                        _cleanup_stale_connection(connection_id)
                except Exception as push_err:
                    print(f"[approve] WS push failed: {push_err}")

            return success_response({
                "status": "completed",
                "action_id": action_id,
                "result": result,
                "message": "Action executed successfully",
            })

        except Exception as e:
            storage.update_pending_action_status(action_id, "failed", decided_by="user", error=str(e))
            return success_response({
                "status": "failed",
                "action_id": action_id,
                "error": str(e),
                "message": f"Action execution failed: {e}",
            })

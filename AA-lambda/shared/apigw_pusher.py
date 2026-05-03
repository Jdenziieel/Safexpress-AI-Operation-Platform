"""
API Gateway WebSocket push helper.

Wraps `boto3.client('apigatewaymanagementapi').post_to_connection`.

Used by:
  - supervisor-ws-chat (Phase 4) — replaces ProgressConnectionManager
  - supervisor-action-approve (Phase 4.C) — pushes resume results back over WS
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Union

import boto3


_clients: Dict[str, Any] = {}  # endpoint_url -> boto3 client


class GoneException(Exception):
    """Raised when the WebSocket connection is no longer alive (410 Gone)."""


def _client_for(endpoint_url: str):
    cli = _clients.get(endpoint_url)
    if cli is None:
        cli = boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=endpoint_url,
            region_name=os.environ.get("AWS_REGION", "ap-southeast-1"),
        )
        _clients[endpoint_url] = cli
    return cli


def _resolve_endpoint(event: Optional[Dict[str, Any]] = None) -> str:
    """Pick an endpoint URL. Order:
      1. WS_API_ENDPOINT env var (deployed)
      2. event["requestContext"]["domainName"] + stage (live request)
      3. ValueError if neither present
    """
    env = os.environ.get("WS_API_ENDPOINT")
    if env:
        return env
    if event:
        rc = event.get("requestContext") or {}
        dn = rc.get("domainName")
        st = rc.get("stage")
        if dn and st:
            return f"https://{dn}/{st}"
    raise ValueError("WS_API_ENDPOINT not set and event lacks requestContext")


def post_to_connection(
    connection_id: str,
    payload: Union[Dict[str, Any], str, bytes],
    event: Optional[Dict[str, Any]] = None,
) -> bool:
    """Send a JSON payload to a WebSocket connection.
    Returns True on success, False on GoneException (caller should clean up
    the connection record).
    """
    endpoint = _resolve_endpoint(event)
    cli = _client_for(endpoint)

    if isinstance(payload, dict):
        body = json.dumps(payload).encode("utf-8")
    elif isinstance(payload, str):
        body = payload.encode("utf-8")
    else:
        body = payload

    try:
        cli.post_to_connection(ConnectionId=connection_id, Data=body)
        return True
    except cli.exceptions.GoneException:
        return False
    except Exception as e:
        print(f"[apigw_pusher] post_to_connection failed for {connection_id}: {e}")
        return False


class ApiGwPusher:
    """Tiny wrapper that remembers the connection_id + endpoint for the
    duration of a Lambda invocation. Convenient inside supervisor-ws-chat."""

    def __init__(self, connection_id: str, event: Optional[Dict[str, Any]] = None):
        self.connection_id = connection_id
        self.endpoint = _resolve_endpoint(event)
        self.client = _client_for(self.endpoint)
        self._gone = False

    def push(self, payload: Union[Dict[str, Any], str, bytes]) -> bool:
        if self._gone:
            return False
        if isinstance(payload, dict):
            body = json.dumps(payload).encode("utf-8")
        elif isinstance(payload, str):
            body = payload.encode("utf-8")
        else:
            body = payload
        try:
            self.client.post_to_connection(ConnectionId=self.connection_id, Data=body)
            return True
        except self.client.exceptions.GoneException:
            self._gone = True
            return False
        except Exception as e:
            print(f"[ApiGwPusher] push failed: {e}")
            return False

    @property
    def gone(self) -> bool:
        return self._gone


def make_pusher_for_event(event: Dict[str, Any]) -> ApiGwPusher:
    """Build a pusher from an incoming WS Lambda event."""
    rc = event.get("requestContext") or {}
    connection_id = rc.get("connectionId")
    if not connection_id:
        raise ValueError("event has no connectionId")
    return ApiGwPusher(connection_id, event)

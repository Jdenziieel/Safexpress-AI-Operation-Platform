"""supervisor-delete-thread — DELETE /threads/{thread_id} (soft archive)"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.join(_HERE, "shared")
for p in (_SHARED, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.lambda_helpers import (
    success_response,
    error_response,
    options_response,
    get_path_param,
    set_request_context_lambda,
)
from shared.persistence_factory import get_thread_manager


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()

    thread_id = get_path_param(event, "thread_id")
    if not thread_id:
        return error_response(400, "thread_id is required")

    tm = get_thread_manager()
    with set_request_context_lambda(event):
        try:
            # Source ``thread_service.delete_thread(hard_delete=False)`` sets
            # status="deleted" (not "archived"). Preserved verbatim. The
            # response message keeps the source's ("archived") wording for
            # response-shape parity with the deployed REST contract.
            success = tm.delete_thread(thread_id, hard_delete=False)
            if not success:
                return error_response(404, f"Thread {thread_id} not found")
            return success_response({
                "thread_id": thread_id,
                "message": "Thread archived successfully",
            })
        except Exception as e:
            return error_response(500, f"Error deleting thread: {e}")

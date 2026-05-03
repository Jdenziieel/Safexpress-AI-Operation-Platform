"""supervisor-admin-pricing-update — PUT /admin/pricing/{model}"""
import os
import sys
from datetime import datetime

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
)
from shared.persistence_factory import get_log_storage


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()

    model = get_path_param(event, "model")
    if not model:
        return error_response(400, "model path parameter is required")

    body = parse_body(event)

    try:
        input_rate = float(body.get("input_rate_per_1k"))
        output_rate = float(body.get("output_rate_per_1k"))
    except (TypeError, ValueError):
        return error_response(400, "input_rate_per_1k and output_rate_per_1k are required floats")
    if input_rate <= 0 or output_rate <= 0:
        return error_response(400, "rates must be > 0")

    cached_raw = body.get("cached_input_rate_per_1k")
    try:
        cached_rate = float(cached_raw) if cached_raw is not None else None
    except (TypeError, ValueError):
        return error_response(400, "cached_input_rate_per_1k must be a float or null")
    if cached_rate is not None and cached_rate < 0:
        return error_response(400, "cached_input_rate_per_1k must be >= 0")

    storage = get_log_storage()
    with set_request_context_lambda(event):
        try:
            storage.update_model_pricing(
                model=model,
                input_rate=input_rate,
                output_rate=output_rate,
                cached_input_rate=cached_rate,
                updated_by="admin",
            )
            try:
                import logging_config as _lc  # type: ignore
                _lc._pricing_cache_ts = 0.0
            except Exception:
                pass
            return success_response({
                "model": model,
                "input_rate_per_1k": input_rate,
                "output_rate_per_1k": output_rate,
                "cached_input_rate_per_1k": cached_rate,
                "updated_at": datetime.utcnow().isoformat(),
                "notice": "Rate changes apply to future usage only. Historical costs are preserved.",
            })
        except Exception as e:
            return error_response(500, f"Error updating pricing: {e}")

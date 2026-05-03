"""supervisor-admin-pricing-list — GET /admin/pricing

Seeds Sup_ModelPricing on first call (idempotent: system_seed rows refresh,
admin-edited rows preserved). Returns merged pricing + usage stats for the dashboard.
"""
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
    set_request_context_lambda,
)
from shared.persistence_factory import get_log_storage


_SEED_PRICING = {
    # GPT-5.4 family — current flagship
    "gpt-5.4":       {"input": 0.0025,   "cached_input": 0.00025,  "output": 0.015},
    "gpt-5.4-mini":  {"input": 0.00075,  "cached_input": 0.000075, "output": 0.0045},
    "gpt-5.4-nano":  {"input": 0.0002,   "cached_input": 0.00002,  "output": 0.00125},
    "gpt-5.4-pro":   {"input": 0.03,     "cached_input": 0.03,     "output": 0.18},
    # GPT-5.2 / 5.1 refreshes
    "gpt-5.2":       {"input": 0.00175,  "cached_input": 0.000175, "output": 0.014},
    "gpt-5.2-pro":   {"input": 0.021,    "cached_input": 0.021,    "output": 0.168},
    "gpt-5.1":       {"input": 0.00125,  "cached_input": 0.000125, "output": 0.01},
    # GPT-5 launch family
    "gpt-5":         {"input": 0.00125,  "cached_input": 0.000125, "output": 0.01},
    "gpt-5-mini":    {"input": 0.00025,  "cached_input": 0.000025, "output": 0.002},
    "gpt-5-nano":    {"input": 0.00005,  "cached_input": 0.000005, "output": 0.0004},
    "gpt-5-pro":     {"input": 0.015,    "cached_input": 0.015,    "output": 0.12},
    # GPT-4.1 family
    "gpt-4.1":       {"input": 0.002,    "cached_input": 0.0005,   "output": 0.008},
    "gpt-4.1-mini":  {"input": 0.0004,   "cached_input": 0.0001,   "output": 0.0016},
    "gpt-4.1-nano":  {"input": 0.0001,   "cached_input": 0.000025, "output": 0.0004},
    # GPT-4o family
    "gpt-4o":        {"input": 0.0025,   "cached_input": 0.00125,  "output": 0.01},
    "gpt-4o-mini":   {"input": 0.00015,  "cached_input": 0.000075, "output": 0.0006},
    # Reasoning models
    "o1":            {"input": 0.015,    "cached_input": 0.0075,   "output": 0.06},
    "o1-pro":        {"input": 0.15,     "cached_input": 0.15,     "output": 0.6},
    "o1-mini":       {"input": 0.0011,   "cached_input": 0.00055,  "output": 0.0044},
    "o3":            {"input": 0.002,    "cached_input": 0.0005,   "output": 0.008},
    "o3-mini":       {"input": 0.0011,   "cached_input": 0.00055,  "output": 0.0044},
    "o3-pro":        {"input": 0.02,     "cached_input": 0.02,     "output": 0.08},
    "o4-mini":       {"input": 0.0011,   "cached_input": 0.000275, "output": 0.0044},
    # Legacy (no cache discount)
    "gpt-4":         {"input": 0.03,     "cached_input": 0.03,     "output": 0.06},
    "gpt-4-turbo":   {"input": 0.01,     "cached_input": 0.01,     "output": 0.03},
    "gpt-3.5-turbo": {"input": 0.0005,   "cached_input": 0.0005,   "output": 0.0015},
}


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()

    storage = get_log_storage()
    with set_request_context_lambda(event):
        try:
            seed_payload = {
                m: {"input": r["input"], "output": r["output"], "cached_input": r.get("cached_input")}
                for m, r in _SEED_PRICING.items()
            }
            storage.seed_model_pricing(seed_payload)
            rows = storage.get_all_model_pricing()
            token_stats = storage.get_token_usage_stats()
            by_model_map = {m["model"]: m for m in token_stats.get("by_model", [])}

            models = []
            for row in rows:
                usage = by_model_map.get(row["model"], {})
                models.append({
                    "model": row["model"],
                    "input_rate_per_1k": row["input_rate_per_1k"],
                    "output_rate_per_1k": row["output_rate_per_1k"],
                    "cached_input_rate_per_1k": row.get("cached_input_rate_per_1k"),
                    "updated_at": row["updated_at"],
                    "updated_by": row["updated_by"],
                    "total_input_tokens": usage.get("input_tokens", 0) or 0,
                    "total_output_tokens": usage.get("output_tokens", 0) or 0,
                    "total_cost_usd": round(usage.get("cost_usd", 0) or 0, 6),
                })

            return success_response({
                "models": models,
                "notice": (
                    "Rate changes apply to future usage only. Historical costs are preserved. "
                    "cached_input_rate_per_1k controls the OpenAI cache discount; leave null to use the hardcoded default."
                ),
            })
        except Exception as e:
            return error_response(500, f"Error retrieving pricing: {e}")

"""
Admin dashboard routes (Privacy-Safe).

Handles all /admin/* endpoints for system monitoring.
All responses have PII redaction applied — safe for admin viewing.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timedelta
from collections import defaultdict

from log_storage import LogStorage
from pii_redactor import PIIRedactor

_SEED_PRICING = {
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
}

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/logs")
async def get_admin_logs(
    level: Optional[str] = None,
    component: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    """
    Get logs with PII redaction for admin dashboard.

    This endpoint returns logs with all sensitive information redacted.
    Admins can see system activity without accessing user private data.

    Query Parameters:
        - level: Filter by log level (WARNING, ERROR, CRITICAL recommended for admins)
        - component: Filter by component
        - start_time: Filter logs after this time (ISO format)
        - end_time: Filter logs before this time (ISO format)
        - limit: Number of logs to return (default 100, max 500)
        - offset: Offset for pagination

    Returns:
        - logs: List of redacted log entries
        - total: Total count of matching logs
        - _privacy: Confirmation that data is redacted
    """
    try:
        storage = LogStorage()

        # Limit max results for admin dashboard
        limit = min(limit, 500)

        logs, total = storage.get_logs(
            level=level.upper() if level else None,
            component=component,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset
        )

        # Redact ALL logs before returning
        redacted_logs = [PIIRedactor.redact_log_entry(log, level='admin') for log in logs]

        return {
            "logs": redacted_logs,
            "total": total,
            "limit": limit,
            "offset": offset,
            "_privacy": {
                "pii_redacted": True,
                "redaction_level": "admin",
                "safe_for_admin_viewing": True
            }
        }

    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Module not available: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving admin logs: {str(e)}")


@router.get("/activity")
async def get_admin_activity(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    agent: Optional[str] = None,
    limit: int = 50
):
    """
    Get privacy-safe activity feed for admin dashboard.

    Shows WHAT happened (actions) without revealing WHO or WHAT content.
    Example: "Email Service: Sent an email" (no recipient, no subject)

    Query Parameters:
        - start_time: Filter after this time (ISO format)
        - end_time: Filter before this time (ISO format)
        - agent: Filter by agent name
        - limit: Number of activities to return (default 50, max 200)

    Returns:
        - activities: List of privacy-safe activity summaries
        - total: Total count
    """
    try:
        storage = LogStorage()
        limit = min(limit, 200)

        agent_calls = storage.get_agent_calls(
            agent_name=agent,
            start_time=start_time,
            end_time=end_time,
            limit=limit
        )

        # Create privacy-safe activity summaries
        activities = [
            PIIRedactor.create_admin_activity_summary(call)
            for call in agent_calls
        ]

        return {
            "activities": activities,
            "total": len(activities),
            "_privacy": {
                "pii_redacted": True,
                "content_hidden": True,
                "safe_for_admin_viewing": True
            }
        }

    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Module not available: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving activity: {str(e)}")


@router.get("/activity/summary")
async def get_admin_activity_summary(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    period: str = "24h"
):
    """
    Get aggregated activity summary for admin dashboard.

    Shows counts and statistics without any user data.
    Example: "Email Service: 24 emails sent, 15 read, 0 failed"

    Query Parameters:
        - start_time: Filter after this time (ISO format)
        - end_time: Filter before this time (ISO format)
        - period: Time period shorthand (1h, 24h, 7d, 30d) - used if no start/end

    Returns:
        - by_agent: Activity counts per agent
        - totals: Overall totals
    """
    try:
        storage = LogStorage()

        # Calculate time range from period if not specified
        if not start_time and not end_time:
            now = datetime.utcnow()
            period_map = {
                '1h': timedelta(hours=1),
                '24h': timedelta(hours=24),
                '7d': timedelta(days=7),
                '30d': timedelta(days=30),
            }
            delta = period_map.get(period, timedelta(hours=24))
            start_time = (now - delta).isoformat() + 'Z'

        # Get all agent calls for the period
        agent_calls = storage.get_agent_calls(
            start_time=start_time,
            end_time=end_time,
            limit=10000  # Get all for aggregation
        )

        # Create aggregated summary
        summary = PIIRedactor.create_activity_aggregation(agent_calls)
        summary['period'] = period
        summary['time_range'] = {
            'start': start_time,
            'end': end_time
        }
        summary['_privacy'] = {
            'pii_redacted': True,
            'aggregated_data_only': True,
            'safe_for_admin_viewing': True
        }

        return summary

    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Module not available: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving summary: {str(e)}")


@router.get("/health")
async def get_system_health(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None
):
    """
    Get system health status for admin dashboard.

    Returns overall system health based on success rates and response times.
    Uses traffic light system: healthy (green), degraded (yellow), unhealthy (red)

    Returns:
        - status: Overall status (healthy, degraded, unhealthy)
        - score: Health score 0-100
        - indicators: Individual health metrics
    """
    try:
        storage = LogStorage()

        # Default to last hour for health check
        if not start_time:
            start_time = (datetime.utcnow() - timedelta(hours=1)).isoformat() + 'Z'

        # Get agent calls for health calculation
        agent_calls = storage.get_agent_calls(
            start_time=start_time,
            end_time=end_time,
            limit=10000
        )

        # Get log counts for error tracking
        log_counts = storage.get_log_counts(start_time=start_time, end_time=end_time)

        # Calculate metrics
        total_calls = len(agent_calls)
        successful_calls = sum(1 for c in agent_calls if c.get('success'))
        failed_calls = total_calls - successful_calls

        success_rate = (successful_calls / total_calls * 100) if total_calls > 0 else 100

        avg_duration = (
            sum(c.get('duration_ms', 0) for c in agent_calls) / total_calls
            if total_calls > 0 else 0
        )

        error_count = log_counts.get('ERROR', 0) + log_counts.get('CRITICAL', 0)
        warning_count = log_counts.get('WARNING', 0)

        # Determine health status
        if success_rate >= 95 and avg_duration < 5000 and error_count == 0:
            status = 'healthy'
            score = 100
        elif success_rate >= 90 and avg_duration < 10000 and error_count <= 5:
            status = 'degraded'
            score = 75
        else:
            status = 'unhealthy'
            score = max(0, int(success_rate * 0.5))

        # Count healthy agents
        agents_status = {}
        for call in agent_calls:
            agent = call.get('agent_name', 'unknown')
            if agent not in agents_status:
                agents_status[agent] = {'total': 0, 'success': 0}
            agents_status[agent]['total'] += 1
            if call.get('success'):
                agents_status[agent]['success'] += 1

        agents_healthy = sum(
            1 for a in agents_status.values()
            if a['total'] > 0 and (a['success'] / a['total']) >= 0.9
        )
        agents_degraded = len(agents_status) - agents_healthy

        return {
            "status": status,
            "score": score,
            "indicators": {
                "success_rate": round(success_rate, 1),
                "avg_response_time_ms": round(avg_duration, 0),
                "error_count_1h": error_count,
                "warning_count_1h": warning_count,
                "total_actions_1h": total_calls,
                "agents_healthy": agents_healthy,
                "agents_degraded": agents_degraded,
            },
            "time_range": {
                "start": start_time,
                "end": end_time or datetime.utcnow().isoformat() + 'Z'
            },
            "last_updated": datetime.utcnow().isoformat() + 'Z'
        }

    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Module not available: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving health: {str(e)}")


@router.get("/alerts")
async def get_admin_alerts(
    hours: int = 1
):
    """
    Get active alerts for admin dashboard.

    Returns recent errors and warnings that need admin attention.

    Query Parameters:
        - hours: Look back period in hours (default 1, max 24)

    Returns:
        - alerts: List of alerts with severity and recommendations
        - summary: Count of errors and warnings
    """
    try:
        storage = LogStorage()
        hours = min(hours, 24)

        start_time = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + 'Z'

        # Get error and warning logs
        error_logs, _ = storage.get_logs(
            level='ERROR',
            start_time=start_time,
            limit=100
        )

        critical_logs, _ = storage.get_logs(
            level='CRITICAL',
            start_time=start_time,
            limit=100
        )

        warning_logs, _ = storage.get_logs(
            level='WARNING',
            start_time=start_time,
            limit=100
        )

        # Aggregate errors by component/agent
        error_groups = defaultdict(list)
        for log in error_logs + critical_logs:
            component = log.get('component', 'system')
            error_groups[component].append(log)

        # Create alerts
        alerts = []

        for component, logs in error_groups.items():
            agent_info = PIIRedactor.get_agent_friendly_name(component)

            # Determine severity
            critical_count = sum(1 for l in logs if l.get('level') == 'CRITICAL')
            severity = 'critical' if critical_count > 0 else 'high'

            # Generic alert message (no PII)
            if len(logs) == 1:
                message = f"{agent_info['name']} encountered an error"
            else:
                message = f"{agent_info['name']} encountered {len(logs)} errors"

            # Recommendation based on component
            recommendations = {
                'gmail': 'Check Gmail API credentials and quota',
                'calendar': 'Check Calendar API credentials',
                'gdocs': 'Check Google Docs API permissions',
                'sheets': 'Check Sheets API permissions',
                'gdrive': 'Check Drive API permissions',
                'llm': 'Check OpenAI API key and quota',
                'orchestrator': 'Review workflow configuration',
            }

            alerts.append({
                'type': 'error',
                'severity': severity,
                'icon': agent_info['icon'],
                'component': component,
                'component_friendly': agent_info['name'],
                'message': message,
                'count': len(logs),
                'first_occurred': logs[-1].get('timestamp') if logs else None,
                'last_occurred': logs[0].get('timestamp') if logs else None,
                'recommendation': recommendations.get(component, 'Review system logs'),
            })

        # Sort by severity and count
        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        alerts.sort(key=lambda x: (severity_order.get(x['severity'], 99), -x['count']))

        return {
            "alerts": alerts,
            "summary": {
                "critical_count": sum(1 for a in alerts if a['severity'] == 'critical'),
                "error_count": len(error_logs) + len(critical_logs),
                "warning_count": len(warning_logs),
                "time_period_hours": hours,
            },
            "time_range": {
                "start": start_time,
                "end": datetime.utcnow().isoformat() + 'Z'
            },
            "_privacy": {
                "pii_redacted": True,
                "error_details_hidden": True,
                "safe_for_admin_viewing": True
            }
        }

    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Module not available: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving alerts: {str(e)}")


# =========================================================================
# USAGE SUMMARY
# =========================================================================

@router.get("/usage/summary")
async def get_usage_summary():
    """
    Aggregated usage counts (conversations & requests) for today, this week,
    and this month.  Privacy-safe: only totals, no user-identifiable data.
    """
    try:
        storage = LogStorage()
        summary = storage.get_usage_summary()
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving usage summary: {str(e)}")


# =========================================================================
# MODEL PRICING
# =========================================================================

class PricingUpdate(BaseModel):
    input_rate_per_1k: float = Field(..., gt=0, description="Cost per 1 000 input tokens (USD)")
    output_rate_per_1k: float = Field(..., gt=0, description="Cost per 1 000 output tokens (USD)")


@router.get("/pricing")
async def get_pricing():
    """Return current per-model pricing rates."""
    try:
        storage = LogStorage()
        storage.seed_model_pricing(_SEED_PRICING)
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
                "updated_at": row["updated_at"],
                "updated_by": row["updated_by"],
                "total_input_tokens": usage.get("input_tokens", 0) or 0,
                "total_output_tokens": usage.get("output_tokens", 0) or 0,
                "total_cost_usd": round(usage.get("cost_usd", 0) or 0, 6),
            })

        return {
            "models": models,
            "notice": "Rate changes apply to future usage only. Historical costs are preserved."
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving pricing: {str(e)}")


@router.put("/pricing/{model}")
async def update_pricing(model: str, body: PricingUpdate):
    """Update input/output rate for a model. Only affects future cost computations."""
    try:
        storage = LogStorage()
        storage.update_model_pricing(
            model=model,
            input_rate=body.input_rate_per_1k,
            output_rate=body.output_rate_per_1k,
            updated_by="admin",
        )

        try:
            import logging_config as _lc
            _lc._pricing_cache_ts = 0.0
        except Exception:
            pass

        return {
            "model": model,
            "input_rate_per_1k": body.input_rate_per_1k,
            "output_rate_per_1k": body.output_rate_per_1k,
            "updated_at": datetime.utcnow().isoformat(),
            "notice": "Rate changes apply to future usage only. Historical costs are preserved."
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating pricing: {str(e)}")


# =========================================================================
# BUDGET SETTINGS
# =========================================================================

class BudgetUpdate(BaseModel):
    monthly_budget_usd: Optional[float] = Field(None, ge=0, description="Monthly budget cap in USD")
    alert_threshold_pct: Optional[float] = Field(None, ge=0, le=100, description="Alert when spend reaches this % of budget")


@router.get("/settings/budget")
async def get_budget():
    """Return the current monthly budget cap and alert threshold."""
    try:
        storage = LogStorage()
        budget_raw = storage.get_setting("monthly_budget_usd")
        threshold_raw = storage.get_setting("alert_threshold_pct")

        monthly_budget = float(budget_raw) if budget_raw else None
        alert_threshold = float(threshold_raw) if threshold_raw else 80.0

        month_start = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"
        token_stats = storage.get_token_usage_stats(start_time=month_start)
        current_month_cost = round(token_stats["totals"].get("total_cost_usd", 0) or 0, 4)

        over_budget = False
        alert_triggered = False
        if monthly_budget and monthly_budget > 0:
            pct_used = (current_month_cost / monthly_budget) * 100
            if pct_used >= 100:
                over_budget = True
            if pct_used >= alert_threshold:
                alert_triggered = True
        else:
            pct_used = 0.0

        return {
            "monthly_budget_usd": monthly_budget,
            "alert_threshold_pct": alert_threshold,
            "current_month_cost_usd": current_month_cost,
            "pct_used": round(pct_used, 1),
            "over_budget": over_budget,
            "alert_triggered": alert_triggered,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving budget: {str(e)}")


@router.put("/settings/budget")
async def update_budget(body: BudgetUpdate):
    """Update monthly budget cap and/or alert threshold."""
    try:
        storage = LogStorage()
        if body.monthly_budget_usd is not None:
            storage.set_setting("monthly_budget_usd", str(body.monthly_budget_usd))
        if body.alert_threshold_pct is not None:
            storage.set_setting("alert_threshold_pct", str(body.alert_threshold_pct))

        return await get_budget()

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating budget: {str(e)}")


# =========================================================================
# AGENT PERFORMANCE METRICS (with system-wide avg response time)
# =========================================================================

@router.get("/metrics")
async def get_admin_metrics(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    period: str = "24h"
):
    """
    Agent performance metrics plus system-wide average response time.

    Per-agent: success_rate, avg_response_time_ms, total_actions, failed_actions.
    System-wide: avg_response_time_ms from request_summaries (time from user
    input to system reply).

    Removed: overall_score, status_label, status_color, speed_score, speed_label.
    """
    try:
        storage = LogStorage()

        if not start_time and not end_time:
            now = datetime.utcnow()
            period_map = {
                '1h': timedelta(hours=1),
                '24h': timedelta(hours=24),
                '7d': timedelta(days=7),
                '30d': timedelta(days=30),
            }
            delta = period_map.get(period, timedelta(hours=24))
            start_time = (now - delta).isoformat() + 'Z'

        agent_calls = storage.get_agent_calls(
            start_time=start_time,
            end_time=end_time,
            limit=10000
        )

        agent_stats: dict = {}
        for call in agent_calls:
            agent = call.get('agent_name', 'unknown')
            if agent not in agent_stats:
                agent_stats[agent] = {
                    'total_calls': 0,
                    'successful_calls': 0,
                    'total_duration_ms': 0,
                }

            stats = agent_stats[agent]
            stats['total_calls'] += 1
            if call.get('success'):
                stats['successful_calls'] += 1
            stats['total_duration_ms'] += call.get('duration_ms', 0)

        agents_out = {}
        for agent, stats in agent_stats.items():
            total = stats['total_calls']
            successful = stats['successful_calls']
            success_rate = (successful / total * 100) if total > 0 else 0
            avg_duration = stats['total_duration_ms'] / total if total > 0 else 0

            agents_out[agent] = {
                'success_rate': round(success_rate, 1),
                'avg_response_time_ms': round(avg_duration, 0),
                'total_actions': total,
                'failed_actions': total - successful,
            }

        system_stats = storage.get_avg_response_time(
            start_time=start_time, end_time=end_time
        )

        return {
            'system': system_stats,
            'agents': agents_out,
            'period': period,
            'time_range': {
                'start': start_time,
                'end': end_time
            },
            '_privacy': {
                'pii_redacted': True,
                'aggregated_metrics_only': True,
                'safe_for_admin_viewing': True
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving metrics: {str(e)}")


# =========================================================================
# INTERNAL COMPONENT METRICS (Conversational + Supervisor layers)
# =========================================================================

_CONVERSATIONAL_TIERS = ("0.5", "1", "formatter", "memory")
_SUPERVISOR_TIERS = ("supervisor", "classifier", "orchestrator")


@router.get("/metrics/internal")
async def get_internal_metrics(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    period: str = "24h"
):
    """
    Internal component metrics derived from LLM calls grouped by tier.

    Returns two logical components:
    - conversational: tiers 0.5, 1, formatter, memory
    - supervisor: tiers supervisor, classifier, orchestrator
    """
    try:
        storage = LogStorage()

        if not start_time and not end_time:
            now = datetime.utcnow()
            period_map = {
                "1h": timedelta(hours=1),
                "24h": timedelta(hours=24),
                "7d": timedelta(days=7),
                "30d": timedelta(days=30),
            }
            delta = period_map.get(period, timedelta(hours=24))
            start_time = (now - delta).isoformat() + "Z"

        all_tiers = _CONVERSATIONAL_TIERS + _SUPERVISOR_TIERS
        placeholders = ",".join("?" for _ in all_tiers)
        time_filter = ""
        params: list = list(all_tiers)
        if start_time:
            time_filter += " AND timestamp >= ?"
            params.append(start_time)
        if end_time:
            time_filter += " AND timestamp <= ?"
            params.append(end_time)

        conn = storage._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT tier,
                   COUNT(*)                    AS total_calls,
                   SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_calls,
                   AVG(duration_ms)            AS avg_duration_ms,
                   SUM(total_tokens)           AS total_tokens,
                   SUM(estimated_cost_usd)     AS total_cost_usd
            FROM llm_calls
            WHERE tier IN ({placeholders}) {time_filter}
            GROUP BY tier
            """,
            params,
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()

        def _aggregate(tiers):
            matching = [r for r in rows if r["tier"] in tiers]
            total = sum(r["total_calls"] for r in matching)
            successful = sum(r["successful_calls"] for r in matching)
            tokens = sum(r["total_tokens"] or 0 for r in matching)
            cost = sum(r["total_cost_usd"] or 0 for r in matching)
            avg_ms = sum((r["avg_duration_ms"] or 0) * r["total_calls"] for r in matching) / total if total else 0
            return {
                "total_calls": total,
                "successful_calls": successful,
                "failed_calls": total - successful,
                "success_rate": round((successful / total * 100) if total > 0 else 0, 1),
                "avg_duration_ms": round(avg_ms, 0),
                "total_tokens": tokens,
                "total_cost_usd": round(cost, 6),
            }

        return {
            "conversational": _aggregate(_CONVERSATIONAL_TIERS),
            "supervisor": _aggregate(_SUPERVISOR_TIERS),
            "period": period,
            "time_range": {"start": start_time, "end": end_time},
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving internal metrics: {str(e)}")

"""
Admin dashboard routes (Privacy-Safe).

Handles all /admin/* endpoints for system monitoring.
All responses have PII redaction applied — safe for admin viewing.
"""

from fastapi import APIRouter, HTTPException
from typing import Optional
from datetime import datetime, timedelta
from collections import defaultdict

from log_storage import LogStorage
from pii_redactor import PIIRedactor

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


@router.get("/metrics")
async def get_admin_metrics(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    period: str = "24h"
):
    """
    Get agent performance metrics for admin dashboard.

    Returns performance scores with plain-language status labels.
    No user data is included.

    Query Parameters:
        - start_time: Filter from this time (ISO format)
        - end_time: Filter until this time (ISO format)
        - period: Time period shorthand (1h, 24h, 7d, 30d)

    Returns:
        - metrics: Performance metrics per agent with friendly labels
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

        # Get agent calls data
        agent_calls = storage.get_agent_calls(
            start_time=start_time,
            end_time=end_time,
            limit=10000
        )

        # Aggregate metrics per agent
        agent_stats = {}
        for call in agent_calls:
            agent = call.get('agent_name', 'unknown')
            if agent not in agent_stats:
                agent_stats[agent] = {
                    'total_calls': 0,
                    'successful_calls': 0,
                    'total_duration_ms': 0,
                    'durations': []
                }

            stats = agent_stats[agent]
            stats['total_calls'] += 1
            if call.get('success'):
                stats['successful_calls'] += 1
            duration = call.get('duration_ms', 0)
            stats['total_duration_ms'] += duration
            stats['durations'].append(duration)

        # Calculate performance scores with friendly labels
        metrics = {}
        for agent, stats in agent_stats.items():
            total = stats['total_calls']
            successful = stats['successful_calls']

            # Success rate
            success_rate = (successful / total * 100) if total > 0 else 0

            # Speed score
            avg_duration = stats['total_duration_ms'] / total if total > 0 else 0
            if avg_duration < 2000:
                speed_score = 100
                speed_label = 'Very Fast'
            elif avg_duration < 5000:
                speed_score = 85
                speed_label = 'Fast'
            elif avg_duration < 10000:
                speed_score = 70
                speed_label = 'Normal'
            else:
                speed_score = 50
                speed_label = 'Slow'

            # Overall score
            overall_score = (success_rate * 0.6) + (speed_score * 0.4)

            # Status label
            if overall_score >= 90:
                status_label = 'Working Great'
                status_color = 'green'
            elif overall_score >= 75:
                status_label = 'Working Well'
                status_color = 'blue'
            elif overall_score >= 50:
                status_label = 'Needs Attention'
                status_color = 'yellow'
            else:
                status_label = 'Having Issues'
                status_color = 'red'

            agent_info = PIIRedactor.get_agent_friendly_name(agent)

            metrics[agent] = {
                'agent': agent,
                'friendly_name': agent_info['name'],
                'icon': agent_info['icon'],
                'status_label': status_label,
                'status_color': status_color,
                'overall_score': round(overall_score, 1),
                'success_rate': round(success_rate, 1),
                'speed_score': round(speed_score, 1),
                'speed_label': speed_label,
                'avg_response_time_ms': round(avg_duration, 0),
                'avg_response_time_friendly': PIIRedactor.format_duration(avg_duration),
                'total_actions': total,
                'successful_actions': successful,
                'failed_actions': total - successful,
            }

        return {
            'metrics': metrics,
            'period': period,
            'time_range': {
                'start': start_time,
                'end': end_time
            },
            'agent_count': len(metrics),
            '_privacy': {
                'pii_redacted': True,
                'aggregated_metrics_only': True,
                'safe_for_admin_viewing': True
            }
        }

    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Module not available: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving metrics: {str(e)}")

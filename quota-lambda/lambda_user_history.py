"""
Lambda Function: quota-user-history
Token consumption history endpoint.

Routes (both wired to this same Lambda)
---------------------------------------
GET /api/quota/me/history
GET /api/quota/me/history?days=30&limit=200&include_resets=false
GET /api/quota/me/history?user_id=<target>      ← admin / staff only

Default behaviour: returns the SIGNED-IN caller's own UsageLogs rows
+ current-period summary. Used by the Profile page Token Consumption
panel.

Admin override (added 2026-05-01)
---------------------------------
If `?user_id=<target>` is present AND the caller's authorizer role
is `admin` or `staff`, the response is built for that target user
instead. This is what powers the Token Management → row → "View
History" modal. Non-admin callers are silently ignored — they see
their own data regardless of what they put in the query string,
preventing IDOR (?user_id=other → still locked to caller).

Auth model
----------
- `user_id` always comes from the authorizer context (NEVER the
  query string for normal users).
- Admin role check is the SAME predicate the other admin endpoints
  use: `authorizer.role.lower() in ('admin', 'staff')`.
- The response carries `viewing_user_id` and `viewer_user_id` so the
  frontend can detect when an admin is impersonating a view (and
  show a "viewing X's history" banner without trusting the URL).

DynamoDB Tables
---------------
- UserQuotas: Primary key = user_id  (current-period summary)
- UsageLogs:  Primary key = log_id   (history rows, scanned by user_id)
"""

import json
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource('dynamodb')
quotas_table = dynamodb.Table(os.environ.get('USER_QUOTAS_TABLE', 'UserQuotas'))
logs_table = dynamodb.Table(os.environ.get('USAGE_LOGS_TABLE', 'UsageLogs'))


def _user_id_from_event(event):
    """Pull the caller's user_id from the authorizer context.

    Mirrors kb-lambda/shared/response_utils.py::get_user_from_authorizer
    exactly — `user_id` is the JWT `user_id` claim that the Lambda
    Authorizer copies into context, and `principalId` is the same value
    written to the IAM policy. ALL UsageLogs rows are keyed by this
    string (chat_message → /quota/report → UsageLogs.user_id), so it
    is the one and only correct identifier here.

    DO NOT fall back to email / gmail. They are NOT user_ids — keying
    DDB by an email would silently return zero results for the legit
    caller, and a future user provisioned with `user_id == "x@y.com"`
    could be impersonated. The earlier draft of this helper had that
    fallback; it's removed deliberately.

    For the (currently unused) HTTP-API v2 JWT authorizer path, claims
    arrive under `requestContext.authorizer.jwt.claims.user_id` — also
    only `user_id` / `sub`, never email.
    """
    rc = event.get('requestContext', {}) or {}
    authorizer = rc.get('authorizer', {}) or {}

    # Lambda Authorizer (REST API v1) — what this stack actually uses.
    user_id = authorizer.get('user_id') or authorizer.get('principalId')
    if user_id:
        return str(user_id)

    # HTTP-API v2 JWT authorizer fallback (forward-compat; not active today).
    jwt_claims = (authorizer.get('jwt', {}) or {}).get('claims', {}) or {}
    user_id = jwt_claims.get('user_id') or jwt_claims.get('sub')
    if user_id:
        return str(user_id)

    return None


def _to_native(value, default=0):
    """Coerce DynamoDB Decimal / None to plain ints/floats for JSON."""
    if value is None:
        return default
    if isinstance(value, Decimal):
        # Preserve int-ness for token counts; floats for cost.
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


def _format_log(log):
    return {
        'id': log.get('log_id', ''),
        'service': log.get('service', ''),
        'operation': log.get('operation', ''),
        'model': log.get('model', ''),
        'tier': log.get('tier'),
        'input_tokens': int(_to_native(log.get('input_tokens'), 0)),
        'output_tokens': int(_to_native(log.get('output_tokens'), 0)),
        'total_tokens': int(_to_native(log.get('total_tokens'), 0)),
        'cached_tokens': int(_to_native(log.get('cached_tokens'), 0)) if log.get('cached_tokens') is not None else 0,
        'cost_usd': float(_to_native(log.get('cost_usd'), 0.0)),
        'duration_ms': float(_to_native(log.get('duration_ms'), 0.0)) if log.get('duration_ms') is not None else None,
        'success': bool(log.get('success', True)),
        'error': log.get('error'),
        'session_id': log.get('session_id'),
        'request_id': log.get('request_id'),
        'record_only': bool(log.get('record_only', False)),
        'timestamp': log.get('timestamp', ''),
    }


def lambda_handler(event, context):
    """Return the caller's own usage history + current-period summary."""

    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'GET,OPTIONS'
    }

    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers, 'body': ''}

    try:
        viewer_user_id = _user_id_from_event(event)
        if not viewer_user_id:
            return {
                'statusCode': 401,
                'headers': cors_headers,
                'body': json.dumps({'error': 'Authentication required'})
            }

        # Resolve the caller's role so we can decide whether the admin
        # override on `?user_id=` is allowed. Same role predicate the
        # other admin endpoints use (lambda_admin_list_users etc.).
        rc = event.get('requestContext', {}) or {}
        authorizer = rc.get('authorizer', {}) or {}
        viewer_role = (authorizer.get('role') or '').lower()
        is_admin = viewer_role in ('admin', 'staff')

        qp = event.get('queryStringParameters', {}) or {}

        # ── Target user_id resolution ────────────────────────────────
        # Admin override: only admins / staff may pass `?user_id=`. For
        # everyone else (including admins who omit the param) the
        # endpoint returns the caller's OWN history. This silently
        # ignores the param for non-admins instead of erroring so the
        # IDOR vector stays closed even on misconfigured frontends.
        requested_user_id = (qp.get('user_id') or '').strip()
        if requested_user_id and is_admin:
            target_user_id = requested_user_id
        else:
            target_user_id = viewer_user_id

        is_impersonation = (target_user_id != viewer_user_id)

        # Query parameters (all optional). days clamped to [1, 365] to
        # bound the scan; limit clamped to [1, 500].
        try:
            days = int(qp.get('days', 30))
        except (TypeError, ValueError):
            days = 30
        days = max(1, min(days, 365))

        # `limit` is the legacy single-page cap kept for backward compat
        # with older frontends. New callers should use `page` + `page_size`.
        # When both are present, page/page_size win.
        try:
            limit = int(qp.get('limit', 200))
        except (TypeError, ValueError):
            limit = 200
        limit = max(1, min(limit, 500))

        # Real backend pagination (Option B). `page` is 1-based; `page_size`
        # is bounded so a malicious caller can't request page_size=10000
        # and force us to ship a 5MB JSON body. The aggregate fields
        # (totals/by_service/by_day) are always computed across the full
        # window — only `logs` is paginated.
        try:
            page = int(qp.get('page', 1))
        except (TypeError, ValueError):
            page = 1
        page = max(1, page)

        try:
            page_size = int(qp.get('page_size', 25))
        except (TypeError, ValueError):
            page_size = 25
        page_size = max(5, min(page_size, 100))

        # If the caller sent ?page or ?page_size, honour them; otherwise
        # fall back to the legacy single-page slice via `limit`.
        use_pagination = ('page' in qp) or ('page_size' in qp)

        include_resets = (qp.get('include_resets', 'true').lower() != 'false')

        now = datetime.now(timezone.utc)
        window_start_iso = (now - timedelta(days=days)).isoformat()

        # --- Current-period summary (always included) -----------------
        # Also captures `fullname` so the admin modal can title the
        # view ("History — Joel D'Mello") without an extra round-trip
        # to /quota/admin/user/{id}.
        summary = None
        target_fullname = ''
        try:
            quota_item = quotas_table.get_item(Key={'user_id': target_user_id}).get('Item')
            if quota_item:
                monthly_limit = int(_to_native(quota_item.get('monthly_limit'), 100000))
                current_usage = int(_to_native(quota_item.get('current_usage'), 0))
                reset_date = quota_item.get('reset_date', '')
                target_fullname = quota_item.get('fullname', '') or ''
                summary = {
                    'tier': quota_item.get('tier', 'free'),
                    'monthly_limit': monthly_limit,
                    'current_usage': current_usage,
                    'current_cost_usd': float(_to_native(quota_item.get('current_cost_usd'), 0.0)),
                    'percentage_used': round(current_usage / monthly_limit * 100, 1) if monthly_limit > 0 else 0,
                    'remaining_tokens': max(0, monthly_limit - current_usage),
                    'reset_date': reset_date,
                    'is_active': quota_item.get('is_active', True),
                    'fullname': target_fullname,
                }
        except Exception as e:
            print(f"[user-history] summary fetch failed for {target_user_id}: {e}")

        # If admin requested a user that doesn't exist, fail loud rather
        # than silently returning empty data — this is what the modal
        # surfaces as an inline error.
        if is_impersonation and summary is None:
            return {
                'statusCode': 404,
                'headers': cors_headers,
                'body': json.dumps({'error': f'User {target_user_id} not found'})
            }

        # --- History rows ---------------------------------------------
        # FilterExpression on a Scan is the only option without a GSI;
        # bounded by the time window (days param) and the in-memory
        # `limit` slice so cost stays predictable for steady-state users.
        # If you later add a GSI on user_id+timestamp, swap this for a
        # Query.
        filter_expr = Attr('user_id').eq(target_user_id) & Attr('timestamp').gte(window_start_iso)
        if not include_resets:
            filter_expr = filter_expr & (Attr('operation').ne('auto_reset') & Attr('operation').ne('admin_reset'))

        all_logs = []
        scan_kwargs = {'FilterExpression': filter_expr}
        response = logs_table.scan(**scan_kwargs)
        all_logs.extend(response.get('Items', []))
        # Cap pagination depth so a runaway scan can't exhaust the
        # function timeout; in practice 30 days of one user's traffic
        # fits in a single page.
        max_pages = 10
        pages = 1
        while 'LastEvaluatedKey' in response and pages < max_pages:
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
            response = logs_table.scan(**scan_kwargs)
            all_logs.extend(response.get('Items', []))
            pages += 1

        all_logs.sort(key=lambda r: r.get('timestamp', ''), reverse=True)

        # Slice for the current page (or legacy limit). Aggregates below
        # still iterate over `all_logs` so totals stay correct regardless
        # of which page the client is on.
        if use_pagination:
            start = (page - 1) * page_size
            end = start + page_size
            page_logs = all_logs[start:end]
        else:
            page_logs = all_logs[:limit]

        # --- Aggregates over the returned window ----------------------
        agg_input = 0
        agg_output = 0
        agg_cached = 0
        agg_total = 0
        agg_cost = 0.0
        billable_total = 0
        billable_cost = 0.0
        per_service = {}
        per_day = {}
        for log in all_logs:
            input_t = int(_to_native(log.get('input_tokens'), 0))
            output_t = int(_to_native(log.get('output_tokens'), 0))
            cached_t = int(_to_native(log.get('cached_tokens'), 0))
            total_t = int(_to_native(log.get('total_tokens'), 0)) or (input_t + output_t)
            cost = float(_to_native(log.get('cost_usd'), 0.0))
            service = log.get('service', 'unknown') or 'unknown'
            ts = log.get('timestamp', '') or ''
            day_key = ts[:10] if len(ts) >= 10 else 'unknown'
            record_only = bool(log.get('record_only', False))
            operation = log.get('operation', '')

            agg_input += input_t
            agg_output += output_t
            agg_cached += cached_t
            agg_total += total_t
            agg_cost += cost

            # "Billable" excludes record_only audit rows (PDF parsing
            # and similar) and reset snapshots (which are book-keeping,
            # not user-driven consumption).
            if not record_only and operation not in ('auto_reset', 'admin_reset'):
                billable_total += total_t
                billable_cost += cost

            svc = per_service.setdefault(service, {
                'service': service, 'total_tokens': 0, 'cost_usd': 0.0, 'calls': 0
            })
            svc['total_tokens'] += total_t
            svc['cost_usd'] += cost
            svc['calls'] += 1

            day = per_day.setdefault(day_key, {
                'date': day_key, 'total_tokens': 0, 'cost_usd': 0.0, 'calls': 0
            })
            day['total_tokens'] += total_t
            day['cost_usd'] += cost
            day['calls'] += 1

        per_service_list = sorted(
            (
                {**v, 'cost_usd': round(v['cost_usd'], 4)}
                for v in per_service.values()
            ),
            key=lambda r: r['total_tokens'], reverse=True
        )
        per_day_list = sorted(
            (
                {**v, 'cost_usd': round(v['cost_usd'], 4)}
                for v in per_day.values()
            ),
            key=lambda r: r['date']
        )

        # ── Per-surface activity counts (added 2026-05-03) ─────────────
        # The admin-wide LogsPage already shows these via /admin/usage/summary
        # (which scans Sup_RequestSummaries). For the per-user Profile page
        # and the per-user Token Consumption History modal we don't need a
        # second backend table — every LLM call already carries request_id
        # + session_id, so the same UsageLogs scan we just did gives us
        # exact-match counts:
        #
        #   - request_id   → unique user-message turns (a "request")
        #   - session_id   → unique threads / KB sessions (a "conversation")
        #
        # Two surfaces are tracked separately because the user thinks of
        # them as distinct products in the UI (sidebar shows AI Assistant
        # and SFX Bot as different items). Service-tag mapping:
        #   - AI Assistant → service == 'supervisor'
        #     (set in AA-lambda/shared/logging_config.py:342 fallback +
        #      every AA-lambda Lambda whose SERVICE_NAME env is unset
        #      or set to "supervisor")
        #   - SFXBot       → service in {'knowledge-base', 'knowledge_base'}
        #     (set in kb-lambda/functions/ws_chat_stream/lambda_ws_chat_stream.py:455
        #      hardcoded; the underscore variant is a legacy spelling
        #      kept here for backfill safety — newer rows are all the
        #      hyphenated form)
        #
        # The agent-* services (supervisor-agent-gmail / docs / mapping)
        # are NOT counted in either bucket — they're transitive sub-LLM
        # calls inside an AI Assistant turn, so counting them as their
        # own conversations would inflate the AI Assistant numbers.
        # Service labels palette: Frontend/src/components/QuotaPage.jsx
        # :HISTORY_SERVICE_LABELS.
        SURFACE_SERVICES = {
            'ai_assistant': {'supervisor'},
            'sfxbot':       {'knowledge-base', 'knowledge_base'},
        }
        window_starts = {
            'today':      (now - timedelta(hours=24)).isoformat(),
            'this_week':  (now - timedelta(days=7)).isoformat(),
            'this_month': (now - timedelta(days=30)).isoformat(),
        }
        # Pre-allocate the empty buckets so a user with zero traffic on
        # a surface still gets {requests: 0, conversations: 0} fields
        # (the frontend renders the panel unconditionally — see
        # Profile/Modal "always rendered when the field is present"
        # comment).
        request_ids = {
            surface: {win: set() for win in window_starts}
            for surface in SURFACE_SERVICES
        }
        session_ids = {
            surface: {win: set() for win in window_starts}
            for surface in SURFACE_SERVICES
        }

        for log in all_logs:
            svc = (log.get('service') or '')
            if bool(log.get('record_only', False)):
                continue
            # Map service tag → surface bucket (or skip if neither).
            surface = None
            for s, services in SURFACE_SERVICES.items():
                if svc in services:
                    surface = s
                    break
            if surface is None:
                continue
            rid = log.get('request_id')
            sid = log.get('session_id')
            ts = log.get('timestamp', '') or ''
            for win, start in window_starts.items():
                if ts >= start:
                    if rid:
                        request_ids[surface][win].add(rid)
                    if sid:
                        session_ids[surface][win].add(sid)

        def _activity_for(surface: str) -> dict:
            return {
                win: {
                    'requests':      len(request_ids[surface][win]),
                    'conversations': len(session_ids[surface][win]),
                }
                for win in ('today', 'this_week', 'this_month')
            }

        ai_assistant_activity = _activity_for('ai_assistant')
        sfxbot_activity = _activity_for('sfxbot')

        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'user_id': target_user_id,
                # Identity context for the frontend: who is viewing vs
                # whose data is being shown. The modal banner uses
                # is_impersonation to render "Viewing X's history (you
                # are admin Y)". Don't trust the URL for this — the
                # backend is the source of truth.
                'viewer_user_id': viewer_user_id,
                'is_impersonation': is_impersonation,
                'window_days': days,
                'window_start': window_start_iso,
                'as_of': now.isoformat(),
                'summary': summary,
                'totals': {
                    'input_tokens': agg_input,
                    'output_tokens': agg_output,
                    'cached_tokens': agg_cached,
                    'total_tokens': agg_total,
                    'billable_tokens': billable_total,
                    'cost_usd': round(agg_cost, 4),
                    'billable_cost_usd': round(billable_cost, 4),
                    'call_count': len(all_logs),
                },
                'by_service': per_service_list,
                'by_day': per_day_list,
                # Per-user AI Assistant activity counts. Always present (the
                # frontend gates on the response shape, not a feature flag).
                # The window keys mirror /admin/usage/summary so the UI can
                # render the same StatsCard layout in the per-user modal /
                # profile panel.
                'ai_assistant_activity': ai_assistant_activity,
                'sfxbot_activity': sfxbot_activity,
                'logs': [_format_log(log) for log in page_logs],
                'logs_returned': len(page_logs),
                'logs_total_in_window': len(all_logs),
                # `truncated` retained for backward compat — true when
                # the caller is on the legacy `limit` path AND there are
                # more rows in the window than the slice contains.
                'truncated': (not use_pagination) and len(all_logs) > len(page_logs),
                # New pagination block. Always emitted so frontends can
                # detect support without sniffing the request mode. When
                # the client used the legacy `limit` path we still report
                # accurate `total` + a synthetic single-page view so
                # newer code can render pagination controls uniformly.
                'pagination': {
                    'page': page if use_pagination else 1,
                    'page_size': page_size if use_pagination else min(limit, len(all_logs) or 1),
                    'total': len(all_logs),
                    'total_pages': (
                        max(1, (len(all_logs) + page_size - 1) // page_size)
                        if use_pagination
                        else 1
                    ),
                    'has_more': (
                        use_pagination and (page * page_size) < len(all_logs)
                    ),
                    # Echo the mode so the client can defensively detect
                    # whether pagination actually took effect.
                    'mode': 'paginated' if use_pagination else 'legacy_limit',
                },
            })
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Failed to load history: {str(e)}'})
        }

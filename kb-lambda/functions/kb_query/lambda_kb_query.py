"""
Lambda function for KB query endpoint.
POST /kb/query - Query knowledge base with AI-generated answer

Quota integration mirrors chat_message and ws_chat_stream so EVERY LLM call
across the SFXchatbot surface is recorded in the quota service and KB_Logs:

  1. Pre-flight `/quota/check` at the start — blocks only when the user has
     ZERO tokens left. If they have any tokens we let the call proceed even
     if the LLM might overshoot the remaining balance — actual usage is
     reported by `/quota/report` afterwards and the next request will be
     blocked at this same gate.

  2. `rerank_chunks` returns its own usage dict; we sum it with the
     `generate_kb_answer` usage so the single `/quota/report` call captures
     the full cost of the request.

  3. Guardrail blocks (prompt injection, profanity, weapons, etc.) and
     quota blocks render as a friendly assistant turn (HTTP 200 with an
     `answer` field) instead of an HTTP 400 error. Frontend can detect
     blocks via the top-level `was_blocked` flag.
"""
import sys
import os
import time
import httpx

# Add shared modules to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.response_utils import (
    success_response, error_response, unauthorized_response,
    server_error_response, options_response, parse_body,
    validation_error_response, get_user_from_authorizer
)
from shared.weaviate_utils import hybrid_search, close_weaviate_client
from shared.openai_utils import generate_kb_answer, rerank_chunks
from shared.db_utils import save_log
from shared.guardrails import ChatGuardrails, GuardrailResult
from shared.service_jwt import service_auth_headers

# Quota service configuration. Env vars set on the Lambda; if not configured
# we fail open (no enforcement, but still no errors) so dev / preview
# deployments without a quota service keep working.
QUOTA_SERVICE_URL = os.environ.get('QUOTA_SERVICE_URL', '')
QUOTA_ENABLED = os.environ.get('QUOTA_ENABLED', 'true').lower() == 'true'


def check_quota(user_id: str, estimated_tokens: int = 1) -> dict:
    """Pre-flight quota check.

    SFXchatbot policy: pass `estimated_tokens=1` so `allowed=true` iff the
    user has AT LEAST one token left. We don't refuse a request just
    because the worst-case estimate doesn't fit — let the call run, the
    actual usage is recorded by `report_usage`, and the next request hits
    the gate.

    Fails open on transient errors so a quota-service hiccup doesn't kill
    the chat surface.
    """
    if not QUOTA_ENABLED or not QUOTA_SERVICE_URL:
        return {'allowed': True, 'remaining_tokens': float('inf')}

    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(
                f"{QUOTA_SERVICE_URL}/quota/check",
                json={
                    'user_id': user_id,
                    'estimated_tokens': estimated_tokens,
                    'service': 'knowledge-base',
                    'operation': 'kb_query',
                },
                headers=service_auth_headers('kb-query'),
            )

            if response.status_code == 404:
                # User not provisioned in UserQuotas. Treat as deactivated
                # so the caller renders the friendly account-deactivated
                # turn (better UX than "user not found").
                raise Exception("Your account has been deactivated. Please contact an administrator.")

            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise Exception("Your account has been deactivated. Please contact an administrator.")
        raise
    except Exception as e:
        print(f"[KB Query] Quota check warning (failing open): {e}")
        return {'allowed': True, 'remaining_tokens': 0}


def report_usage(user_id: str, usage: dict, *,
                 request_id: str = None, duration_ms: float = None,
                 success: bool = True, error: str = None,
                 prompt_summary: str = None,
                 metadata: dict = None):
    """Report token usage to quota service (always called after an LLM call).

    Schema-aligned with supervisor-agent `llm_calls`:
      - `input_tokens` INCLUDES `cached_tokens` (cached is a subset that
        gets the discounted rate; the quota service applies the discount
        server-side in its own estimate_cost).

    `metadata` ships per-LLM-stage breakdown (rerank vs answer model/tokens/
    cost) so /quota/admin/logs has the same per-stage transparency KB_Logs
    has.

    Wraps in try/except internally — quota-service failures should never
    propagate to the user.
    """
    if not QUOTA_ENABLED or not QUOTA_SERVICE_URL:
        return

    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(
                f"{QUOTA_SERVICE_URL}/quota/report",
                json={
                    'user_id': user_id,
                    'service': 'knowledge-base',
                    'operation': 'kb_query',
                    'tier': 'chat',
                    'model': usage.get('model', 'unknown'),
                    'input_tokens': int(usage.get('input_tokens', 0) or 0),
                    'output_tokens': int(usage.get('output_tokens', 0) or 0),
                    'cached_tokens': int(usage.get('cached_tokens', 0) or 0),
                    'cost_usd': float(usage.get('cost_usd', 0.0) or 0.0),
                    'duration_ms': float(duration_ms) if duration_ms is not None else None,
                    'success': bool(success),
                    'error': error,
                    'prompt_summary': (prompt_summary or '')[:200] if prompt_summary else None,
                    'request_id': request_id,
                    'metadata': metadata,
                },
                headers=service_auth_headers('kb-query'),
            )
            # Loud failure: 401/4xx/5xx surface as warnings instead of
            # the 3-month silent drop we just diagnosed.
            response.raise_for_status()
    except Exception as e:
        print(f"[KB Query] Usage report warning: {e}")


def _friendly_block_response(query: str, friendly: str, reason: str,
                             start_time: float):
    """Build a HTTP 200 response that renders as a friendly assistant turn.

    Used for guardrail blocks, quota blocks, and account-deactivated paths
    so the frontend doesn't see a red error toast for what should be a
    user-friendly explanation.
    """
    return success_response({
        'success': True,
        'query': query,
        'answer': friendly,
        'sources': [],
        'metadata': {
            'result_count': 0,
            'chunks_used': 0,
        },
        'usage': {
            'input_tokens': 0,
            'output_tokens': 0,
            'total_tokens': 0,
            'cost_usd': 0,
            'model': 'none',
        },
        'duration_ms': (time.time() - start_time) * 1000,
        'was_blocked': True,
        'block_reason': reason,
    })


def lambda_handler(event, context):
    """
    Query knowledge base and generate AI answer.

    Request body:
    {
        "query": "Your question here",
        "document_filter": ["doc_id_1", "doc_id_2"],  // optional
        "max_sources": 5,  // optional, default 5
        "include_sources": true  // optional, default true
    }
    """
    if event.get('requestContext', {}).get('http', {}).get('method') == 'OPTIONS':
        return options_response()

    start_time = time.time()
    query = ''  # Defined early so error handler can include it on failure

    try:
        try:
            user = get_user_from_authorizer(event)
            user_id = user['user_id']
        except Exception as e:
            return unauthorized_response(str(e))

        body = parse_body(event)
        query = body.get('query', '').strip()
        if not query:
            return validation_error_response("Query is required")

        # ── INPUT GUARDRAILS ──────────────────────────────────────────────
        # `block_off_topic=True` keeps REST + WebSocket policy aligned. The
        # OFF_TOPIC_PATTERNS list is hard-line only (weapons, system intrusion);
        # soft cases (code/poems/opinions) are handled by the LLM SCOPE clause
        # in the system prompt. Profanity / targeted abuse is checked always.
        guardrails = ChatGuardrails(strict_mode=True, block_off_topic=True)
        input_check = guardrails.check_input(query, user_id=user_id)
        if input_check.result == GuardrailResult.BLOCKED:
            print(f"[KB Query] Blocked by guardrails: {input_check.reason}")
            friendly = input_check.message or (
                "I can only help with knowledge base questions. "
                "What would you like to ask?"
            )
            return _friendly_block_response(
                query, friendly, input_check.reason, start_time
            )

        # ── QUOTA CHECK (SFXchatbot policy) ──────────────────────────────
        # Block ONLY when remaining_tokens == 0. Mid-call overshoot is
        # allowed (the LLM completes, actual usage is reported, the next
        # request hits the gate).
        try:
            quota_check_result = check_quota(user_id, estimated_tokens=1)
            if not quota_check_result.get('allowed', True):
                friendly = (
                    "You've used up your monthly token budget. "
                    "Your quota will reset on " +
                    str(quota_check_result.get('resets_at', 'the next billing date')) +
                    ". Please contact an administrator if you need it raised."
                )
                return _friendly_block_response(
                    query, friendly, 'quota_exhausted', start_time
                )
        except Exception as e:
            if "deactivated" in str(e).lower():
                friendly = (
                    "Your account has been deactivated. "
                    "Please contact an administrator to restore access."
                )
                return _friendly_block_response(
                    query, friendly, 'account_deactivated', start_time
                )
            # Other quota errors: fail open (already logged in check_quota)

        document_filter = body.get('document_filter', [])
        max_sources = body.get('max_sources', 5)
        include_sources = body.get('include_sources', True)

        print(f"[KB Query] User: {user_id}, Query: {query[:100]}...")

        # Step 1: Search Weaviate (BYO vectors — query embedded inside
        # hybrid_search via openai_utils.embed_texts). Pass user_id +
        # request_id so embedding tokens are recorded in UsageLogs as
        # tier='embedding', record_only=True (audit row, no deduction).
        print("[KB Query] Searching Weaviate...")
        search_results = hybrid_search(
            query=query,
            limit=50,
            alpha=0.7,
            doc_filter=document_filter if document_filter else None,
            user_id=user_id,
            request_id=event.get('requestContext', {}).get('requestId'),
        )

        # Per-stage usage so the single quota_report at the end captures
        # ALL LLM calls (rerank + answer), not just the main answer call.
        rerank_usage = {
            'input_tokens': 0, 'output_tokens': 0, 'cached_tokens': 0,
            'total_tokens': 0, 'cost_usd': 0.0, 'model': 'none',
        }
        usage = {
            'input_tokens': 0, 'output_tokens': 0, 'cached_tokens': 0,
            'total_tokens': 0, 'cost_usd': 0.0, 'model': 'none',
        }

        if not search_results:
            answer = "I couldn't find any relevant information in the knowledge base for your query."
            sources = []
            top_chunks = []
        else:
            print(f"[KB Query] Found {len(search_results)} initial results")

            # Step 2: Rerank (LLM call) — capture usage so it rolls into report
            print("[KB Query] Reranking results...")
            reranked, rerank_usage = rerank_chunks(query, search_results, top_n=max_sources)
            top_chunks = [chunk for chunk, score in reranked]

            print(f"[KB Query] Using top {len(top_chunks)} chunks for answer generation")

            # Step 3: Generate answer (LLM call)
            print("[KB Query] Generating answer...")
            answer, sources, usage = generate_kb_answer(
                query=query,
                context_chunks=top_chunks
            )

        # Layer 4 output guardrail — strip leak markers, mask PII, block on
        # sensitive-data leaks. Runs on both no-results and real-answer paths.
        output_check = guardrails.check_output(answer)
        if output_check.result == GuardrailResult.BLOCKED:
            print(f"[KB Query] Output blocked: {output_check.reason}")
            answer = output_check.message or (
                "I found information I shouldn't share. Please rephrase your question."
            )
        elif output_check.result == GuardrailResult.MODIFIED:
            print("[KB Query] Output sanitized (PII / leak markers removed)")
            answer = output_check.sanitized

        # Calculate duration once for both report_usage and save_log
        duration_ms = (time.time() - start_time) * 1000

        # Sum rerank + answer usage. Per supervisor-agent guide §1:
        # input_tokens INCLUDES cached_tokens (cached is a subset that gets
        # the discounted rate). Summing matches the same convention.
        combined_usage = {
            'input_tokens': int(usage.get('input_tokens', 0) or 0)
                          + int(rerank_usage.get('input_tokens', 0) or 0),
            'output_tokens': int(usage.get('output_tokens', 0) or 0)
                           + int(rerank_usage.get('output_tokens', 0) or 0),
            'cached_tokens': int(usage.get('cached_tokens', 0) or 0)
                           + int(rerank_usage.get('cached_tokens', 0) or 0),
            'cost_usd': float(usage.get('cost_usd', 0.0) or 0.0)
                      + float(rerank_usage.get('cost_usd', 0.0) or 0.0),
            'model': usage.get('model', 'unknown'),
        }
        combined_usage['total_tokens'] = (
            combined_usage['input_tokens'] + combined_usage['output_tokens']
        )

        print(f"[KB Query] Answer generated. Total tokens: {combined_usage['total_tokens']} "
              f"(answer={usage.get('total_tokens', 0)}, "
              f"rerank={rerank_usage.get('total_tokens', 0)}), "
              f"cost: ${combined_usage['cost_usd']:.6f}")

        # ── REPORT USAGE TO QUOTA SERVICE (mandatory after every LLM call) ─
        # Reports the SUM of rerank + answer tokens. The quota service may
        # push the user's balance to 0 or negative — that's fine, the next
        # request gets blocked at the pre-flight gate.
        # `metadata` ships per-LLM-stage breakdown so /quota/admin/logs can
        # show "rerank cost X, answer cost Y" the same way KB_Logs does.
        try:
            report_usage(
                user_id,
                combined_usage,
                request_id=event.get('requestContext', {}).get('requestId'),
                duration_ms=duration_ms,
                success=True,
                prompt_summary=query[:200],
                metadata={
                    'stages': {
                        'rerank': {
                            'model': rerank_usage.get('model'),
                            'input_tokens': int(rerank_usage.get('input_tokens', 0) or 0),
                            'output_tokens': int(rerank_usage.get('output_tokens', 0) or 0),
                            'cached_tokens': int(rerank_usage.get('cached_tokens', 0) or 0),
                            'total_tokens': int(rerank_usage.get('total_tokens', 0) or 0),
                            'cost_usd': float(rerank_usage.get('cost_usd', 0.0) or 0.0),
                        },
                        'answer': {
                            'model': usage.get('model'),
                            'input_tokens': int(usage.get('input_tokens', 0) or 0),
                            'output_tokens': int(usage.get('output_tokens', 0) or 0),
                            'cached_tokens': int(usage.get('cached_tokens', 0) or 0),
                            'total_tokens': int(usage.get('total_tokens', 0) or 0),
                            'cost_usd': float(usage.get('cost_usd', 0.0) or 0.0),
                        },
                    },
                    'chunks_used': len(sources) if sources else 0,
                    'query_length': len(query),
                    'answer_length': len(answer or ''),
                },
            )
        except Exception as e:
            print(f"[KB Query] Usage report warning: {e}")

        # ── ANALYTICS LOG ────────────────────────────────────────────────
        # Same shape as chat_message + ws_chat_stream so analytics queries
        # can union all three sources cleanly.
        try:
            save_log('chat', {
                'operation': 'kb_query',
                'tier': 'chat',
                'model': usage.get('model'),
                'rerank_model': rerank_usage.get('model'),
                'user_id_hash': hash(user_id) % 10000000,
                'query_length': len(query),
                'answer_length': len(answer),
                'chunks_retrieved': len(search_results),
                'chunks_used': len(top_chunks),
                'tokens_used': combined_usage['total_tokens'],
                'input_tokens': combined_usage['input_tokens'],
                'output_tokens': combined_usage['output_tokens'],
                'cached_tokens': combined_usage['cached_tokens'],
                'cost_usd': combined_usage['cost_usd'],
                'rerank_tokens': int(rerank_usage.get('total_tokens', 0) or 0),
                'rerank_cost_usd': float(rerank_usage.get('cost_usd', 0.0) or 0.0),
                'answer_tokens': int(usage.get('total_tokens', 0) or 0),
                'answer_cost_usd': float(usage.get('cost_usd', 0.0) or 0.0),
                'duration_ms': duration_ms,
                'prompt_summary': query[:200],
                'success': True,
            })
        except Exception as e:
            print(f"[KB Query] Logging warning: {e}")

        from datetime import datetime
        response_data = {
            'success': True,
            'query': query,
            'answer': answer,
            'metadata': {
                'result_count': len(search_results),
                'chunks_used': len(top_chunks),
                'generated_at': datetime.now().isoformat(),
                'max_sources': max_sources,
            },
            'usage': {
                'input_tokens': combined_usage['input_tokens'],
                'output_tokens': combined_usage['output_tokens'],
                'cached_tokens': combined_usage['cached_tokens'],
                'total_tokens': combined_usage['total_tokens'],
                'cost_usd': combined_usage['cost_usd'],
                'model': combined_usage['model'],
            },
            'duration_ms': duration_ms,
        }

        if include_sources:
            response_data['sources'] = sources

        return success_response(response_data)

    except Exception as e:
        print(f"[KB Query] Error: {e}")
        import traceback
        traceback.print_exc()

        # Per supervisor-agent guide invariant §8.5 — always log failures
        # with the same shape as success (minus the token split) so analytics
        # can compute success rates per operation.
        try:
            save_log('chat', {
                'operation': 'kb_query',
                'tier': 'chat',
                'duration_ms': (time.time() - start_time) * 1000,
                'prompt_summary': query[:200] if query else None,
                'success': False,
                'error': str(e),
            })
        except Exception:
            pass

        return server_error_response(str(e))

    finally:
        try:
            close_weaviate_client()
        except Exception:
            pass

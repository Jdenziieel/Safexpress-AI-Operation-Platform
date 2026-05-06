"""
Lambda function for chat message processing.
POST /chat/message - Send a message and get AI response

Matches original knowledge-base/api/chat_routes.py and services/chat_service.py
with guardrails, query enhancement, and full chat pipeline.
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
    validation_error_response, forbidden_response, get_user_from_authorizer
)
from shared.db_utils import (
    get_session, save_message, get_session_messages, save_log,
    update_session_metadata
)
from shared.weaviate_utils import hybrid_search, close_weaviate_client
from shared.openai_utils import generate_kb_answer, rerank_chunks
from shared.guardrails import ChatGuardrails, GuardrailResult, enhance_query
from shared.service_jwt import service_auth_headers

# Quota service configuration
QUOTA_SERVICE_URL = os.environ.get('QUOTA_SERVICE_URL', '')
QUOTA_ENABLED = os.environ.get('QUOTA_ENABLED', 'true').lower() == 'true'


def check_quota(user_id: str, estimated_tokens: int = 0) -> dict:
    """Check user quota with quota service."""
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
                    'operation': 'chat'
                },
                headers=service_auth_headers('kb-chat-message'),
            )
            
            if response.status_code == 404:
                raise Exception("User not found or deactivated")
            
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise Exception("Your account has been deactivated. Please contact an administrator.")
        raise
    except Exception as e:
        print(f"Quota check warning: {e}")
        # Allow on quota service error (fail open)
        return {'allowed': True, 'remaining_tokens': 0}


def report_usage(user_id: str, usage: dict, *, session_id: str = None,
                 request_id: str = None, duration_ms: float = None,
                 success: bool = True, error: str = None,
                 prompt_summary: str = None,
                 metadata: dict = None):
    """
    Report token usage to quota service using the /quota/report schema.

    Schema aligned with supervisor-agent `llm_calls` convention:
        input_tokens INCLUDES cached_tokens. The quota service applies the
        cache discount server-side in its own estimate_cost.

    `usage` is the dict returned by shared.openai_utils.chat_completion:
        {"input_tokens", "output_tokens", "cached_tokens", "total_tokens",
         "model", "cost_usd"}

    `metadata` is an optional free-form JSON dict the quota service stores
    in the UsageLogs row alongside the totals. Use it to ship per-stage
    breakdown (rerank vs answer tokens/cost/model) so /quota/admin/logs
    has the same transparency KB_Logs does.
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
                    'operation': 'chat',
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
                    'session_id': session_id,
                    'metadata': metadata,
                },
                headers=service_auth_headers('kb-chat-message'),
            )
            # Without raise_for_status, 401/4xx/5xx silently no-op and the
            # call never reaches quota-report's CloudWatch — fail loudly.
            response.raise_for_status()
    except Exception as e:
        print(f"Usage report warning: {e}")


def lambda_handler(event, context):
    """
    Process a chat message and generate AI response.
    
    Request body:
    {
        "session_id": "uuid",
        "message": "User's message",
        "options": {
            "max_sources": 5,
            "include_context": true,
            "document_filter": []
        }
    }
    """
    # Handle CORS preflight
    if event.get('requestContext', {}).get('http', {}).get('method') == 'OPTIONS':
        return options_response()
    
    start_time = time.time()
    
    try:
        # Get user from API Gateway authorizer context
        try:
            user = get_user_from_authorizer(event)
            user_id = user['user_id']
        except Exception as e:
            return unauthorized_response(str(e))
        
        # Parse request body
        body = parse_body(event)
        
        session_id = body.get('session_id')
        message = body.get('message', '').strip()
        options = body.get('options', {})
        
        if not session_id:
            return validation_error_response("session_id is required")
        if not message:
            return validation_error_response("message is required")
        
        # ── Validate session & ownership FIRST so we have somewhere to save
        # the user msg + a friendly refusal turn even when guardrails block.
        session = get_session(session_id)
        if not session:
            return error_response("Session not found", 404)
        if session.get('user_id') != user_id:
            return forbidden_response("Access denied - you don't own this session")

        # ── INPUT GUARDRAILS ──────────────────────────────────────────────
        # `block_off_topic=True` keeps REST + WebSocket policy aligned.
        # The OFF_TOPIC_PATTERNS list is now hard-line only (weapons/hacking)
        # — soft cases (code/poems/opinions) are deferred to the LLM SCOPE
        # clause in the system prompt. Profanity / targeted abuse is checked
        # always (independent of block_off_topic).
        guardrails = ChatGuardrails(strict_mode=True, block_off_topic=True)
        input_check = guardrails.check_input(message)

        if input_check.result == GuardrailResult.BLOCKED:
            print(f"[Chat] Message blocked by guardrails: {input_check.reason}")
            # Friendly block: render as a normal assistant turn instead of a
            # red error toast. Saves both sides of the exchange so chat
            # history stays coherent and analytics see the block via
            # metadata.was_blocked.
            friendly = input_check.message or (
                "I can only help with knowledge base questions. "
                "What would you like to ask?"
            )
            save_message(session_id=session_id, role='user', content=message)
            assistant_msg = save_message(
                session_id=session_id,
                role='assistant',
                content=friendly,
                sources=[],
                metadata={
                    'was_blocked': True,
                    'block_reason': input_check.reason,
                    'tokens_used': 0,
                    'cost_usd': 0,
                }
            )
            return success_response({
                'success': True,
                'message_id': assistant_msg['message_id'],
                'content': friendly,
                'sources': [],
                'usage': {'tokens_used': 0, 'cost_usd': 0},
                'duration_ms': (time.time() - start_time) * 1000,
                'was_blocked': True,
                'block_reason': input_check.reason,
            })

        # ── QUOTA CHECK (SFXchatbot policy) ───────────────────────────────
        # Block ONLY when the user has zero tokens left. If they have ANY
        # remaining tokens we let the call proceed even if the LLM might
        # overshoot — the actual usage is reported by `report_usage` after
        # the call, and the next request will be blocked at this gate.
        try:
            quota_check = check_quota(user_id, estimated_tokens=1)
            if not quota_check.get('allowed', True):
                friendly = (
                    "You've used up your monthly token budget. "
                    "Your quota will reset on " +
                    str(quota_check.get('resets_at', 'the next billing date')) +
                    ". Please contact an administrator if you need it raised."
                )
                save_message(session_id=session_id, role='user', content=message)
                assistant_msg = save_message(
                    session_id=session_id,
                    role='assistant',
                    content=friendly,
                    sources=[],
                    metadata={
                        'was_blocked': True,
                        'block_reason': 'quota_exhausted',
                        'remaining_tokens': quota_check.get('remaining_tokens', 0),
                    }
                )
                return success_response({
                    'success': True,
                    'message_id': assistant_msg['message_id'],
                    'content': friendly,
                    'sources': [],
                    'usage': {'tokens_used': 0, 'cost_usd': 0},
                    'duration_ms': (time.time() - start_time) * 1000,
                    'was_blocked': True,
                    'block_reason': 'quota_exhausted',
                })
        except Exception as e:
            if "deactivated" in str(e).lower():
                friendly = (
                    "Your account has been deactivated. "
                    "Please contact an administrator to restore access."
                )
                save_message(session_id=session_id, role='user', content=message)
                assistant_msg = save_message(
                    session_id=session_id,
                    role='assistant',
                    content=friendly,
                    sources=[],
                    metadata={'was_blocked': True, 'block_reason': 'account_deactivated'}
                )
                return success_response({
                    'success': True,
                    'message_id': assistant_msg['message_id'],
                    'content': friendly,
                    'sources': [],
                    'usage': {'tokens_used': 0, 'cost_usd': 0},
                    'duration_ms': (time.time() - start_time) * 1000,
                    'was_blocked': True,
                    'block_reason': 'account_deactivated',
                })
            # Other quota errors: fail open (already logged in check_quota)
        
        print(f"[Chat] Processing message for session {session_id}")
        
        # Save user message
        user_msg = save_message(
            session_id=session_id,
            role="user",
            content=message
        )
        
        # Get options
        max_sources = options.get('max_sources', 5)
        include_context = options.get('include_context', True)
        document_filter = options.get('document_filter', [])
        
        # Get conversation history if needed
        conversation_history = []
        if include_context:
            all_messages = get_session_messages(session_id)
            # Get last 10 messages for context (excluding the just-saved one)
            conversation_history = all_messages[-11:-1] if len(all_messages) > 1 else []
        
        # Enhance query for better search
        processed_query = enhance_query(message, conversation_history)
        search_query = processed_query['search_query']
        print(f"[Chat] Original: {message[:100]}...")
        if processed_query['is_expanded']:
            print(f"[Chat] Enhanced: {search_query[:100]}...")
        
        # Search knowledge base (BYO vectors — query embedded inside
        # hybrid_search via openai_utils.embed_texts). Pass user_id +
        # request_id so embedding tokens are recorded in UsageLogs as
        # tier='embedding', record_only=True (audit row, no deduction).
        print("[Chat] Searching knowledge base...")
        search_results = hybrid_search(
            query=search_query,
            limit=50,
            alpha=0.7,
            doc_filter=document_filter if document_filter else None,
            user_id=user_id,
            request_id=event.get('requestContext', {}).get('requestId'),
            # Tag the embedding row with session_id so the per-user
            # history view can collapse this audit row into the
            # parent chat_stream row by exact match. Falls back to
            # time-window matching client-side if missing.
            session_id=session_id,
        )
        
        # Track per-LLM-call usage so the single quota_report at the end
        # of the request includes EVERY LLM call we made (rerank + answer),
        # not just the main answer call. This closes the rerank "ghost spend"
        # gap (~10% of total chat cost on gpt-4o-mini was previously untracked).
        rerank_usage = {
            'input_tokens': 0, 'output_tokens': 0, 'cached_tokens': 0,
            'total_tokens': 0, 'cost_usd': 0.0, 'model': 'none',
        }

        if not search_results:
            # No KB results - generate a simple response (no LLM call, zero usage).
            answer = "I couldn't find any relevant information in the knowledge base for your question. Please try rephrasing or ask about topics covered in the uploaded documents."
            sources = []
            usage = {
                'input_tokens': 0,
                'output_tokens': 0,
                'cached_tokens': 0,
                'total_tokens': 0,
                'cost_usd': 0,
                'model': 'none',
            }
        else:
            # Rerank (LLM call) — capture its usage so it rolls into quota_report.
            print(f"[Chat] Found {len(search_results)} results, reranking...")
            reranked, rerank_usage = rerank_chunks(message, search_results, top_n=max_sources)
            top_chunks = [chunk for chunk, score in reranked]

            print("[Chat] Generating answer...")
            answer, sources, usage = generate_kb_answer(
                query=message,
                context_chunks=top_chunks,
                conversation_history=conversation_history
            )

        # Layer 4 output guardrail — strip leak markers, mask PII, block on
        # sensitive-data leaks. Runs on both the no-results stub and real
        # KB answer paths since both produce a string in `answer`.
        output_check = guardrails.check_output(answer)
        if output_check.result == GuardrailResult.BLOCKED:
            print(f"[Chat] Output blocked: {output_check.reason}")
            answer = output_check.message or (
                "I found information I shouldn't share. Please rephrase your question."
            )
        elif output_check.result == GuardrailResult.MODIFIED:
            print("[Chat] Output sanitized (PII / leak markers removed)")
            answer = output_check.sanitized

        # Calculate duration first so both report_usage and save_log see it.
        duration_ms = (time.time() - start_time) * 1000

        # Sum rerank + main answer usage so quota_report reflects the TOTAL
        # spend for this request, not just the main answer call.
        # Per supervisor-agent guide §1: input_tokens INCLUDES cached_tokens;
        # cached is a subset that gets the discounted rate. Summing matches
        # the same convention.
        combined_usage = {
            'input_tokens': int(usage.get('input_tokens', 0) or 0)
                          + int(rerank_usage.get('input_tokens', 0) or 0),
            'output_tokens': int(usage.get('output_tokens', 0) or 0)
                           + int(rerank_usage.get('output_tokens', 0) or 0),
            'cached_tokens': int(usage.get('cached_tokens', 0) or 0)
                           + int(rerank_usage.get('cached_tokens', 0) or 0),
            'cost_usd': float(usage.get('cost_usd', 0.0) or 0.0)
                      + float(rerank_usage.get('cost_usd', 0.0) or 0.0),
            # Use the answer model as the canonical model on the report.
            # Rerank model is captured in save_log below for analytics.
            'model': usage.get('model', 'unknown'),
        }
        combined_usage['total_tokens'] = (
            combined_usage['input_tokens'] + combined_usage['output_tokens']
        )

        # Save assistant message with the COMBINED usage so per-message
        # metadata matches what we report to the quota service.
        assistant_msg = save_message(
            session_id=session_id,
            role="assistant",
            content=answer,
            sources=sources,
            metadata={
                'tokens_used': combined_usage['total_tokens'],
                'cost_usd': combined_usage['cost_usd'],
                'model': combined_usage.get('model', 'unknown'),
                'rerank_model': rerank_usage.get('model'),
                'rerank_tokens': int(rerank_usage.get('total_tokens', 0) or 0),
                'rerank_cost_usd': float(rerank_usage.get('cost_usd', 0.0) or 0.0),
                'answer_tokens': int(usage.get('total_tokens', 0) or 0),
                'answer_cost_usd': float(usage.get('cost_usd', 0.0) or 0.0),
                'chunks_used': len(sources),
            }
        )

        # Report usage to quota service (schema-aligned with supervisor-agent).
        # `metadata` carries per-LLM-call breakdown so /quota/admin/logs has
        # the same per-stage transparency as KB_Logs (cost-attribution down
        # to which LLM call drove the spend, not just the total).
        try:
            report_usage(
                user_id,
                combined_usage,
                session_id=session_id,
                request_id=event.get('requestContext', {}).get('requestId'),
                duration_ms=duration_ms,
                success=True,
                prompt_summary=message[:200],
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
                    'chunks_used': len(sources),
                    'message_length': len(message),
                    'answer_length': len(answer),
                },
            )
        except Exception as e:
            print(f"Usage report warning: {e}")

        # Log the interaction. Additive schema: legacy `tokens_used`/`cost_usd`
        # kept; adding input/output/cached split + tier + model + prompt_summary
        # plus the rerank-call breakdown so analytics can break down cost
        # per LLM stage (rerank vs answer).
        try:
            save_log('chat', {
                'operation': 'chat_message',
                'tier': 'chat',
                'model': usage.get('model'),
                'rerank_model': rerank_usage.get('model'),
                'session_id_hash': hash(session_id) % 10000000,
                'user_id_hash': hash(user_id) % 10000000,
                'message_length': len(message),
                'answer_length': len(answer),
                'chunks_used': len(sources),
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
                'prompt_summary': message[:200],
                'success': True
            })
        except Exception as e:
            print(f"Logging warning: {e}")
        
        # Update session metadata (documents referenced, chunks used)
        try:
            session_meta = session.get('metadata', {}) or {}
            docs_referenced = session_meta.get('documents_referenced', [])
            
            # Add new document IDs from sources
            for source in sources:
                doc_id = source.get('doc_id') or source.get('document_id')
                if doc_id and doc_id not in docs_referenced:
                    docs_referenced.append(doc_id)
            
            update_session_metadata(session_id, {
                'documents_referenced': docs_referenced,
                'total_chunks_used': session_meta.get('total_chunks_used', 0) + len(sources),
                'last_search_query': search_query
            })
        except Exception as e:
            print(f"Session metadata update warning: {e}")
        
        print(
            f"[Chat] Response generated in {duration_ms:.0f}ms. "
            f"Total tokens: {combined_usage['total_tokens']} "
            f"(answer={usage.get('total_tokens', 0)}, "
            f"rerank={rerank_usage.get('total_tokens', 0)})"
        )

        return success_response({
            'success': True,
            'message_id': assistant_msg['message_id'],
            'content': answer,
            'sources': sources,
            'usage': {
                'tokens_used': combined_usage['total_tokens'],
                'cost_usd': combined_usage['cost_usd'],
            },
            'duration_ms': duration_ms,
        })
        
    except Exception as e:
        print(f"Error processing chat message: {e}")
        import traceback
        traceback.print_exc()
        
        # Log error. Per supervisor-agent guide invariant §8.5 — always log
        # failures with the same shape as success (minus the token split).
        try:
            save_log('chat', {
                'operation': 'chat_message',
                'tier': 'chat',
                'duration_ms': (time.time() - start_time) * 1000,
                'prompt_summary': (message[:200] if 'message' in locals() else None),
                'success': False,
                'error': str(e)
            })
        except:
            pass
        
        return server_error_response(str(e))
    
    finally:
        # Clean up Weaviate connection
        try:
            close_weaviate_client()
        except:
            pass

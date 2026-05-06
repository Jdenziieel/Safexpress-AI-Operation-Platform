"""
WebSocket Chat Stream Handler - Full Pipeline

Handles streaming chat messages with real-time AI responses.
This is the main handler for the 'sendMessage' action.

FULL PIPELINE (matching original knowledge-base system):
1. Receives user message via WebSocket
2. Fetches conversation history from DynamoDB (last 10 messages)
3. Enhances query (follow-up detection, pronoun resolution via GPT-4o-mini)
4. Searches Weaviate for 50 relevant chunks (v4 API with ofDocument cross-references)
5. Multi-factor reranks to top 15 chunks (section, tags, type, length scoring)
6. Builds rich context with ContextManager (metadata headers, smart truncation)
7. Streams OpenAI gpt-4o response with rich system prompt + conversation history
8. Saves complete conversation to DynamoDB
9. Auto-generates session title on first message
"""
import json
import os
import re
import sys
import boto3
import uuid
from datetime import datetime
from decimal import Decimal
import traceback
import time

# Add shared modules to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
connections_table = dynamodb.Table(os.environ.get('CONNECTIONS_TABLE', 'KB_WebSocketConnections'))
sessions_table = dynamodb.Table(os.environ.get('SESSIONS_TABLE', 'KB_ChatSessions'))
messages_table = dynamodb.Table(os.environ.get('MESSAGES_TABLE', 'KB_ChatMessages'))
logs_table = dynamodb.Table(os.environ.get('LOGS_TABLE', 'KB_Logs'))

# Import shared modules (from shared/ folder)
# Each import is separate so one failure doesn't cascade to all others
context_manager = None
guardrails = None
wrap_untrusted_content = None  # populated below; kept None on import failure

try:
    from shared.weaviate_utils import get_weaviate_client, hybrid_search, close_weaviate_client
except ImportError as e:
    print(f"Import warning (weaviate_utils): {e}")

try:
    from shared.query_processor import enhance_query, rerank_results
except ImportError as e:
    print(f"Import warning (query_processor): {e}")

try:
    from shared.context_manager import ContextManager
    context_manager = ContextManager()
except ImportError as e:
    print(f"Import warning (context_manager): {e}")

try:
    from shared.guardrails import (
        SFXBotGuardrails,
        GuardrailResult,
        wrap_untrusted_content as _wrap_untrusted_content,
    )
    guardrails = SFXBotGuardrails(
        strict_mode=True, block_off_topic=True, mask_pii_in_output=True
    )
    wrap_untrusted_content = _wrap_untrusted_content
except ImportError as e:
    print(f"Import warning (guardrails): {e}")

try:
    from shared.db_utils import save_log
except ImportError as e:
    print(f"Import warning (db_utils): {e}")

try:
    from openai import OpenAI
except ImportError as e:
    print(f"Import warning (openai): {e}")

try:
    import httpx
except ImportError as e:
    print(f"Import warning (httpx): {e}")

# Quota service configuration
QUOTA_SERVICE_URL = os.environ.get('QUOTA_SERVICE_URL', '')
QUOTA_ENABLED = os.environ.get('QUOTA_ENABLED', 'true').lower() == 'true'

# Service-to-service auth: WebSocket messages don't carry an Authorization
# header (the user JWT was only sent at $connect), so each outbound
# /quota/* call mints its own short-lived JWT. See shared/service_jwt.py.
try:
    from shared.service_jwt import service_auth_headers
except ImportError as e:
    print(f"Import warning (service_jwt): {e}")
    def service_auth_headers(principal: str = 'kb-ws-chat-stream') -> dict:
        return {}

# ─── Per-role model selection (see supervisor-agent model-change guide §2) ────
# OPENAI_CHAT_MODEL = main KB answer. gpt-4.1 wins here: big repeatable system
# prompt (safety + KB context + history) gets a 75% cache discount, and 1M
# context fits the full chunk set without trimming.
# TITLE_MODEL = 20-token one-shot title. Prompt changes every call → no cache
# hit. gpt-4o-mini is cheaper than gpt-4.1-mini on cold prompts, so we keep it.
DEFAULT_CHAT_MODEL = os.environ.get('OPENAI_CHAT_MODEL', 'gpt-4.1')
TITLE_MODEL = os.environ.get('TITLE_MODEL', 'gpt-4o-mini')


# ============================================================
# Citation policy
# ============================================================
#
# Old behavior: rule 2 of the system prompt forced inline
# `[Source: filename, Page X]` after every answer. That was noisy for
# casual questions AND, because of an unrelated upload-side bug
# (weaviate_utils field-path mismatch, fixed 2026-05-01), every chunk
# in Weaviate was stored with `page=1`. So forcing the citation made
# the AI dutifully print "Page 1" on every answer regardless of source.
#
# New behavior:
#   - Default: answer naturally, mention document names when it adds
#     clarity, but DO NOT emit bracketed `[Source: ...]` citations.
#   - On the first turn of a session: append a one-line tip telling the
#     user they can ask "where is this from?" to get sources.
#   - When the user explicitly asks for sources / pages / proof / cites,
#     switch into full-citation mode for that turn (page, section,
#     filename, all explicit).

CITATION_REQUEST_PATTERN = re.compile(
    r"\b("
    # Direct asks
    r"cite|citing|citation|citations|"
    r"sources?|references?|bibliography|footnotes?|"
    # Page asks
    r"what\s+page|which\s+page|page\s*(?:no\.?|number|num|#)?|"
    # Provenance asks
    r"where\s+(?:is|did|does|do|are)\s+\w[\w\s]{0,30}?(?:from|come\s+from|get|got|find|found)|"
    r"where\s+did\s+(?:you|that|this|it)\s+come\s+from|"
    r"where\s+(?:in|on)\s+(?:the\s+)?(?:doc|document|pdf|file|manual|sop|hse)|"
    # Verification asks
    r"prove\s+(?:it|that|this)|back\s+(?:this|that|it)\s+up|"
    r"verify|verifiable|verification|"
    # Show-me asks
    r"show\s+(?:me\s+)?(?:the\s+)?(?:source|sources|reference|references|page|pages|proof|evidence)|"
    r"give\s+(?:me\s+)?(?:the\s+)?(?:source|sources|reference|references|citation|citations)|"
    r"evidence"
    r")\b",
    re.IGNORECASE,
)


def user_wants_citations(message: str) -> bool:
    """Return True if the user message looks like an explicit ask for sources."""
    if not message:
        return False
    return bool(CITATION_REQUEST_PATTERN.search(message))


# ============================================================
# Rich system prompt (matching original knowledge-base system)
# ============================================================

# Citation-mode subsection. We render one of three variants into the main
# template based on (a) whether the user is asking for sources, and
# (b) whether this is the first assistant turn of the session.
_CITE_MODE_FULL = """\
CITATION POLICY — FULL CITATION MODE (the user is asking about sources):
- After every distinct claim or quote, append the source inline using
  this exact format: [Source: <filename>, Section <section>, Page <page>]
- Use the Section, Page, and filename values exactly as given in the
  Available Document Context below.
- If a chunk's section is empty, omit the Section part.
- If a chunk's page is missing or appears to be wrong (every chunk says
  "Page 1" while the document is multi-page), say so honestly:
  "(page numbers in the knowledge base may be out of date — please
  re-upload the document for accurate pages)".
- Do NOT invent page numbers."""

_CITE_MODE_FIRST_TURN_HINT = """\
CITATION POLICY — NATURAL MODE (with one-time tip):
- Answer naturally and clearly. You may mention document names when it
  adds clarity (e.g. "according to HSE.pdf,").
- DO NOT print bracketed [Source: ...] citations — they make the answer
  feel mechanical for casual questions.
- Because this is the first reply in this conversation, append exactly
  this line on its own row at the very end of your answer (use it
  verbatim, including the leading underscore which renders as italic):

  _Tip: Want exact sources or page numbers? Just ask "where is this from?" and I'll cite them._

- Do NOT add this tip to any other turn — only this first one."""

_CITE_MODE_NATURAL = """\
CITATION POLICY — NATURAL MODE:
- Answer naturally and clearly. You may mention document names when it
  adds clarity (e.g. "according to HSE.pdf,").
- DO NOT print bracketed [Source: ...] citations unless the user asks.
- If the user later asks "where is this from", "what's the source", or
  similar, you'll be told to switch to full-citation mode for that turn."""


SYSTEM_PROMPT_TEMPLATE = """You are a helpful assistant that answers questions based on uploaded documents in a knowledge base.

IMPORTANT RULES:
1. Base your answers ONLY on the provided document excerpts below
2. {citation_policy}
3. If the information needed to answer the question is not in the provided excerpts, say "I don't have enough information in the uploaded documents to answer that question fully."
4. Be conversational but accurate
5. Use direct quotes when appropriate
6. If asked about something not in the documents, politely say so and suggest what topics the documents do cover
7. Pay attention to the Type field (heading, list, table, image, etc.) to understand the content structure
8. Consider the Section, Context, and Tags provided with each source for better understanding

⚠️ CRITICAL: READ ALL PROVIDED SOURCES
- You will receive multiple document excerpts below (Source 1, Source 2, etc.)
- Each source has been pre-filtered for relevance, so READ THEM ALL CAREFULLY
- DO NOT only focus on Source 1 or high-scored sources
- Lower-numbered sources might be section headers, while later sources contain the detailed content
- SYNTHESIZE information from ALL sources to provide a complete answer
- If Source 1 is a heading/intro and Sources 2-5 have the details, USE THE DETAILS
- When a user asks about a section, look for both the section introduction AND its detailed content across all sources

Available Document Context:
{kb_context}

Note: Each source may include:
- Section: The document section this content belongs to
- Type: Content type (heading, paragraph, list, table, image, etc.)
- Context: A brief description of the content's purpose
- Tags: Keywords categorizing this content

Use all this information to provide comprehensive answers that synthesize ALL provided sources."""


def _select_citation_policy(wants_citations: bool, is_first_turn: bool) -> str:
    """Pick which citation policy block goes into the system prompt."""
    if wants_citations:
        return _CITE_MODE_FULL
    if is_first_turn:
        return _CITE_MODE_FIRST_TURN_HINT
    return _CITE_MODE_NATURAL


# ============================================================
# Helper functions
# ============================================================

def get_apigw_client(event):
    """Create API Gateway Management API client for sending messages."""
    domain = event['requestContext']['domainName']
    stage = event['requestContext']['stage']
    endpoint = f"https://{domain}/{stage}"
    return boto3.client('apigatewaymanagementapi', endpoint_url=endpoint)


def send_to_client(apigw, connection_id, message):
    """Send a message to the WebSocket client."""
    try:
        apigw.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(message).encode('utf-8')
        )
        return True
    except apigw.exceptions.GoneException:
        print(f"Connection {connection_id} is gone")
        return False
    except Exception as e:
        print(f"Error sending to client: {e}")
        return False


def get_or_create_session(session_id, user_id):
    """Get existing session or create a new one."""
    if session_id:
        try:
            response = sessions_table.get_item(Key={'session_id': session_id})
            if 'Item' in response:
                return response['Item']
        except Exception as e:
            print(f"Error getting session: {e}")
    
    # Create new session
    new_session_id = session_id or str(uuid.uuid4())
    session = {
        'session_id': new_session_id,
        'user_id': user_id,
        'title': 'New Chat',
        'created_at': datetime.utcnow().isoformat(),
        'updated_at': datetime.utcnow().isoformat(),
        'message_count': 0
    }
    
    sessions_table.put_item(Item=session)
    return session


def save_message(session_id, role, content, tokens_used=0, sources=None):
    """Save a message to DynamoDB."""
    message_id = str(uuid.uuid4())
    message = {
        'message_id': message_id,
        'session_id': session_id,
        'role': role,
        'content': content,
        'timestamp': datetime.utcnow().isoformat(),
        'tokens_used': tokens_used
    }
    
    if sources:
        message['sources'] = sources
    
    messages_table.put_item(Item=message)
    
    # Update session message count and timestamp
    sessions_table.update_item(
        Key={'session_id': session_id},
        UpdateExpression='SET message_count = message_count + :inc, updated_at = :ts',
        ExpressionAttributeValues={
            ':inc': 1,
            ':ts': datetime.utcnow().isoformat()
        }
    )
    
    return message_id


def get_conversation_history(session_id, max_messages=10):
    """
    Fetch recent messages from DynamoDB for conversation context.
    Tries GSI first, falls back to scan.
    
    Returns:
        List of message dicts [{'role': ..., 'content': ...}]
    """
    try:
        from boto3.dynamodb.conditions import Key, Attr
        
        messages = []
        
        # Try querying with session_id GSI
        try:
            response = messages_table.query(
                IndexName='session_id-index',
                KeyConditionExpression=Key('session_id').eq(session_id),
                ScanIndexForward=True,
            )
            messages = response.get('Items', [])
        except Exception:
            try:
                # Try session_id as partition key
                response = messages_table.query(
                    KeyConditionExpression=Key('session_id').eq(session_id),
                    ScanIndexForward=True,
                )
                messages = response.get('Items', [])
            except Exception:
                # Fallback: scan with filter
                response = messages_table.scan(
                    FilterExpression=Attr('session_id').eq(session_id),
                )
                messages = response.get('Items', [])
        
        # Sort by timestamp
        messages.sort(key=lambda x: x.get('timestamp', ''))
        
        # Return recent messages (exclude the last one which is the current user message just saved)
        recent = messages[-(max_messages + 1):-1] if len(messages) > 1 else []
        
        history = [
            {'role': msg.get('role', 'user'), 'content': msg.get('content', '')}
            for msg in recent
            if msg.get('content', '').strip()  # Skip empty messages
        ]
        
        print(f"[History] Retrieved {len(history)} messages for session {session_id}")
        return history
        
    except Exception as e:
        print(f"[History] Error fetching conversation history: {e}")
        return []


def log_activity(log_type, user_id, details):
    """Log activity to DynamoDB."""
    try:
        logs_table.put_item(Item={
            'log_id': str(uuid.uuid4()),
            'log_type': log_type,
            'timestamp': datetime.utcnow().isoformat(),
            'user_id': user_id,
            'details': details
        })
    except Exception as e:
        print(f"Error logging activity: {e}")


def check_quota(user_id: str, estimated_tokens: int = 0) -> dict:
    """Check user quota with quota service. Fails open on errors."""
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
                    'operation': 'chat_stream'
                },
                headers=service_auth_headers('kb-ws-chat-stream'),
            )
            if response.status_code == 404:
                return {'allowed': False, 'error': 'Account deactivated'}
            response.raise_for_status()
            return response.json()
    except Exception as e:
        print(f"[Quota] Check warning: {e}")
        return {'allowed': True, 'remaining_tokens': 0}


def report_usage(user_id: str, usage: dict, *, session_id: str = None,
                 request_id: str = None, duration_ms: float = None,
                 success: bool = True, error: str = None,
                 prompt_summary: str = None,
                 metadata: dict = None):
    """
    Report token usage to quota service using the /quota/report schema.

    Schema aligned with supervisor-agent `llm_calls` convention:
        input_tokens INCLUDES cached_tokens (cached is a subset — the quota
        service applies the cache discount in its own estimate_cost).

    `usage` keys expected:
        "input_tokens", "output_tokens", "cached_tokens", "model", "cost_usd"

    `metadata` is an optional free-form JSON dict shipped to UsageLogs.
    Used here to record per-LLM-stage breakdown (enhance / answer / title)
    so /quota/admin/logs has the same per-stage transparency KB_Logs has.
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
                    'operation': 'chat_stream',
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
                headers=service_auth_headers('kb-ws-chat-stream'),
            )
            # Without raise_for_status, 401/404/5xx silently no-op and
            # quota-report never gets invoked — exactly the bug we just hit.
            response.raise_for_status()
    except Exception as e:
        print(f"[Quota] Usage report warning: {e}")


def update_session_metadata(session_id, chunks_used, sources):
    """Update session with documents_referenced and total_chunks_used."""
    try:
        # Get current session metadata
        response = sessions_table.get_item(Key={'session_id': session_id})
        session = response.get('Item', {})
        
        existing_docs = session.get('documents_referenced', [])
        existing_chunks = int(session.get('total_chunks_used', 0))
        
        # Add new unique document names from sources
        for src in sources:
            doc_name = src.get('file_name', '')
            if doc_name and doc_name not in existing_docs:
                existing_docs.append(doc_name)
        
        sessions_table.update_item(
            Key={'session_id': session_id},
            UpdateExpression='SET documents_referenced = :docs, total_chunks_used = :chunks, updated_at = :ts',
            ExpressionAttributeValues={
                ':docs': existing_docs,
                ':chunks': existing_chunks + chunks_used,
                ':ts': datetime.utcnow().isoformat()
            }
        )
        print(f"[Session] Updated metadata: {len(existing_docs)} docs, {existing_chunks + chunks_used} total chunks")
    except Exception as e:
        print(f"[Session] Metadata update warning: {e}")


_TITLE_ZERO_USAGE = {
    'input_tokens': 0,
    'output_tokens': 0,
    'cached_tokens': 0,
    'total_tokens': 0,
    'cost_usd': 0.0,
    'model': 'none',
}


def generate_session_title(user_message, assistant_response=""):
    """
    Generate a short, descriptive title for a chat session based on the first message.
    Uses OpenAI to create a concise 3-7 word title.

    Returns:
        Tuple of (title, usage_dict). usage_dict has the standard shape so
        the caller can roll it into the per-request quota_report.
    """
    try:
        openai_client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))

        prompt = f"""Generate a very short title (3-7 words max) for a chat conversation that starts with this message.
The title should be descriptive and concise, like a subject line.
Do NOT use quotes or special characters. Just return the plain title text.

User's first message: "{user_message[:200]}"
"""

        response = openai_client.chat.completions.create(
            model=TITLE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=20
        )

        title = response.choices[0].message.content.strip()
        # Clean up: remove quotes, limit length
        title = title.strip('"\'')
        if len(title) > 100:
            title = title[:97] + '...'

        # Capture token usage so the caller's quota_report includes this call
        usage_obj = getattr(response, 'usage', None)
        if usage_obj is not None:
            input_tokens = int(getattr(usage_obj, 'prompt_tokens', 0) or 0)
            output_tokens = int(getattr(usage_obj, 'completion_tokens', 0) or 0)
            cached_tokens = 0
            prompt_details = getattr(usage_obj, 'prompt_tokens_details', None)
            if prompt_details is not None:
                cached_tokens = int(getattr(prompt_details, 'cached_tokens', 0) or 0)
            try:
                from shared.openai_utils import estimate_cost as _estimate_cost
                cost = _estimate_cost(
                    input_tokens, output_tokens, TITLE_MODEL,
                    cached_tokens=cached_tokens,
                )
            except Exception:
                # gpt-4o-mini fallback rates
                cost = (max(input_tokens - cached_tokens, 0) * 0.00015
                        + cached_tokens * 0.000075
                        + output_tokens * 0.0006) / 1000.0
            usage = {
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'cached_tokens': cached_tokens,
                'total_tokens': input_tokens + output_tokens,
                'cost_usd': cost,
                'model': TITLE_MODEL,
            }
        else:
            usage = dict(_TITLE_ZERO_USAGE)
            usage['model'] = TITLE_MODEL

        return (title if title else 'New Chat'), usage

    except Exception as e:
        print(f"Error generating session title: {e}")
        # Fallback: use first ~50 chars of the user message
        fallback = user_message[:50].strip()
        if len(user_message) > 50:
            fallback += '...'
        return (fallback or 'New Chat'), dict(_TITLE_ZERO_USAGE)


def search_knowledge_base(query, top_k=50, user_id=None, request_id=None, session_id=None):
    """
    Search Weaviate using v4 hybrid search with rich metadata.
    
    user_id + request_id + session_id are forwarded to hybrid_search so
    the embedding call (BYO vectors path) is recorded in UsageLogs
    against the right user with request_id correlation AND tagged with
    session_id. The session_id tag lets the frontend chat-turn grouper
    collapse this audit row into the parent chat_stream row by exact
    match (instead of falling back to time-window heuristics).
    record_only=True is set inside weaviate_utils so this never
    decrements the user's chat balance.
    """
    try:
        results = hybrid_search(
            query=query,
            limit=top_k,
            user_id=user_id,
            request_id=request_id,
            session_id=session_id,
        )
        print(f"[Search] Retrieved {len(results)} chunks from Weaviate")
        return results
    except Exception as e:
        print(f"[Search] Error: {e}")
        traceback.print_exc()
        return []


# ============================================================
# Main Lambda Handler
# ============================================================

def lambda_handler(event, context):
    """
    Handle WebSocket sendMessage action with FULL pipeline.
    
    Expected message format:
    {
        "action": "sendMessage",
        "session_id": "optional-session-id",
        "message": "User's question",
        "options": {
            "temperature": 0.7,
            "max_tokens": 2000
        }
    }
    """
    connection_id = event['requestContext']['connectionId']
    apigw = get_apigw_client(event)
    
    try:
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        user_message = body.get('message', '')
        session_id = body.get('session_id')
        options = body.get('options', {})
        pipeline_start_time = time.time()
        
        if not user_message:
            send_to_client(apigw, connection_id, {
                'type': 'error',
                'message': 'No message provided'
            })
            return {'statusCode': 400}
        
        # Get user info from connection
        try:
            conn_response = connections_table.get_item(Key={'connection_id': connection_id})
            user_id = conn_response.get('Item', {}).get('user_id', 'anonymous')
        except:
            user_id = 'anonymous'
        
        # ── INPUT GUARDRAILS ──────────────────────────────────────────────
        # Friendly block: instead of `type:error` (which the frontend renders
        # as a red toast), stream the polite refusal as if it were the
        # assistant's reply (`token` + `complete`). The chat UI then renders
        # it as a normal turn, plus the `was_blocked` flag lets analytics
        # distinguish blocked turns from real answers.
        if guardrails is not None:
            input_check = guardrails.check_input(user_message, user_id=user_id, session_id=session_id)
            if input_check.result == GuardrailResult.BLOCKED:
                print(f"[Guardrails] ⚠️ Message blocked: {input_check.reason}")
                friendly = input_check.message or (
                    "I can only help with knowledge base questions. "
                    "What would you like to ask?"
                )
                # Resolve session before saving so chat history stays coherent
                _block_session = get_or_create_session(session_id, user_id)
                _block_session_id = _block_session['session_id']
                save_message(_block_session_id, 'user', user_message)
                save_message(_block_session_id, 'assistant', friendly, 0, [])
                send_to_client(apigw, connection_id, {
                    'type': 'token',
                    'content': friendly,
                    'session_id': _block_session_id,
                })
                send_to_client(apigw, connection_id, {
                    'type': 'complete',
                    'session_id': _block_session_id,
                    'full_response': friendly,
                    'sources': [],
                    'tokens_used': 0,
                    'model': 'none',
                    'was_blocked': True,
                    'block_reason': input_check.reason,
                })
                log_activity('guardrail_block', user_id, {
                    'session_id': _block_session_id,
                    'reason': input_check.reason,
                    'message_preview': user_message[:100],
                })
                return {'statusCode': 200}
        else:
            print("[Guardrails] ⚠️ Guardrails not available, skipping input check")

        # ── QUOTA CHECK (SFXchatbot policy) ───────────────────────────────
        # Block ONLY when the user has zero tokens left. If they have ANY
        # remaining tokens we let the call proceed even if the LLM might
        # overshoot — actual usage is reported by `report_usage` afterwards
        # and the next request will be blocked at this same gate.
        try:
            quota_check = check_quota(user_id, estimated_tokens=1)
            if not quota_check.get('allowed', True):
                error_msg = quota_check.get('error', '')
                if 'deactivated' in error_msg.lower():
                    friendly = (
                        "Your account has been deactivated. "
                        "Please contact an administrator to restore access."
                    )
                    block_reason = 'account_deactivated'
                else:
                    friendly = (
                        "You've used up your monthly token budget. "
                        "Your quota will reset on " +
                        str(quota_check.get('resets_at', 'the next billing date')) +
                        ". Please contact an administrator if you need it raised."
                    )
                    block_reason = 'quota_exhausted'
                _block_session = get_or_create_session(session_id, user_id)
                _block_session_id = _block_session['session_id']
                save_message(_block_session_id, 'user', user_message)
                save_message(_block_session_id, 'assistant', friendly, 0, [])
                send_to_client(apigw, connection_id, {
                    'type': 'token',
                    'content': friendly,
                    'session_id': _block_session_id,
                })
                send_to_client(apigw, connection_id, {
                    'type': 'complete',
                    'session_id': _block_session_id,
                    'full_response': friendly,
                    'sources': [],
                    'tokens_used': 0,
                    'model': 'none',
                    'was_blocked': True,
                    'block_reason': block_reason,
                })
                return {'statusCode': 200}
        except Exception as quota_err:
            print(f"[Quota] Check error (continuing): {quota_err}")
        
        # Send acknowledgment
        send_to_client(apigw, connection_id, {
            'type': 'status',
            'status': 'processing',
            'message': 'Searching knowledge base...'
        })
        
        # Get or create session
        session = get_or_create_session(session_id, user_id)
        session_id = session['session_id']
        
        # Save user message
        save_message(session_id, 'user', user_message)
        
        # ==========================================================
        # FULL PIPELINE (matching original knowledge-base system)
        # ==========================================================
        
        # Step 1: Get conversation history for context
        print(f"\n{'='*60}")
        print(f"[Pipeline] Processing: {user_message[:100]}...")
        print(f"[Pipeline] Step 1: Fetching conversation history")
        conversation_history = get_conversation_history(session_id, max_messages=10)
        print(f"[Pipeline] Retrieved {len(conversation_history)} history messages")
        
        # Step 2: Enhance query (follow-up detection + pronoun resolution).
        # `enhance_query` may make a small LLM call (gpt-4o-mini, ~150 tokens
        # round-trip) when the query is detected as a follow-up. The returned
        # `usage` dict is captured so it rolls into the single quota_report
        # at the end of the request — no more "ghost" pronoun-resolver spend.
        print(f"[Pipeline] Step 2: Enhancing query")
        processed_query = enhance_query(
            query=user_message,
            context=conversation_history
        )
        search_query = processed_query['search_query']
        enhance_usage = processed_query.get('usage', {
            'input_tokens': 0, 'output_tokens': 0, 'cached_tokens': 0,
            'total_tokens': 0, 'cost_usd': 0.0, 'model': 'none',
        })
        if search_query != user_message:
            print(
                f"[Pipeline] Query enhanced: '{user_message[:60]}' -> "
                f"'{search_query[:60]}' "
                f"(resolver tokens={enhance_usage.get('total_tokens', 0)})"
            )
        else:
            print(f"[Pipeline] Query unchanged (not a follow-up)")
        
        # Step 3: Search Weaviate for 50 chunks (v4 hybrid search with cross-references)
        # BYO vectors — query is embedded inside hybrid_search; usage logged
        # as tier='embedding', record_only=True so it appears in UsageLogs
        # but does not deduct from the user's chat balance.
        print(f"[Pipeline] Step 3: Searching Weaviate (50 chunks, v4 hybrid)")
        search_results = search_knowledge_base(
            search_query,
            top_k=50,
            user_id=user_id,
            request_id=event.get('requestContext', {}).get('requestId'),
            session_id=session_id,
        )
        print(f"[Pipeline] Got {len(search_results)} raw results")
        
        # Step 4: Multi-factor rerank to top 15
        print(f"[Pipeline] Step 4: Reranking {len(search_results)} -> top 15")
        top_chunks = rerank_results(
            query=user_message,
            results=search_results,
            top_k=15
        )
        print(f"[Pipeline] Selected {len(top_chunks)} chunks after reranking")
        
        # Step 5: Build rich context with ContextManager
        print(f"[Pipeline] Step 5: Building rich context with metadata")
        if context_manager is not None:
            kb_context = context_manager.build_kb_context(top_chunks)
        else:
            # Fallback: simple concatenation if ContextManager failed to import
            print("[Pipeline] ⚠️ ContextManager not available, using simple context")
            kb_context = "\n\n".join(
                f"Source: {c.get('document_name', 'Unknown')}\n{c.get('content', '')}"
                for c in top_chunks
            )
        
        # Get sources for citation
        sources = [{'file_name': c.get('document_name', 'Unknown')} for c in top_chunks]
        unique_sources = list({s['file_name']: s for s in sources}.values())
        
        # Send status update
        send_to_client(apigw, connection_id, {
            'type': 'status',
            'status': 'generating',
            'message': f'Found {len(search_results)} results, using top {len(top_chunks)} chunks. Generating response...',
            'sources': unique_sources
        })
        
        # Step 6: Build messages with rich system prompt + conversation history
        print(f"[Pipeline] Step 6: Building OpenAI messages (history={len(conversation_history)} msgs)")

        # Layer 3: wrap retrieved KB context in <UNTRUSTED_*> framing so the
        # LLM treats it as data, not instructions. Falls through to raw
        # kb_context only if the guardrails import failed at cold start.
        if wrap_untrusted_content is not None:
            safe_kb_context = wrap_untrusted_content(
                kb_context, source_label="knowledge base content"
            )
        else:
            safe_kb_context = kb_context

        # Citation-mode selection (see CITATION POLICY block above):
        #   - wants_citations: user explicitly asked for sources / pages
        #   - is_first_turn:   first assistant reply in this session
        # Both are computed BEFORE history is appended so the prompt sees
        # the right state.
        wants_citations = user_wants_citations(user_message)
        is_first_turn = len(conversation_history) == 0
        citation_policy = _select_citation_policy(wants_citations, is_first_turn)
        print(
            f"[Citations] wants_citations={wants_citations} "
            f"is_first_turn={is_first_turn} mode="
            f"{'FULL' if wants_citations else ('FIRST_TURN_HINT' if is_first_turn else 'NATURAL')}"
        )

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            kb_context=safe_kb_context,
            citation_policy=citation_policy,
        )

        # PRIVACY block (Layer 2) goes first — early tokens get the most
        # attention from the model and this is also fixed text, so it
        # improves gpt-4.1 prompt-cache hit rate.
        safety_prompt = guardrails.get_safety_system_prompt() if guardrails else ""

        messages = [{"role": "system", "content": safety_prompt + "\n\n" + system_prompt}]
        
        # Add conversation history for continuity
        for msg in conversation_history:
            messages.append({
                "role": msg['role'],
                "content": msg['content']
            })
        
        # Add current user message
        messages.append({
            "role": "user",
            "content": user_message
        })
        
        # Step 7: Stream with OpenAI (gpt-4.1 by default for cache-discounted
        # big KB system prompt; overridable via OPENAI_CHAT_MODEL env var).
        openai_client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))
        
        temperature = options.get('temperature', 0.7)
        max_tokens = options.get('max_tokens', 2000)
        model = DEFAULT_CHAT_MODEL
        
        print(f"[Pipeline] Step 7: Streaming with {model} (temp={temperature}, max_tokens={max_tokens})")
        
        full_response = ""
        token_count = 0
        stream_usage = None  # Populated from the final chunk when stream_options.include_usage is supported
        
        try:
            stream = openai_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
            
            for chunk in stream:
                # The final chunk has empty choices[] but carries the `usage` block
                # when stream_options={"include_usage": True} is requested.
                if getattr(chunk, "usage", None):
                    stream_usage = chunk.usage

                if not chunk.choices:
                    continue

                if chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_response += token
                    token_count += 1
                    
                    # Send token to client
                    if not send_to_client(apigw, connection_id, {
                        'type': 'token',
                        'content': token,
                        'session_id': session_id
                    }):
                        # Connection closed, stop streaming
                        break
            
            # ── OUTPUT GUARDRAILS ─────────────────────────────────────
            # Check LLM output for prompt leaks, sensitive data, mask PII
            output_check = guardrails.check_output(full_response)
            if output_check.result == GuardrailResult.BLOCKED:
                print(f"[Guardrails] ⚠️ Output blocked: {output_check.reason}")
                full_response = output_check.message or "I found information I shouldn't share. Please rephrase your question."
            elif output_check.result == GuardrailResult.MODIFIED:
                print(f"[Guardrails] Output sanitized (PII masked or prompt leak removed)")
                full_response = output_check.sanitized or full_response
            
            # Save assistant message
            save_message(session_id, 'assistant', full_response, token_count, unique_sources)

            # ── ACCURATE TOKEN COUNTS ────────────────────────────────
            # Prefer the `usage` block from the streaming response (requires
            # stream_options={"include_usage": True} + OpenAI SDK >= 1.26).
            # Fall back to the rough delta-count estimate if unavailable.
            #
            # Per supervisor-agent guide §1, input_tokens INCLUDES cached_tokens.
            # Cached count lives at usage.prompt_tokens_details.cached_tokens.
            cached_tokens_actual = 0
            if stream_usage is not None:
                input_tokens_actual = int(getattr(stream_usage, "prompt_tokens", 0) or 0)
                output_tokens_actual = int(getattr(stream_usage, "completion_tokens", 0) or 0)
                prompt_details = getattr(stream_usage, "prompt_tokens_details", None)
                if prompt_details is not None:
                    cached_tokens_actual = int(getattr(prompt_details, "cached_tokens", 0) or 0)
            else:
                input_tokens_actual = 0
                output_tokens_actual = token_count

            # Use the shared pricing table with the cached-aware formula so
            # cost here matches what the quota service computes server-side.
            try:
                from shared.openai_utils import estimate_cost as _estimate_cost
                estimated_cost = _estimate_cost(
                    input_tokens_actual,
                    output_tokens_actual,
                    model,
                    cached_tokens=cached_tokens_actual,
                )
            except Exception:
                # Shared module unavailable — conservative fallback that still
                # discounts cached tokens at 50% of input (same half-off guess
                # the guide recommends for unknown models).
                _out_rate = 10.0 / 1_000_000
                _in_rate = 2.0 / 1_000_000  # gpt-4.1 default
                _cached_rate = _in_rate * 0.25  # 75% off for gpt-4.1 family
                _non_cached_in = max(input_tokens_actual - cached_tokens_actual, 0)
                estimated_cost = (
                    _non_cached_in * _in_rate
                    + cached_tokens_actual * _cached_rate
                    + output_tokens_actual * _out_rate
                )

            answer_usage = {
                'input_tokens': input_tokens_actual,
                'output_tokens': output_tokens_actual,
                'total_tokens': input_tokens_actual + output_tokens_actual,
                'cached_tokens': cached_tokens_actual,
                'model': model,
                'cost_usd': estimated_cost,
            }

            # NOTE: usage_for_report (the SUM across all LLM calls in this
            # request) is built AFTER the title-generation step below, since
            # title generation is also an LLM call we want to track.
            
            # ── SESSION METADATA UPDATE ──────────────────────────────
            try:
                update_session_metadata(session_id, len(top_chunks), unique_sources)
            except Exception as meta_err:
                print(f"[Session] Metadata update error: {meta_err}")
            
            # Auto-generate session title on first message. This is a small
            # gpt-4o-mini LLM call (~120 tokens round-trip); its usage is
            # captured into `title_usage` so the single quota_report at the
            # end of this request includes the full per-turn cost.
            generated_title = None
            title_usage = {
                'input_tokens': 0, 'output_tokens': 0, 'cached_tokens': 0,
                'total_tokens': 0, 'cost_usd': 0.0, 'model': 'none',
            }
            try:
                current_session = sessions_table.get_item(Key={'session_id': session_id}).get('Item', {})
                msg_count = int(current_session.get('message_count', 0))
                current_title = current_session.get('title', 'New Chat')

                # Generate title only on first exchange (2 messages = 1 user + 1 assistant)
                if msg_count <= 2 and current_title in ('New Chat', '', None):
                    print(f"[AutoTitle] Generating title for session {session_id} (message_count={msg_count})")
                    generated_title, title_usage = generate_session_title(user_message)

                    # Update session title in DynamoDB
                    sessions_table.update_item(
                        Key={'session_id': session_id},
                        UpdateExpression='SET title = :t, updated_at = :ts',
                        ExpressionAttributeValues={
                            ':t': generated_title,
                            ':ts': datetime.utcnow().isoformat()
                        }
                    )
                    print(
                        f"[AutoTitle] Session {session_id} titled: {generated_title} "
                        f"(tokens={title_usage.get('total_tokens', 0)})"
                    )
            except Exception as title_err:
                print(f"[AutoTitle] Error generating title: {title_err}")

            # ── ROLL UP ALL LLM CALLS INTO ONE QUOTA REPORT ──────────
            # Sum: enhance_query (pronoun resolver, may be 0) + main answer
            # streaming + session title (first turn only). Per supervisor-agent
            # guide §1, input_tokens INCLUDES cached_tokens.
            usage_for_report = {
                'input_tokens': int(answer_usage.get('input_tokens', 0) or 0)
                              + int(enhance_usage.get('input_tokens', 0) or 0)
                              + int(title_usage.get('input_tokens', 0) or 0),
                'output_tokens': int(answer_usage.get('output_tokens', 0) or 0)
                               + int(enhance_usage.get('output_tokens', 0) or 0)
                               + int(title_usage.get('output_tokens', 0) or 0),
                'cached_tokens': int(answer_usage.get('cached_tokens', 0) or 0)
                               + int(enhance_usage.get('cached_tokens', 0) or 0)
                               + int(title_usage.get('cached_tokens', 0) or 0),
                'cost_usd': float(answer_usage.get('cost_usd', 0.0) or 0.0)
                          + float(enhance_usage.get('cost_usd', 0.0) or 0.0)
                          + float(title_usage.get('cost_usd', 0.0) or 0.0),
                # Use the answer model as the canonical model for reporting;
                # the per-stage models are recorded in save_log below.
                'model': answer_usage.get('model', 'unknown'),
            }
            usage_for_report['total_tokens'] = (
                usage_for_report['input_tokens'] + usage_for_report['output_tokens']
            )

            # ── QUOTA USAGE REPORTING ────────────────────────────────
            # `metadata` ships per-LLM-stage breakdown so /quota/admin/logs
            # can show "enhance cost X, answer cost Y, title cost Z" the
            # same way KB_Logs does. Title stage may be all zeros if this
            # isn't the first turn of the session.
            try:
                report_usage(
                    user_id,
                    usage_for_report,
                    session_id=session_id,
                    request_id=event.get('requestContext', {}).get('requestId'),
                    duration_ms=(time.time() - pipeline_start_time) * 1000,
                    success=True,
                    prompt_summary=user_message[:200],
                    metadata={
                        'stages': {
                            'enhance': {
                                'model': enhance_usage.get('model'),
                                'input_tokens': int(enhance_usage.get('input_tokens', 0) or 0),
                                'output_tokens': int(enhance_usage.get('output_tokens', 0) or 0),
                                'cached_tokens': int(enhance_usage.get('cached_tokens', 0) or 0),
                                'total_tokens': int(enhance_usage.get('total_tokens', 0) or 0),
                                'cost_usd': float(enhance_usage.get('cost_usd', 0.0) or 0.0),
                            },
                            'answer': {
                                'model': answer_usage.get('model'),
                                'input_tokens': int(answer_usage.get('input_tokens', 0) or 0),
                                'output_tokens': int(answer_usage.get('output_tokens', 0) or 0),
                                'cached_tokens': int(answer_usage.get('cached_tokens', 0) or 0),
                                'total_tokens': int(answer_usage.get('total_tokens', 0) or 0),
                                'cost_usd': float(answer_usage.get('cost_usd', 0.0) or 0.0),
                            },
                            'title': {
                                'model': title_usage.get('model'),
                                'input_tokens': int(title_usage.get('input_tokens', 0) or 0),
                                'output_tokens': int(title_usage.get('output_tokens', 0) or 0),
                                'cached_tokens': int(title_usage.get('cached_tokens', 0) or 0),
                                'total_tokens': int(title_usage.get('total_tokens', 0) or 0),
                                'cost_usd': float(title_usage.get('cost_usd', 0.0) or 0.0),
                            },
                        },
                        'message_length': len(user_message),
                    },
                )
            except Exception as quota_err:
                print(f"[Quota] Usage report error: {quota_err}")
            
            # Send completion message (include generated title if available)
            completion_msg = {
                'type': 'complete',
                'session_id': session_id,
                'full_response': full_response,
                'sources': unique_sources,
                'tokens_used': token_count,
                'model': model
            }
            if generated_title:
                completion_msg['generated_title'] = generated_title
            
            send_to_client(apigw, connection_id, completion_msg)
            
            # Log activity using shared save_log. Schema aligned with
            # supervisor-agent `llm_calls` and matches chat_message.py /
            # kb_query.py shapes so analytics queries can union all three
            # chat surfaces. We log the COMBINED tokens (rolled-up cost) PLUS
            # the per-stage breakdown so per-LLM-call cost is observable.
            duration_ms = (time.time() - pipeline_start_time) * 1000
            try:
                save_log('chat', {
                    'operation': 'chat_stream',
                    'tier': 'chat',
                    'model': model,
                    'enhance_model': enhance_usage.get('model'),
                    'title_model': title_usage.get('model'),
                    'session_id_hash': hash(session_id) % 10000000,
                    'user_id_hash': hash(user_id) % 10000000,
                    'message_length': len(user_message),
                    'answer_length': len(full_response),
                    'chunks_used': len(top_chunks),
                    'tokens_used': usage_for_report['total_tokens'],
                    'input_tokens': usage_for_report['input_tokens'],
                    'output_tokens': usage_for_report['output_tokens'],
                    'cached_tokens': usage_for_report['cached_tokens'],
                    'cost_usd': usage_for_report['cost_usd'],
                    # Per-stage breakdown so dashboards can isolate enhance /
                    # answer / title cost (each is a separate LLM call):
                    'answer_tokens': int(answer_usage.get('total_tokens', 0) or 0),
                    'answer_cost_usd': float(answer_usage.get('cost_usd', 0.0) or 0.0),
                    'enhance_tokens': int(enhance_usage.get('total_tokens', 0) or 0),
                    'enhance_cost_usd': float(enhance_usage.get('cost_usd', 0.0) or 0.0),
                    'title_tokens': int(title_usage.get('total_tokens', 0) or 0),
                    'title_cost_usd': float(title_usage.get('cost_usd', 0.0) or 0.0),
                    'duration_ms': duration_ms,
                    'prompt_summary': user_message[:200],
                    'success': True
                })
            except Exception as log_err:
                print(f"[Log] Activity logging error: {log_err}")

            print(
                f"[Pipeline] ✅ Complete: total_tokens={usage_for_report['total_tokens']} "
                f"(answer={answer_usage.get('total_tokens', 0)}, "
                f"enhance={enhance_usage.get('total_tokens', 0)}, "
                f"title={title_usage.get('total_tokens', 0)}), "
                f"{len(top_chunks)} chunks, model={model}, {duration_ms:.0f}ms"
            )
            print(f"{'='*60}\n")
            
        except Exception as e:
            error_msg = f"OpenAI streaming error: {str(e)}"
            print(error_msg)
            traceback.print_exc()
            send_to_client(apigw, connection_id, {
                'type': 'error',
                'message': error_msg,
                'session_id': session_id
            })
            
            # Log error using shared save_log. Per supervisor-agent guide
            # invariant §8.5 — always log failures (and with the same shape
            # as the success path) so analytics can compute success rate.
            try:
                save_log('chat', {
                    'operation': 'chat_stream',
                    'tier': 'chat',
                    'model': model,
                    'session_id_hash': hash(session_id) % 10000000 if session_id else 0,
                    'duration_ms': (time.time() - pipeline_start_time) * 1000,
                    'prompt_summary': (user_message[:200] if 'user_message' in locals() else None),
                    'success': False,
                    'error': str(e)
                })
            except Exception as log_err:
                print(f"[Log] Error logging failed: {log_err}")
        
        return {'statusCode': 200}
        
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"Error in ws_chat_stream: {error_trace}")
        
        try:
            send_to_client(apigw, connection_id, {
                'type': 'error',
                'message': f"Server error: {str(e)}"
            })
        except:
            pass
        
        return {'statusCode': 500}

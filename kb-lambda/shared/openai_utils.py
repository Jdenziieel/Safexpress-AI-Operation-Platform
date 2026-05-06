"""
OpenAI utilities for Knowledge Base Lambda functions.
Provides chat completion and reranking functionality.

Logging schema aligned with the supervisor-agent `llm_calls` convention:
  input_tokens always INCLUDES cached_tokens (cached is a subset that gets
  the discounted rate). See the model-change / logging guide §1 and §4.
"""
import os
import re
import openai
from typing import List, Dict, Optional, Tuple

# Layer 3 + Layer 7 helpers (second-order injection defense + PRIVACY block).
# Imported lazily-tolerant: if shared/ isn't on sys.path yet (very early cold
# start), fall back to no-op shims so generate_kb_answer still functions.
try:
    from shared.guardrails import (
        strip_injection_delimiters,
        wrap_untrusted_content,
        SFXBotGuardrails,
    )
except ImportError:  # pragma: no cover — defensive only
    def strip_injection_delimiters(text):  # type: ignore
        return text or ""

    def wrap_untrusted_content(text, source_label="untrusted content"):  # type: ignore
        return text or ""

    SFXBotGuardrails = None  # type: ignore

# ─── Citation policy (mirrors ws_chat_stream — keep these in sync) ───────────
# Default behavior: don't force inline [Source: ...] tags on every answer.
# Switch to FULL citation mode only when the user asks for sources / pages
# / proof. On the first turn of a session, append a one-line tip telling
# the user how to get sources.
_CITATION_REQUEST_PATTERN = re.compile(
    r"\b("
    r"cite|citing|citation|citations|"
    r"sources?|references?|bibliography|footnotes?|"
    r"what\s+page|which\s+page|page\s*(?:no\.?|number|num|#)?|"
    r"where\s+(?:is|did|does|do|are)\s+\w[\w\s]{0,30}?(?:from|come\s+from|get|got|find|found)|"
    r"where\s+did\s+(?:you|that|this|it)\s+come\s+from|"
    r"where\s+(?:in|on)\s+(?:the\s+)?(?:doc|document|pdf|file|manual|sop|hse)|"
    r"prove\s+(?:it|that|this)|back\s+(?:this|that|it)\s+up|"
    r"verify|verifiable|verification|"
    r"show\s+(?:me\s+)?(?:the\s+)?(?:source|sources|reference|references|page|pages|proof|evidence)|"
    r"give\s+(?:me\s+)?(?:the\s+)?(?:source|sources|reference|references|citation|citations)|"
    r"evidence"
    r")\b",
    re.IGNORECASE,
)


def _user_wants_citations(message: str) -> bool:
    """True if the user message looks like an explicit ask for sources."""
    if not message:
        return False
    return bool(_CITATION_REQUEST_PATTERN.search(message))


_CITE_MODE_FULL = (
    "Cite sources using [Source: <filename>, Section <section>, Page <page>] "
    "after each distinct claim. Use the values exactly as given in the "
    "context. If a chunk's section is empty, omit the Section part. If page "
    "numbers look wrong (every chunk says \"Page 1\" while the document is "
    "multi-page), say so honestly: \"(page numbers in the knowledge base may "
    "be out of date — please re-upload the document for accurate pages)\". "
    "Do NOT invent page numbers."
)
_CITE_MODE_FIRST_TURN_HINT = (
    "Answer naturally. You may mention document names when it adds clarity, "
    "but do NOT print bracketed [Source: ...] citations. At the very end of "
    "your answer, append exactly this line on its own row (verbatim, "
    "including the leading underscore which renders as italic): "
    "\"_Tip: Want exact sources or page numbers? Just ask 'where is this "
    "from?' and I'll cite them._\". Do NOT add this tip to any other turn."
)
_CITE_MODE_NATURAL = (
    "Answer naturally. You may mention document names when it adds clarity, "
    "but do NOT print bracketed [Source: ...] citations unless the user "
    "asks. If the user later asks 'where is this from', 'what's the "
    "source', or similar, you'll be told to switch to full-citation mode."
)


def _select_citation_policy(wants_citations: bool, is_first_turn: bool) -> str:
    if wants_citations:
        return _CITE_MODE_FULL
    if is_first_turn:
        return _CITE_MODE_FIRST_TURN_HINT
    return _CITE_MODE_NATURAL


# ─── Model selection (per-role, env-driven — see supervisor guide §2) ─────────
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
# Main KB answer (REST /chat/message).  gpt-4.1 has 75% cache discount and a
# 1M context window, which fits the big repeatable KB system prompt.
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4.1')
# Short reranker calls (unique inputs each time → no cache benefit).
# gpt-4o-mini is cheaper than gpt-4.1-mini on cold prompts.
RERANK_MODEL = os.environ.get('RERANK_MODEL', 'gpt-4o-mini')
EMBEDDING_MODEL = os.environ.get('EMBEDDING_MODEL', 'text-embedding-3-small')

# ─── Pricing rate card (USD per 1K tokens) ────────────────────────────────────
# Columns: input / cached_input / output
# Family conventions from the supervisor-agent model-change guide §1 /
# TOKEN_LOGGING_REFERENCE §6.1 (source of truth):
#   gpt-5.4*  → 90% off cached input (current flagship, 2026-04)
#   gpt-5.2 / gpt-5.1 / gpt-5*  → 90% off cached input
#   gpt-4.1*  → 75% off cached input
#   gpt-4o*   → 50% off cached input
#   o1 / o3 / o4-mini  → 50% off cached input (reasoning models — reasoning
#                        tokens are billed as output)
#   *-pro variants  → no cache discount (cached_input == input)
#   gpt-4 / gpt-4-turbo / gpt-3.5-turbo → no cache discount (legacy)
# `default` row tracks OPENAI_MODEL (gpt-4.1) so the unknown-model fallback
# is sane. IMPORTANT: keep in sync with quota-lambda/lambda_quota_report.py
# MODEL_PRICING and quota-lambda/lambda_quota_usage.py MODEL_PRICING.
PRICING = {
    # GPT-5.4 family — current flagship (2026-04). 90% cache discount.
    'gpt-5.4':              {'input': 0.0025,   'cached_input': 0.00025,   'output': 0.015},
    'gpt-5.4-mini':         {'input': 0.00075,  'cached_input': 0.000075,  'output': 0.0045},
    'gpt-5.4-nano':         {'input': 0.0002,   'cached_input': 0.00002,   'output': 0.00125},
    'gpt-5.4-pro':          {'input': 0.03,     'cached_input': 0.03,      'output': 0.18},
    # GPT-5.2 / 5.1 refreshes
    'gpt-5.2':              {'input': 0.00175,  'cached_input': 0.000175,  'output': 0.014},
    'gpt-5.2-pro':          {'input': 0.021,    'cached_input': 0.021,     'output': 0.168},
    'gpt-5.1':              {'input': 0.00125,  'cached_input': 0.000125,  'output': 0.01},
    # GPT-5 launch family (Aug 2025) — 90% cache discount
    'gpt-5':                {'input': 0.00125,  'cached_input': 0.000125,  'output': 0.01},
    'gpt-5-mini':           {'input': 0.00025,  'cached_input': 0.000025,  'output': 0.002},
    'gpt-5-nano':           {'input': 0.00005,  'cached_input': 0.000005,  'output': 0.0004},
    'gpt-5-pro':            {'input': 0.015,    'cached_input': 0.015,     'output': 0.12},
    # GPT-4.1 family (1M context; 75% cache discount)
    'gpt-4.1':              {'input': 0.002,    'cached_input': 0.0005,    'output': 0.008},
    'gpt-4.1-mini':         {'input': 0.0004,   'cached_input': 0.0001,    'output': 0.0016},
    'gpt-4.1-nano':         {'input': 0.0001,   'cached_input': 0.000025,  'output': 0.0004},
    # GPT-4o family (50% cache discount)
    'gpt-4o':               {'input': 0.0025,   'cached_input': 0.00125,   'output': 0.01},
    'gpt-4o-mini':          {'input': 0.00015,  'cached_input': 0.000075,  'output': 0.0006},
    # Reasoning models — reasoning tokens billed as output
    'o1':                   {'input': 0.015,    'cached_input': 0.0075,    'output': 0.06},
    'o1-pro':               {'input': 0.15,     'cached_input': 0.15,      'output': 0.6},
    'o1-mini':              {'input': 0.0011,   'cached_input': 0.00055,   'output': 0.0044},
    'o3':                   {'input': 0.002,    'cached_input': 0.0005,    'output': 0.008},
    'o3-mini':              {'input': 0.0011,   'cached_input': 0.00055,   'output': 0.0044},
    'o3-pro':               {'input': 0.02,     'cached_input': 0.02,      'output': 0.08},
    'o4-mini':              {'input': 0.0011,   'cached_input': 0.000275,  'output': 0.0044},
    # Legacy (no prompt caching)
    'gpt-4':                {'input': 0.03,     'cached_input': 0.03,      'output': 0.06},
    'gpt-4-turbo':          {'input': 0.01,     'cached_input': 0.01,      'output': 0.03},
    'gpt-3.5-turbo':        {'input': 0.0005,   'cached_input': 0.0005,    'output': 0.0015},
    # Embedding models (used for vector search; not LLMs — output rate is 0)
    'text-embedding-3-small': {'input': 0.00002, 'cached_input': 0.00002, 'output': 0},
    'text-embedding-3-large': {'input': 0.00013, 'cached_input': 0.00013, 'output': 0},
    # Fallback: tracks OPENAI_MODEL so misconfigured models still bill plausibly.
    'default':              {'input': 0.002,    'cached_input': 0.0005,    'output': 0.008},
}

# Singleton client
_client = None


def get_openai_client() -> openai.OpenAI:
    """Get or create OpenAI client."""
    global _client
    
    if _client is None:
        if not OPENAI_API_KEY:
            raise Exception("OPENAI_API_KEY not configured")
        _client = openai.OpenAI(api_key=OPENAI_API_KEY)
    
    return _client


# ─── Embeddings (BYO vectors for Weaviate, see weaviate_utils.py) ─────────────
# OpenAI's /v1/embeddings endpoint accepts up to 2048 inputs per request and
# 8192 tokens per input. We batch defensively at 1000 inputs per request to
# stay well under the limit and to keep individual response payloads small
# (each 1536-dim vector ≈ 6KB JSON, so 1000 ≈ 6MB which is fine for HTTPS).
_EMBED_BATCH_SIZE = 1000


def embed_texts(
    texts: List[str],
    model: str = None,
) -> Tuple[List[List[float]], int]:
    """
    Generate embeddings for a list of texts via OpenAI's embeddings API.
    
    Returns:
        Tuple of (vectors, prompt_tokens). prompt_tokens is the EXACT count
        from OpenAI's response.usage (not an estimate), suitable for direct
        UsageLogs reporting at the same fidelity as chat completion calls.
    
    Behavior:
      - Empty/whitespace-only inputs are coerced to a single space ' ' so
        OpenAI's API accepts them. The resulting vector is near-zero — those
        chunks won't match anything in vector search, which is the correct
        behavior for empty content anyway.
      - Inputs are batched in groups of 1000 (well under OpenAI's 2048
        per-request limit) so very large uploads don't trip the API.
      - Output vector order matches input order across batches.
    
    Used by weaviate_utils for both chunk embedding (upload path) and
    query embedding (search path) under the BYO-vector design.
    """
    if not texts:
        return [], 0
    
    embedding_model = model or EMBEDDING_MODEL
    
    # OpenAI rejects empty strings; whitespace-only also triggers errors on
    # some accounts. Coerce defensively — a near-zero vector is preferable
    # to a 400 that breaks the whole batch. The (t or '') guard also turns
    # None into '' so callers can blindly pass chunk dicts without first
    # validating that 'text' is a string.
    safe_texts = [((t or '').strip() or ' ') for t in texts]
    
    client = get_openai_client()
    all_vectors: List[List[float]] = []
    total_tokens = 0
    
    for batch_start in range(0, len(safe_texts), _EMBED_BATCH_SIZE):
        batch = safe_texts[batch_start:batch_start + _EMBED_BATCH_SIZE]
        response = client.embeddings.create(model=embedding_model, input=batch)
        # response.data is in input order (per OpenAI's spec); preserve it.
        all_vectors.extend(d.embedding for d in response.data)
        # Embeddings have only prompt_tokens (no output) — matches the
        # PRICING table where output rate is 0 for embedding models.
        total_tokens += int(getattr(response.usage, 'prompt_tokens', 0) or 0)
    
    return all_vectors, total_tokens


def get_model_pricing(model: str) -> Dict[str, float]:
    """
    Resolve pricing for a model, falling back to the `default` row for
    unknown models. Guarantees a `cached_input` key is always present
    (falls back to input * 0.5 for rows without one, per guide §4).
    """
    rates = PRICING.get(model) or PRICING['default']
    if 'cached_input' not in rates:
        rates = {**rates, 'cached_input': rates['input'] * 0.5}
    return rates


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str = None,
    cached_tokens: int = 0,
) -> float:
    """
    Estimate cost for an LLM call using the supervisor-agent guide §4 formula:

        non_cached_input = max(input_tokens - cached_tokens, 0)
        cost = (non_cached_input * input_rate
              + cached_tokens     * cached_rate
              + output_tokens     * output_rate) / 1000

    Invariant: `input_tokens` INCLUDES cached tokens (OpenAI bills the same
    prompt_tokens number; cached_tokens is a subset that gets the discount).
    Do not subtract cached from input anywhere outside this formula.
    """
    model = model or OPENAI_MODEL
    rates = get_model_pricing(model)

    cached = max(int(cached_tokens or 0), 0)
    non_cached_input = max(int(input_tokens or 0) - cached, 0)

    return (
        (non_cached_input * rates['input'])
        + (cached * rates['cached_input'])
        + (int(output_tokens or 0) * rates['output'])
    ) / 1000.0


def _extract_cached_tokens(usage) -> int:
    """
    Pull cached_tokens out of OpenAI's response.usage object.

    For the raw `openai` SDK, cached count lives at
    `usage.prompt_tokens_details.cached_tokens`. Returns 0 if absent
    (older SDK, non-caching model, or cache miss).
    """
    if usage is None:
        return 0
    details = getattr(usage, 'prompt_tokens_details', None)
    if details is None:
        # Fall back to dict-style access (LangChain passes a plain dict).
        if isinstance(usage, dict):
            details = usage.get('prompt_tokens_details', {}) or {}
        else:
            return 0
    if isinstance(details, dict):
        return int(details.get('cached_tokens', 0) or 0)
    return int(getattr(details, 'cached_tokens', 0) or 0)


def chat_completion(
    messages: List[Dict],
    model: str = None,
    temperature: float = 0.7,
    max_tokens: int = 2000
) -> Tuple[str, Dict]:
    """
    Generate chat completion.
    
    Returns:
        Tuple of (response_text, usage_dict). usage_dict keys:
            input_tokens, output_tokens, total_tokens, cached_tokens,
            model, cost_usd
    """
    client = get_openai_client()
    model = model or OPENAI_MODEL
    
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens
    )
    
    content = response.choices[0].message.content
    
    input_tokens = response.usage.prompt_tokens
    output_tokens = response.usage.completion_tokens
    cached_tokens = _extract_cached_tokens(response.usage)
    
    usage = {
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'total_tokens': response.usage.total_tokens,
        'cached_tokens': cached_tokens,
        'model': model,
        'cost_usd': estimate_cost(
            input_tokens,
            output_tokens,
            model,
            cached_tokens=cached_tokens,
        ),
    }
    
    return content, usage


def generate_kb_answer(
    query: str,
    context_chunks: List[Dict],
    conversation_history: List[Dict] = None
) -> Tuple[str, List[Dict], Dict]:
    """
    Generate answer from knowledge base context.
    
    Args:
        query: User's question
        context_chunks: Retrieved KB chunks with text and metadata
        conversation_history: Optional previous messages
        
    Returns:
        Tuple of (answer, sources_used, usage_dict)
    """
    # Build context string. Each chunk's body is run through
    # strip_injection_delimiters() so role markers / OpenAI control tokens
    # planted in source documents can't flip our prompt structure.
    context_parts = []
    sources = []

    for i, chunk in enumerate(context_chunks[:10]):  # Limit to top 10 chunks
        text = strip_injection_delimiters(
            chunk.get('text', chunk.get('content', ''))
        )
        section = chunk.get('section', 'Unknown')
        page = chunk.get('page', 'N/A')
        file_name = chunk.get('file_name', 'Unknown')

        context_parts.append(
            f"[Source {i+1}: {file_name}, Section: {section}, Page {page}]\n{text}"
        )

        sources.append({
            'index': i + 1,
            'file_name': file_name,
            'section': section,
            'page': page,
            'doc_id': chunk.get('doc_id'),
            'chunk_id': chunk.get('chunk_id'),
            'score': chunk.get('score')
        })

    context_text = "\n\n---\n\n".join(context_parts)

    # Wrap the joined context in <UNTRUSTED_KNOWLEDGE_BASE_CONTENT> so the
    # LLM treats it as data, not instructions (Layer 3, guardrails.md §6).
    safe_context = wrap_untrusted_content(
        context_text, source_label="knowledge base content"
    )

    # PRIVACY block (Layer 2 + Layer 7) goes FIRST — model attends most
    # strongly to early system tokens, and this block is fixed text so it
    # also boosts gpt-4.1 prompt-cache hit rate.
    privacy_block = (
        SFXBotGuardrails().get_safety_system_prompt()
        if SFXBotGuardrails is not None
        else ""
    )

    # Citation mode is selected per-turn (see CITATION POLICY below). The
    # streaming path (ws_chat_stream) has the same logic — keep these in
    # sync if you change the rules.
    wants_citations = _user_wants_citations(query)
    is_first_turn = not conversation_history
    citation_policy = _select_citation_policy(wants_citations, is_first_turn)

    system_prompt = privacy_block + f"""

=== KB ANSWERING RULES ===
You are an assistant for a company's knowledge base. You answer questions
based ONLY on the provided context from company documents.

Guidelines:
1. Answer based solely on the provided context
2. {citation_policy}
3. If information isn't in the context, say so clearly
4. Summarize across multiple sources when relevant
5. Be concise but thorough

If the answer is not found in the provided documents, respond:
"I couldn't find specific information about this in the knowledge base. Please try rephrasing your question or contact the relevant department."
"""

    messages = [{"role": "system", "content": system_prompt}]

    if conversation_history:
        for msg in conversation_history[-6:]:  # Last 6 messages for context
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", "")
            })

    user_message = f"""Context from Knowledge Base:
{safe_context}

---

User Question: {query}

Please provide a helpful answer based on the context above."""

    messages.append({"role": "user", "content": user_message})

    answer, usage = chat_completion(messages)

    return answer, sources, usage


def _zero_usage(model: str = 'none') -> Dict:
    """Empty usage dict for code paths that didn't make an LLM call."""
    return {
        'input_tokens': 0,
        'output_tokens': 0,
        'cached_tokens': 0,
        'total_tokens': 0,
        'cost_usd': 0.0,
        'model': model,
    }


def _usage_from_response(response, model: str) -> Dict:
    """Build a standard usage dict from an OpenAI ChatCompletion response."""
    usage = getattr(response, 'usage', None)
    if usage is None:
        return _zero_usage(model)
    input_tokens = int(getattr(usage, 'prompt_tokens', 0) or 0)
    output_tokens = int(getattr(usage, 'completion_tokens', 0) or 0)
    cached_tokens = 0
    prompt_details = getattr(usage, 'prompt_tokens_details', None)
    if prompt_details is not None:
        cached_tokens = int(getattr(prompt_details, 'cached_tokens', 0) or 0)
    cost = estimate_cost(input_tokens, output_tokens, model, cached_tokens=cached_tokens)
    return {
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'cached_tokens': cached_tokens,
        'total_tokens': input_tokens + output_tokens,
        'cost_usd': cost,
        'model': model,
    }


def rerank_chunks(
    query: str,
    chunks: List[Dict],
    top_n: int = 5,
) -> Tuple[List[Tuple[Dict, float]], Dict]:
    """
    Rerank chunks using OpenAI for better relevance.

    Uses RERANK_MODEL (env, default `gpt-4o-mini`). Inputs are unique per
    call (no caching benefit), so the cheaper mini family wins here.

    Returns:
        Tuple of (reranked_chunks, usage_dict). The usage dict is always
        present so callers can roll it into a single quota_report.
        On error or when chunks is empty, usage is the zero-shape so the
        caller's sum is unaffected.
    """
    if not chunks:
        return [], _zero_usage(RERANK_MODEL)

    client = get_openai_client()

    # Build reranking prompt
    chunk_texts = []
    for i, chunk in enumerate(chunks[:20]):  # Limit to 20 for reranking
        text = chunk.get('text', chunk.get('content', ''))[:500]  # Truncate
        chunk_texts.append(f"[{i}] {text}")

    prompt = f"""Given the query: "{query}"

Rate the relevance of each text chunk on a scale of 0-10 (10 = highly relevant).
Return ONLY a JSON array of scores in order, e.g., [8, 3, 9, 5, ...]

Chunks:
{chr(10).join(chunk_texts)}

Scores:"""

    try:
        response = client.chat.completions.create(
            model=RERANK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=200
        )

        usage = _usage_from_response(response, RERANK_MODEL)

        import json
        scores_text = response.choices[0].message.content.strip()
        # Extract JSON array
        if '[' in scores_text:
            start = scores_text.index('[')
            end = scores_text.rindex(']') + 1
            scores = json.loads(scores_text[start:end])
        else:
            # Fallback: use original order
            scores = list(range(len(chunks), 0, -1))

        # Pair chunks with scores
        scored_chunks = []
        for i, chunk in enumerate(chunks[:len(scores)]):
            score = scores[i] if i < len(scores) else 0
            scored_chunks.append((chunk, float(score)))

        # Sort by score descending
        scored_chunks.sort(key=lambda x: x[1], reverse=True)

        return scored_chunks[:top_n], usage

    except Exception as e:
        print(f"Reranking error: {e}")
        # Fallback: return top chunks in original order, with zero usage
        # since the call failed (the caller's quota_report should still
        # capture this as a zero-cost rerank).
        return [(chunk, 1.0) for chunk in chunks[:top_n]], _zero_usage(RERANK_MODEL)


def check_openai_connection() -> bool:
    """
    Check if OpenAI API is accessible.
    
    Returns:
        bool: True if API is working
    """
    try:
        client = get_openai_client()
        # Simple test call
        client.models.list()
        return True
    except Exception as e:
        print(f"OpenAI connection error: {e}")
        return False

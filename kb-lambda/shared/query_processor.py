"""
Query Processor for Knowledge Base Lambda functions.

Handles query enhancement (follow-up detection, pronoun resolution)
and multi-factor result reranking.

Ported from original knowledge-base/services/query_processor.py to maintain
the robust chat pipeline that was lost during Lambda migration.
"""
import os
import openai
from typing import Dict, List

# Pronoun / follow-up resolver model. Per supervisor-agent model-change guide
# §2: this is a short, every-prompt-is-unique call (conversation context
# differs each turn) — prompt caching won't help. gpt-4o-mini wins on cold
# cost ($0.00015 / 1K input) so we keep it here and make it env-overridable.
QUERY_RESOLVER_MODEL = os.environ.get('QUERY_RESOLVER_MODEL', 'gpt-4o-mini')

# Singleton OpenAI client
_openai_client = None


def _get_openai_client():
    """Get or create OpenAI client."""
    global _openai_client
    if _openai_client is None:
        api_key = os.environ.get('OPENAI_API_KEY', '')
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
        _openai_client = openai.OpenAI(api_key=api_key)
    return _openai_client


_ZERO_USAGE = {
    'input_tokens': 0,
    'output_tokens': 0,
    'cached_tokens': 0,
    'total_tokens': 0,
    'cost_usd': 0.0,
    'model': 'none',
}


def enhance_query(query: str, context: List[Dict]) -> Dict:
    """
    Enhance user query with context and extract search terms.
    If there's conversation context and the query is a follow-up,
    resolve pronouns and references to make the query standalone.

    Args:
        query: The user's raw query
        context: List of recent conversation messages [{'role': ..., 'content': ...}]

    Returns:
        Dict with original_query, resolved_query, search_query, and `usage`.
        `usage` is the token / cost dict for any LLM call made during
        resolution (zero-shape when no LLM call happened) so callers can
        roll it into a single `quota_report` per request.
    """
    # If there's context, check for follow-up patterns
    if context and _is_followup(query):
        resolved_query, usage = _resolve_references(query, context)
    else:
        resolved_query = query
        usage = dict(_ZERO_USAGE)

    return {
        'original_query': query,
        'resolved_query': resolved_query,
        'search_query': resolved_query,
        'usage': usage,
    }


def _is_followup(query: str) -> bool:
    """
    Check if query is a follow-up question that needs context resolution.
    Uses pattern matching and pronoun detection.
    """
    followup_patterns = [
        # Original patterns
        'what about', 'how about', 'tell me more',
        'can you explain', 'what does that mean',
        'elaborate', 'more details', 'continue',
        'and that', 'about it', 'about that',
        'the same', 'similar',
        
        # Questions asking for more
        'explain further', 'go deeper', 'more on',
        'expand on', 'clarify', 'break down',
        
        # Comparative follow-ups
        'compared to', 'versus', 'difference between',
        'what\'s the difference', 'how does that differ',
        
        # Continuation patterns
        'also', 'additionally', 'furthermore',
        'what else', 'anything else', 'what more',
        
        # Specific aspect requests
        'what part', 'which section', 'where in',
        'show me the', 'find the part where',
        
        # Clarification requests
        'i don\'t understand', 'confused about',
        'what did you mean', 'can you rephrase'
    ]
    query_lower = query.lower()
    
    # Enhanced pronoun detection (including possessives)
    pronouns = ['it', 'that', 'this', 'those', 'these', 'they', 'them', 'its', 'their', 'theirs']
    words = query_lower.split()
    has_pronoun = any(word in pronouns for word in words)
    
    # Check for follow-up patterns
    has_pattern = any(pattern in query_lower for pattern in followup_patterns)
    
    # Detect very short questions (likely follow-ups)
    is_very_short = len(words) <= 4 and ('?' in query or has_pronoun)
    
    return has_pronoun or has_pattern or is_very_short


def _resolve_references(query: str, context: List[Dict]):
    """
    Resolve ambiguous references (pronouns, "it", "that", etc.)
    using conversation context via GPT-4o-mini.

    Returns:
        Tuple of (resolved_query, usage_dict). usage_dict matches the
        shared shape so callers can sum it into a single quota_report.
    """
    last_messages = context[-4:] if len(context) >= 4 else context

    if not last_messages:
        return query, dict(_ZERO_USAGE)

    context_text = "\n".join([
        f"{msg['role']}: {msg['content']}"
        for msg in last_messages
    ])

    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model=QUERY_RESOLVER_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Rewrite the user's query to be standalone by resolving pronouns and references using the conversation context. Keep it concise and preserve the question's intent."
                },
                {
                    "role": "user",
                    "content": f"Conversation context:\n{context_text}\n\nQuery to resolve: {query}\n\nStandalone query:"
                }
            ],
            temperature=0,
            max_tokens=100
        )

        resolved = response.choices[0].message.content.strip()
        usage = _usage_from_resolver_response(response, QUERY_RESOLVER_MODEL)
        print(f"[QueryProcessor] Resolved '{query}' -> '{resolved}' "
              f"(tokens={usage['total_tokens']}, ${usage['cost_usd']:.6f})")
        return resolved, usage

    except Exception as e:
        print(f"[QueryProcessor] Error resolving query: {e}")
        return query, dict(_ZERO_USAGE)


def _usage_from_resolver_response(response, model: str) -> Dict:
    """Build a usage dict from the resolver's OpenAI response.

    Mirrors `openai_utils._usage_from_response` but lives here so this
    module stays standalone (kb-lambda Lambdas import them from different
    paths). Cost uses the shared `estimate_cost` if available, else a
    conservative gpt-4o-mini fallback.
    """
    usage = getattr(response, 'usage', None)
    if usage is None:
        return dict(_ZERO_USAGE)
    input_tokens = int(getattr(usage, 'prompt_tokens', 0) or 0)
    output_tokens = int(getattr(usage, 'completion_tokens', 0) or 0)
    cached_tokens = 0
    prompt_details = getattr(usage, 'prompt_tokens_details', None)
    if prompt_details is not None:
        cached_tokens = int(getattr(prompt_details, 'cached_tokens', 0) or 0)

    # Cost: prefer the shared formula so all 3 quota tables stay in sync.
    try:
        from shared.openai_utils import estimate_cost as _estimate_cost
        cost = _estimate_cost(
            input_tokens, output_tokens, model, cached_tokens=cached_tokens
        )
    except Exception:
        # Fallback: gpt-4o-mini @ $0.00015 / $0.0006 per 1K tokens
        in_rate, cached_rate, out_rate = 0.00015, 0.000075, 0.0006
        non_cached = max(input_tokens - cached_tokens, 0)
        cost = (non_cached * in_rate + cached_tokens * cached_rate
                + output_tokens * out_rate) / 1000.0

    return {
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'cached_tokens': cached_tokens,
        'total_tokens': input_tokens + output_tokens,
        'cost_usd': cost,
        'model': model,
    }


def rerank_results(query: str, results: List[Dict], top_k: int = 15) -> List[Dict]:
    """
    Rerank search results using multi-factor scoring:
    - Weaviate hybrid score (35% weight)
    - Query-specific section/context match (25% weight)
    - Tags match (15% weight)
    - Content type preference (15% weight)
    - Text length preference (15% weight)
    
    Includes deduplication and low-relevance filtering.
    
    Args:
        query: The user's query
        results: Raw search results from Weaviate
        top_k: Number of top results to return (default 15)
        
    Returns:
        List of reranked and filtered results
    """
    if not results:
        return []
    
    # STEP 0: Deduplicate results by text content (hash first 500 chars)
    seen_content = set()
    unique_results = []
    for result in results:
        text = result.get('text', '')[:500].strip()
        content_key = hash(text)
        if content_key not in seen_content:
            seen_content.add(content_key)
            unique_results.append(result)
    
    dedup_count = len(results) - len(unique_results)
    if dedup_count > 0:
        print(f"[QueryProcessor] Removed {dedup_count} duplicate chunks ({len(results)} -> {len(unique_results)})")
    
    results = unique_results
    print(f"[QueryProcessor] Reranking {len(results)} results")
    
    # Extract query keywords (remove common stop words)
    query_lower = query.lower()
    stop_words = {
        'the', 'a', 'an', 'in', 'on', 'at', 'to', 'for', 'of', 'and', 'or', 'but',
        'is', 'are', 'was', 'were', 'can', 'you', 'me', 'about', 'tell', 'what', 'how',
        'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might',
        'i', 'my', 'we', 'our', 'your', 'it', 'its', 'be', 'been', 'being', 'have', 'has'
    }
    query_words = set(word for word in query_lower.split() if word not in stop_words and len(word) > 2)
    
    # Score each result with multiple factors
    for result in results:
        base_score = result.get('score', 0.5)
        
        # Factor 1: Base Weaviate score (35% weight)
        score_component = base_score * 0.35
        
        # Factor 2: Enhanced Section Matching with Hierarchy (25% weight)
        section = result.get('section', '').lower()
        section_title = result.get('section_title', '').lower()
        parent_section = result.get('parent_section', '').lower()
        context_info = result.get('context', '').lower()
        text = result.get('text', '').lower()
        
        section_match = 0.0
        
        # Match against section title (most descriptive)
        if section_title and any(word in section_title for word in query_words if len(word) > 3):
            section_match = 0.8
        
        # Match against parent section (for subsection content)
        elif parent_section:
            parent_title = ''
            for r in results:
                if r.get('section', '') == parent_section:
                    parent_title = r.get('section_title', '').lower()
                    break
            if parent_title and any(word in parent_title for word in query_words if len(word) > 3):
                section_match = 0.7
        
        # Match against context
        if context_info and any(word in context_info for word in query_words if len(word) > 3):
            section_match = max(section_match, 0.6)
        
        # Fallback: Check if keywords appear in chunk text
        if section_match == 0 and any(word in text[:300] for word in query_words if len(word) > 4):
            section_match = 0.4
        
        section_component = section_match * 0.25
        
        # Factor 3: Tags match (15% weight)
        tags = result.get('tags', [])
        tags_match = 0.0
        if tags and query_words:
            tags_lower = [str(tag).lower() for tag in tags]
            matching_tags = sum(1 for word in query_words if any(word in tag for tag in tags_lower))
            if matching_tags > 0:
                tags_match = min(matching_tags / len(query_words), 1.0)
        
        tags_component = tags_match * 0.15
        
        # Factor 4: Content type preference (15% weight)
        chunk_type = result.get('chunk_type', 'text').lower()
        text_length = len(result.get('text', ''))
        
        type_score = 0.0
        if chunk_type in ['paragraph', 'text'] and text_length > 200:
            type_score = 1.0  # Detailed paragraphs are best
        elif chunk_type in ['list', 'table']:
            type_score = 0.9  # Lists and tables have structured info
        elif chunk_type == 'heading':
            if text_length < 100:
                # Heavily penalize short headers when details are requested
                detail_words = ['about', 'tell', 'what', 'how', 'explain', 'describe', 'detail']
                if any(word in query_lower for word in detail_words):
                    type_score = 0.1
                else:
                    type_score = 0.3
            else:
                type_score = 0.5
        else:
            type_score = 0.7
        
        type_component = type_score * 0.15
        
        # Factor 5: Text length preference (15% weight)
        length_score = min(text_length / 1000.0, 1.0)
        length_component = length_score * 0.15
        
        # Calculate final rerank score
        rerank_score = score_component + section_component + tags_component + type_component + length_component
        
        result['original_score'] = base_score
        result['rerank_score'] = rerank_score
    
    # Sort by rerank score
    sorted_results = sorted(results, key=lambda x: x.get('rerank_score', 0), reverse=True)
    
    # Filter out low-relevance results (score threshold) but keep at least top 5
    min_score_threshold = 0.20
    filtered_results = []
    for i, result in enumerate(sorted_results):
        score = result.get('rerank_score', 0)
        if score >= min_score_threshold or i < 5:
            filtered_results.append(result)
    
    if len(filtered_results) < len(sorted_results):
        print(f"[QueryProcessor] Filtered out {len(sorted_results) - len(filtered_results)} low-relevance chunks (below {min_score_threshold})")
    
    top = filtered_results[:top_k]
    
    # Log top results
    for i, r in enumerate(top[:5]):
        doc = r.get('document_name', 'Unknown')
        page = r.get('page', 'N/A')
        orig = r.get('original_score', 0)
        new = r.get('rerank_score', 0)
        ctype = r.get('chunk_type', 'text')
        print(f"[QueryProcessor] #{i+1}: {doc} p{page} | {orig:.3f} -> {new:.3f} | {ctype}")
    
    return top

"""
OpenAI utilities for Knowledge Base Lambda functions.
Provides chat completion and reranking functionality.
"""
import os
import openai
from typing import List, Dict, Optional, Tuple

# OpenAI configuration
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
EMBEDDING_MODEL = os.environ.get('EMBEDDING_MODEL', 'text-embedding-3-small')

# Pricing per 1M tokens (approximate)
PRICING = {
    'gpt-4o-mini': {'input': 0.15, 'output': 0.60},
    'gpt-4o': {'input': 2.50, 'output': 10.00},
    'gpt-4-turbo': {'input': 10.00, 'output': 30.00},
    'text-embedding-3-small': {'input': 0.02, 'output': 0},
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


def estimate_cost(input_tokens: int, output_tokens: int, model: str = None) -> float:
    """
    Estimate cost for token usage.
    
    Args:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        model: Model name (default from env)
        
    Returns:
        float: Estimated cost in USD
    """
    model = model or OPENAI_MODEL
    pricing = PRICING.get(model, PRICING['gpt-4o-mini'])
    
    input_cost = (input_tokens / 1_000_000) * pricing['input']
    output_cost = (output_tokens / 1_000_000) * pricing['output']
    
    return input_cost + output_cost


def chat_completion(
    messages: List[Dict],
    model: str = None,
    temperature: float = 0.7,
    max_tokens: int = 2000
) -> Tuple[str, Dict]:
    """
    Generate chat completion.
    
    Args:
        messages: List of message dicts with 'role' and 'content'
        model: Model to use
        temperature: Sampling temperature
        max_tokens: Maximum response tokens
        
    Returns:
        Tuple of (response_text, usage_dict)
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
    
    usage = {
        'input_tokens': response.usage.prompt_tokens,
        'output_tokens': response.usage.completion_tokens,
        'total_tokens': response.usage.total_tokens,
        'model': model,
        'cost_usd': estimate_cost(
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
            model
        )
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
    # Build context string
    context_parts = []
    sources = []
    
    for i, chunk in enumerate(context_chunks[:10]):  # Limit to top 10 chunks
        text = chunk.get('text', chunk.get('content', ''))
        section = chunk.get('section', 'Unknown')
        page = chunk.get('page', 'N/A')
        file_name = chunk.get('file_name', 'Unknown')
        
        context_parts.append(f"[Source {i+1}: {file_name}, Section: {section}, Page {page}]\n{text}")
        
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
    
    # System prompt
    system_prompt = """You are an assistant for a company's knowledge base. You answer questions based ONLY on the provided context from company documents.

Guidelines:
1. Answer based solely on the provided context
2. Cite sources using [Source X] notation
3. If information isn't in the context, say so clearly
4. Summarize across multiple sources when relevant
5. Be concise but thorough

If the answer is not found in the provided documents, respond:
"I couldn't find specific information about this in the knowledge base. Please try rephrasing your question or contact the relevant department."
"""
    
    # Build messages
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add conversation history if provided
    if conversation_history:
        for msg in conversation_history[-6:]:  # Last 6 messages for context
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", "")
            })
    
    # Add current query with context
    user_message = f"""Context from Knowledge Base:
{context_text}

---

User Question: {query}

Please provide a helpful answer based on the context above."""
    
    messages.append({"role": "user", "content": user_message})
    
    # Generate response
    answer, usage = chat_completion(messages)
    
    return answer, sources, usage


def rerank_chunks(query: str, chunks: List[Dict], top_n: int = 5) -> List[Tuple[Dict, float]]:
    """
    Rerank chunks using OpenAI for better relevance.
    
    Args:
        query: Search query
        chunks: List of chunks to rerank
        top_n: Number of top results to return
        
    Returns:
        List of (chunk, score) tuples, sorted by relevance
    """
    if not chunks:
        return []
    
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
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=200
        )
        
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
        
        return scored_chunks[:top_n]
        
    except Exception as e:
        print(f"Reranking error: {e}")
        # Fallback: return top chunks in original order
        return [(chunk, 1.0) for chunk in chunks[:top_n]]


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

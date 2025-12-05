# Knowledge Base Query System Design

## Overview

This system is designed for **querying and exploring uploaded PDF documents** through a conversational interface. Unlike a general chatbot, every response must be **grounded in the knowledge base** - the uploaded PDFs and their extracted chunks. The core purpose is document retrieval, analysis, and synthesis, not general conversation.

### Core Principles
1. **KB-First**: All answers must come from uploaded documents
2. **Transparency**: Always show which document/page the answer comes from
3. **Accuracy over Creativity**: Cite exact text, don't hallucinate
4. **Multi-Document**: Query across multiple uploaded PDFs
5. **Conversational Refinement**: Follow-up questions to dig deeper into documents

---

## Architecture Layers

### 1. **Document Management Layer**
Handles uploaded PDFs, their metadata, and indexing status.

### 2. **Query Processing Layer**
Interprets user queries in the context of available documents.

### 3. **Retrieval Layer**
Searches across documents using hybrid search (semantic + keyword).

### 4. **Answer Synthesis Layer**
Generates responses strictly from retrieved document chunks.

### 5. **Session Layer**
Maintains query history for contextual follow-ups within document exploration.

---

## Core Query Types (KB-Specific)

### Document Exploration Queries
```python
class KBQueryType(Enum):
    # Direct document queries
    FIND_INFORMATION = "find"          # "What does the document say about X?"
    COMPARE_DOCUMENTS = "compare"       # "How do doc A and B differ on X?"
    SUMMARIZE = "summarize"            # "Summarize the findings in doc X"
    
    # Citation and verification
    FIND_QUOTE = "quote"               # "Find the exact quote about X"
    VERIFY_CLAIM = "verify"            # "Does any document mention X?"
    GET_SOURCE = "source"              # "Which document/page is this from?"
    
    # Cross-document analysis
    SYNTHESIZE = "synthesize"          # "What do all documents say about X?"
    FIND_CONTRADICTIONS = "contradiction" # "Do any documents contradict each other?"
    
    # Navigation and exploration
    LIST_DOCUMENTS = "list"            # "What documents are available?"
    FIND_SECTIONS = "sections"         # "Show all sections about X"
    FOLLOW_UP = "followup"             # "Tell me more about that"
    
    # Out of scope
    OUT_OF_KB = "out_of_kb"           # Question not answerable from KB
```

### Key Difference from General Chat
Every query type expects a **document-backed answer**. No creative generation, only information retrieval and synthesis.

---

## Database Schema Design

### Document Registry Table
```python
{
  "document_id": "uuid",
  "filename": "research_paper.pdf",
  "upload_timestamp": "2025-01-17T14:30:00Z",
  "page_count": 25,
  "chunk_count": 150,
  "status": "indexed|processing|failed",
  "metadata": {
    "file_size_bytes": 2500000,
    "processing_time_ms": 45000,
    "main_topics": ["machine learning", "neural networks"],
    "document_type": "research|report|manual|other"
  }
}
```

### Query Session Table
```python
{
  "session_id": "uuid",
  "user_id": "string",
  "created_at": "timestamp",
  "last_active": "timestamp",
  "focused_documents": ["doc-id-1", "doc-id-2"],  # Documents user is exploring
  "query_count": 15,
  "metadata": {
    "exploration_path": ["topic_A", "topic_B"],  # Topics explored in order
    "session_type": "single_doc|multi_doc|comparative"
  }
}
```

### Query History Table
```python
{
  "query_id": "uuid",
  "session_id": "uuid",
  "query_text": "What are the main findings?",
  "query_type": "find_information",
  "timestamp": "timestamp",
  "results": {
    "chunks_retrieved": 5,
    "documents_referenced": ["doc-1", "doc-2"],
    "answer_generated": true,
    "confidence_score": 0.87
  },
  "metadata": {
    "processing_time_ms": 1850,
    "tokens_used": 1500,
    "cache_hit": false,
    "user_feedback": "helpful|not_helpful|null"
  }
}
```

### Document Access Log
```python
{
  "log_id": "uuid",
  "session_id": "uuid",
  "document_id": "uuid",
  "accessed_at": "timestamp",
  "access_type": "query|download|view",
  "chunks_accessed": ["chunk-1", "chunk-2"],  # Which parts were retrieved
  "pages_referenced": [5, 6, 12]
}
```

---

## API Design

### 1. List Available Documents
```http
GET /documents
```

**Purpose:** Show what's in the knowledge base

**Response:**
```json
{
  "documents": [
    {
      "document_id": "doc-123",
      "filename": "research_paper.pdf",
      "upload_date": "2025-01-17T14:30:00Z",
      "page_count": 25,
      "chunk_count": 150,
      "status": "indexed",
      "topics": ["machine learning", "neural networks"],
      "summary": "This paper discusses...",
      "query_count": 45  // How many times queried
    }
  ],
  "total": 5
}
```

---

### 2. Start Document Exploration Session
```http
POST /sessions
```

**Request:**
```json
{
  "user_id": "user-123",
  "document_scope": {
    "document_ids": ["doc-1", "doc-2"],  // Optional: limit to specific docs
    "all_documents": false               // Or query all
  }
}
```

**Response:**
```json
{
  "session_id": "sess-uuid",
  "created_at": "2025-01-17T14:30:00Z",
  "document_count": 2,
  "total_chunks": 300,
  "message": "Session started. You can now query documents."
}
```

---

### 3. Query Knowledge Base
```http
POST /sessions/{session_id}/query
```

**Request:**
```json
{
  "query": "What are the main findings about neural networks?",
  "options": {
    "use_previous_context": true,      // Use previous queries for context
    "document_filter": ["doc-1"],      // Optional: limit to specific docs
    "page_filter": {"min": 1, "max": 10}, // Optional: limit to page range
    "max_chunks": 10,                  // How many chunks to retrieve
    "response_style": {
      "include_quotes": true,          // Include exact quotes
      "include_page_numbers": true,    // Show page references
      "include_images": false,         // Include image descriptions
      "confidence_threshold": 0.7      // Min relevance score
    },
    "streaming": false
  }
}
```

**Response:**
```json
{
  "query_id": "query-uuid",
  "query": "What are the main findings about neural networks?",
  "answer": {
    "summary": "Based on the documents, the main findings are...",
    "confidence": 0.89,
    "source_count": 5,
    "document_count": 2
  },
  "sources": [
    {
      "chunk_id": "chunk-1",
      "document_id": "doc-1",
      "document_name": "research_paper.pdf",
      "page": 5,
      "text": "Neural networks demonstrated a 95% accuracy rate...",
      "relevance_score": 0.92,
      "chunk_type": "text",
      "bounding_box": {
        "page": 5,
        "coordinates": {"l": 0.1, "t": 0.2, "r": 0.9, "b": 0.5}
      }
    }
  ],
  "related_topics": ["deep learning", "accuracy metrics"],
  "suggested_followups": [
    "What methodology was used to achieve 95% accuracy?",
    "Are there any limitations mentioned?",
    "How does this compare to previous research?"
  ],
  "metadata": {
    "chunks_retrieved": 10,
    "chunks_used_in_answer": 5,
    "documents_referenced": ["research_paper.pdf"],
    "processing_time_ms": 1850,
    "tokens_used": 1500,
    "cache_hit": false
  }
}
```

**Out of KB Response:**
```json
{
  "query_id": "query-uuid",
  "query": "What's the weather today?",
  "answer": null,
  "error": "out_of_knowledge_base",
  "message": "This question cannot be answered from the uploaded documents.",
  "suggestions": [
    "Try asking about: machine learning, neural networks, training methodology",
    "View available documents: GET /documents"
  ],
  "available_topics": ["machine learning", "neural networks", "deep learning"]
}
```

---

### 4. Get Document Chunks by Page
```http
GET /documents/{document_id}/pages/{page_number}/chunks
```

**Purpose:** Browse specific sections of a document

**Response:**
```json
{
  "document_id": "doc-123",
  "document_name": "research_paper.pdf",
  "page": 5,
  "chunks": [
    {
      "chunk_id": "chunk-1",
      "text": "The experimental results show...",
      "chunk_type": "text",
      "bounding_box": {"l": 0.1, "t": 0.1, "r": 0.9, "b": 0.3},
      "section": "Results",
      "context": "Main findings section"
    }
  ]
}
```

---

### 5. Compare Documents
```http
POST /sessions/{session_id}/compare
```

**Request:**
```json
{
  "document_ids": ["doc-1", "doc-2"],
  "comparison_query": "How do these documents differ in their approach to neural networks?",
  "comparison_aspects": ["methodology", "findings", "conclusions"]
}
```

**Response:**
```json
{
  "comparison": {
    "summary": "Document A focuses on supervised learning while Document B emphasizes unsupervised approaches...",
    "similarities": [
      {
        "topic": "accuracy metrics",
        "doc_1_excerpt": "Achieved 95% accuracy...",
        "doc_2_excerpt": "Reached 94% accuracy...",
        "similarity_score": 0.88
      }
    ],
    "differences": [
      {
        "aspect": "methodology",
        "doc_1_approach": "Supervised learning with labeled data",
        "doc_2_approach": "Unsupervised clustering",
        "doc_1_source": {"page": 3, "chunk_id": "chunk-5"},
        "doc_2_source": {"page": 2, "chunk_id": "chunk-8"}
      }
    ]
  }
}
```

---

### 6. Get Query History
```http
GET /sessions/{session_id}/history
```

**Response:**
```json
{
  "session_id": "sess-uuid",
  "queries": [
    {
      "query_id": "query-1",
      "query": "What are the main findings?",
      "timestamp": "2025-01-17T14:30:00Z",
      "documents_referenced": ["research_paper.pdf"],
      "chunks_retrieved": 5,
      "user_feedback": "helpful"
    }
  ],
  "exploration_summary": {
    "topics_explored": ["neural networks", "accuracy", "methodology"],
    "documents_accessed": ["doc-1", "doc-2"],
    "total_queries": 8,
    "session_duration_minutes": 15
  }
}
```

---

### 7. Verify Citation
```http
POST /verify
```

**Request:**
```json
{
  "claim": "The accuracy rate was 95%",
  "document_id": "doc-123",  // Optional: specific document
  "page_hint": 5             // Optional: expected page
}
```

**Response:**
```json
{
  "verified": true,
  "exact_matches": [
    {
      "chunk_id": "chunk-1",
      "document": "research_paper.pdf",
      "page": 5,
      "exact_text": "Neural networks demonstrated a 95% accuracy rate",
      "confidence": 0.98
    }
  ],
  "similar_matches": []
}
```

---

## Query Processing Strategy (KB-Focused)

### 1. Query Understanding
```python
def process_kb_query(query: str, session_context: dict) -> ProcessedQuery:
    """
    Understand what the user wants to know from the documents
    """
    # Step 1: Classify query type
    query_type = classify_kb_query(query)
    
    # Step 2: Extract document-related entities
    entities = extract_document_entities(query)
    # → topics: ["neural networks", "accuracy"]
    # → document_refs: ["research paper", "doc-1"]
    # → page_refs: [5, 6]
    
    # Step 3: Determine search scope
    if entities['document_refs']:
        # Query mentions specific documents
        scope = resolve_document_references(entities['document_refs'])
    elif session_context['focused_documents']:
        # Use documents from current session
        scope = session_context['focused_documents']
    else:
        # Search all documents
        scope = "all"
    
    # Step 4: Check if answerable from KB
    if is_out_of_kb_scope(query, session_context['available_topics']):
        return OutOfScopeQuery(
            reason="Question not related to uploaded documents",
            suggestions=get_relevant_topics(session_context)
        )
    
    return ProcessedQuery(
        query_type=query_type,
        normalized_query=query,
        topics=entities['topics'],
        document_scope=scope,
        page_hints=entities['page_refs'],
        needs_comparison=query_type == KBQueryType.COMPARE_DOCUMENTS
    )
```

### 2. Retrieval Strategy

```python
def retrieve_from_kb(processed_query: ProcessedQuery, limit: int = 10) -> RetrievalResult:
    """
    Retrieve relevant chunks from knowledge base
    """
    # Build hybrid search query
    search_params = {
        "query_text": processed_query.normalized_query,
        "query_embedding": get_embedding(processed_query.normalized_query),
        "document_filter": processed_query.document_scope,
        "page_filter": processed_query.page_hints,
        "alpha": 0.5,  # Balance between semantic and keyword
        "limit": limit
    }
    
    # Execute hybrid search
    results = hybrid_search(**search_params)
    
    # Rerank based on relevance
    reranked = rerank_results(
        results,
        processed_query.normalized_query,
        context=processed_query.topics
    )
    
    # Filter by confidence threshold
    filtered = [r for r in reranked if r['score'] > 0.7]
    
    # Group by document for better context
    grouped = group_chunks_by_document(filtered)
    
    return RetrievalResult(
        chunks=filtered,
        grouped_by_document=grouped,
        total_found=len(results),
        total_returned=len(filtered),
        documents_referenced=list(grouped.keys())
    )
```

### 3. Answer Generation (KB-Grounded)
```python
def generate_kb_answer(
    query: str,
    retrieved_chunks: list,
    query_type: KBQueryType
) -> KBAnswer:
    """
    Generate answer strictly from retrieved chunks
    """
    # Build prompt that enforces grounding
    system_prompt = """You are a document analysis assistant. 
    
CRITICAL RULES:
1. ONLY use information from the provided document chunks
2. If information is not in the chunks, say "This information is not in the documents"
3. Always cite the source (document name, page number)
4. Use exact quotes when possible
5. If chunks contradict each other, mention both perspectives
6. Do not add external knowledge or make assumptions

Your role is to help users understand what's IN their documents, not to generate new information."""
    
    # Format chunks with citations
    context = format_chunks_with_citations(retrieved_chunks)
    
    # Type-specific prompts
    if query_type == KBQueryType.FIND_QUOTE:
        instruction = "Find and return the exact quote that answers this question."
    elif query_type == KBQueryType.COMPARE_DOCUMENTS:
        instruction = "Compare what each document says, noting similarities and differences."
    elif query_type == KBQueryType.SUMMARIZE:
        instruction = "Summarize what the documents say about this topic."
    else:
        instruction = "Answer based only on what the documents state."
    
    # Generate with strict grounding
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{instruction}\n\nQuery: {query}\n\nDocuments:\n{context}"}
        ],
        temperature=0.1  # Low temperature for factual accuracy
    )
    
    answer_text = response.choices[0].message.content
    
    # Verify all claims are backed by chunks
    verified = verify_claims_in_chunks(answer_text, retrieved_chunks)
    
    return KBAnswer(
        text=answer_text,
        sources=retrieved_chunks,
        verified=verified,
        confidence=calculate_answer_confidence(answer_text, retrieved_chunks)
    )
```

---

## Context Management Strategy

### Sliding Window Context
Balance between context quality and token consumption:

```python
def build_conversation_context(
    session_id: str,
    max_history: int = 5,
    max_tokens: int = 2000
) -> ConversationContext:
    """
    Build optimized conversation context
    """
    # Get recent messages
    messages = get_recent_messages(session_id, limit=max_history)
    
    # Calculate token budget
    available_tokens = max_tokens
    context_messages = []
    
    # Always include the most recent message
    context_messages.append(messages[0])
    available_tokens -= count_tokens(messages[0])
    
    # Add previous messages until token limit
    for msg in messages[1:]:
        msg_tokens = count_tokens(msg)
        if available_tokens - msg_tokens < 500:  # Reserve for system prompt
            break
        context_messages.append(msg)
        available_tokens -= msg_tokens
    
    # Summarize older context if needed
    if len(messages) > len(context_messages):
        summary = summarize_conversation(
            messages[len(context_messages):],
            max_tokens=300
        )
        context_messages.append({
            "role": "system",
            "content": f"Earlier conversation summary: {summary}"
        })
    
    return ConversationContext(
        messages=context_messages,
        tokens_used=max_tokens - available_tokens
    )
```

### Smart Context Selection
Only retrieve relevant history for follow-up questions:

```python
def get_relevant_context(
    current_query: str,
    session_history: list,
    query_type: QueryType
) -> list:
    """
    Retrieve only relevant context based on query type
    """
    if query_type == QueryType.FOLLOWUP:
        # Use last 2-3 messages
        return session_history[-3:]
    
    elif query_type == QueryType.CLARIFICATION:
        # Find what they're clarifying
        return find_referenced_messages(current_query, session_history)
    
    elif query_type == QueryType.DIRECT_QUESTION:
        # No history needed, fresh search
        return []
    
    elif query_type == QueryType.COMPARISON:
        # Find all mentions of compared topics
        return find_topic_messages(current_query, session_history)
    
    else:
        # Default: last 3 messages
        return session_history[-3:]
```

---

## Token Optimization Strategies

### 1. **Prompt Caching**
Cache expensive static prompts:

```python
class PromptCache:
    def __init__(self):
        self.system_prompt = """You are a helpful assistant..."""
        self.system_prompt_tokens = count_tokens(self.system_prompt)
        
    def get_cached_prompt(self, document_context: str) -> dict:
        """
        Use cached system prompt + dynamic document context
        """
        cache_key = hash(document_context)
        
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        prompt = {
            "system": self.system_prompt,  # Cached
            "context": document_context,    # Dynamic
            "total_tokens": self.system_prompt_tokens + count_tokens(document_context)
        }
        
        self.cache[cache_key] = prompt
        return prompt
```

### 2. **Chunk Selection Optimization**
Don't send all retrieved chunks to LLM:

```python
def optimize_chunks_for_llm(
    chunks: list,
    query: str,
    max_tokens: int = 3000
) -> list:
    """
    Select most relevant chunks within token budget
    """
    # Sort by relevance score
    chunks.sort(key=lambda x: x['score'], reverse=True)
    
    selected_chunks = []
    used_tokens = 0
    
    for chunk in chunks:
        chunk_tokens = count_tokens(chunk['text'])
        
        # Include if within budget
        if used_tokens + chunk_tokens <= max_tokens:
            selected_chunks.append(chunk)
            used_tokens += chunk_tokens
        else:
            break
    
    # If we have room, add chunk summaries instead of full text
    if used_tokens < max_tokens * 0.8:
        remaining_chunks = chunks[len(selected_chunks):]
        for chunk in remaining_chunks[:5]:  # Top 5 remaining
            summary = f"[{chunk['metadata']['page']}]: {chunk['text'][:100]}..."
            summary_tokens = count_tokens(summary)
            
            if used_tokens + summary_tokens <= max_tokens:
                selected_chunks.append({
                    **chunk,
                    'text': summary,
                    'is_summary': True
                })
                used_tokens += summary_tokens
    
    return selected_chunks
```

### 3. **Embedding Cache**
Cache query embeddings for similar questions:

```python
class EmbeddingCache:
    def __init__(self, similarity_threshold=0.95):
        self.cache = {}
        self.threshold = similarity_threshold
    
    def get_or_create_embedding(self, query: str) -> list:
        """
        Return cached embedding if query is similar enough
        """
        # Check for similar cached queries
        for cached_query, cached_embedding in self.cache.items():
            similarity = compute_similarity(query, cached_query)
            if similarity > self.threshold:
                print(f"Cache hit: {similarity:.2f} similarity")
                return cached_embedding
        
        # Create new embedding
        embedding = create_embedding(query)
        self.cache[query] = embedding
        return embedding
```

---

## Latency Optimization

### 1. **Parallel Processing**
Process independent operations concurrently:

```python
async def handle_query_parallel(query: str, session_id: str):
    """
    Execute independent operations in parallel
    """
    # Run these concurrently
    results = await asyncio.gather(
        classify_query(query),                    # 50ms
        get_recent_history(session_id, limit=5),  # 30ms
        get_embedding(query),                      # 100ms
        return_exceptions=True
    )
    
    query_type, history, embedding = results
    
    # Now do KB search (depends on embedding)
    kb_results = await search_knowledge_base(embedding)
    
    # Generate response (depends on all previous)
    response = await generate_response(
        query, query_type, history, kb_results
    )
    
    return response
```

### 2. **Streaming Responses**
Start sending tokens immediately:

```python
async def stream_response(query: str, session_id: str):
    """
    Stream response tokens as they're generated
    """
    # Quick operations first
    context = await get_context(session_id)
    chunks = await search_kb(query)
    
    # Start streaming immediately
    async for token in generate_streaming(query, context, chunks):
        yield {
            "event": "token",
            "data": {"delta": token}
        }
    
    # Send sources after generation complete
    yield {
        "event": "sources",
        "data": {"sources": format_sources(chunks)}
    }
```

### 3. **Tiered Response Strategy**
Provide quick initial response, then enhance:

```python
async def tiered_response(query: str, session_id: str):
    """
    Fast initial response, then enhanced version
    """
    # Tier 1: Quick response (500ms target)
    quick_result = await quick_search(query, limit=3)
    initial_response = await generate_response(
        query, quick_result, max_tokens=150
    )
    
    yield {
        "type": "initial",
        "content": initial_response,
        "latency_ms": 500
    }
    
    # Tier 2: Enhanced response (2s target)
    full_results = await full_search(query, limit=10)
    enhanced_response = await generate_response(
        query, full_results, max_tokens=500
    )
    
    yield {
        "type": "enhanced",
        "content": enhanced_response,
        "sources": full_results,
        "latency_ms": 2000
    }
```

---

## Handling Edge Cases

### 1. **Unintelligible Input**
```python
def handle_unintelligible(message: str, session_context: dict):
    """
    Handle unclear or gibberish input
    """
    # Check if it's a typo of recent topic
    recent_topics = extract_topics(session_context['recent_messages'])
    corrected = spell_check_with_context(message, recent_topics)
    
    if corrected != message:
        return {
            "response": f"Did you mean: '{corrected}'?",
            "type": "clarification_request",
            "suggestions": [corrected]
        }
    
    # Ask for clarification
    return {
        "response": "I'm not sure I understand. Could you rephrase that?",
        "type": "clarification_request",
        "suggestions": [
            "Try asking a specific question about the documents",
            "Use complete sentences for better understanding"
        ]
    }
```

### 2. **Out of Knowledge Base Scope**
```python
def handle_out_of_kb(query: str, session_context: dict):
    """
    Detect and handle queries that cannot be answered from documents
    """
    available_topics = session_context['kb_metadata']['main_topics']
    available_docs = session_context['kb_metadata']['documents']
    
    # Check if query relates to any document topics
    query_topics = extract_topics(query)
    topic_overlap = set(query_topics) & set(available_topics)
    
    if len(topic_overlap) == 0:
        # Completely out of scope
        return {
            "answerable": False,
            "reason": "out_of_kb_scope",
            "message": f"I cannot answer this from your uploaded documents. Your documents cover: {', '.join(available_topics[:5])}",
            "suggestions": [
                f"Try asking about: {', '.join(available_topics[:3])}",
                "Upload relevant documents to expand the knowledge base",
                "View all documents: GET /documents"
            ],
            "available_documents": available_docs
        }
    
    # Partial overlap - search but warn
    return {
        "answerable": True,
        "confidence": "low",
        "warning": f"Limited information available. Documents mainly cover: {', '.join(topic_overlap)}",
        "should_search": True
    }
```

### 3. **Ambiguous Follow-ups**
```python
def handle_ambiguous_followup(query: str, context: list):
    """
    Resolve ambiguous pronouns and references
    """
    # "Can you elaborate on that?" - What is "that"?
    references = extract_references(query)  # ["that", "it", "this"]
    
    if references:
        # Find most recent relevant noun/topic
        previous_message = context[-1]
        topics = extract_main_topics(previous_message['content'])
        
        # Replace ambiguous reference
        resolved_query = resolve_coreference(query, topics)
        
        return {
            "resolved_query": resolved_query,
            "confidence": 0.85,
            "ask_confirmation": True,
            "confirmation_message": f"You're asking about: {topics[0]}?"
        }
    
    return {"resolved_query": query, "confidence": 1.0}
```

### 4. **Token Limit Exceeded**
```python
def handle_token_overflow(
    query: str,
    context: list,
    chunks: list,
    max_tokens: int = 4000
):
    """
    Handle cases where context exceeds token limit
    """
    # Calculate current usage
    context_tokens = count_tokens(context)
    chunks_tokens = count_tokens(chunks)
    query_tokens = count_tokens(query)
    total = context_tokens + chunks_tokens + query_tokens
    
    if total > max_tokens:
        # Strategy 1: Reduce context history
        if context_tokens > max_tokens * 0.3:
            context = summarize_context(context, target_tokens=max_tokens * 0.2)
        
        # Strategy 2: Reduce chunk count
        if count_tokens(chunks) > max_tokens * 0.5:
            chunks = optimize_chunks_for_llm(
                chunks,
                query,
                max_tokens=max_tokens * 0.4
            )
        
        # Strategy 3: Split into multiple queries
        if still_too_large(context, chunks, query, max_tokens):
            return split_into_sub_queries(query, chunks)
    
    return {
        "context": context,
        "chunks": chunks,
        "query": query,
        "total_tokens": count_tokens(context, chunks, query)
    }
```

---

## Resource Budgeting

### Per-User Limits
```python
class UserResourceBudget:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.daily_limits = {
            "tokens": 100000,        # 100K tokens per day
            "queries": 100,          # 100 queries per day
            "sessions": 10,          # 10 concurrent sessions
            "cost_usd": 5.00         # $5 per day
        }
        self.current_usage = self.load_usage()
    
    def can_process_query(self, estimated_tokens: int) -> tuple[bool, str]:
        """
        Check if user has sufficient budget
        """
        if self.current_usage['tokens'] + estimated_tokens > self.daily_limits['tokens']:
            return False, "Daily token limit exceeded"
        
        if self.current_usage['queries'] >= self.daily_limits['queries']:
            return False, "Daily query limit exceeded"
        
        estimated_cost = estimated_tokens * 0.00002  # $0.02 per 1K tokens
        if self.current_usage['cost_usd'] + estimated_cost > self.daily_limits['cost_usd']:
            return False, "Daily cost limit exceeded"
        
        return True, "OK"
    
    def update_usage(self, tokens_used: int, cost: float):
        """Update resource usage"""
        self.current_usage['tokens'] += tokens_used
        self.current_usage['queries'] += 1
        self.current_usage['cost_usd'] += cost
        self.save_usage()
```

### Adaptive Resource Allocation
```python
def allocate_resources(query_type: QueryType, user_tier: str) -> dict:
    """
    Allocate tokens and model based on query type and user tier
    """
    allocations = {
        QueryType.DIRECT_QUESTION: {
            "free": {"max_tokens": 300, "model": "gpt-4o-mini", "kb_limit": 5},
            "pro": {"max_tokens": 800, "model": "gpt-4o", "kb_limit": 15},
            "enterprise": {"max_tokens": 2000, "model": "gpt-4o", "kb_limit": 30}
        },
        QueryType.FOLLOWUP: {
            "free": {"max_tokens": 200, "model": "gpt-4o-mini", "kb_limit": 3},
            "pro": {"max_tokens": 500, "model": "gpt-4o", "kb_limit": 10},
            "enterprise": {"max_tokens": 1000, "model": "gpt-4o", "kb_limit": 20}
        },
        QueryType.SUMMARY: {
            "free": {"max_tokens": 500, "model": "gpt-4o-mini", "kb_limit": 10},
            "pro": {"max_tokens": 1500, "model": "gpt-4o", "kb_limit": 30},
            "enterprise": {"max_tokens": 3000, "model": "gpt-4o", "kb_limit": 50}
        }
    }
    
    return allocations[query_type][user_tier]
```

---

## Monitoring & Analytics

### Track Key Metrics
```python
class ConversationMetrics:
    metrics_to_track = [
        "query_latency_ms",           # Response time
        "tokens_per_query",           # Token consumption
        "cache_hit_rate",             # Cache effectiveness
        "query_type_distribution",    # What users ask
        "user_satisfaction_score",    # Thumbs up/down
        "conversation_length",        # Messages per session
        "context_window_usage",       # How much history used
        "cost_per_query_usd",        # Economics
        "error_rate",                # Failed queries
        "out_of_scope_rate"          # Questions we can't answer
    ]
    
    def log_query_metrics(self, query_data: dict):
        """Log metrics for analysis"""
        metrics = {
            "timestamp": datetime.now(),
            "session_id": query_data['session_id'],
            "query_type": query_data['query_type'],
            "latency_ms": query_data['processing_time'],
            "tokens_used": query_data['tokens']['total'],
            "cache_hit": query_data['cache_hit'],
            "kb_chunks_retrieved": len(query_data['sources']),
            "cost_usd": calculate_cost(query_data['tokens'])
        }
        
        # Send to analytics service
        self.analytics_db.insert(metrics)
```

---

## Recommended Implementation Plan

### Phase 1: Core Conversational API (Week 1)
- [ ] Implement session management (create, get, delete)
- [ ] Add message endpoint with basic history
- [ ] Query classification system
- [ ] Basic context selection

### Phase 2: Optimization (Week 2)
- [ ] Implement caching (embeddings, prompts, results)
- [ ] Add streaming responses
- [ ] Token optimization strategies
- [ ] Parallel processing

### Phase 3: Edge Cases (Week 3)
- [ ] Unintelligible input handling
- [ ] Out-of-scope detection
- [ ] Ambiguity resolution
- [ ] Token overflow handling

### Phase 4: Resource Management (Week 4)
- [ ] User budgets and limits
- [ ] Adaptive resource allocation
- [ ] Cost tracking
- [ ] Rate limiting

### Phase 5: Analytics & Monitoring (Week 5)
- [ ] Metrics collection
- [ ] Dashboard for monitoring
- [ ] Alerting system
- [ ] A/B testing framework

---

## Complete Query Flow Example

```python
# 1. User uploads documents
POST /parse-pdf (file: research_paper.pdf)
→ Document parsed: 25 pages, 150 chunks
POST /upload-to-kb
→ Document indexed: doc-123

# 2. Start exploration session
POST /sessions
{
  "user_id": "user-456",
  "document_scope": {"all_documents": true}
}
→ session_id: "sess-789"
→ 5 documents available, 750 total chunks

# 3. First query - Direct question
POST /sessions/sess-789/query
{
  "query": "What are the main findings about neural networks?",
  "options": {"max_chunks": 10}
}
→ Query Type: FIND_INFORMATION
→ Topics extracted: ["neural networks", "findings"]
→ Document scope: All (5 documents)
→ Hybrid search: 50 candidates → 10 reranked → 5 used
→ Documents referenced: ["research_paper.pdf", "technical_report.pdf"]
→ Answer: "The documents report a 95% accuracy rate... [research_paper.pdf, p.5]"
→ Sources: 5 chunks with exact citations
→ Tokens: 1,200 (context) + 300 (answer) = 1,500
→ Latency: 1,850ms
→ Cost: $0.003

# 4. Follow-up query - Contextual
POST /sessions/sess-789/query
{
  "query": "What methodology was used to achieve that accuracy?",
  "options": {"use_previous_context": true}
}
→ Query Type: FOLLOWUP
→ Context resolution: "that accuracy" → "95% accuracy rate"
→ Resolved query: "What methodology achieved 95% accuracy in neural networks?"
→ Document scope: Same documents (research_paper.pdf, technical_report.pdf)
→ KB Search: 8 chunks, 3 used
→ Answer: "The methodology used supervised learning with... [research_paper.pdf, p.3]"
→ Tokens: 800 (context + history) + 600 (chunks) + 250 (answer) = 1,650
→ Latency: 1,400ms (some cached embeddings)
→ Cost: $0.003

# 5. Comparison query
POST /sessions/sess-789/compare
{
  "document_ids": ["doc-123", "doc-456"],
  "comparison_query": "How do these differ in approach?"
}
→ Query Type: COMPARE_DOCUMENTS
→ Search doc-123: 5 chunks about methodology
→ Search doc-456: 5 chunks about methodology
→ Comparison generated:
  - Similarity: Both use neural networks
  - Difference: Doc A supervised, Doc B unsupervised
→ Sources: 10 chunks (5 per document) with side-by-side citations
→ Latency: 2,500ms
→ Cost: $0.006

# 6. Citation verification
POST /verify
{
  "claim": "95% accuracy rate",
  "document_id": "doc-123"
}
→ Exact match found: research_paper.pdf, page 5
→ Confidence: 0.98
→ Latency: 300ms (embedding + search)
→ Cost: $0.001

# 7. Out of scope query
POST /sessions/sess-789/query
{
  "query": "What's the weather in New York?"
}
→ Query Type: OUT_OF_KB
→ Topics: ["weather", "New York"]
→ Available topics: ["neural networks", "machine learning", "deep learning"]
→ No overlap detected
→ Response: "I cannot answer this from your documents. Your documents cover: machine learning, neural networks..."
→ Suggestions: ["Try asking about machine learning", "Upload weather-related documents"]
→ No KB search performed
→ Latency: 200ms
→ Cost: $0.0005

# 8. Session summary
GET /sessions/sess-789/history
→ Total queries: 6
→ Successful: 5
→ Out of scope: 1
→ Documents accessed: 2
→ Topics explored: ["neural networks", "accuracy", "methodology"]
→ Total tokens: 8,900
→ Total cost: $0.0165
→ Avg latency: 1,375ms
→ Session duration: 12 minutes
```

---

## Technology Stack Recommendations

### Database
- **PostgreSQL**: Session/message storage, ACID compliance
- **Redis**: Caching (embeddings, results), session state
- **Weaviate**: Knowledge base (existing)

### Backend
- **FastAPI**: Async support, WebSocket/SSE for streaming
- **Celery**: Background tasks (analytics, cleanup)
- **APScheduler**: Scheduled jobs (cache cleanup)

### Monitoring
- **Prometheus**: Metrics collection
- **Grafana**: Dashboards
- **Sentry**: Error tracking

### Cost Management
- **Stripe/Custom**: Billing integration
- **Redis**: Rate limiting (sliding window)

---

## Conclusion

Building a robust conversational Q&A system requires:

1. **Smart Context Management**: Don't include everything, select what's relevant
2. **Aggressive Caching**: Cache embeddings, prompts, and common queries
3. **Parallel Processing**: Don't wait when you can do things simultaneously
4. **Tiered Responses**: Quick initial response, enhanced if needed
5. **Resource Budgets**: Protect against runaway costs
6. **Edge Case Handling**: Plan for unclear, ambiguous, and out-of-scope inputs
7. **Comprehensive Monitoring**: Track everything to optimize

The key is finding the right balance between **quality**, **latency**, and **cost** for your specific use case and user base.

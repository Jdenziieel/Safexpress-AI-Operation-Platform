# Chat System Architecture & Data Flow

## Overview
This document explains the complete RAG (Retrieval-Augmented Generation) chat system architecture, data flow, and how each component works together to process user queries and generate AI responses.

---

## System Components

### 1. **FastAPI Application** (`app.py`)
- **Role**: Entry point, initializes the application
- **Responsibilities**:
  - Starts the FastAPI server on port 8009
  - Registers all API routes
  - Configures CORS middleware
  - Manages Weaviate connection lifecycle

### 2. **API Routes** (`api/chat_routes.py`)
- **Role**: HTTP endpoints for chat operations
- **Key Endpoints**:
  - `POST /chat/message` - Process a chat message
  - `GET /chat/sessions` - List user's chat sessions
  - `POST /chat/session/new` - Create new session
  - `GET /chat/session/{id}/history` - Get conversation history

### 3. **JWT Middleware** (`middleware/jwt_middleware.py`)
- **Role**: Authentication & authorization
- **Process**:
  1. Extracts JWT token from `Authorization: Bearer <token>` header
  2. Verifies token signature using `JWT_SECRET_KEY`
  3. Decodes token payload (supports both `sub` and `user_id` claims)
  4. Attaches user identity to request
- **Supports**: Django SimpleJWT and standard JWT tokens

### 4. **Chat Service** (`services/chat_service.py`)
- **Role**: Core orchestrator of the chat pipeline
- **Responsibilities**: Coordinates all steps from query to response

### 5. **Weaviate Search Service** (`services/weaviate_search_service.py`)
- **Role**: Knowledge base retrieval from vector database
- **Search Types**:
  - **Hybrid Search**: Combines semantic (vector) + keyword (BM25)
  - **Semantic Search**: Pure vector similarity search

### 6. **Query Processor** (`services/query_processor.py`)
- **Role**: Query enhancement and result reranking
- **Functions**:
  - Expands queries with context
  - Resolves references (e.g., "it", "that")
  - Reranks results for relevance

### 7. **Context Manager** (`services/context_manager.py`)
- **Role**: Manages conversation context
- **Functions**:
  - Retrieves recent messages
  - Formats knowledge base context
  - Manages token limits

### 8. **Chat Database** (`database/chat_db.py`)
- **Role**: Stores chat sessions and messages
- **Storage**: SQLite database (`chat_sessions.db`)
- **Tables**:
  - `sessions` - Chat session metadata
  - `messages` - Individual messages with sources

---

## Complete Data Flow: User Query → AI Response

### **Step 1: User Sends Message**

**Frontend Request:**
```javascript
POST /chat/message
Headers: {
  'Authorization': 'Bearer eyJhbGc...',
  'Content-Type': 'application/json'
}
Body: {
  "session_id": "abc-123",
  "message": "What is the refund policy?",
  "options": {
    "max_sources": 5,
    "include_context": true,
    "document_filter": []
  }
}
```

**Input Fields:**
- `session_id` (string): Unique identifier for this conversation
- `message` (string): User's question
- `options.max_sources` (int): Maximum number of document chunks to use
- `options.include_context` (bool): Include conversation history
- `options.document_filter` (array): Filter by specific document IDs

---

### **Step 2: JWT Authentication**

**Process:**
```python
# middleware/jwt_middleware.py
1. Extract token from header: "Bearer eyJhbGc..."
2. Verify signature with JWT_SECRET_KEY
3. Decode payload: {'user_id': '5', 'exp': 1763558455, ...}
4. Extract user_id from 'sub' or 'user_id' claim
5. Attach to request: current_user = {'user_id': '5', ...}
```

**Output:**
- Authenticated user object passed to endpoint
- User ID: `"5"`

---

### **Step 3: Validate Session Ownership**

**Process:**
```python
# Check if user owns this session
session = chat_db.get_session(session_id)
if session['user_id'] != current_user_id:
    raise Exception("Access denied")
```

**Purpose:** Ensures users can only access their own conversations

---

### **Step 4: Save User Message**

**Database Operation:**
```sql
INSERT INTO messages (session_id, role, content, timestamp)
VALUES ('abc-123', 'user', 'What is the refund policy?', NOW())
```

**Output:**
```python
{
  'message_id': 'msg-789',
  'session_id': 'abc-123',
  'role': 'user',
  'content': 'What is the refund policy?',
  'timestamp': '2025-11-19T19:34:20Z'
}
```

---

### **Step 5: Retrieve Conversation Context**

**Process:**
```python
# Get last 10 messages from this session
all_messages = chat_db.get_session_messages(session_id)
context = context_manager.get_recent_context(
    messages=all_messages[:-1],  # Exclude current message
    max_messages=10,
    max_tokens=2000
)
```

**Output:**
```python
[
  {
    'role': 'user',
    'content': 'Do you sell laptops?',
    'timestamp': '...'
  },
  {
    'role': 'assistant',
    'content': 'Yes, we sell various laptop models...',
    'timestamp': '...'
  }
]
```

**Purpose:** Provides conversation history for context-aware responses

---

### **Step 6: Query Processing & Enhancement**

**Process:**
```python
# services/query_processor.py
processed_query = query_processor.enhance_query(
    query="What is the refund policy?",
    context=[previous messages]
)
```

**Enhancement Examples:**
- **Resolve References**: "What about it?" → "What about the refund policy?"
- **Expand Query**: "refund?" → "refund policy return process"
- **Add Context**: Uses conversation history to understand intent

**Output:**
```python
{
  'search_query': 'refund policy return process customer satisfaction',
  'original_query': 'What is the refund policy?',
  'is_expanded': True, #Need to test LLM usage and results
  'context_used': True #Need to test LLM usage and results
}
```

---

### **Step 7: Weaviate Knowledge Base Search**

**Input to Weaviate:**
```python
search_service.hybrid_search(
    query="refund policy return process customer satisfaction",
    limit=10,  # max_sources * 2 for reranking
    filters=None  # or {'document_ids': [...]}
)
```

**Weaviate Query Details:**

#### **Collection Structure:**
```
DocumentChunk Collection:
- chunk_id: "chunk-123"
- text: "Our refund policy allows returns within 30 days..."
- chunk_type: "text" | "table" | "image"
- document_id: "doc-456"
- document_name: "customer_policy.pdf"
- page: 5
- section: "Refund Policy"
- metadata: {...}
- vector: [0.123, 0.456, ...] (1536 dimensions)
```

#### **Hybrid Search Algorithm:**
Weaviate combines two search methods:

1. **Vector Search (Semantic)**:
   - Converts query to embedding vector
   - Finds chunks with similar meaning
   - Uses cosine similarity

2. **BM25 Search (Keyword)**:
   - Traditional keyword matching
   - Ranks by term frequency
   - Handles exact matches

3. **Fusion**:
   - Combines scores from both methods
   - Weighted average (configurable alpha)
   - Returns unified ranking

**Weaviate Response:**
```python
{
  'objects': [
    {
      'properties': {
        'chunk_id': 'chunk-123',
        'text': 'Our refund policy allows returns within 30 days...',
        'document_name': 'customer_policy.pdf',
        'page': 5,
        'document_id': 'doc-456'
      },
      'metadata': {
        'score': 0.89,  # Hybrid relevance score
        'distance': 0.23
      }
    },
    # ... more results
  ]
}
```

**Output (Formatted):**
```python
[
  {
    'chunk_id': 'chunk-123',
    'text': 'Our refund policy allows returns within 30 days of purchase...',
    'document_name': 'customer_policy.pdf',
    'document_id': 'doc-456',
    'page': 5,
    'section': 'Refund Policy',
    'score': 0.89,
    'chunk_type': 'text',
    'metadata': {}
  },
  {
    'chunk_id': 'chunk-456',
    'text': 'To initiate a refund, customers must contact support...',
    'document_name': 'support_guide.pdf',
    'document_id': 'doc-789',
    'page': 12,
    'score': 0.85,
    ...
  },
  # ... 8 more results (total: 10)
]
```

---


### **Step 8: Result Reranking**

**Purpose:** Further refine results using a more sophisticated model

**Process:**
```python
top_chunks = query_processor.rerank_results(
    query="What is the refund policy?",  # Original query
    results=[10 search results],
    top_k=5  # Reduce to top 5
)
```

**Reranking Algorithm:**
- Uses cross-encoder or scoring model
- Considers query-document interaction
- More accurate than initial hybrid search
- Computationally expensive (only on pre-filtered results)

**Output:**
```python
[
  {
    'chunk_id': 'chunk-123',
    'text': 'Our refund policy allows returns within 30 days...',
    'rerank_score': 0.95,  # Higher precision score
    'original_score': 0.89,
    'document_name': 'customer_policy.pdf',
    'page': 5
  },
  # ... top 4 more chunks
]
```

---

### **Step 9: Build Knowledge Base Context**

**Process:**
```python
kb_context = context_manager.build_kb_context(top_chunks)
```

**Output (Formatted String):**
```
Document Excerpts:

[Source: customer_policy.pdf, Page 5]
Our refund policy allows returns within 30 days of purchase. Items must be in original condition with tags attached. Refunds are processed within 5-7 business days.

[Source: support_guide.pdf, Page 12]
To initiate a refund, customers must contact support at support@example.com or call 1-800-SUPPORT with their order number.

[Source: customer_policy.pdf, Page 6]
Shipping costs are non-refundable unless the return is due to our error. Customers are responsible for return shipping fees.

... (2 more sources)
```

---

### **Step 10: Generate AI Response with OpenAI**

**Input to OpenAI:**
```python
messages = [
  {
    "role": "system",
    "content": """You are a helpful assistant that answers questions based on uploaded documents.

IMPORTANT RULES:
1. Base your answers ONLY on the provided document excerpts
2. Always cite sources using [Source: filename, Page X] format
3. If information is not in the excerpts, say so
4. Be conversational but accurate

Available Document Context:
[Source: customer_policy.pdf, Page 5]
Our refund policy allows returns within 30 days...
...
"""
  },
  {
    "role": "user",
    "content": "Do you sell laptops?"
  },
  {
    "role": "assistant",
    "content": "Yes, we sell various laptop models..."
  },
  {
    "role": "user",
    "content": "What is the refund policy?"
  }
]

# OpenAI API Call
response = openai.chat.completions.create(
    model="gpt-4o",
    messages=messages,
    temperature=0.7,
    max_tokens=1000
)
```

**OpenAI Response:**
```python
{
  'choices': [{
    'message': {
      'role': 'assistant',
      'content': 'Our refund policy allows returns within 30 days of purchase [Source: customer_policy.pdf, Page 5]. Items must be in original condition with tags attached, and refunds are processed within 5-7 business days.\n\nTo initiate a refund, you can contact support at support@example.com or call 1-800-SUPPORT with your order number [Source: support_guide.pdf, Page 12].\n\nPlease note that shipping costs are non-refundable unless the return is due to our error, and you\'ll be responsible for return shipping fees [Source: customer_policy.pdf, Page 6].'
    }
  }],
  'usage': {
    'prompt_tokens': 450,
    'completion_tokens': 120,
    'total_tokens': 570
  }
}
```

**Extracted Response:**
```python
{
  'content': 'Our refund policy allows returns within 30 days...',
  'tokens_used': 570
}
```

---

### **Step 11: Format Sources**

**Process:**
```python
sources = context_manager.format_sources(top_chunks)
```

**Output:**
```python
[
  {
    'document_name': 'customer_policy.pdf',
    'document_id': 'doc-456',
    'page': 5,
    'section': 'Refund Policy',
    'chunk_id': 'chunk-123',
    'relevance_score': 0.95
  },
  {
    'document_name': 'support_guide.pdf',
    'document_id': 'doc-789',
    'page': 12,
    'section': 'Customer Support',
    'chunk_id': 'chunk-456',
    'relevance_score': 0.92
  },
  # ... 3 more sources
]
```

---

### **Step 12: Save Assistant Message**

**Database Operation:**
```sql
INSERT INTO messages (
  session_id, role, content, sources, metadata, timestamp
) VALUES (
  'abc-123',
  'assistant',
  'Our refund policy allows returns within 30 days...',
  '[{"document_name": "customer_policy.pdf", ...}]',
  '{"tokens_used": 570, "chunks_used": 5}',
  NOW()
)
```

**Saved Record:**
```python
{
  'message_id': 'msg-790',
  'session_id': 'abc-123',
  'role': 'assistant',
  'content': 'Our refund policy allows returns within 30 days...',
  'sources': [
    {'document_name': 'customer_policy.pdf', 'page': 5, ...},
    ...
  ],
  'metadata': {
    'tokens_used': 570,
    'chunks_retrieved': 10,
    'chunks_used': 5,
    'search_query': 'refund policy return process customer satisfaction'
  },
  'timestamp': '2025-11-19T19:34:25Z'
}
```

---

### **Step 13: Update Session Metadata**

**Process:**
```python
# Track which documents were referenced
metadata = {
  'documents_referenced': ['doc-456', 'doc-789'],
  'total_chunks_used': 5,
  'last_message_timestamp': '2025-11-19T19:34:25Z'
}
chat_db.update_session_metadata(session_id, metadata)
```

---

### **Step 14: Return Response to Frontend**

**HTTP Response:**
```json
{
  "success": true,
  "message_id": "msg-790",
  "session_id": "abc-123",
  "role": "assistant",
  "content": "Our refund policy allows returns within 30 days of purchase [Source: customer_policy.pdf, Page 5]. Items must be in original condition...",
  "sources": [
    {
      "document_name": "customer_policy.pdf",
      "document_id": "doc-456",
      "page": 5,
      "section": "Refund Policy",
      "chunk_id": "chunk-123",
      "relevance_score": 0.95
    },
    {
      "document_name": "support_guide.pdf",
      "document_id": "doc-789",
      "page": 12,
      "section": "Customer Support",
      "chunk_id": "chunk-456",
      "relevance_score": 0.92
    }
  ],
  "metadata": {
    "tokens_used": 570,
    "chunks_retrieved": 10,
    "chunks_used": 5,
    "search_query": "refund policy return process customer satisfaction"
  },
  "timestamp": "2025-11-19T19:34:25Z"
}
```

---

## Data Models & Schemas

### **Session Model**
```python
{
  'session_id': str,          # Unique identifier
  'user_id': str,             # Owner's user ID
  'title': str,               # Optional session title
  'created_at': datetime,     # Creation timestamp
  'updated_at': datetime,     # Last update timestamp
  'is_active': bool,          # Soft delete flag
  'metadata': {
    'documents_referenced': List[str],  # Document IDs used
    'total_chunks_used': int,           # Total chunks across all messages
    'total_tokens_used': int            # Total OpenAI tokens
  }
}
```

### **Message Model**
```python
{
  'message_id': str,          # Unique identifier
  'session_id': str,          # Parent session
  'role': str,                # 'user' or 'assistant'
  'content': str,             # Message text
  'sources': List[Dict],      # Source documents (assistant only)
  'metadata': Dict,           # Additional info
  'timestamp': datetime       # Creation time
}
```

### **Document Chunk Model** (Weaviate)
```python
{
  'chunk_id': str,            # Unique chunk identifier
  'text': str,                # Chunk content
  'chunk_type': str,          # 'text', 'table', 'image'
  'document_id': str,         # Parent document ID
  'document_name': str,       # Source filename
  'page': int,                # Page number
  'section': str,             # Section/heading
  'metadata': Dict,           # Additional properties
  'vector': List[float]       # Embedding (1536 dimensions)
}
```

---

## Performance Characteristics

### **Typical Latency Breakdown**
```
Authentication:         ~5ms
Session Validation:     ~10ms
Context Retrieval:      ~50ms
Query Processing:       ~100ms
Weaviate Search:        ~200ms  (hybrid search)
Reranking:             ~150ms
OpenAI Generation:      ~2000ms (varies by response length)
Database Save:          ~30ms
Total:                 ~2545ms (~2.5 seconds)
```

### **Token Usage**
- **System Prompt**: ~150 tokens
- **Context (10 messages)**: ~500 tokens
- **KB Context (5 chunks)**: ~800 tokens
- **User Query**: ~20 tokens
- **Response**: ~200 tokens
- **Total**: ~1670 tokens per request

### **Scaling Considerations**
- Weaviate can handle millions of chunks
- SQLite suitable for 1000s of sessions (consider PostgreSQL for production)
- OpenAI rate limits: 10,000 RPM (tokens per minute)
- FastAPI can handle 1000s of concurrent requests

---

## Configuration

### **Environment Variables** (`.env`)
```bash
# OpenAI
OPENAI_API_KEY=sk-...

# Weaviate
WEAVIATE_URL=http://localhost:8080
WEAVIATE_API_KEY=your-api-key

# JWT
JWT_SECRET_KEY=your-secret-key  # MUST match auth server

# Server
PORT=8009
DEBUG=True
```

### **Search Parameters**
```python
# In chat_service.py
max_sources = 5           # Number of chunks to use
limit = max_sources * 2   # Initial search results (before reranking)
HYBRID_SEARCH_ALPHA = 0.5 # Vector vs BM25 weight (0.0-1.0)
```

---

## Error Handling

### **Common Errors**

1. **401 Unauthorized**
   - Invalid JWT token
   - Token expired
   - Missing `sub` or `user_id` claim

2. **403 Forbidden**
   - User doesn't own the session
   - Access control violation

3. **404 Not Found**
   - Session doesn't exist
   - Message not found

4. **500 Internal Server Error**
   - Weaviate connection failed
   - OpenAI API error
   - Database error

### **Retry Logic**
- OpenAI: 3 retries with exponential backoff
- Weaviate: Connection pool with automatic reconnection
- Database: Transaction rollback on failure

---

## Security

### **Authentication Flow**
```
1. User logs in to Django auth server
2. Auth server creates JWT with user_id
3. Frontend stores JWT in localStorage
4. Frontend includes JWT in every request
5. FastAPI verifies JWT signature
6. FastAPI extracts user_id from token
7. FastAPI validates session ownership
```

### **Data Isolation**
- Users can only access their own sessions
- All queries include user_id filter
- Soft deletes preserve audit trail

---

## Monitoring & Debugging

### **Console Output Format**
```
================================================================================
[ChatService] 🚀 STARTING MESSAGE PROCESSING
[ChatService] Session ID: abc-123
[ChatService] User ID: 5
[ChatService] User Message: What is the refund policy?
================================================================================

[ChatService] 📚 CONTEXT RETRIEVAL
[ChatService] Retrieved 2 context messages from history

[ChatService] 🔍 QUERY PROCESSING
[ChatService] Original Query: What is the refund policy?
[ChatService] Enhanced Query: refund policy return process customer satisfaction

[WeaviateSearch] 🔍 HYBRID SEARCH STARTING
[WeaviateSearch] Query: refund policy return process customer satisfaction
[WeaviateSearch] Executing hybrid search (vector + BM25)...
[WeaviateSearch] ✅ Hybrid search returned 10 results

[ChatService] 🎯 RERANKING RESULTS
[ChatService] ✅ Selected top 5 chunks after reranking

[ChatService] 🤖 GENERATING AI RESPONSE
[ChatService] ✅ Generated response
[ChatService] Tokens Used: 570

[ChatService] ✨ MESSAGE PROCESSING COMPLETE
================================================================================
```

---

## Future Enhancements

1. **Streaming Responses**: Real-time token streaming from OpenAI
2. **Multi-Modal**: Support images and tables in responses
3. **Advanced Filtering**: Filter by date, author, document type
4. **Caching**: Cache frequent queries to reduce latency
5. **Analytics**: Track popular queries and document usage
6. **A/B Testing**: Compare different search/reranking strategies

---

## Troubleshooting

### **No Results Returned**
- Check if documents are uploaded to Weaviate
- Verify embeddings are generated correctly
- Try lowering similarity threshold

### **Poor Response Quality**
- Increase `max_sources` for more context
- Check chunk size (too small/large affects quality)
- Verify system prompt is appropriate

### **Slow Performance**
- Enable Weaviate query caching
- Reduce context window
- Use faster OpenAI model (gpt-3.5-turbo)

---

**Last Updated**: November 19, 2025

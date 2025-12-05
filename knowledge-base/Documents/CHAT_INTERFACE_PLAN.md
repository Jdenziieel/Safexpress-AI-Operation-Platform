# Chat Interface Plan - ChatGPT-Style Document Query System

## Overview

Build a ChatGPT-like chat interface that uses Weaviate and semantic search as the backend for querying uploaded PDF documents. Users interact through a conversational UI while the system retrieves information from the knowledge base.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Frontend (React)                         │
│  ┌────────────────────────────────────────────────────────┐ │
│  │         ChatGPT-Style Chat Interface                   │ │
│  │  • Message history display                             │ │
│  │  • Input box with send button                          │ │
│  │  • Document source citations                           │ │
│  │  • File upload integration                             │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            ↕ HTTP/WebSocket
┌─────────────────────────────────────────────────────────────┐
│                     Backend (Flask)                          │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              Chat API Endpoints                        │ │
│  │  • POST /chat/message                                  │ │
│  │  • GET /chat/history                                   │ │
│  │  • POST /chat/session/new                              │ │
│  │  • GET /chat/session/{id}                              │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │           Query Processing Layer                       │ │
│  │  • Intent detection                                    │ │
│  │  • Query enrichment with context                       │ │
│  │  • Weaviate semantic search                            │ │
│  │  • OpenAI response generation                          │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            ↕
┌─────────────────────────────────────────────────────────────┐
│              Weaviate Vector Database                        │
│  • Document chunks with embeddings                           │
│  • Hybrid search (semantic + keyword)                        │
│  • Source attribution metadata                               │
└─────────────────────────────────────────────────────────────┘
```

---

## Database Schema

### 1. Chat Sessions Table (PostgreSQL/SQLite)
```python
{
  "session_id": "uuid",
  "user_id": "string",
  "created_at": "timestamp",
  "updated_at": "timestamp",
  "title": "string",  # Auto-generated from first message
  "message_count": "integer",
  "metadata": {
    "documents_referenced": ["doc_id_1", "doc_id_2"],
    "total_chunks_used": 45
  }
}
```

### 2. Chat Messages Table (PostgreSQL/SQLite)
```python
{
  "message_id": "uuid",
  "session_id": "uuid",  # Foreign key
  "role": "user|assistant|system",
  "content": "string",
  "timestamp": "timestamp",
  "sources": [  # For assistant messages only
    {
      "chunk_id": "uuid",
      "document_name": "research_paper.pdf",
      "page": 5,
      "relevance_score": 0.92,
      "text_snippet": "Neural networks demonstrated..."
    }
  ],
  "metadata": {
    "tokens_used": 150,
    "processing_time_ms": 1200,
    "search_query": "what are neural networks"  # Actual query sent to Weaviate
  }
}
```

### 3. Weaviate Schema (Already Exists)
```python
class DocumentChunk:
    chunk_id: str
    text: str
    chunk_type: str  # text|image|table
    document_id: str
    document_name: str
    page: int
    section: str
    metadata: dict
    vector: list[float]  # Embedding
```

---

## Backend API Design

### 1. Create New Chat Session
```http
POST /chat/session/new
Content-Type: application/json

Request:
{
  "user_id": "user-123",
  "initial_message": "What are the main findings in the uploaded documents?"  # Optional
}

Response:
{
  "session_id": "sess-uuid",
  "created_at": "2025-11-18T10:30:00Z",
  "message": "Session created. You can now chat with your knowledge base."
}
```

### 2. Send Message (Main Chat Endpoint)
```http
POST /chat/message
Content-Type: application/json

Request:
{
  "session_id": "sess-uuid",
  "message": "What are the main findings about neural networks?",
  "options": {
    "max_sources": 5,          # Number of KB chunks to retrieve
    "include_context": true,   # Use previous messages for context
    "document_filter": [],     # Optional: limit to specific docs
    "stream": false            # Stream response token by token
  }
}

Response:
{
  "message_id": "msg-uuid",
  "session_id": "sess-uuid",
  "role": "assistant",
  "content": "Based on the uploaded documents, the main findings about neural networks are:\n\n1. They achieved 95% accuracy in image classification tasks [Source: research_paper.pdf, p.5]\n2. Training time was reduced by 40% using the new optimizer [Source: technical_report.pdf, p.12]\n3. The model generalizes well to unseen data [Source: research_paper.pdf, p.8]",
  "sources": [
    {
      "chunk_id": "chunk-123",
      "document_name": "research_paper.pdf",
      "page": 5,
      "relevance_score": 0.92,
      "text": "Neural networks demonstrated a 95% accuracy rate in image classification...",
      "bounding_box": {"l": 0.1, "t": 0.2, "r": 0.9, "b": 0.5}
    },
    {
      "chunk_id": "chunk-456",
      "document_name": "technical_report.pdf",
      "page": 12,
      "relevance_score": 0.87,
      "text": "The new optimizer reduced training time by approximately 40%...",
      "bounding_box": {"l": 0.1, "t": 0.3, "r": 0.9, "b": 0.6}
    }
  ],
  "metadata": {
    "tokens_used": 350,
    "processing_time_ms": 1450,
    "chunks_retrieved": 10,
    "chunks_used": 3,
    "search_query": "neural networks findings accuracy performance"
  },
  "timestamp": "2025-11-18T10:31:00Z"
}
```

### 3. Get Chat History
```http
GET /chat/session/{session_id}/history?limit=50

Response:
{
  "session_id": "sess-uuid",
  "messages": [
    {
      "message_id": "msg-1",
      "role": "user",
      "content": "What are the main findings?",
      "timestamp": "2025-11-18T10:30:00Z"
    },
    {
      "message_id": "msg-2",
      "role": "assistant",
      "content": "Based on the documents...",
      "sources": [...],
      "timestamp": "2025-11-18T10:30:05Z"
    }
  ],
  "total_messages": 24,
  "has_more": true
}
```

### 4. List User Sessions
```http
GET /chat/sessions?user_id=user-123&limit=20

Response:
{
  "sessions": [
    {
      "session_id": "sess-1",
      "title": "Neural Networks Research",
      "created_at": "2025-11-18T09:00:00Z",
      "last_message_at": "2025-11-18T10:30:00Z",
      "message_count": 15,
      "preview": "What are the main findings about neural networks?"
    }
  ],
  "total": 35,
  "has_more": true
}
```

### 5. Upload Document (Enhanced)
```http
POST /documents/upload
Content-Type: multipart/form-data

Request:
- file: document.pdf
- session_id: sess-uuid (optional, to associate with current chat)

Response:
{
  "document_id": "doc-uuid",
  "filename": "research_paper.pdf",
  "status": "processing",
  "chunks_created": 0,  # Will be updated when processing completes
  "message": "Document uploaded. Processing in background..."
}

# Background processing:
# 1. Parse PDF → chunks
# 2. Generate embeddings
# 3. Upload to Weaviate
# 4. Send notification to session (if provided)
```

---

## Backend Implementation

### File Structure
```
backend/
├── app.py                          # Main Flask app
├── config.py                       # Configuration
├── requirements.txt
│
├── api/
│   ├── __init__.py
│   ├── chat_routes.py             # NEW: Chat endpoints
│   ├── document_routes.py         # Enhanced document endpoints
│   └── session_routes.py          # NEW: Session management
│
├── services/
│   ├── __init__.py
│   ├── chat_service.py            # NEW: Main chat orchestration
│   ├── query_processor.py         # NEW: Query enhancement
│   ├── weaviate_search_service.py # NEW: Semantic search wrapper
│   ├── response_generator.py      # NEW: OpenAI response synthesis
│   ├── context_manager.py         # NEW: Conversation context
│   └── (existing services...)
│
├── database/
│   ├── __init__.py
│   ├── chat_db.py                 # NEW: Chat session/message storage
│   ├── weaviate_client.py         # Existing
│   └── operations.py              # Existing
│
└── models/
    ├── __init__.py
    ├── chat_models.py             # NEW: Chat session/message models
    └── schemas.py                 # Existing
```

### Core Service: `chat_service.py`
```python
# services/chat_service.py
from typing import List, Dict, Optional
import openai
from database.chat_db import ChatDatabase
from services.weaviate_search_service import WeaviateSearchService
from services.query_processor import QueryProcessor
from services.context_manager import ContextManager

class ChatService:
    def __init__(self):
        self.chat_db = ChatDatabase()
        self.search_service = WeaviateSearchService()
        self.query_processor = QueryProcessor()
        self.context_manager = ContextManager()
        self.openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    async def process_message(
        self,
        session_id: str,
        user_message: str,
        options: Dict = None
    ) -> Dict:
        """
        Main chat processing pipeline
        """
        options = options or {}
        max_sources = options.get('max_sources', 5)
        include_context = options.get('include_context', True)
        
        # 1. Save user message
        user_msg = self.chat_db.save_message(
            session_id=session_id,
            role="user",
            content=user_message
        )
        
        # 2. Get conversation context
        context = []
        if include_context:
            context = self.context_manager.get_recent_context(
                session_id=session_id,
                max_messages=10,
                max_tokens=2000
            )
        
        # 3. Process query (expand, extract keywords, etc.)
        processed_query = self.query_processor.enhance_query(
            query=user_message,
            context=context
        )
        
        # 4. Search Weaviate knowledge base
        search_results = await self.search_service.hybrid_search(
            query=processed_query['search_query'],
            limit=max_sources * 2,  # Get more, then rerank
            filters=options.get('document_filter')
        )
        
        # 5. Rerank results with query relevance
        top_chunks = self.query_processor.rerank_results(
            query=user_message,
            results=search_results,
            top_k=max_sources
        )
        
        # 6. Generate response with OpenAI
        assistant_response = await self._generate_response(
            user_message=user_message,
            context=context,
            knowledge_chunks=top_chunks
        )
        
        # 7. Save assistant message with sources
        assistant_msg = self.chat_db.save_message(
            session_id=session_id,
            role="assistant",
            content=assistant_response['content'],
            sources=assistant_response['sources'],
            metadata={
                'tokens_used': assistant_response['tokens_used'],
                'chunks_retrieved': len(search_results),
                'chunks_used': len(top_chunks),
                'search_query': processed_query['search_query']
            }
        )
        
        # 8. Update session metadata
        self.chat_db.update_session(
            session_id=session_id,
            documents_referenced=[c['document_id'] for c in top_chunks]
        )
        
        return assistant_msg
    
    async def _generate_response(
        self,
        user_message: str,
        context: List[Dict],
        knowledge_chunks: List[Dict]
    ) -> Dict:
        """
        Generate response using OpenAI with KB context
        """
        # Build context from knowledge base chunks
        kb_context = "\n\n".join([
            f"[Source: {chunk['document_name']}, Page {chunk['page']}]\n{chunk['text']}"
            for chunk in knowledge_chunks
        ])
        
        # Build messages for OpenAI
        messages = [
            {
                "role": "system",
                "content": f"""You are a helpful assistant that answers questions based on uploaded documents.

IMPORTANT RULES:
1. Base your answers ONLY on the provided document excerpts
2. Always cite sources using [Source: filename, Page X] format
3. If information is not in the documents, say "I don't have information about that in the uploaded documents"
4. Be conversational but accurate
5. Use direct quotes when appropriate

Available Document Context:
{kb_context}
"""
            }
        ]
        
        # Add conversation history
        for msg in context:
            messages.append({
                "role": msg['role'],
                "content": msg['content']
            })
        
        # Add current user message
        messages.append({
            "role": "user",
            "content": user_message
        })
        
        # Call OpenAI
        response = self.openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7,
            max_tokens=1000
        )
        
        return {
            'content': response.choices[0].message.content,
            'sources': [
                {
                    'chunk_id': chunk['chunk_id'],
                    'document_name': chunk['document_name'],
                    'page': chunk['page'],
                    'relevance_score': chunk['score'],
                    'text': chunk['text'][:200] + "..."  # Preview
                }
                for chunk in knowledge_chunks
            ],
            'tokens_used': response.usage.total_tokens
        }
```

### Query Processor: `query_processor.py`
```python
# services/query_processor.py
import openai
from typing import Dict, List

class QueryProcessor:
    def __init__(self):
        self.openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    def enhance_query(self, query: str, context: List[Dict]) -> Dict:
        """
        Enhance user query with context and extract search terms
        """
        # If there's context, check for follow-up patterns
        if context and self._is_followup(query):
            # Resolve references like "it", "that", "this"
            resolved_query = self._resolve_references(query, context)
        else:
            resolved_query = query
        
        # Extract key search terms
        search_query = self._extract_search_terms(resolved_query)
        
        return {
            'original_query': query,
            'resolved_query': resolved_query,
            'search_query': search_query
        }
    
    def _is_followup(self, query: str) -> bool:
        """Check if query is a follow-up"""
        followup_patterns = [
            'what about', 'how about', 'tell me more',
            'can you explain', 'what does that mean',
            'it', 'that', 'this', 'those', 'these'
        ]
        query_lower = query.lower()
        return any(pattern in query_lower for pattern in followup_patterns)
    
    def _resolve_references(self, query: str, context: List[Dict]) -> str:
        """Resolve ambiguous references using context"""
        # Get last assistant message to understand what "it" refers to
        last_messages = context[-3:] if len(context) >= 3 else context
        
        context_text = "\n".join([
            f"{msg['role']}: {msg['content']}"
            for msg in last_messages
        ])
        
        # Use OpenAI to resolve
        response = self.openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Rewrite the user's query to be standalone by resolving pronouns and references using the conversation context."
                },
                {
                    "role": "user",
                    "content": f"Context:\n{context_text}\n\nQuery to resolve: {query}\n\nStandalone query:"
                }
            ],
            temperature=0,
            max_tokens=100
        )
        
        return response.choices[0].message.content.strip()
    
    def _extract_search_terms(self, query: str) -> str:
        """Extract optimal search terms for Weaviate"""
        # For now, return the query itself
        # Can be enhanced with keyword extraction
        return query
    
    def rerank_results(
        self,
        query: str,
        results: List[Dict],
        top_k: int = 5
    ) -> List[Dict]:
        """
        Rerank search results using semantic similarity with OpenAI embeddings
        """
        if not results:
            return []
        
        # Get query embedding
        query_embedding = self._get_embedding(query)
        
        # Calculate similarity scores
        from numpy import dot
        from numpy.linalg import norm
        
        for result in results:
            # Weaviate already provides vector, calculate cosine similarity
            chunk_vector = result.get('vector', [])
            if chunk_vector:
                similarity = dot(query_embedding, chunk_vector) / (
                    norm(query_embedding) * norm(chunk_vector)
                )
                result['rerank_score'] = similarity
            else:
                result['rerank_score'] = result.get('score', 0)
        
        # Sort by rerank score
        results.sort(key=lambda x: x['rerank_score'], reverse=True)
        
        return results[:top_k]
    
    def _get_embedding(self, text: str) -> List[float]:
        """Get embedding for text"""
        response = self.openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding
```

### Weaviate Search Service: `weaviate_search_service.py`
```python
# services/weaviate_search_service.py
from typing import List, Dict, Optional
import weaviate
from database.weaviate_client import get_weaviate_client

class WeaviateSearchService:
    def __init__(self):
        self.client = get_weaviate_client()
        self.collection_name = "DocumentChunk"
    
    async def hybrid_search(
        self,
        query: str,
        limit: int = 10,
        filters: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Perform hybrid search (semantic + keyword) on Weaviate
        """
        try:
            collection = self.client.collections.get(self.collection_name)
            
            # Build where filter if provided
            where_filter = None
            if filters:
                if 'document_ids' in filters:
                    where_filter = {
                        "path": ["document_id"],
                        "operator": "ContainsAny",
                        "valueTextArray": filters['document_ids']
                    }
            
            # Hybrid search (combines vector and BM25)
            response = collection.query.hybrid(
                query=query,
                limit=limit,
                where=where_filter,
                return_metadata=["score", "distance"],
                return_properties=[
                    "chunk_id",
                    "text",
                    "chunk_type",
                    "document_id",
                    "document_name",
                    "page",
                    "section",
                    "metadata"
                ]
            )
            
            # Format results
            results = []
            for obj in response.objects:
                results.append({
                    'chunk_id': obj.properties.get('chunk_id'),
                    'text': obj.properties.get('text'),
                    'chunk_type': obj.properties.get('chunk_type'),
                    'document_id': obj.properties.get('document_id'),
                    'document_name': obj.properties.get('document_name'),
                    'page': obj.properties.get('page'),
                    'section': obj.properties.get('section'),
                    'metadata': obj.properties.get('metadata', {}),
                    'score': obj.metadata.score,
                    'vector': obj.vector if hasattr(obj, 'vector') else None
                })
            
            return results
            
        except Exception as e:
            print(f"Error in hybrid search: {e}")
            return []
    
    async def semantic_search(
        self,
        query: str,
        limit: int = 10,
        filters: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Perform pure semantic (vector) search
        """
        try:
            collection = self.client.collections.get(self.collection_name)
            
            where_filter = None
            if filters and 'document_ids' in filters:
                where_filter = {
                    "path": ["document_id"],
                    "operator": "ContainsAny",
                    "valueTextArray": filters['document_ids']
                }
            
            response = collection.query.near_text(
                query=query,
                limit=limit,
                where=where_filter,
                return_metadata=["distance"],
                return_properties=[
                    "chunk_id", "text", "chunk_type", "document_id",
                    "document_name", "page", "section", "metadata"
                ]
            )
            
            results = []
            for obj in response.objects:
                # Convert distance to similarity score (0-1)
                score = 1 / (1 + obj.metadata.distance)
                
                results.append({
                    'chunk_id': obj.properties.get('chunk_id'),
                    'text': obj.properties.get('text'),
                    'chunk_type': obj.properties.get('chunk_type'),
                    'document_id': obj.properties.get('document_id'),
                    'document_name': obj.properties.get('document_name'),
                    'page': obj.properties.get('page'),
                    'section': obj.properties.get('section'),
                    'metadata': obj.properties.get('metadata', {}),
                    'score': score
                })
            
            return results
            
        except Exception as e:
            print(f"Error in semantic search: {e}")
            return []
```

### Chat Database: `chat_db.py`
```python
# database/chat_db.py
import sqlite3
import json
import uuid
from datetime import datetime
from typing import List, Dict, Optional

class ChatDatabase:
    def __init__(self, db_path: str = "chat_sessions.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                message_count INTEGER DEFAULT 0,
                metadata TEXT
            )
        """)
        
        # Messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                sources TEXT,
                metadata TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions (session_id)
            )
        """)
        
        # Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_user ON sessions(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_session ON messages(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_timestamp ON messages(timestamp)")
        
        conn.commit()
        conn.close()
    
    def create_session(self, user_id: str) -> Dict:
        """Create new chat session"""
        session_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO sessions (session_id, user_id, created_at, updated_at, metadata)
            VALUES (?, ?, ?, ?, ?)
        """, (session_id, user_id, now, now, json.dumps({})))
        
        conn.commit()
        conn.close()
        
        return {
            'session_id': session_id,
            'user_id': user_id,
            'created_at': now,
            'message_count': 0
        }
    
    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        sources: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None
    ) -> Dict:
        """Save a message to the session"""
        message_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO messages (message_id, session_id, role, content, timestamp, sources, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            message_id,
            session_id,
            role,
            content,
            now,
            json.dumps(sources or []),
            json.dumps(metadata or {})
        ))
        
        # Update session
        cursor.execute("""
            UPDATE sessions
            SET updated_at = ?, message_count = message_count + 1
            WHERE session_id = ?
        """, (now, session_id))
        
        # Auto-generate title from first user message
        cursor.execute("""
            SELECT message_count FROM sessions WHERE session_id = ?
        """, (session_id,))
        
        message_count = cursor.fetchone()[0]
        if message_count == 1 and role == "user":
            title = content[:50] + "..." if len(content) > 50 else content
            cursor.execute("""
                UPDATE sessions SET title = ? WHERE session_id = ?
            """, (title, session_id))
        
        conn.commit()
        conn.close()
        
        return {
            'message_id': message_id,
            'session_id': session_id,
            'role': role,
            'content': content,
            'sources': sources or [],
            'metadata': metadata or {},
            'timestamp': now
        }
    
    def get_session_messages(
        self,
        session_id: str,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """Get all messages for a session"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = """
            SELECT * FROM messages
            WHERE session_id = ?
            ORDER BY timestamp ASC
        """
        
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query, (session_id,))
        rows = cursor.fetchall()
        conn.close()
        
        messages = []
        for row in rows:
            messages.append({
                'message_id': row['message_id'],
                'session_id': row['session_id'],
                'role': row['role'],
                'content': row['content'],
                'timestamp': row['timestamp'],
                'sources': json.loads(row['sources']) if row['sources'] else [],
                'metadata': json.loads(row['metadata']) if row['metadata'] else {}
            })
        
        return messages
    
    def get_user_sessions(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0
    ) -> List[Dict]:
        """Get all sessions for a user"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM sessions
            WHERE user_id = ?
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
        """, (user_id, limit, offset))
        
        rows = cursor.fetchall()
        conn.close()
        
        sessions = []
        for row in rows:
            sessions.append({
                'session_id': row['session_id'],
                'user_id': row['user_id'],
                'title': row['title'] or 'New Chat',
                'created_at': row['created_at'],
                'updated_at': row['updated_at'],
                'message_count': row['message_count'],
                'metadata': json.loads(row['metadata']) if row['metadata'] else {}
            })
        
        return sessions
```

---

## Frontend Implementation

### UI Components

```jsx
// src/components/ChatInterface.jsx
import React, { useState, useEffect, useRef } from 'react';
import '../css/ChatInterface.css';

function ChatInterface() {
  const [sessions, setSessions] = useState([]);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  
  const messagesEndRef = useRef(null);
  const userId = 'user-123'; // Replace with actual user ID from auth

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Load sessions on mount
  useEffect(() => {
    loadSessions();
  }, []);

  const loadSessions = async () => {
    try {
      const res = await fetch(`http://localhost:8009/chat/sessions?user_id=${userId}`);
      const data = await res.json();
      setSessions(data.sessions || []);
    } catch (err) {
      console.error('Error loading sessions:', err);
    }
  };

  const createNewSession = async () => {
    try {
      const res = await fetch('http://localhost:8009/chat/session/new', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
      });
      const data = await res.json();
      setCurrentSessionId(data.session_id);
      setMessages([]);
      loadSessions(); // Refresh session list
    } catch (err) {
      console.error('Error creating session:', err);
    }
  };

  const loadSession = async (sessionId) => {
    try {
      const res = await fetch(`http://localhost:8009/chat/session/${sessionId}/history`);
      const data = await res.json();
      setCurrentSessionId(sessionId);
      setMessages(data.messages || []);
    } catch (err) {
      console.error('Error loading session:', err);
    }
  };

  const sendMessage = async () => {
    if (!input.trim()) return;
    if (!currentSessionId) {
      await createNewSession();
      return;
    }

    const userMessage = { role: 'user', content: input };
    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setLoading(true);

    try {
      const res = await fetch('http://localhost:8009/chat/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: currentSessionId,
          message: input,
          options: {
            max_sources: 5,
            include_context: true
          }
        })
      });

      const data = await res.json();
      setMessages((prev) => [...prev, {
        role: 'assistant',
        content: data.content,
        sources: data.sources || [],
        timestamp: data.timestamp
      }]);
    } catch (err) {
      console.error('Error sending message:', err);
      setMessages((prev) => [...prev, {
        role: 'assistant',
        content: '⚠️ Error: Could not get response. Please try again.'
      }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chat-interface">
      {/* Sidebar with sessions */}
      <div className="chat-sidebar">
        <div className="sidebar-header">
          <h2>Chats</h2>
          <button onClick={createNewSession} className="new-chat-btn">
            + New Chat
          </button>
        </div>
        
        <div className="sessions-list">
          {sessions.map((session) => (
            <div
              key={session.session_id}
              className={`session-item ${currentSessionId === session.session_id ? 'active' : ''}`}
              onClick={() => loadSession(session.session_id)}
            >
              <div className="session-title">{session.title}</div>
              <div className="session-time">
                {new Date(session.updated_at).toLocaleDateString()}
              </div>
            </div>
          ))}
        </div>

        <div className="sidebar-footer">
          <button onClick={() => setUploadModalOpen(true)} className="upload-docs-btn">
            📄 Upload Documents
          </button>
        </div>
      </div>

      {/* Main chat area */}
      <div className="chat-main">
        {!currentSessionId ? (
          <div className="chat-welcome">
            <h1>Knowledge Base Chat</h1>
            <p>Ask questions about your uploaded documents</p>
            <button onClick={createNewSession} className="start-chat-btn">
              Start New Chat
            </button>
          </div>
        ) : (
          <>
            <div className="chat-messages">
              {messages.map((msg, idx) => (
                <div key={idx} className={`message ${msg.role}`}>
                  <div className="message-content">
                    {msg.content}
                  </div>
                  
                  {/* Show sources for assistant messages */}
                  {msg.role === 'assistant' && msg.sources && msg.sources.length > 0 && (
                    <div className="message-sources">
                      <div className="sources-label">Sources:</div>
                      {msg.sources.map((source, sidx) => (
                        <div key={sidx} className="source-item">
                          <span className="source-doc">{source.document_name}</span>
                          <span className="source-page">Page {source.page}</span>
                          <span className="source-score">{(source.relevance_score * 100).toFixed(0)}%</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
              
              {loading && (
                <div className="message assistant">
                  <div className="message-content loading">
                    <span className="dot">.</span>
                    <span className="dot">.</span>
                    <span className="dot">.</span>
                  </div>
                </div>
              )}
              
              <div ref={messagesEndRef} />
            </div>

            {/* Input area */}
            <div className="chat-input-container">
              <div className="chat-input-wrapper">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyPress={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      sendMessage();
                    }
                  }}
                  placeholder="Ask a question about your documents..."
                  rows={1}
                  className="chat-input"
                />
                <button
                  onClick={sendMessage}
                  disabled={loading || !input.trim()}
                  className="send-btn"
                >
                  Send
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Upload Modal */}
      {uploadModalOpen && (
        <UploadModal
          onClose={() => setUploadModalOpen(false)}
          sessionId={currentSessionId}
        />
      )}
    </div>
  );
}

export default ChatInterface;
```

### Styling

```css
/* src/css/ChatInterface.css */
.chat-interface {
  display: flex;
  height: 100vh;
  background: #f8f9fa;
}

/* Sidebar */
.chat-sidebar {
  width: 280px;
  background: #fff;
  border-right: 1px solid #e0e0e0;
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 20px;
  border-bottom: 1px solid #e0e0e0;
}

.sidebar-header h2 {
  margin: 0 0 12px 0;
  font-size: 20px;
}

.new-chat-btn {
  width: 100%;
  padding: 10px;
  background: #007bff;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 600;
}

.new-chat-btn:hover {
  background: #0056b3;
}

.sessions-list {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
}

.session-item {
  padding: 12px;
  margin-bottom: 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.2s;
}

.session-item:hover {
  background: #f0f0f0;
}

.session-item.active {
  background: #e3f2fd;
}

.session-title {
  font-weight: 500;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-time {
  font-size: 12px;
  color: #666;
}

.sidebar-footer {
  padding: 20px;
  border-top: 1px solid #e0e0e0;
}

.upload-docs-btn {
  width: 100%;
  padding: 10px;
  background: #28a745;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 600;
}

.upload-docs-btn:hover {
  background: #218838;
}

/* Main chat area */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #fff;
}

.chat-welcome {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  text-align: center;
}

.chat-welcome h1 {
  font-size: 32px;
  margin-bottom: 16px;
}

.chat-welcome p {
  color: #666;
  margin-bottom: 32px;
}

.start-chat-btn {
  padding: 14px 32px;
  background: #007bff;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
}

.start-chat-btn:hover {
  background: #0056b3;
}

/* Messages */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.message {
  display: flex;
  flex-direction: column;
  max-width: 70%;
}

.message.user {
  align-self: flex-end;
}

.message.assistant {
  align-self: flex-start;
}

.message-content {
  padding: 12px 16px;
  border-radius: 12px;
  line-height: 1.5;
}

.message.user .message-content {
  background: #007bff;
  color: white;
}

.message.assistant .message-content {
  background: #f0f0f0;
  color: #000;
}

.message-content.loading {
  display: flex;
  gap: 4px;
}

.message-content.loading .dot {
  animation: blink 1.4s infinite;
}

.message-content.loading .dot:nth-child(2) {
  animation-delay: 0.2s;
}

.message-content.loading .dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes blink {
  0%, 60%, 100% { opacity: 0.3; }
  30% { opacity: 1; }
}

/* Sources */
.message-sources {
  margin-top: 8px;
  padding: 10px;
  background: #f9f9f9;
  border-radius: 8px;
  font-size: 13px;
}

.sources-label {
  font-weight: 600;
  margin-bottom: 6px;
  color: #666;
}

.source-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  background: white;
  border-radius: 4px;
  margin-bottom: 4px;
}

.source-doc {
  flex: 1;
  font-weight: 500;
  color: #007bff;
}

.source-page {
  color: #666;
  font-size: 12px;
}

.source-score {
  padding: 2px 6px;
  background: #e3f2fd;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  color: #007bff;
}

/* Input area */
.chat-input-container {
  border-top: 1px solid #e0e0e0;
  padding: 20px;
  background: #fff;
}

.chat-input-wrapper {
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

.chat-input {
  flex: 1;
  padding: 12px;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  resize: none;
  font-family: inherit;
  font-size: 14px;
  max-height: 120px;
}

.chat-input:focus {
  outline: none;
  border-color: #007bff;
}

.send-btn {
  padding: 12px 24px;
  background: #007bff;
  color: white;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

.send-btn:hover:not(:disabled) {
  background: #0056b3;
}

.send-btn:disabled {
  background: #ccc;
  cursor: not-allowed;
}
```

---

## Implementation Timeline

### Week 1: Backend Foundation
- [ ] Set up database schema (SQLite tables for sessions/messages)
- [ ] Implement `chat_service.py` - core orchestration
- [ ] Implement `query_processor.py` - query enhancement
- [ ] Implement `weaviate_search_service.py` - search wrapper
- [ ] Create API endpoints in `chat_routes.py`
- [ ] Test with Postman/curl

### Week 2: Frontend Implementation
- [ ] Create `ChatInterface.jsx` component
- [ ] Implement session management UI
- [ ] Implement message display with sources
- [ ] Create chat input component
- [ ] Add document upload integration
- [ ] Style with CSS

### Week 3: Integration & Enhancement
- [ ] Connect frontend to backend APIs
- [ ] Implement context management
- [ ] Add response streaming (optional)
- [ ] Implement reference resolution (follow-ups)
- [ ] Add error handling and loading states

### Week 4: Testing & Polish
- [ ] End-to-end testing
- [ ] Performance optimization
- [ ] UI/UX refinements
- [ ] Add keyboard shortcuts
- [ ] Mobile responsiveness

---

## Key Features

### ✅ ChatGPT-Style Interface
- Clean, modern UI similar to ChatGPT
- Sidebar with conversation history
- Message bubbles for user/assistant
- Auto-scrolling to latest message

### ✅ Document Grounding
- All responses cite sources from knowledge base
- Show document name, page number, relevance score
- Click source to view original document location

### ✅ Semantic Search with Weaviate
- Hybrid search (semantic + keyword)
- Automatic query enhancement
- Reranking for best results
- Context-aware follow-ups

### ✅ Conversation Memory
- Multi-turn conversations
- Context from previous messages
- Reference resolution ("it", "that", etc.)
- Session persistence

### ✅ Document Management
- Upload PDFs mid-conversation
- Query across multiple documents
- Filter by specific documents

---

## Testing Plan

### Backend Tests
```bash
# Test session creation
curl -X POST http://localhost:8009/chat/session/new \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test-user"}'

# Test message sending
curl -X POST http://localhost:8009/chat/message \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "SESSION_ID",
    "message": "What are the main findings?",
    "options": {"max_sources": 5}
  }'

# Test session history
curl http://localhost:8009/chat/session/SESSION_ID/history
```

### Frontend Tests
1. Create new chat session
2. Send message and verify response
3. Check source citations appear
4. Test follow-up questions
5. Switch between sessions
6. Upload document mid-chat

---

## Deployment Considerations

### Environment Variables
```bash
# .env
OPENAI_API_KEY=your_key_here
WEAVIATE_URL=http://localhost:8080
WEAVIATE_API_KEY=your_key_here
CHAT_DB_PATH=chat_sessions.db
FLASK_PORT=8009
```

### Production Enhancements
- [ ] Add authentication (JWT tokens)
- [ ] Rate limiting per user
- [ ] WebSocket for real-time streaming
- [ ] Redis for session caching
- [ ] PostgreSQL instead of SQLite
- [ ] CDN for frontend assets
- [ ] Docker containerization
- [ ] Monitoring and logging

---

## Success Metrics

1. **Functionality**: All queries answered with KB sources
2. **Accuracy**: >90% of responses cite relevant documents
3. **Performance**: <2s response time for queries
4. **UX**: ChatGPT-like conversational experience
5. **Integration**: Seamless Weaviate semantic search

This plan provides a complete ChatGPT-style interface while maintaining document-grounded responses using Weaviate semantic search.

# services/chat_service.py
import os
import time
import openai
import asyncio
from typing import List, Dict, Optional
from dotenv import load_dotenv
from database.chat_db import ChatDatabase
from services.weaviate_search_service import WeaviateSearchService
from services.query_processor import QueryProcessor
from services.context_manager import ContextManager
from utils.kb_logger import KBLogger
from utils.token_tracker import TokenTracker, estimate_cost
from utils.quota_client import QuotaClientSync  # Only using for reporting, not enforcement
from utils.llm_error_handler import handle_llm_error, LLMServiceException, is_llm_error

# Ensure environment variables are loaded
load_dotenv()

# Initialize logger and token tracker
kb_logger = KBLogger()
token_tracker = TokenTracker()

# Initialize quota client (sync version for non-async methods)
# Set QUOTA_SERVICE_URL env var or defaults to http://localhost:8011
quota_client = QuotaClientSync()

# Enable/disable quota enforcement
QUOTA_ENABLED = os.getenv("QUOTA_ENABLED", "true").lower() == "true"


class ChatService:
    def __init__(self):
        self.chat_db = ChatDatabase()
        self.search_service = WeaviateSearchService()
        self.query_processor = QueryProcessor()
        self.context_manager = ContextManager()
        
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
        self.openai_client = openai.OpenAI(api_key=api_key)
    
    def process_message(
        self,
        session_id: str,
        user_message: str,
        options: Optional[Dict] = None,
        user_id: Optional[str] = None
    ) -> Dict:
        """
        Main chat processing pipeline
        
        Args:
            session_id: Chat session ID
            user_message: User's message
            options: Optional settings (max_sources, include_context, document_filter)
            user_id: User ID from JWT token for access control
        
        Returns:
            Dict with assistant message details
        """
        options = options or {}
        max_sources = options.get('max_sources', 5)
        include_context = options.get('include_context', True)
        document_filter = options.get('document_filter', [])
        
        print("\n" + "="*80)
        print(f"[ChatService] 🚀 STARTING MESSAGE PROCESSING")
        print(f"[ChatService] Session ID: {session_id}")
        print(f"[ChatService] User ID: {user_id}")
        print(f"[ChatService] User Message: {user_message}")
        print(f"[ChatService] Options: max_sources={max_sources}, include_context={include_context}")
        print(f"[ChatService] Document Filter: {document_filter}")
        print("="*80)
        
        # 0. Validate session ownership
        if user_id:
            session = self.chat_db.get_session(session_id)
            if not session:
                raise Exception("Session not found")
            if session.get('user_id') != user_id:
                raise Exception("Access denied - you don't own this session")
        
        # 1. Save user message
        user_msg = self.chat_db.save_message(
            session_id=session_id,
            role="user",
            content=user_message
        )
        print(f"[ChatService] Saved user message: {user_msg['message_id']}")
        
        # 2. Get conversation context
        context = []
        if include_context:
            all_messages = self.chat_db.get_session_messages(session_id)
            # Exclude the just-saved user message for context
            context = self.context_manager.get_recent_context(
                messages=all_messages[:-1],  # All except last (current message)
                max_messages=10,
                max_tokens=2000
            )
            print(f"\n[ChatService] 📚 CONTEXT RETRIEVAL")
            print(f"[ChatService] Retrieved {len(context)} context messages from history")
            for i, ctx_msg in enumerate(context[-3:]):  # Show last 3 for brevity
                print(f"[ChatService]   Context {i+1}: [{ctx_msg['role']}] {ctx_msg['content'][:100]}...")
        
        # 3. Process query (expand, resolve references)
        print(f"\n[ChatService] 🔍 QUERY PROCESSING")
        print(f"[ChatService] Original Query: {user_message}")
        processed_query = self.query_processor.enhance_query(
            query=user_message,
            context=context
        )
        print(f"[ChatService] Enhanced Query: {processed_query['search_query']}")
        print(f"[ChatService] Query expanded: {processed_query.get('is_expanded', False)}")
        
        # 4. Search Weaviate knowledge base
        search_filters = None
        if document_filter:
            search_filters = {'document_ids': document_filter}
        
        print(f"\n[ChatService] 🔎 WEAVIATE SEARCH")
        print(f"[ChatService] Search Query: {processed_query['search_query']}")
        print(f"[ChatService] Search Limit: 50")
        print(f"[ChatService] Search Filters: {search_filters}")
        
        search_results = self.search_service.hybrid_search(
            query=processed_query['search_query'],
            limit=50,  # Retrieve 50 chunks for comprehensive coverage
            filters=search_filters
        )
        
        print(f"[ChatService] ✅ Found {len(search_results)} search results from Weaviate")
        for i, result in enumerate(search_results[:3]):  # Show first 3
            print(f"[ChatService]   Result {i+1}:")
            print(f"[ChatService]     - Document: {result.get('document_name', 'Unknown')}")
            print(f"[ChatService]     - Page: {result.get('page', 'N/A')}")
            print(f"[ChatService]     - Score: {result.get('score', 0):.3f}")
            print(f"[ChatService]     - Text Preview: {result.get('text', '')[:100]}...")
        
        # 5. Rerank results
        print(f"\n[ChatService] 🎯 RERANKING RESULTS")
        print(f"[ChatService] Reranking {len(search_results)} results to top 15")
        
        top_chunks = self.query_processor.rerank_results(
            query=user_message,
            results=search_results,
            top_k=15  # Use top 15 chunks after reranking for better coverage
        )
        
        print(f"[ChatService] ✅ Selected top {len(top_chunks)} chunks after reranking")
        for i, chunk in enumerate(top_chunks):
            print(f"[ChatService]   Chunk {i+1}:")
            print(f"[ChatService]     - Document: {chunk.get('document_name', 'Unknown')}")
            print(f"[ChatService]     - Page: {chunk.get('page', 'N/A')}")
            print(f"[ChatService]     - Rerank Score: {chunk.get('rerank_score', chunk.get('score', 0)):.3f}")
        
        # 6. Token estimation (for logging purposes only - no enforcement)
        # Note: Token quota enforcement is disabled for Knowledge Base.
        # Users can use the KB functionality regardless of token usage.
        # Usage is still tracked/reported for analytics purposes after the LLM call.
        if QUOTA_ENABLED and user_id:
            estimated_tokens = self._estimate_tokens(user_message, context, top_chunks)
            print(f"\n[ChatService] 💰 TOKEN ESTIMATE (tracking only, no enforcement)")
            print(f"[ChatService] User ID: {user_id}")
            print(f"[ChatService] Estimated tokens: {estimated_tokens}")
        
        # 7. Generate response with OpenAI
        print(f"\n[ChatService] 🤖 GENERATING AI RESPONSE")
        print(f"[ChatService] Using {len(top_chunks)} knowledge chunks")
        print(f"[ChatService] Context messages: {len(context)}")
        
        assistant_response = self._generate_response(
            user_message=user_message,
            context=context,
            knowledge_chunks=top_chunks,
            chunks_retrieved=len(search_results),
            chunks_used=len(top_chunks),
            session_id=session_id,
            user_id=user_id
        )
        
        print(f"[ChatService] ✅ Generated response")
        print(f"[ChatService] Response Length: {len(assistant_response['content'])} characters")
        print(f"[ChatService] Tokens Used: {assistant_response['tokens_used']}")
        print(f"[ChatService] Response Preview: {assistant_response['content'][:200]}...")
        
        # 7. Save assistant message WITHOUT sources (sources removed for cleaner UI)
        assistant_msg = self.chat_db.save_message(
            session_id=session_id,
            role="assistant",
            content=assistant_response['content'],
            sources=None,  # No longer sending sources to frontend
            metadata={
                'tokens_used': assistant_response['tokens_used'],
                'chunks_retrieved': len(search_results),
                'chunks_used': len(top_chunks),
                'search_query': processed_query['search_query']
            }
        )
        
        print(f"\n[ChatService] 💾 SAVING RESULTS")
        print(f"[ChatService] Assistant Message ID: {assistant_msg['message_id']}")
        print(f"\n[ChatService] ✨ MESSAGE PROCESSING COMPLETE")
        print(f"[ChatService] Summary:")
        print(f"[ChatService]   - Chunks Retrieved: {len(search_results)}")
        print(f"[ChatService]   - Chunks Used: {len(top_chunks)}")
        print(f"[ChatService]   - Tokens Used: {assistant_response['tokens_used']}")
        print("="*80 + "\n")
        
        # 8. Update session metadata
        session = self.chat_db.get_session(session_id)
        if session:
            metadata = session.get('metadata', {})
            docs_referenced = metadata.get('documents_referenced', [])
            
            # Add new document IDs
            for chunk in top_chunks:
                doc_id = chunk.get('document_id')
                if doc_id and doc_id not in docs_referenced:
                    docs_referenced.append(doc_id)
            
            metadata['documents_referenced'] = docs_referenced
            metadata['total_chunks_used'] = metadata.get('total_chunks_used', 0) + len(top_chunks)
            
            self.chat_db.update_session_metadata(session_id, metadata)
        
        return assistant_msg
    
    def _estimate_tokens(
        self,
        user_message: str,
        context: List[Dict],
        knowledge_chunks: List[Dict]
    ) -> int:
        """
        Estimate tokens for a chat request.
        
        Rough estimation: ~4 characters = 1 token
        Plus buffer for system prompt and response.
        """
        # User message
        tokens = len(user_message) // 4
        
        # Context messages (previous conversation)
        for msg in context:
            tokens += len(msg.get('content', '')) // 4
        
        # Knowledge chunks
        for chunk in knowledge_chunks:
            tokens += len(chunk.get('text', '')) // 4
        
        # System prompt (~500 tokens) + expected response (~500 tokens)
        tokens += 1000
        
        return tokens
    
    def _generate_response(
        self,
        user_message: str,
        context: List[Dict],
        knowledge_chunks: List[Dict],
        chunks_retrieved: int = 0,
        chunks_used: int = 0,
        session_id: str = None,
        user_id: str = None
    ) -> Dict:
        """
        Generate response using OpenAI with KB context
        """
        start_time = time.time()  # Track response time
        
        # Build context from knowledge base chunks
        kb_context = self.context_manager.build_kb_context(knowledge_chunks)
        
        # Build messages for OpenAI
        messages = [
            {
                "role": "system",
                "content": f"""You are a helpful assistant that answers questions based on uploaded documents in a knowledge base.

IMPORTANT RULES:
1. Base your answers ONLY on the provided document excerpts below
2. Always cite sources using [Source: filename, Page X] format in your response
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

Use all this information to provide comprehensive, well-cited answers that synthesize ALL provided sources.
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
        
        try:
            # Call OpenAI
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                temperature=0.7,
                max_tokens=1000
            )
            
            duration_ms = (time.time() - start_time) * 1000  # Calculate duration
            tokens_used = response.usage.total_tokens
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
            cost = estimate_cost("gpt-4o", total_tokens=tokens_used)
            
            # Log the chat LLM call with full metrics
            kb_logger.log_llm_call(
                pipeline_type="chat",
                stage="response_generation",
                model="gpt-4o",
                tokens=tokens_used,
                cost=cost,
                success=True,
                duration_ms=duration_ms,
                chunks_retrieved=chunks_retrieved,
                chunks_used=chunks_used,
                session_id=session_id
            )
            
            # Report usage to Token Quota Service
            if QUOTA_ENABLED and user_id:
                try:
                    quota_client.report(
                        user_id=user_id,
                        service="knowledge-base",
                        model="gpt-4o",
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        operation="chat",
                        session_id=session_id,
                        metadata={
                            "chunks_retrieved": chunks_retrieved,
                            "chunks_used": chunks_used,
                            "duration_ms": duration_ms
                        }
                    )
                    print(f"[ChatService] 📊 Reported {tokens_used} tokens to quota service")
                except Exception as quota_error:
                    print(f"[ChatService] ⚠️ Failed to report quota: {quota_error}")
            
            return {
                'content': response.choices[0].message.content,
                'tokens_used': tokens_used,
                'duration_ms': duration_ms
            }
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            print(f"[ChatService] Error generating response: {e}")
            import traceback
            traceback.print_exc()
            
            # Log the error with duration
            kb_logger.log_llm_call(
                pipeline_type="chat",
                stage="response_generation",
                model="gpt-4o",
                tokens=0,
                cost=0,
                success=False,
                error=str(e),
                duration_ms=duration_ms,
                chunks_retrieved=chunks_retrieved,
                chunks_used=chunks_used,
                session_id=session_id
            )
            
            # Check if this is an LLM-specific error and raise it properly
            if is_llm_error(e):
                llm_error = handle_llm_error(e, context="KB Chat - Response Generation")
                raise LLMServiceException(llm_error)
            
            # Fallback response for non-LLM errors
            return {
                'content': "I apologize, but I encountered an error while processing your question. Please try again.",
                'tokens_used': 0
            }
    
    def create_session(self, user_id: str, title: str = None) -> Dict:
        """Create a new chat session"""
        return self.chat_db.create_session(user_id, title)
    
    def get_session_history(self, session_id: str, limit: Optional[int] = None, user_id: Optional[str] = None) -> Dict:
        """Get session with message history, enforcing ownership"""
        session = self.chat_db.get_session(session_id)
        if not session:
            return None
        
        # Validate ownership
        if user_id and session.get('user_id') != user_id:
            return None
        
        messages = self.chat_db.get_session_messages(session_id, limit=limit)
        
        return {
            'session': session,
            'messages': messages
        }
    
    def get_user_sessions(self, user_id: str, limit: int = 20, offset: int = 0) -> Dict:
        """Get all sessions for a user"""
        sessions, total = self.chat_db.get_user_sessions(user_id, limit, offset)
        
        return {
            'sessions': sessions,
            'total': total,
            'limit': limit,
            'offset': offset,
            'has_more': offset + len(sessions) < total
        }
    
    def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """Delete a session, enforcing ownership"""
        # Validate ownership before deletion
        if user_id:
            session = self.chat_db.get_session(session_id)
            if not session:
                return False
            if session.get('user_id') != user_id:
                return False
        
        return self.chat_db.delete_session(session_id)
    
    def stream_response(
        self,
        session_id: str,
        user_message: str,
        options: Optional[Dict] = None,
        user_id: Optional[str] = None
    ):
        """
        Stream response tokens one by one via generator.
        This method performs all the same steps as process_message,
        but yields tokens progressively instead of returning full response.
        
        Yields:
            JSON string: {"type": "token", "content": "token text"}
            JSON string: {"type": "done", "content": "full_response", "tokens": count}
            JSON string: {"type": "error", "content": "error message"}
        """
        import json
        
        options = options or {}
        max_sources = options.get('max_sources', 5)
        include_context = options.get('include_context', True)
        document_filter = options.get('document_filter', [])
        
        try:
            # Validate session ownership
            if user_id:
                session = self.chat_db.get_session(session_id)
                if not session:
                    yield json.dumps({"type": "error", "content": "Session not found"})
                    return
                if session.get('user_id') != user_id:
                    yield json.dumps({"type": "error", "content": "Access denied"})
                    return
            
            # Save user message
            user_msg = self.chat_db.save_message(
                session_id=session_id,
                role="user",
                content=user_message
            )
            
            # Get conversation context
            context = []
            if include_context:
                all_messages = self.chat_db.get_session_messages(session_id)
                context = self.context_manager.get_recent_context(
                    messages=all_messages[:-1],
                    max_messages=10,
                    max_tokens=2000
                )
            
            # Process query
            processed_query = self.query_processor.enhance_query(
                query=user_message,
                context=context
            )
            
            # Search Weaviate
            search_filters = None
            if document_filter:
                search_filters = {'document_ids': document_filter}
            
            search_results = self.search_service.hybrid_search(
                query=processed_query['search_query'],
                limit=50,
                filters=search_filters
            )
            
            # Rerank results
            top_chunks = self.query_processor.rerank_results(
                query=user_message,
                results=search_results,
                top_k=15
            )
            
            # Generate streaming response
            start_time = time.time()
            kb_context = self.context_manager.build_kb_context(top_chunks)
            
            # Build messages for OpenAI
            messages = [
                {
                    "role": "system",
                    "content": f"""You are a helpful assistant that answers questions based on uploaded documents in a knowledge base.

IMPORTANT RULES:
1. Base your answers ONLY on the provided document excerpts below
2. Always cite sources using [Source: filename, Page X] format in your response
3. If the information needed to answer the question is not in the provided excerpts, say "I don't have enough information in the uploaded documents to answer that question fully."
4. Be conversational but accurate
5. Use direct quotes when appropriate
6. If asked about something not in the documents, politely say so and suggest what topics the documents do cover
7. Pay attention to the Type field (heading, list, table, image, etc.) to understand the content structure
8. Consider the Section, Context, and Tags provided with each source for better understanding

Available Document Context:
{kb_context}

Note: Each source may include section, type, context, and tags information.
Use all this information to provide comprehensive, well-cited answers."""
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
            
            # Stream from OpenAI with streaming=True
            full_response = ""
            total_tokens = 0
            input_tokens = 0
            output_tokens = 0
            
            with self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                temperature=0.7,
                max_tokens=1000,
                stream=True  # Enable streaming
            ) as stream:
                for chunk in stream:
                    if chunk.choices[0].delta.content:
                        token = chunk.choices[0].delta.content
                        full_response += token
                        # Yield token to client
                        yield json.dumps({"type": "token", "content": token})
                    
                    # Check for usage info in final chunk
                    if hasattr(chunk, 'usage') and chunk.usage:
                        total_tokens = chunk.usage.total_tokens
                        input_tokens = chunk.usage.prompt_tokens
                        output_tokens = chunk.usage.completion_tokens
            
            # If we didn't get usage from streaming (OpenAI limitation), estimate
            if not total_tokens:
                total_tokens = len(full_response) // 4 + len("".join([m.get('content', '') for m in messages])) // 4
                output_tokens = len(full_response) // 4
                input_tokens = total_tokens - output_tokens
            
            # Save assistant message
            assistant_msg = self.chat_db.save_message(
                session_id=session_id,
                role="assistant",
                content=full_response,
                sources=None,
                metadata={
                    'tokens_used': total_tokens,
                    'chunks_retrieved': len(search_results),
                    'chunks_used': len(top_chunks),
                    'search_query': processed_query['search_query']
                }
            )
            
            # Report usage to Token Quota Service
            if QUOTA_ENABLED and user_id:
                try:
                    quota_client.report(
                        user_id=user_id,
                        service="knowledge-base",
                        model="gpt-4o",
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        operation="chat_stream",
                        session_id=session_id,
                        metadata={
                            "chunks_retrieved": len(search_results),
                            "chunks_used": len(top_chunks),
                            "duration_ms": (time.time() - start_time) * 1000
                        }
                    )
                    print(f"[ChatService] 📊 Reported {total_tokens} tokens to quota service (streaming)")
                except Exception as quota_error:
                    print(f"[ChatService] ⚠️ Failed to report quota: {quota_error}")
            
            # Send completion signal with token count
            yield json.dumps({"type": "done", "content": full_response, "tokens": total_tokens})
            
        except Exception as e:
            print(f"[ChatService] Error streaming response: {e}")
            import traceback
            traceback.print_exc()
            
            if is_llm_error(e):
                llm_error = handle_llm_error(e, context="KB Chat - Stream Response")
                yield json.dumps({"type": "error", "content": llm_error.get('message', str(e))})
            else:
                yield json.dumps({"type": "error", "content": "Failed to generate response. Please try again."})

# services/query_processor.py
import os
import openai
from typing import Dict, List
from dotenv import load_dotenv
from utils.kb_logger import KBLogger
from utils.token_tracker import TokenTracker, estimate_cost

# Ensure environment variables are loaded
load_dotenv()

# Initialize logger and token tracker
kb_logger = KBLogger()
token_tracker = TokenTracker()

class QueryProcessor:
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
        self.openai_client = openai.OpenAI(api_key=api_key)
    
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
        
        # Extract key search terms (for now just use the resolved query)
        search_query = resolved_query
        
        return {
            'original_query': query,
            'resolved_query': resolved_query,
            'search_query': search_query
        }
    
    def _is_followup(self, query: str) -> bool:
        """Check if query is a follow-up"""
        # Expanded pattern list for better detection
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
    
    def _resolve_references(self, query: str, context: List[Dict]) -> str:
        """Resolve ambiguous references using context"""
        # Get last few messages to understand what "it" refers to
        last_messages = context[-4:] if len(context) >= 4 else context
        
        if not last_messages:
            return query
        
        context_text = "\n".join([
            f"{msg['role']}: {msg['content']}"
            for msg in last_messages
        ])
        
        try:
            # Use OpenAI to resolve
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
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
            
            # Log the reference resolution LLM call
            tokens_used = response.usage.total_tokens if response.usage else 0
            cost = estimate_cost("gpt-4o-mini", total_tokens=tokens_used)
            kb_logger.log_llm_call(
                pipeline_type="chat",
                stage="reference_resolution",
                model="gpt-4o-mini",
                tokens=tokens_used,
                cost=cost,
                success=True
            )
            
            print(f"[QueryProcessor] Resolved '{query}' to '{resolved}'")
            return resolved
        except Exception as e:
            # Log error
            kb_logger.log_llm_call(
                pipeline_type="chat",
                stage="reference_resolution",
                model="gpt-4o-mini",
                tokens=0,
                cost=0,
                success=False,
                error=str(e)
            )
            print(f"[QueryProcessor] Error resolving query: {e}")
            return query
    
    def rerank_results(
        self,
        query: str,
        results: List[Dict],
        top_k: int = 5
    ) -> List[Dict]:
        """
        Rerank search results using multi-factor scoring:
        - Weaviate hybrid score (semantic + BM25)
        - Query-specific section/context match
        - Content type preference (detailed content > headers)
        - Text length (longer chunks often have more detail)
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
            print(f"[QueryProcessor] 🗑️ Removed {dedup_count} duplicate chunks ({len(results)} → {len(unique_results)})")
        
        results = unique_results
        print(f"[QueryProcessor] 🎯 Intelligent reranking of {len(results)} results")
        
        # Extract query keywords for matching (remove common stop words)
        query_lower = query.lower()
        stop_words = {'the', 'a', 'an', 'in', 'on', 'at', 'to', 'for', 'of', 'and', 'or', 'but', 'is', 'are', 'was', 'were', 'can', 'you', 'me', 'about', 'tell'}
        query_words = set(word for word in query_lower.split() if word not in stop_words and len(word) > 2)
        
        print(f"[QueryProcessor] 🔍 Query keywords: {query_words}")
        
        # Score each result with multiple factors
        for result in results:
            base_score = result.get('score', 0.5)
            
            # Factor 1: Base Weaviate score (35% weight)
            score_component = base_score * 0.35
            
            # Factor 2: Enhanced Section Matching with Hierarchy (25% weight)
            section = result.get('section', '').lower()
            section_title = result.get('section_title', '').lower()
            parent_section = result.get('parent_section', '').lower()
            context = result.get('context', '').lower()
            text = result.get('text', '').lower()
            
            section_match = 0.0
            
            # Match against section title (most descriptive)
            if section_title and any(word in section_title for word in query_words if len(word) > 3):
                section_match = 0.8
                print(f"[QueryProcessor]   ✅ Section title match: '{section_title}' for section {section}")
            
            # Match against parent section (for subsection content)
            elif parent_section:
                # Check if query is about the parent section
                parent_title = ''
                # Find parent section title from other results
                for r in results:
                    if r.get('section', '') == parent_section:
                        parent_title = r.get('section_title', '').lower()
                        break
                
                if parent_title and any(word in parent_title for word in query_words if len(word) > 3):
                    section_match = 0.7  # Subsection content is highly relevant
                    print(f"[QueryProcessor]   🔗 Parent section match: section {section} under parent '{parent_section}' ({parent_title})")
            
            # Match against context
            if context and any(word in context for word in query_words if len(word) > 3):
                section_match = max(section_match, 0.6)
            
            # Fallback: Check if keywords appear in chunk text
            if section_match == 0 and any(word in text[:300] for word in query_words if len(word) > 4):
                section_match = 0.4
            
            section_component = section_match * 0.25
            
            # Factor 3: Tags match (15% weight - NEW!)
            tags = result.get('tags', [])
            tags_match = 0.0
            if tags:
                # Convert tags to lowercase for comparison
                tags_lower = [str(tag).lower() for tag in tags]
                # Check how many query words match tags
                matching_tags = sum(1 for word in query_words if any(word in tag for tag in tags_lower))
                if matching_tags > 0:
                    tags_match = min(matching_tags / len(query_words), 1.0)  # Normalize
            
            tags_component = tags_match * 0.15
            
            # Factor 4: Content type preference (15% weight)
            # Prefer detailed content over headers
            chunk_type = result.get('chunk_type', 'text').lower()
            text_length = len(result.get('text', ''))
            
            type_score = 0.0
            if chunk_type in ['paragraph', 'text'] and text_length > 200:
                type_score = 1.0  # Detailed paragraphs are best
            elif chunk_type in ['list', 'table']:
                type_score = 0.9  # Lists and tables have structured info
            elif chunk_type == 'heading':
                # ENHANCED: Penalize headers more when query asks for details
                if text_length < 100:
                    # Very short header (like "SECTION 3: TITLE")
                    # Check if query is asking for details (contains words like "about", "tell", "what", "how")
                    detail_words = ['about', 'tell', 'what', 'how', 'explain', 'describe', 'detail']
                    if any(word in query_lower for word in detail_words):
                        type_score = 0.1  # Heavily penalize headers when details are requested
                    else:
                        type_score = 0.3  # Still low, but not as bad
                else:
                    type_score = 0.5  # Longer headers might have some content
            else:
                type_score = 0.7  # Other content
            
            type_component = type_score * 0.15
            
            # Factor 5: Text length preference (15% weight)
            # Longer chunks often have more detailed information
            length_score = min(text_length / 1000.0, 1.0)  # Normalize to 0-1
            length_component = length_score * 0.15
            
            # Calculate final rerank score
            rerank_score = score_component + section_component + tags_component + type_component + length_component
            
            # Store both original and rerank scores
            result['original_score'] = base_score
            result['rerank_score'] = rerank_score
            result['score_breakdown'] = {
                'base': score_component,
                'section_match': section_component,
                'tags_match': tags_component,
                'content_type': type_component,
                'length': length_component
            }
        
        # Sort by rerank score
        sorted_results = sorted(results, key=lambda x: x.get('rerank_score', 0), reverse=True)
        
        # Filter out low-relevance results (score threshold)
        # Only keep chunks that scored at least 0.20 OR are in top 5
        min_score_threshold = 0.20
        filtered_results = []
        for i, result in enumerate(sorted_results):
            score = result.get('rerank_score', 0)
            if score >= min_score_threshold or i < 5:
                filtered_results.append(result)
        
        if len(filtered_results) < len(sorted_results):
            print(f"[QueryProcessor] 🎯 Filtered out {len(sorted_results) - len(filtered_results)} low-relevance chunks (below {min_score_threshold})")
        
        sorted_results = filtered_results
        
        # Log reranking details
        print(f"[QueryProcessor] 📊 Reranking results:")
        for i, result in enumerate(sorted_results[:top_k]):
            doc = result.get('document_name', 'Unknown')
            page = result.get('page', 'N/A')
            orig = result.get('original_score', 0)
            new = result.get('rerank_score', 0)
            chunk_type = result.get('chunk_type', 'text')
            text_preview = result.get('text', '')[:50]
            breakdown = result.get('score_breakdown', {})
            tags = result.get('tags', [])
            
            print(f"[QueryProcessor]   #{i+1}: {doc} p{page} | Original: {orig:.3f} → Rerank: {new:.3f} | Type: {chunk_type}")
            print(f"[QueryProcessor]        Preview: {text_preview}...")
            print(f"[QueryProcessor]        Breakdown: Base={breakdown.get('base', 0):.3f}, Section={breakdown.get('section_match', 0):.3f}, Tags={breakdown.get('tags_match', 0):.3f}, Type={breakdown.get('content_type', 0):.3f}, Length={breakdown.get('length', 0):.3f}")
            if tags:
                print(f"[QueryProcessor]        Tags: {', '.join(str(t) for t in tags[:5])}")
        
        return sorted_results[:top_k]

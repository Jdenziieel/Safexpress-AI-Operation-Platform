"""
Context Manager for Knowledge Base Lambda functions.

Builds rich context strings from knowledge base chunks with intelligent handling:
- Rich source headers with section, type, context, tags metadata
- Smart sentence-boundary truncation (no mid-sentence cuts)
- Structured content splitting for tables/lists (preserves headers)
- Conversation history formatting for OpenAI

Ported from original knowledge-base/services/context_manager.py to maintain
the robust context building that was lost during Lambda migration.
"""
import re
from typing import List, Dict


class ContextManager:
    def __init__(self):
        self.max_context_tokens = 3000  # Token budget for context
        self.max_chunk_length = 800     # Max chars per regular text chunk
        self.structured_content_limit = 1200  # Higher limit for tables/lists
    
    def get_recent_context(
        self,
        messages: List[Dict],
        max_messages: int = 10,
        max_tokens: int = 2000
    ) -> List[Dict]:
        """
        Get recent conversation context for query processing.
        
        Args:
            messages: List of message dicts with role and content
            max_messages: Maximum number of messages to include
            max_tokens: Maximum token estimate for context
        
        Returns:
            List of message dicts suitable for OpenAI API
        """
        if not messages:
            return []
        
        # Take the most recent messages
        recent_messages = messages[-max_messages:] if len(messages) > max_messages else messages
        
        # Estimate tokens (rough: ~4 chars per token)
        context = []
        total_chars = 0
        max_chars = max_tokens * 4
        
        # Go backwards to prioritize recent messages
        for msg in reversed(recent_messages):
            content = msg.get('content', '')
            chars = len(content)
            
            if total_chars + chars > max_chars and context:
                break
            
            context.insert(0, {
                'role': msg['role'],
                'content': content
            })
            total_chars += chars
        
        return context
    
    def build_kb_context(self, chunks: List[Dict]) -> str:
        """
        Build context string from knowledge base chunks with intelligent handling.
        
        Creates rich source headers with metadata and handles different content types
        (text, tables, lists) appropriately.
        
        Args:
            chunks: List of chunk dicts from Weaviate search + reranking
        
        Returns:
            Formatted context string with sources, sections, context, types, and tags
        """
        if not chunks:
            return "No relevant information found in the knowledge base."
        
        context_parts = []
        truncation_events = 0
        
        for i, chunk in enumerate(chunks, 1):
            doc_name = chunk.get('document_name', 'Unknown')
            page = chunk.get('page', 'N/A')
            text = chunk.get('text', '')
            chunk_type = chunk.get('chunk_type', 'text')
            original_length = len(text)
            
            # Extract metadata properties
            section = chunk.get('section', '')
            context_info = chunk.get('context', '')
            tags = chunk.get('tags', [])
            
            # Handle different chunk types with intelligent splitting
            if chunk_type in ['table', 'list']:
                # For structured content, use higher limit or split if too long
                if len(text) > self.structured_content_limit:
                    sub_texts = self._split_structured_content(text, chunk_type)
                    for j, sub_text in enumerate(sub_texts):
                        source_header = self._format_source_header(
                            doc_name, page, section, chunk_type, i,
                            j + 1 if len(sub_texts) > 1 else None
                        )
                        context_line = f"Context: {context_info}\n" if context_info and context_info.strip() else ""
                        tags_line = f"Tags: {', '.join(str(t) for t in tags)}\n" if tags and len(tags) > 0 else ""
                        source_block = f"{source_header}\n{context_line}{tags_line}{sub_text}"
                        context_parts.append(source_block)
                    truncation_events += 1
                    print(f"[ContextManager] Split large {chunk_type} chunk {i}: {original_length} chars -> {len(sub_texts)} parts")
                else:
                    # Keep structured content intact even if slightly over regular limit
                    source_header = self._format_source_header(doc_name, page, section, chunk_type, i)
                    context_line = f"Context: {context_info}\n" if context_info and context_info.strip() else ""
                    tags_line = f"Tags: {', '.join(str(t) for t in tags)}\n" if tags and len(tags) > 0 else ""
                    source_block = f"{source_header}\n{context_line}{tags_line}{text}"
                    context_parts.append(source_block)
            else:
                # Handle regular text with smart truncation
                if len(text) > self.max_chunk_length:
                    text = self._smart_truncate(text, self.max_chunk_length)
                    truncation_events += 1
                    print(f"[ContextManager] Truncated chunk {i}: {original_length} -> {len(text)} chars")
                
                source_header = self._format_source_header(doc_name, page, section, chunk_type, i)
                context_line = f"Context: {context_info}\n" if context_info and context_info.strip() else ""
                tags_line = f"Tags: {', '.join(str(t) for t in tags)}\n" if tags and len(tags) > 0 else ""
                source_block = f"{source_header}\n{context_line}{tags_line}{text}"
                context_parts.append(source_block)
        
        if truncation_events > 0:
            print(f"[ContextManager] {truncation_events}/{len(chunks)} chunks were truncated or split")
        
        return "\n\n".join(context_parts)
    
    def _format_source_header(
        self,
        doc_name: str,
        page,
        section: str,
        chunk_type: str,
        index: int,
        sub_index: int = None
    ) -> str:
        """Format source header with all metadata."""
        header = f"[Source {index}"
        if sub_index:
            header += f".{sub_index}"
        header += f": {doc_name}, Page {page}"
        
        if section and section.strip():
            header += f", Section: {section}"
        
        if chunk_type and chunk_type not in ['text', 'paragraph']:
            header += f", Type: {chunk_type}"
        
        header += "]"
        return header
    
    def _split_structured_content(self, text: str, chunk_type: str) -> List[str]:
        """Split tables/lists at natural boundaries to preserve all information."""
        if chunk_type == 'table':
            return self._split_table(text)
        elif chunk_type == 'list':
            return self._split_list(text)
        else:
            return [text]
    
    def _split_table(self, text: str) -> List[str]:
        """Split table at row boundaries, preserving header."""
        lines = text.split('\n')
        
        if len(lines) <= 6:  # Small table, keep together
            return [text]
        
        # Identify header (usually first 1-2 lines)
        header_lines = []
        data_lines = []
        
        for i, line in enumerate(lines):
            if i == 0 or (i == 1 and ('|' in line or '-' in line)):
                header_lines.append(line)
            elif line.strip():
                data_lines.append(line)
        
        header = '\n'.join(header_lines)
        
        # Group data lines into chunks
        groups = []
        current_group = []
        current_length = len(header)
        
        for line in data_lines:
            line_length = len(line) + 1  # +1 for newline
            
            if current_length + line_length > 800 and current_group:
                group_text = header + '\n' + '\n'.join(current_group)
                groups.append(group_text)
                current_group = [line]
                current_length = len(header) + line_length
            else:
                current_group.append(line)
                current_length += line_length
        
        if current_group:
            group_text = header + '\n' + '\n'.join(current_group)
            groups.append(group_text)
        
        return groups if groups else [text]
    
    def _split_list(self, text: str) -> List[str]:
        """Split list at item boundaries."""
        items = re.split(r'\n(?=\d+\.|[\-\*\•]|\w+\))', text)
        
        if len(items) <= 5:  # Small list, keep together
            return [text]
        
        groups = []
        current_group = []
        current_length = 0
        
        for item in items:
            item_length = len(item) + 1
            
            if current_length + item_length > 800 and current_group:
                groups.append('\n'.join(current_group))
                current_group = [item]
                current_length = item_length
            else:
                current_group.append(item)
                current_length += item_length
        
        if current_group:
            groups.append('\n'.join(current_group))
        
        return groups if groups else [text]
    
    def _smart_truncate(self, text: str, max_length: int) -> str:
        """
        Truncate text at natural boundaries (sentence/paragraph) to minimize information loss.
        
        Args:
            text: Text to truncate
            max_length: Maximum character length
        
        Returns:
            Truncated text with continuation indicator
        """
        if len(text) <= max_length:
            return text
        
        truncated = text[:max_length]
        
        # Find last sentence end within the last 30% of the truncated text
        search_start = int(max_length * 0.7)
        
        sentence_ends = [
            (truncated.rfind('. ', search_start), '. '),
            (truncated.rfind('.\n', search_start), '.\n'),
            (truncated.rfind('! ', search_start), '! '),
            (truncated.rfind('? ', search_start), '? '),
            (truncated.rfind('\n\n', search_start), '\n\n')
        ]
        
        best_pos = -1
        best_suffix = ''
        for pos, suffix in sentence_ends:
            if pos > best_pos:
                best_pos = pos
                best_suffix = suffix
        
        if best_pos > 0:
            return text[:best_pos + len(best_suffix)] + "[Content continues...]"
        
        # Fallback: truncate at word boundary
        last_space = truncated.rfind(' ', search_start)
        if last_space > 0:
            return text[:last_space] + "..."
        
        # Last resort: hard truncate
        return text[:max_length] + "..."
    
    def format_sources(self, chunks: List[Dict]) -> List[Dict]:
        """
        Format chunks into source citations with all metadata.
        
        Args:
            chunks: List of chunk dicts from Weaviate
        
        Returns:
            List of formatted source dicts with complete metadata
        """
        sources = []
        for chunk in chunks:
            sources.append({
                'chunk_id': chunk.get('chunk_id'),
                'document_name': chunk.get('document_name', 'Unknown'),
                'page': chunk.get('page', 0),
                'section': chunk.get('section', ''),
                'chunk_type': chunk.get('chunk_type', 'text'),
                'relevance_score': chunk.get('score', 0),
                'text': chunk.get('text', '')[:200] + "..." if len(chunk.get('text', '')) > 200 else chunk.get('text', ''),
                'context': chunk.get('context', ''),
                'tags': chunk.get('tags', [])
            })
        
        return sources

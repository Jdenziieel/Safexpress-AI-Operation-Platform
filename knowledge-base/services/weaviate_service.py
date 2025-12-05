"""Weaviate service for knowledge base operations."""
import json
from database.weaviate_client import get_weaviate_client
from services.openai_service import get_openai_client, rerank_with_openai
from config import Config


def query_weaviate():
    """Query the Weaviate knowledge base with reranking."""
    client = get_weaviate_client()
    openai_client = get_openai_client()
    knowledge_base = client.collections.use("KnowledgeBase")

    generate_prompt = """You are an assistant for a logistics company's knowledge base. You are given chunks of text retrieved from company documents (policies, manuals, contracts, and other uploaded files). Your task is to:

    Answer the user's question based only on the provided chunks.

    Summarize or explain clearly if the answer requires synthesis across multiple chunks.

    Always cite your sources by including the document name, section, and page number (if available) where the information came from.

    If the answer is not found in the chunks, say that the information is not available in the provided documents. Do not make up information."""

    query_text = "Who are the members of the project?"

    # Retrieve chunks using hybrid search
    response = knowledge_base.query.hybrid(
        query=query_text,
        alpha=Config.HYBRID_SEARCH_ALPHA,
        limit=Config.HYBRID_SEARCH_LIMIT,
    )

    print(f"Initial retrieval: {len(response.objects)} chunks")

    # Step 2: Rerank the retrieved chunks
    reranked_chunks = rerank_with_openai(query_text, response.objects, top_m=Config.TOP_M_RERANK)
    print(f"After reranking: {len(reranked_chunks)} chunks")

    # Step 3: Extract just the chunk objects for context
    top_chunks = [chunk for chunk, score in reranked_chunks]
    
    # Build context string from top reranked chunks
    context_parts = []
    for i, (chunk, score) in enumerate(reranked_chunks, 1):
        props = chunk.properties
        source_info = f"[Source: {props.get('section', 'Unknown')}, Page {props.get('page', 'N/A')}]"
        context_parts.append(f"Chunk {i} (relevance: {score:.2f}): {props.get('text', '')} {source_info}")
    
    context_text = "\n\n".join(context_parts)
    
    # Generate final response using OpenAI directly
    messages = [
        {"role": "system", "content": generate_prompt},
        {"role": "user", "content": f"Query: {query_text}\n\nContext:\n{context_text}\n\nAnswer:"}
    ]
    
    try:
        generation_response = openai_client.chat.completions.create(
            model=Config.OPENAI_MODEL,
            messages=messages,
            temperature=Config.TEMPERATURE,
            max_tokens=Config.MAX_TOKENS
        )
        
        generated_answer = generation_response.choices[0].message.content
        
        # Print results
        print("Retrieved and reranked context:")
        for i, (chunk, score) in enumerate(reranked_chunks, 1):
            print(f"\nChunk {i} (Score: {score:.2f}):")
            print(json.dumps(chunk.properties, indent=2))
        
        print(f"\nGenerated Answer:\n{generated_answer}")
        
        return {
            "answer": generated_answer,
            "context_chunks": [chunk.properties for chunk, score in reranked_chunks],
            "rerank_scores": [score for chunk, score in reranked_chunks]
        }
        
    except Exception as e:
        print(f"Error in generation: {e}")
        return None

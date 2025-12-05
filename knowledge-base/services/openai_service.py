"""OpenAI API service for AI operations."""
import re
from openai import OpenAI
from config import Config


# Initialize OpenAI client
client = OpenAI(api_key=Config.OPENAI_API_KEY)


def get_openai_client():
    """Get the OpenAI client instance."""
    return client


def rerank_with_openai(query, retrieved_chunks, top_m=5):
    """Rerank retrieved chunks using OpenAI."""
    reranked = []
    for chunk in retrieved_chunks:
        text = chunk.properties.get("text", "")
        if not text.strip():
            continue
            
        prompt = f"""Score the relevance of this passage to the query on a scale of 0.0 to 1.0.
        Only respond with a number.

        Query: {query}
        Passage: {text[:1000]}...

        Relevance score:"""

        try:
            response = client.chat.completions.create(
                model=Config.OPENAI_MINI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=10
            )
            
            score_text = response.choices[0].message.content.strip()
            # Extract just the number from the response
            score_match = re.search(r'(\d*\.?\d+)', score_text)
            if score_match:
                score = float(score_match.group(1))
                score = min(1.0, max(0.0, score))  # Clamp between 0 and 1
            else:
                score = 0.0
                
            reranked.append((chunk, score))
            
        except Exception as e:
            print(f"Error scoring chunk: {e}")
            # Fallback score
            reranked.append((chunk, 0.5))
    
    # Sort by score, descending
    reranked.sort(key=lambda x: x[1], reverse=True)
    return reranked[:top_m]

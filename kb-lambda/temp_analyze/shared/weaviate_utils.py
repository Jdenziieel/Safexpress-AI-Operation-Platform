"""
Weaviate utilities for Knowledge Base Lambda functions.
Connects to Weaviate Cloud for vector operations.
"""
import os
import weaviate
from weaviate.classes.config import Configure, Property, DataType
from weaviate.classes.query import MetadataQuery, Filter
from typing import List, Dict, Optional, Any

# Weaviate configuration from environment
WEAVIATE_URL = os.environ.get('WEAVIATE_URL', '')
WEAVIATE_API_KEY = os.environ.get('WEAVIATE_API_KEY', '')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')

# Singleton client
_client = None


def get_weaviate_client():
    """
    Get or create Weaviate client connection.
    
    Returns:
        weaviate.WeaviateClient: Connected client
    """
    global _client
    
    if _client is None:
        if not WEAVIATE_URL or not WEAVIATE_API_KEY:
            raise Exception("Weaviate configuration missing: WEAVIATE_URL and WEAVIATE_API_KEY required")
        
        _client = weaviate.connect_to_weaviate_cloud(
            cluster_url=WEAVIATE_URL,
            auth_credentials=weaviate.auth.AuthApiKey(WEAVIATE_API_KEY),
            headers={"X-OpenAI-Api-Key": OPENAI_API_KEY}
        )
    
    return _client


def close_weaviate_client():
    """Close Weaviate client connection."""
    global _client
    if _client:
        _client.close()
        _client = None


def ensure_collections_exist():
    """
    Ensure required Weaviate collections exist.
    Creates them if they don't.
    """
    client = get_weaviate_client()
    
    # Check/create KnowledgeBase collection
    if not client.collections.exists("KnowledgeBase"):
        client.collections.create(
            name="KnowledgeBase",
            vectorizer_config=Configure.Vectorizer.text2vec_openai(
                model="text-embedding-3-small"
            ),
            properties=[
                Property(name="text", data_type=DataType.TEXT),
                Property(name="chunk_id", data_type=DataType.TEXT),
                Property(name="doc_id", data_type=DataType.TEXT),
                Property(name="file_name", data_type=DataType.TEXT),
                Property(name="section", data_type=DataType.TEXT),
                Property(name="page", data_type=DataType.INT),
                Property(name="chunk_index", data_type=DataType.INT),
                Property(name="total_chunks", data_type=DataType.INT),
                Property(name="metadata", data_type=DataType.TEXT),
            ]
        )
        print("Created KnowledgeBase collection")


def get_knowledge_base_collection():
    """Get the KnowledgeBase collection."""
    client = get_weaviate_client()
    ensure_collections_exist()
    return client.collections.get("KnowledgeBase")


def upload_chunks_to_weaviate(chunks: List[Dict], doc_id: str, file_name: str) -> int:
    """
    Upload chunks to Weaviate KnowledgeBase collection.
    
    Args:
        chunks: List of chunk dictionaries with text and metadata
        doc_id: Document ID
        file_name: Source filename
        
    Returns:
        int: Number of chunks uploaded
    """
    import json
    import uuid
    
    collection = get_knowledge_base_collection()
    uploaded = 0
    
    with collection.batch.dynamic() as batch:
        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}-{i}"
            
            properties = {
                "text": chunk.get("text", chunk.get("content", "")),
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "file_name": file_name,
                "section": chunk.get("section", chunk.get("metadata", {}).get("section", "Unknown")),
                "page": chunk.get("page", chunk.get("metadata", {}).get("page", 1)),
                "chunk_index": i,
                "total_chunks": len(chunks),
                "metadata": json.dumps(chunk.get("metadata", {}))
            }
            
            batch.add_object(
                properties=properties,
                uuid=str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id))
            )
            uploaded += 1
    
    return uploaded


def hybrid_search(query: str, limit: int = 10, alpha: float = 0.7, 
                  doc_filter: List[str] = None) -> List[Dict]:
    """
    Perform hybrid search (vector + keyword) on knowledge base.
    
    Args:
        query: Search query
        limit: Maximum results
        alpha: Balance between vector (1.0) and keyword (0.0) search
        doc_filter: Optional list of doc_ids to filter by
        
    Returns:
        List of matching chunks with metadata
    """
    collection = get_knowledge_base_collection()
    
    # Build filter if doc_filter provided
    filters = None
    if doc_filter:
        filters = Filter.by_property("doc_id").contains_any(doc_filter)
    
    response = collection.query.hybrid(
        query=query,
        alpha=alpha,
        limit=limit,
        filters=filters,
        return_metadata=MetadataQuery(score=True, distance=True)
    )
    
    results = []
    for obj in response.objects:
        result = {
            **obj.properties,
            "score": obj.metadata.score if obj.metadata else None,
            "uuid": str(obj.uuid)
        }
        results.append(result)
    
    return results


def delete_document_chunks(doc_id: str) -> int:
    """
    Delete all chunks for a document from Weaviate.
    
    Args:
        doc_id: Document ID
        
    Returns:
        int: Number of chunks deleted
    """
    collection = get_knowledge_base_collection()
    
    # Find and delete all chunks for this doc_id
    response = collection.query.fetch_objects(
        filters=Filter.by_property("doc_id").equal(doc_id),
        limit=10000
    )
    
    deleted = 0
    for obj in response.objects:
        collection.data.delete_by_id(obj.uuid)
        deleted += 1
    
    return deleted


def get_weaviate_documents() -> List[Dict]:
    """
    Get list of all documents in Weaviate with chunk counts.
    
    Returns:
        List of document summaries
    """
    collection = get_knowledge_base_collection()
    
    # Fetch all objects (limited)
    response = collection.query.fetch_objects(
        limit=10000,
        return_metadata=MetadataQuery(creation_time=True)
    )
    
    # Group by doc_id
    doc_map = {}
    for obj in response.objects:
        doc_id = obj.properties.get("doc_id", "unknown")
        if doc_id not in doc_map:
            doc_map[doc_id] = {
                "doc_id": doc_id,
                "file_name": obj.properties.get("file_name", "unknown"),
                "chunk_count": 0,
                "weaviate_doc_id": doc_id
            }
        doc_map[doc_id]["chunk_count"] += 1
    
    return list(doc_map.values())


def check_weaviate_connection() -> bool:
    """
    Check if Weaviate connection is healthy.
    
    Returns:
        bool: True if connected
    """
    try:
        client = get_weaviate_client()
        return client.is_ready()
    except Exception as e:
        print(f"Weaviate connection error: {e}")
        return False

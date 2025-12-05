"""Database CRUD operations for Weaviate."""
import uuid
from weaviate.classes.query import Filter
from database.weaviate_client import get_weaviate_client, ensure_collections_exist
from config import Config


def insert_document(file_metadata: dict, chunks: list, doc_id: str = None):
    """Insert a parent Document and all its KnowledgeBase chunks."""
    
    client = get_weaviate_client()
    
    # Ensure collections exist
    ensure_collections_exist()

    # Generate or reuse Document ID
    doc_id = doc_id or str(uuid.uuid4())

    # Insert parent Document
    client.collections.get("Document").data.insert(file_metadata, uuid=doc_id)

    # Insert child chunks
    chunks_collection = client.collections.get("KnowledgeBase")
    with chunks_collection.batch.fixed_size(batch_size=Config.BATCH_SIZE) as batch:
        for c in chunks:
            meta = c.get("metadata", {})
            chunk_obj = {
                "text": c.get("text"),
                "type": meta.get("type", "text"),
                "section": meta.get("section", ""),
                "section_title": meta.get("section_title", ""),
                "parent_section": meta.get("parent_section", ""),
                "context": meta.get("context", ""),
                "tags": meta.get("tags", []),
                "created_at": meta.get("created_at", ""),
                "page": meta.get("page", None),
                "chunk_id": c.get("chunk_id", None),
            }
            # Add reference properly using references parameter
            batch.add_object(
                properties=chunk_obj,
                references={"ofDocument": doc_id}
            )

    print(f"✅ Inserted Document {file_metadata['file_name']} with {len(chunks)} chunks")
    return doc_id


def delete_document_and_chunks(doc_id: str):
    """Delete a document and cascade delete all its chunks."""
    client = get_weaviate_client()
    
    docs = client.collections.get("Document")
    chunks = client.collections.get("KnowledgeBase")

    # Delete children (chunks) using proper Filter.by_ref syntax
    chunks.data.delete_many(
        where=Filter.by_ref("ofDocument").by_id().equal(doc_id)
    )

    # Delete parent (document)
    docs.data.delete_by_id(doc_id)

    print(f"🗑️ Deleted Document {doc_id} and all related chunks")


def replace_document(file_metadata: dict, chunks: list, doc_id: str):
    """Replace an existing Document and its chunks with new content."""
    # Delete old doc + chunks
    delete_document_and_chunks(doc_id)

    # Reinsert with the same doc_id (to keep references stable)
    new_doc_id = insert_document(file_metadata, chunks, doc_id=doc_id)

    print(f"♻️ Replaced Document {file_metadata['file_name']} with {len(chunks)} chunks")
    return new_doc_id

"""Weaviate client initialization and management."""
import weaviate
from weaviate.classes.config import Configure, Property, DataType
try:
    from weaviate.classes.config import ReferenceProperty
except ImportError:
    # Fallback for older versions
    ReferenceProperty = None
from config import Config


# Initialize configuration
Config.validate()

# Create Weaviate client
headers = {
    "X-OpenAI-Api-Key": Config.OPENAI_API_KEY,
}

weaviate_client = weaviate.connect_to_weaviate_cloud(
    cluster_url=Config.WEAVIATE_URL,
    auth_credentials=weaviate.auth.AuthApiKey(Config.WEAVIATE_API_KEY),
    headers=headers
)

# Connect the client
if not weaviate_client.is_connected():
    print("🔌 Connecting to Weaviate...")
    weaviate_client.connect()
    print("✅ Connected to Weaviate")


def ensure_collections_exist():
    """Ensure Document and KnowledgeBase collections exist in Weaviate with correct schema."""
    
    # Reconnect if disconnected
    if not weaviate_client.is_connected():
        print("🔌 Reconnecting to Weaviate...")
        weaviate_client.connect()
        print("✅ Reconnected to Weaviate")
    
    existing_collections = weaviate_client.collections.list_all()
    
    # Only create collections if they don't exist (don't delete existing data)
    if "Document" in existing_collections:
        print("✅ Document collection already exists")
    else:
        # Create Document collection with minimal schema
        try:
            weaviate_client.collections.create(
                name="Document",
                properties=[
                    Property(name="file_name", data_type=DataType.TEXT),
                    Property(name="page_count", data_type=DataType.NUMBER),
                ]
            )
            print("✅ Created Document collection")
        except Exception as e:
            print(f"❌ Error creating Document collection: {e}")
            raise
    
    # Only create KnowledgeBase if it doesn't exist
    if "KnowledgeBase" in existing_collections:
        print("✅ KnowledgeBase collection already exists")
    else:
        # Create KnowledgeBase collection with proper schema
        try:
            collection_config = {
                "name": "KnowledgeBase",
                "vector_config": [
                    Configure.Vectors.text2vec_openai(
                        name="text_vector",
                        source_properties=["text"],
                        model=Config.EMBEDDING_MODEL,
                        dimensions=Config.EMBEDDING_DIMENSIONS
                    )
                ],
                "generative_config": Configure.Generative.openai(
                    model=Config.OPENAI_MODEL,
                    temperature=Config.TEMPERATURE,
                ),
                "properties": [
                    Property(name="text", data_type=DataType.TEXT),
                    Property(name="type", data_type=DataType.TEXT),
                    Property(name="section", data_type=DataType.TEXT),
                    Property(name="section_title", data_type=DataType.TEXT),
                    Property(name="parent_section", data_type=DataType.TEXT),
                    Property(name="context", data_type=DataType.TEXT),
                    Property(name="tags", data_type=DataType.TEXT_ARRAY),
                    Property(name="page", data_type=DataType.NUMBER),
                    Property(name="chunk_id", data_type=DataType.TEXT),
                    Property(name="created_at", data_type=DataType.TEXT),
                ]
            }
            
            # Add references if ReferenceProperty is available
            if ReferenceProperty is not None:
                collection_config["references"] = [
                    ReferenceProperty(name="ofDocument", target_collection="Document")
                ]
            
            weaviate_client.collections.create(**collection_config)
            print("✅ Created KnowledgeBase collection")
        except Exception as e:
            print(f"❌ Error creating KnowledgeBase collection: {e}")
            raise


def get_weaviate_client():
    """Get the Weaviate client instance."""
    return weaviate_client

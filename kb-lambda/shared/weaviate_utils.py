"""
Weaviate utilities for Knowledge Base Lambda functions.
Connects to Weaviate Cloud for vector operations.

Uses weaviate-client v4 API with adaptive schema detection:
- KnowledgeBase collection (text, type, section, section_title, parent_section, context, tags, page, chunk_id)
- Document collection (file_name, page_count)
- ofDocument cross-reference from KnowledgeBase -> Document (if it exists in schema)

Automatically detects whether the ofDocument cross-reference exists and falls back
to chunk_id-based document resolution when it doesn't.
"""
import os
import weaviate
import weaviate.classes as wvc
from typing import List, Dict, Optional, Any

# Weaviate configuration from environment
WEAVIATE_URL = os.environ.get('WEAVIATE_URL', '')
WEAVIATE_API_KEY = os.environ.get('WEAVIATE_API_KEY', '')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')

# Quota service config (optional) — embedding-call usage is reported here
# so /admin/usage/summary and /admin/logs surface the same per-call detail
# they already have for chat completions. Reporting is best-effort and
# wrapped in try/except internally; quota outages never break upload/search.
QUOTA_SERVICE_URL = os.environ.get('QUOTA_SERVICE_URL', '')
# Default 'true' to match every other Lambda in this codebase
# (chat_message, kb_query, ws_chat_stream, chat_quota, chat_session_create
# all default to 'true'). The actual gate is QUOTA_SERVICE_URL: if it's
# unset, _report_embedding_usage() short-circuits anyway, so the
# 'true' default is safe and only matters when QUOTA_ENABLED is left
# entirely unset on a Lambda.
QUOTA_ENABLED = os.environ.get('QUOTA_ENABLED', 'true').lower() == 'true'

# httpx imported lazily so weaviate_utils can be loaded in environments
# without httpx (e.g., admin Lambdas that don't talk to the quota service).
_httpx = None
try:
    import httpx as _httpx
except ImportError:  # pragma: no cover — defensive only
    pass

# Singleton client
_client = None

# Cached schema detection: None = not checked, True/False = result
_has_of_document_ref = None
# Cached document name lookup: {doc_id_prefix: file_name}
_document_name_cache = {}
# Cached list of actual property names in KnowledgeBase collection
_kb_property_names = None


def get_weaviate_client():
    """
    Get or create Weaviate client connection (v4 API).
    Uses connect_to_weaviate_cloud() matching the original knowledge-base system.
    
    Returns:
        weaviate.WeaviateClient: Connected v4 client
    """
    global _client
    
    if _client is not None:
        try:
            if _client.is_connected():
                return _client
        except Exception:
            _client = None
    
    if not WEAVIATE_URL or not WEAVIATE_API_KEY:
        raise Exception("Weaviate configuration missing: WEAVIATE_URL and WEAVIATE_API_KEY required")
    
    # Clean URL - connect_to_weaviate_cloud expects cluster URL without scheme
    url = WEAVIATE_URL.strip()
    for prefix in ['https://', 'http://']:
        if url.startswith(prefix):
            url = url[len(prefix):]
    url = url.rstrip('/')
    
    headers = {}
    if OPENAI_API_KEY:
        headers["X-OpenAI-Api-Key"] = OPENAI_API_KEY
    
    _client = weaviate.connect_to_weaviate_cloud(
        cluster_url=url,
        auth_credentials=weaviate.auth.AuthApiKey(api_key=WEAVIATE_API_KEY),
        headers=headers,
        skip_init_checks=True  # Skip gRPC readiness checks for Lambda environment
    )
    
    print(f"[Weaviate] Connected to Weaviate Cloud (v4 client)")
    return _client


def close_weaviate_client():
    """Close Weaviate client connection."""
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
        _client = None


def _report_embedding_usage(
    user_id: Optional[str],
    operation: str,
    input_tokens: int,
    duration_ms: Optional[float] = None,
    request_id: Optional[str] = None,
    chunk_count: Optional[int] = None,
    metadata: Optional[Dict] = None,
    session_id: Optional[str] = None,
) -> None:
    """
    Best-effort report of an embedding-call to the quota service.
    
    Mirrors lambda_pdf_parse.report_pdf_usage exactly: tier='embedding',
    record_only=True. The row appears in UsageLogs (full audit trail with
    exact token counts from OpenAI's response) but does NOT decrement
    UserQuotas.current_usage. Embeddings are infrastructure cost, like
    PDF parsing — they should never drain the user's chat balance.
    
    Cost is computed via openai_utils.estimate_cost so it tracks the
    EMBEDDING_MODEL pricing row automatically (text-embedding-3-small at
    $0.02/1M, text-embedding-3-large at $0.13/1M, etc.). Quota service
    will recompute its own cost from input_tokens too — providing the
    pre-computed value here just keeps the UsageLogs row useful even if
    pricing tables ever drift between Lambdas.
    
    Wraps httpx in try/except — quota outages never block embedding
    calls. Skips silently when QUOTA_ENABLED=false or the optional
    httpx dependency isn't available (e.g., on the admin Lambdas).
    """
    if not QUOTA_ENABLED or not QUOTA_SERVICE_URL or _httpx is None:
        return
    if not user_id:
        # /quota/report rejects requests without user_id — skip silently
        # rather than spam CloudWatch (anonymous searches are legitimate).
        return
    
    try:
        from shared.openai_utils import EMBEDDING_MODEL, estimate_cost
        cost_usd = estimate_cost(input_tokens, 0, EMBEDDING_MODEL)
        model = EMBEDDING_MODEL
    except Exception:
        # Fallback if openai_utils import fails — use the small-model rate.
        cost_usd = (input_tokens or 0) * 0.02 / 1_000_000
        model = 'text-embedding-3-small'
    
    # Service JWT headers — /api/quota/report is JWT-gated. Imported lazily
    # so weaviate_utils stays importable in deploys that don't ship the
    # service_jwt module yet.
    try:
        from shared.service_jwt import service_auth_headers
        _auth_headers = service_auth_headers('kb-weaviate-utils')
    except Exception:
        _auth_headers = {}

    try:
        with _httpx.Client(timeout=5.0) as client:
            response = client.post(
                f"{QUOTA_SERVICE_URL}/quota/report",
                json={
                    'user_id': user_id,
                    'service': 'knowledge-base',
                    'operation': operation,
                    'tier': 'embedding',
                    'model': model,
                    'input_tokens': int(input_tokens or 0),
                    'output_tokens': 0,
                    'cached_tokens': 0,
                    'cost_usd': float(cost_usd),
                    'duration_ms': float(duration_ms) if duration_ms is not None else None,
                    'success': True,
                    'request_id': request_id,
                    # session_id is the chat session this embedding
                    # was generated for. Threaded so the per-user
                    # history view's chat-turn grouper can collapse
                    # the embedding row into its parent chat_stream
                    # via strict equality (deterministic) instead of
                    # falling back to time-window matching.
                    # Optional — non-chat embedding callers (e.g. KB
                    # ingestion) leave it unset and the column stays
                    # null in DynamoDB.
                    'session_id': session_id,
                    # CRITICAL: record_only=True → audit row written to
                    # UsageLogs, UserQuotas balance NOT touched. Same rule
                    # as PDF parsing — see lambda_pdf_parse.report_pdf_usage.
                    'record_only': True,
                    'metadata': {
                        'chunk_count': chunk_count,
                        **(metadata or {}),
                    },
                },
                headers=_auth_headers,
            )
            response.raise_for_status()
    except Exception as e:
        print(f"[Quota] Embedding usage report warning: {e}")


def _detect_schema(collection) -> None:
    """Detect KnowledgeBase schema: available properties + ofDocument cross-reference (cached)."""
    global _has_of_document_ref, _kb_property_names
    if _has_of_document_ref is not None and _kb_property_names is not None:
        return  # Already detected
    
    try:
        schema = collection.config.get()
        
        # Detect properties
        _kb_property_names = [p.name for p in schema.properties] if schema.properties else []
        print(f"[Weaviate] Schema properties ({len(_kb_property_names)}): {_kb_property_names}")
        
        # Detect cross-references
        ref_names = [r.name for r in (schema.references or [])] if schema.references else []
        _has_of_document_ref = "ofDocument" in ref_names
        print(f"[Weaviate] Schema check: ofDocument cross-reference {'FOUND' if _has_of_document_ref else 'NOT FOUND (using chunk_id fallback)'}")
    except Exception as e:
        print(f"[Weaviate] Schema detection failed: {e}")
        if _has_of_document_ref is None:
            _has_of_document_ref = False
        if _kb_property_names is None:
            # Minimal fallback — only request 'text' and 'chunk_id' which must exist
            _kb_property_names = ["text", "chunk_id"]


def _check_of_document_ref(collection) -> bool:
    """Check if KnowledgeBase collection has ofDocument cross-reference (cached)."""
    _detect_schema(collection)
    return _has_of_document_ref


def _get_return_properties() -> List[str]:
    """
    Get the list of properties to request from KnowledgeBase, filtered to only those
    that actually exist in the schema. Prevents 'no such prop' GRPC errors.
    """
    # All properties our code would LIKE to have
    desired = ["text", "type", "section", "section_title",
               "parent_section", "context", "tags", "page", "chunk_id",
               "file_name", "doc_id"]
    
    if _kb_property_names is None:
        # Schema not yet detected — return minimal safe set
        return ["text", "chunk_id"]
    
    available = [p for p in desired if p in _kb_property_names]
    
    # Log which properties were requested but missing
    missing = [p for p in desired if p not in _kb_property_names]
    if missing:
        print(f"[Weaviate] Properties not in schema (skipped): {missing}")
    
    return available


def _resolve_document_names(client, results: List[Dict]) -> None:
    """
    Resolve document names for search results when ofDocument cross-reference is missing.
    Extracts doc_id from chunk_id (format: '{doc_id}-{index}') and looks up Document collection.
    Modifies results in-place.
    """
    global _document_name_cache
    import uuid as uuid_module
    
    # Collect unique doc_id prefixes from chunk_ids
    doc_ids_to_resolve = set()
    for result in results:
        chunk_id = result.get('chunk_id', '')
        if chunk_id:
            # chunk_id format: "{doc_id}-{index}" — doc_id itself may contain hyphens (UUID)
            # Extract everything before the last hyphen-number
            parts = chunk_id.rsplit('-', 1)
            if len(parts) == 2 and parts[1].isdigit():
                doc_id_prefix = parts[0]
                if doc_id_prefix not in _document_name_cache:
                    doc_ids_to_resolve.add(doc_id_prefix)
    
    # Look up Document collection for unresolved doc_ids
    if doc_ids_to_resolve:
        try:
            doc_collection = client.collections.get("Document")
            for doc_id_prefix in doc_ids_to_resolve:
                try:
                    # The Document UUID is uuid5(NAMESPACE_DNS, doc_id)
                    doc_uuid = str(uuid_module.uuid5(uuid_module.NAMESPACE_DNS, doc_id_prefix))
                    doc_obj = doc_collection.query.fetch_object_by_id(doc_uuid)
                    if doc_obj:
                        _document_name_cache[doc_id_prefix] = doc_obj.properties.get('file_name', 'Unknown')
                    else:
                        _document_name_cache[doc_id_prefix] = 'Unknown'
                except Exception:
                    _document_name_cache[doc_id_prefix] = 'Unknown'
            
            print(f"[Weaviate] Resolved {len(doc_ids_to_resolve)} document names via chunk_id lookup")
        except Exception as e:
            print(f"[Weaviate] Document name resolution error: {e}")
            for doc_id_prefix in doc_ids_to_resolve:
                _document_name_cache[doc_id_prefix] = 'Unknown'
    
    # Apply resolved names to results
    for result in results:
        chunk_id = result.get('chunk_id', '')
        if chunk_id:
            parts = chunk_id.rsplit('-', 1)
            if len(parts) == 2 and parts[1].isdigit():
                doc_id_prefix = parts[0]
                result['document_name'] = _document_name_cache.get(doc_id_prefix, 'Unknown')


def hybrid_search(
    query: str,
    limit: int = 50,
    alpha: float = 0.75,
    doc_filter: List[str] = None,
    user_id: Optional[str] = None,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> List[Dict]:
    """
    Perform hybrid search (vector + keyword) using v4 API with BYO vectors.
    
    Computes the query embedding via openai_utils.embed_texts and passes
    vector= explicitly to collection.query.hybrid. The query text is also
    forwarded as `query=` because the BM25 keyword half of the hybrid
    search needs the raw text. Weaviate weights the two halves by `alpha`
    (1.0 = pure vector, 0.0 = pure keyword, default 0.75 = vector-leaning).
    
    Embedding tokens are reported to the quota service as tier='embedding'
    with record_only=True so they appear in UsageLogs (audit trail) but
    do NOT decrement the user's chat balance — embeddings are infra cost.
    
    Adaptive: detects whether ofDocument cross-reference exists in schema.
    - If yes: uses return_references for efficient document name resolution
    - If no: queries without references, resolves doc names via chunk_id -> Document lookup
    
    Graceful degradation: if the embedding API is down, falls back to
    BM25-only keyword search rather than returning zero results — better
    to give the user partial recall than to silently fail.
    
    Args:
        query: Search query text.
        limit: Maximum number of results (default 50 for reranking pipeline).
        alpha: Balance between vector (1.0) and keyword (0.0) search.
        doc_filter: Optional list of document UUIDs to filter by.
        user_id: Optional — when provided, embedding usage is logged to
            the quota service against this user (record_only).
        request_id: Optional — API Gateway requestId for log correlation.
        
    Returns:
        List of chunk dicts with full metadata.
    """
    import time
    
    client = get_weaviate_client()
    collection = client.collections.get("KnowledgeBase")
    
    # Detect schema capabilities (cached after first call)
    _detect_schema(collection)
    has_ref = _has_of_document_ref
    return_props = _get_return_properties()
    
    # Step 1: Embed the query. Wrapped in try/except so a transient OpenAI
    # outage degrades gracefully to BM25-only keyword search rather than
    # returning zero results. The user gets weaker recall but still gets
    # something useful.
    embed_start = time.time()
    query_vector: Optional[List[float]] = None
    prompt_tokens = 0
    try:
        from shared.openai_utils import embed_texts
        vectors, prompt_tokens = embed_texts([query])
        if vectors:
            query_vector = vectors[0]
        embed_duration_ms = (time.time() - embed_start) * 1000
        print(f"[Weaviate] Query embedded ({prompt_tokens} tokens, {embed_duration_ms:.0f}ms)")
    except Exception as e:
        embed_duration_ms = (time.time() - embed_start) * 1000
        print(f"[Weaviate] Query embedding failed (falling back to BM25-only): {e}")
    
    # Step 2: Best-effort log of embedding usage to the quota service.
    # Skipped when prompt_tokens=0 (embedding failed) — no real call to log.
    if user_id and prompt_tokens > 0:
        _report_embedding_usage(
            user_id=user_id,
            operation='search_embed',
            input_tokens=prompt_tokens,
            duration_ms=embed_duration_ms,
            request_id=request_id,
            session_id=session_id,
            chunk_count=None,
            metadata={
                'query_length': len(query or ''),
            },
        )
    
    try:
        print(f"[Weaviate] Hybrid search: query='{query[:80]}...', limit={limit}, has_ofDocument={has_ref}, props={len(return_props)}, has_vector={query_vector is not None}")
        
        # Build optional filter for document filtering
        search_filters = None
        if doc_filter and has_ref:
            print(f"[Weaviate] Applying document filter: {len(doc_filter)} document(s)")
            if len(doc_filter) == 1:
                search_filters = wvc.query.Filter.by_ref("ofDocument").by_id().equal(doc_filter[0])
            else:
                search_filters = wvc.query.Filter.by_ref("ofDocument").by_id().contains_any(doc_filter)
        elif doc_filter and not has_ref:
            print(f"[Weaviate] WARNING: doc_filter ignored — ofDocument cross-reference not in schema")
        
        # Common kwargs used by both hybrid and bm25 paths.
        common_kwargs = {
            'query': query,
            'limit': limit,
            'return_metadata': wvc.query.MetadataQuery(score=True, distance=True),
            'return_properties': return_props,
        }
        
        if search_filters:
            common_kwargs['filters'] = search_filters
        
        # Only request cross-reference if it exists in schema
        if has_ref:
            common_kwargs['return_references'] = [
                wvc.query.QueryReference(
                    link_on="ofDocument",
                    return_properties=["file_name"]
                )
            ]
        
        # Branch on whether we have a query vector. With vectorizer_none on
        # the collection, calling .hybrid() WITHOUT a vector argument would
        # fail with VectorFromInput error (Weaviate has no module to make
        # one). So when the embedding step failed, we degrade to BM25-only
        # keyword search — same return shape, just weaker recall.
        if query_vector is not None:
            response = collection.query.hybrid(
                **common_kwargs,
                alpha=alpha,
                vector=query_vector,
            )
        else:
            print(f"[Weaviate] BM25-only fallback (embedding unavailable)")
            response = collection.query.bm25(**common_kwargs)
        
        results = []
        for obj in response.objects:
            # Get document name — prefer direct file_name property on chunk
            document_name = obj.properties.get('file_name') or 'Unknown'
            document_id = obj.properties.get('doc_id') or None
            
            # Fallback: ofDocument cross-reference (if file_name not on chunk)
            if document_name == 'Unknown' and has_ref and hasattr(obj, 'references') and obj.references:
                of_doc = obj.references.get('ofDocument')
                if of_doc and of_doc.objects:
                    doc_ref = of_doc.objects[0]
                    document_name = doc_ref.properties.get('file_name', 'Unknown')
                    document_id = str(doc_ref.uuid) if hasattr(doc_ref, 'uuid') else None
            
            # Extract score safely
            score = 0.5
            if hasattr(obj, 'metadata') and obj.metadata:
                if hasattr(obj.metadata, 'score') and obj.metadata.score is not None:
                    score = obj.metadata.score
            
            result = {
                'text': obj.properties.get('text', ''),
                'chunk_type': obj.properties.get('type', 'text'),
                'section': obj.properties.get('section', ''),
                'section_title': obj.properties.get('section_title', ''),
                'parent_section': obj.properties.get('parent_section', ''),
                'context': obj.properties.get('context', ''),
                'tags': obj.properties.get('tags', []),
                'page': obj.properties.get('page', 0),
                'chunk_id': obj.properties.get('chunk_id', ''),
                'document_name': document_name,
                'document_id': document_id,
                'score': score,
            }
            results.append(result)
        
        # Resolve remaining 'Unknown' document names via chunk_id -> Document lookup
        unknown_results = [r for r in results if r.get('document_name') == 'Unknown']
        if unknown_results:
            _resolve_document_names(client, unknown_results)
        
        print(f"[Weaviate] Hybrid search returned {len(results)} results")
        if results:
            print(f"[Weaviate] Top result: {results[0].get('document_name')} (score: {results[0].get('score', 0):.3f})")
        
        return results
        
    except Exception as e:
        print(f"[Weaviate] Error in hybrid search: {e}")
        import traceback
        traceback.print_exc()
        return []


# ============================================================
# Legacy functions below - updated to v4 API
# Used by other Lambda functions (kb_upload, kb_delete, etc.)
# ============================================================

def ensure_collections_exist():
    """
    Idempotently bootstrap KnowledgeBase + Document collections.
    
    Creates either collection ONLY when missing — pre-existing collections
    are never modified or dropped (destructive operations belong in the
    one-time migration script, not in a self-healing path that runs on
    every Lambda cold start). When sandbox clusters expire and you spin up
    a fresh one, the next `kb_upload` call recreates the schema correctly
    without manual intervention.
    
    Schema design (BYO vectors — see Option B in the conversation that
    introduced this bootstrap):
    
      Document collection
        - vectorizer: none (pure metadata holder, never searched by vector)
        - properties: file_name (text), page_count (int)
    
      KnowledgeBase collection
        - vectorizer: none (we compute embeddings via openai_utils.embed_texts
          and pass them explicitly on every batch.add_object — see
          upload_chunks_to_weaviate)
        - vector index: HNSW with cosine distance (the standard for OpenAI
          embeddings; matches what text-embedding-3-small expects)
        - properties: 12 fields covering chunk content + metadata + source
          attribution. file_name and doc_id are stored on the chunk itself
          so hybrid_search results can be attributed without joining back
          to Document via the cross-reference.
        - cross-reference: ofDocument → Document (kept for richer schemas
          and forward compatibility; current search code falls back to
          chunk-level file_name/doc_id when the ref is absent)
    
    Returns True if both collections are present (or were just created),
    False on any error from Weaviate.
    """
    client = get_weaviate_client()
    try:
        existing = client.collections.list_all()
    except Exception as e:
        print(f"[Weaviate] Error listing collections: {e}")
        return False
    
    has_kb = "KnowledgeBase" in existing
    has_doc = "Document" in existing
    print(f"[Weaviate] Collections present: KnowledgeBase={has_kb}, Document={has_doc}")
    
    # Document must exist BEFORE KnowledgeBase because the latter has a
    # cross-reference targeting Document — Weaviate rejects ReferenceProperty
    # creation if the target collection is missing.
    if not has_doc:
        try:
            client.collections.create(
                name="Document",
                vectorizer_config=wvc.config.Configure.Vectorizer.none(),
                properties=[
                    wvc.config.Property(name="file_name", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="page_count", data_type=wvc.config.DataType.INT),
                ],
            )
            print(f"[Weaviate] Created Document collection (vectorizer=none, 2 props)")
        except Exception as e:
            print(f"[Weaviate] Failed to create Document collection: {e}")
            return False
    
    if not has_kb:
        try:
            client.collections.create(
                name="KnowledgeBase",
                vectorizer_config=wvc.config.Configure.Vectorizer.none(),
                vector_index_config=wvc.config.Configure.VectorIndex.hnsw(
                    distance_metric=wvc.config.VectorDistances.COSINE,
                ),
                properties=[
                    # Content fields — these carry the actual searchable text.
                    wvc.config.Property(name="text", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="section_title", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="context", data_type=wvc.config.DataType.TEXT),
                    # Identity — chunk_id is "{doc_id}-{index}", file_name and
                    # doc_id are duplicated here for direct lookup so search
                    # results can be attributed without a separate Document
                    # query (was the cause of "Properties not in schema" log
                    # warnings on the auto-created collection).
                    wvc.config.Property(name="chunk_id", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="file_name", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="doc_id", data_type=wvc.config.DataType.TEXT),
                    # Structural metadata — used for filtering and display.
                    wvc.config.Property(name="type", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="section", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="parent_section", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="tags", data_type=wvc.config.DataType.TEXT_ARRAY),
                    wvc.config.Property(name="page", data_type=wvc.config.DataType.INT),
                    wvc.config.Property(name="created_at", data_type=wvc.config.DataType.TEXT),
                ],
                references=[
                    wvc.config.ReferenceProperty(
                        name="ofDocument",
                        target_collection="Document",
                    ),
                ],
            )
            print(f"[Weaviate] Created KnowledgeBase collection "
                  f"(vectorizer=none, HNSW+cosine, 12 props, ofDocument ref)")
        except Exception as e:
            print(f"[Weaviate] Failed to create KnowledgeBase collection: {e}")
            return False
    
    # Reset cached schema detection so a freshly-bootstrapped collection
    # is observed on the very next hybrid_search / upload call without
    # waiting for a Lambda cold start to clear module globals.
    global _has_of_document_ref, _kb_property_names
    _has_of_document_ref = None
    _kb_property_names = None
    
    return True


def get_knowledge_base_collection():
    """Get reference to KnowledgeBase collection (v4 API)."""
    client = get_weaviate_client()
    return client.collections.get("KnowledgeBase")


def upload_chunks_to_weaviate(
    chunks: List[Dict],
    doc_id: str,
    file_name: str,
    user_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> int:
    """
    Upload chunks to Weaviate KnowledgeBase using v4 batch API with
    BYO vectors (computed via openai_utils.embed_texts).
    
    Flow:
      1. Ensure parent Document object exists (vectorless metadata holder).
      2. Batch-embed all chunk texts in one OpenAI call (or a few, if the
         document is huge — embed_texts auto-splits at 1000 inputs).
      3. Report embedding tokens to the quota service as tier='embedding'
         with record_only=True (audit row, no quota deduction).
      4. Insert chunks into Weaviate with `vector=...` per object.
    
    file_name and doc_id are also written into chunk-level properties (not
    just on the Document) so search results can be attributed without
    joining back through the cross-reference. The ofDocument ref is still
    populated when the schema supports it for richer queries / forward
    compatibility.
    
    Args:
        chunks: List of chunk dicts with text + metadata.
        doc_id: Logical document UUID; chunk_ids will be "{doc_id}-{i}".
        file_name: Display name for attribution.
        user_id: Optional — when provided, embedding usage is logged to
            the quota service against this user (record_only).
        request_id: Optional — API Gateway requestId for log correlation.
    
    Returns:
        Number of chunks queued for insert (the batch is flushed when the
        `with` block exits; transient errors are logged by Weaviate v4's
        batch executor but don't raise here — same behavior as before).
    """
    import uuid as uuid_module
    import time
    
    client = get_weaviate_client()
    kb_collection = client.collections.get("KnowledgeBase")
    doc_collection = client.collections.get("Document")
    
    has_ref = _check_of_document_ref(kb_collection)
    
    # Step 1: Find or create the parent Document object.
    doc_uuid = str(uuid_module.uuid5(uuid_module.NAMESPACE_DNS, doc_id))
    try:
        doc_collection.data.insert(
            properties={"file_name": file_name},
            uuid=doc_uuid
        )
        print(f"[Weaviate] Created Document: {file_name} ({doc_uuid})")
    except Exception:
        print(f"[Weaviate] Document already exists: {file_name}")
    
    if not chunks:
        print(f"[Weaviate] No chunks to upload for {file_name}")
        return 0
    
    # Step 2: Embed all chunk texts in one batched OpenAI call.
    # Done up-front so we can fail fast if the embedding API is down
    # rather than partially populating Weaviate with vectorless objects.
    chunk_texts = [c.get("text", c.get("content", "")) for c in chunks]
    
    embed_start = time.time()
    try:
        from shared.openai_utils import embed_texts
        vectors, prompt_tokens = embed_texts(chunk_texts)
        embed_duration_ms = (time.time() - embed_start) * 1000
        print(f"[Weaviate] Embedded {len(vectors)} chunks "
              f"({prompt_tokens} tokens, {embed_duration_ms:.0f}ms)")
    except Exception as e:
        print(f"[Weaviate] Embedding failed for {file_name}: {e}")
        # Re-raise — without vectors the chunks would be invisible to
        # vector search, defeating the purpose of the upload. Caller
        # (lambda_kb_upload) already wraps in try/except and falls back
        # to DynamoDB-only storage.
        raise
    
    # Step 3: Best-effort log of embedding usage to the quota service.
    # tier='embedding', record_only=True — uploader's chat balance is
    # NOT deducted. Same convention as PDF parsing.
    if user_id:
        _report_embedding_usage(
            user_id=user_id,
            operation='upload_embed',
            input_tokens=prompt_tokens,
            duration_ms=embed_duration_ms,
            request_id=request_id,
            chunk_count=len(chunks),
            metadata={
                'doc_id': doc_id,
                'file_name': file_name,
            },
        )
    
    # Step 4: Insert chunks + vectors via batch API.
    #
    # IMPORTANT — field-path contract (was a silent bug):
    # AI-produced chunks (per `kb-lambda/functions/pdf_parse/schemas.py`)
    # nest semantic fields inside `metadata`:
    #   { "text": "...", "metadata": { "type", "section", "section_title",
    #                                   "parent_section", "context", "tags",
    #                                   "page", ... } }
    # The frontend reads `chunk.metadata.section`, but this function used
    # to read `chunk.get("section")` at the top level — which silently
    # returned "" for every AI-uploaded chunk, leaving Weaviate without
    # any structured metadata to filter or boost on. We now look in
    # `metadata` first and fall back to top-level for any legacy / hand-
    # authored chunk shapes.
    uploaded = 0
    with kb_collection.batch.dynamic() as batch:
        for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
            chunk_id = f"{doc_id}-{i}"
            chunk_uuid = str(uuid_module.uuid5(uuid_module.NAMESPACE_DNS, chunk_id))

            md = chunk.get("metadata") or {}

            def _md_field(key, default=""):
                """Prefer chunk.metadata.<key>, fall back to chunk.<key> (legacy)."""
                if key in md and md.get(key) not in (None, ""):
                    return md.get(key)
                return chunk.get(key, default)

            properties = {
                "text": chunk.get("text", chunk.get("content", "")),
                "chunk_id": chunk_id,
                "file_name": file_name,
                "doc_id": doc_id,
                "type": _md_field("type", _md_field("chunk_type", "text")),
                "section": _md_field("section", ""),
                "section_title": _md_field("section_title", ""),
                "parent_section": _md_field("parent_section", ""),
                "context": _md_field("context", ""),
                "tags": _md_field("tags", []),
                "page": int(_md_field("page", 1) or 1),
                "created_at": _md_field("created_at", ""),
            }
            
            add_kwargs = {
                "properties": properties,
                "uuid": chunk_uuid,
                "vector": vector,
            }
            
            if has_ref:
                add_kwargs["references"] = {"ofDocument": doc_uuid}
            
            batch.add_object(**add_kwargs)
            uploaded += 1
    
    print(f"[Weaviate] Uploaded {uploaded} chunks for document: {file_name} "
          f"(BYO vectors, ofDocument ref={has_ref})")
    return uploaded


def delete_document_chunks(doc_id: str) -> int:
    """Delete all chunks for a document using v4 API."""
    client = get_weaviate_client()
    collection = client.collections.get("KnowledgeBase")
    
    try:
        result = collection.data.delete_many(
            where=wvc.query.Filter.by_property("chunk_id").like(f"{doc_id}-*")
        )
        deleted = result.successful if hasattr(result, 'successful') else 0
        print(f"[Weaviate] Deleted {deleted} chunks for doc: {doc_id}")
        return deleted
    except Exception as e:
        print(f"[Weaviate] Error deleting chunks: {e}")
        return 0


def get_weaviate_documents() -> List[Dict]:
    """
    Get list of documents from Weaviate Document collection with chunk counts.
    
    Adaptive: uses ofDocument cross-reference for chunk counting when available,
    falls back to chunk_id prefix grouping when cross-reference is missing.
    
    Returns doc_id as the deterministic UUID (uuid5 of the application doc_id)
    to match what kb_list and admin_documents expect for DynamoDB lookups.
    """
    import uuid as uuid_module
    
    client = get_weaviate_client()
    
    try:
        doc_collection = client.collections.get("Document")
        kb_collection = client.collections.get("KnowledgeBase")
        
        # Check if cross-reference exists
        has_ref = _check_of_document_ref(kb_collection)
        
        response = doc_collection.query.fetch_objects(limit=100)
        
        if has_ref:
            # --- Path A: Use ofDocument cross-reference for chunk counting ---
            documents = []
            for obj in response.objects:
                doc_uuid = str(obj.uuid)
                file_name = obj.properties.get("file_name", "unknown")
                
                chunk_count = 0
                try:
                    chunk_filter = wvc.query.Filter.by_ref("ofDocument").by_id().equal(doc_uuid)
                    agg_result = kb_collection.aggregate.over_all(
                        total_count=True,
                        filters=chunk_filter
                    )
                    chunk_count = agg_result.total_count if agg_result else 0
                except Exception as count_err:
                    print(f"[Weaviate] Could not count chunks for {file_name}: {count_err}")
                
                documents.append({
                    "doc_id": doc_uuid,
                    "file_name": file_name,
                    "chunk_count": chunk_count,
                })
        else:
            # --- Path B: Fallback — count chunks by chunk_id prefix grouping ---
            print("[Weaviate] Using chunk_id prefix fallback for chunk counting")
            
            # Build Document UUID -> file_name map
            doc_map = {}  # {uuid_str: file_name}
            for obj in response.objects:
                doc_map[str(obj.uuid)] = obj.properties.get("file_name", "unknown")
            
            # Fetch all chunk_ids from KnowledgeBase
            chunk_prefix_counts = {}  # {app_doc_id: count}
            offset = 0
            batch_size = 200
            while True:
                chunk_response = kb_collection.query.fetch_objects(
                    limit=batch_size,
                    offset=offset,
                    return_properties=["chunk_id"]
                )
                if not chunk_response.objects:
                    break
                
                for obj in chunk_response.objects:
                    chunk_id = obj.properties.get("chunk_id", "")
                    if chunk_id:
                        parts = chunk_id.rsplit('-', 1)
                        if len(parts) == 2 and parts[1].isdigit():
                            prefix = parts[0]
                            chunk_prefix_counts[prefix] = chunk_prefix_counts.get(prefix, 0) + 1
                
                if len(chunk_response.objects) < batch_size:
                    break
                offset += batch_size
            
            # Match prefixes to Documents via uuid5(NAMESPACE_DNS, prefix)
            documents = []
            matched_uuids = set()
            for prefix, count in chunk_prefix_counts.items():
                expected_uuid = str(uuid_module.uuid5(uuid_module.NAMESPACE_DNS, prefix))
                file_name = doc_map.get(expected_uuid, "Unknown")
                matched_uuids.add(expected_uuid)
                
                documents.append({
                    "doc_id": expected_uuid,
                    "file_name": file_name,
                    "chunk_count": count,
                })
            
            # Add any Document objects that had no matching chunks
            for uuid_str, file_name in doc_map.items():
                if uuid_str not in matched_uuids:
                    documents.append({
                        "doc_id": uuid_str,
                        "file_name": file_name,
                        "chunk_count": 0,
                    })
        
        print(f"[Weaviate] Found {len(documents)} documents with chunk counts")
        return documents
    except Exception as e:
        print(f"[Weaviate] Error getting documents: {e}")
        return []


def check_weaviate_connection() -> bool:
    """Check if Weaviate connection is healthy."""
    try:
        client = get_weaviate_client()
        return client.is_connected()
    except Exception:
        return False


def get_weaviate_chunk_count() -> int:
    """Get total number of chunks stored in Weaviate."""
    try:
        client = get_weaviate_client()
        collection = client.collections.get("KnowledgeBase")
        result = collection.aggregate.over_all(total_count=True)
        return result.total_count if result else 0
    except Exception as e:
        print(f"[Weaviate] Error getting chunk count: {e}")
        return 0

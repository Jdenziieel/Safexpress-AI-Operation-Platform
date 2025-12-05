# API Documentation

Base URL: `http://localhost:8009`

## Endpoints

### 1. Parse PDF
Parse a PDF file and extract structured chunks with AI.

**Endpoint:** `POST /parse-pdf`

**Content-Type:** `multipart/form-data`

**Request:**
```bash
curl -X POST http://localhost:8009/parse-pdf \
  -F "file=@document.pdf"
```

**Response:**
```json
{
  "chunks": [
    {
      "chunk_id": "uuid-string",
      "text": "chunk content",
      "chunk_type": "text|image|table",
      "grounding": [
        {
          "box": {"l": 0.1, "t": 0.2, "r": 0.9, "b": 0.8},
          "page": 1
        }
      ],
      "metadata": {
        "page": 1,
        "section": "Introduction",
        "context": "Opening paragraph",
        "anchored": true,
        "source_file": "document.pdf"
      }
    }
  ],
  "document_metadata": {
    "source_file": "document.pdf",
    "total_chunks": 25,
    "processing_method": "two_pass_with_anchoring"
  }
}
```

---

### 2. Upload to Knowledge Base
Upload processed chunks to Weaviate knowledge base.

**Endpoint:** `POST /upload-to-kb`

**Content-Type:** `application/json`

**Request:**
```bash
curl -X POST http://localhost:8009/upload-to-kb \
  -H "Content-Type: application/json" \
  -d '{
    "chunks": [
      {
        "chunk_id": "uuid",
        "text": "content",
        "chunk_type": "text",
        "metadata": {
          "page": 1,
          "section": "Introduction"
        }
      }
    ],
    "source_filename": "document.pdf",
    "document_metadata": {
      "total_pages": 10
    }
  }'
```

**Response:**
```json
{
  "success": true,
  "message": "Successfully uploaded 25 chunks to knowledge base",
  "doc_id": "uuid-of-document",
  "filename": "kb_20250117_143022_document.json"
}
```

---

### 3. Query Knowledge Base
Query the knowledge base with natural language questions.

**Endpoint:** `POST /query`

**Content-Type:** `application/json`

**Request:**
```bash
curl -X POST http://localhost:8009/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the main findings in the document?",
    "limit": 5,
    "generate_answer": true
  }'
```

**Parameters:**
- `query` (string, required): The question to ask
- `limit` (integer, optional): Maximum number of results to return (default: 5)
- `generate_answer` (boolean, optional): Whether to generate AI answer (default: true)

**Response:**
```json
{
  "success": true,
  "query": "What are the main findings in the document?",
  "results": [
    {
      "text": "Relevant chunk content...",
      "chunk_id": "uuid",
      "metadata": {
        "page": 3,
        "section": "Results",
        "source_file": "document.pdf"
      },
      "score": 0.89
    }
  ],
  "answer": "Based on the document, the main findings are...",
  "metadata": {
    "result_count": 5,
    "generated_at": "2025-01-17T14:30:22",
    "limit": 5
  }
}
```

**How it works:**
1. **Hybrid Search**: Combines semantic (vector) and keyword (BM25) search with alpha=0.5
2. **Reranking**: Uses GPT-4o-mini to rerank results based on relevance
3. **Answer Generation**: Uses GPT-4o to generate a comprehensive answer from top results

---

### 4. List Knowledge Base Files
List all uploaded files in the knowledge base.

**Endpoint:** `GET /list-kb`

**Request:**
```bash
curl http://localhost:8009/list-kb
```

**Response:**
```json
{
  "success": true,
  "files": [
    {
      "filename": "kb_20250117_143022_document.json",
      "original_filename": "document.pdf",
      "upload_time": "2025-01-17 14:30:22",
      "size": 125678
    }
  ]
}
```

---

### 5. Health Check
Check if the API is running.

**Endpoint:** `GET /health`

**Request:**
```bash
curl http://localhost:8009/health
```

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-01-17T14:30:22"
}
```

---

## Typical Workflow

### Upload and Query a Document

```bash
# Step 1: Parse the PDF
curl -X POST http://localhost:8009/parse-pdf \
  -F "file=@research_paper.pdf" \
  -o parsed_output.json

# Step 2: Upload to knowledge base
curl -X POST http://localhost:8009/upload-to-kb \
  -H "Content-Type: application/json" \
  -d @parsed_output.json

# Step 3: Query the knowledge base
curl -X POST http://localhost:8009/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What methodology was used in this research?",
    "limit": 5
  }'
```

---

## Error Responses

All endpoints return error responses in this format:

```json
{
  "success": false,
  "error": "Error message describing what went wrong"
}
```

### Common Error Codes:
- **400 Bad Request**: Missing required parameters or invalid input
- **404 Not Found**: Endpoint or resource not found
- **500 Internal Server Error**: Server-side error during processing

---

## Configuration

Required environment variables (in `.env`):

```env
OPENAI_API_KEY=your_openai_key
WEAVIATE_URL=your_weaviate_cloud_url
WEAVIATE_API_KEY=your_weaviate_key
```

Default settings:
- **Port**: 8009
- **Debug Mode**: Enabled (disable in production)
- **CORS**: Enabled for all origins
- **OpenAI Model**: gpt-4o
- **Embedding Model**: text-embedding-3-small
- **Embedding Dimensions**: 1536

---

## Rate Limits & Best Practices

### PDF Parsing
- **Max file size**: Depends on available memory
- **Processing time**: ~2-10 seconds per page (varies by complexity)
- **Best for**: Multi-page documents with mixed content (text, images, tables)

### Knowledge Base Queries
- **Response time**: ~1-3 seconds
- **Limit parameter**: Recommended 3-10 for best results
- **Cost**: Each query makes OpenAI API calls (embedding + generation)

### Tips:
1. **Parse once, query many**: Upload documents to KB and query repeatedly
2. **Adjust limit**: Use lower limit (3-5) for faster responses, higher (10-20) for comprehensive answers
3. **Disable answer generation**: Set `generate_answer: false` to only get relevant chunks (faster, cheaper)
4. **Monitor costs**: Each query uses OpenAI API tokens

---

## Examples

### Python Client

```python
import requests

BASE_URL = "http://localhost:8009"

# Parse PDF
with open("document.pdf", "rb") as f:
    response = requests.post(
        f"{BASE_URL}/parse-pdf",
        files={"file": f}
    )
    result = response.json()

# Upload to KB
requests.post(
    f"{BASE_URL}/upload-to-kb",
    json=result
)

# Query
response = requests.post(
    f"{BASE_URL}/query",
    json={
        "query": "What is the main topic?",
        "limit": 5
    }
)
answer = response.json()["answer"]
print(answer)
```

### JavaScript/TypeScript Client

```javascript
const BASE_URL = "http://localhost:8009";

// Parse PDF
const formData = new FormData();
formData.append("file", pdfFile);

const parseResponse = await fetch(`${BASE_URL}/parse-pdf`, {
  method: "POST",
  body: formData
});
const result = await parseResponse.json();

// Upload to KB
await fetch(`${BASE_URL}/upload-to-kb`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(result)
});

// Query
const queryResponse = await fetch(`${BASE_URL}/query`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    query: "What is the main topic?",
    limit: 5
  })
});
const answer = await queryResponse.json();
console.log(answer.answer);
```

---

## Need Help?

- **Check logs**: Application prints debug information to console
- **Test endpoints**: Use the `/health` endpoint to verify the server is running
- **Environment**: Ensure all environment variables are set correctly
- **Dependencies**: Run `pip install -r requirements.txt` to install dependencies

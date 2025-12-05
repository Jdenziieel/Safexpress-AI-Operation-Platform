# Knowledge Base Upload System Architecture & Data Flow

## Overview
This document explains the complete knowledge base upload system architecture, from PDF file upload through extraction, chunking, duplicate detection, to vector database storage. It covers the entire pipeline that processes documents and makes them available for semantic search and AI-powered question answering.

---

## System Flow Visualization

### **High-Level Architecture**
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PDF UPLOAD & PROCESSING FLOW                        │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────┐
│   Frontend   │
│   (User)     │
└──────┬───────┘
       │
       │ 1. Upload PDF File
       │ POST /pdf/parse-pdf
       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 1: PDF PARSING & DUPLICATE DETECTION (parse-pdf endpoint)         │
├──────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐      ┌──────────────────┐                          │
│  │ Security        │──────▶│ Calculate Hash   │                          │
│  │ Validation      │      │ & File Size      │                          │
│  └─────────────────┘      └────────┬─────────┘                          │
│                                     │                                     │
│                                     ▼                                     │
│                          ┌──────────────────────┐                        │
│                          │ Check SQLite DB      │                        │
│                          │ for Duplicates       │                        │
│                          │ (filename & hash)    │                        │
│                          └──────────┬───────────┘                        │
│                                     │                                     │
│                          ┌──────────┴───────────┐                        │
│                          │                      │                        │
│                    Duplicate?              No Duplicate                  │
│                          │                      │                        │
│                          ▼                      ▼                        │
│                   ┌────────────┐      ┌────────────────┐                │
│                   │ Return 409 │      │ Continue Parse │                │
│                   │ Conflict   │      │ PDF            │                │
│                   └────────────┘      └────────┬───────┘                │
│                                                 │                        │
│                                                 ▼                        │
│                                    ┌─────────────────────┐              │
│                                    │ PDF Extraction      │              │
│                                    │ - Text Lines        │              │
│                                    │ - Images (base64)   │              │
│                                    │ - Tables            │              │
│                                    └──────────┬──────────┘              │
│                                               │                         │
│                                               ▼                         │
│                                    ┌─────────────────────┐             │
│                                    │ AI Chunking         │             │
│                                    │ - Text Pass (GPT-4) │             │
│                                    │ - Image Pass        │             │
│                                    │ - Merge & Anchor    │             │
│                                    └──────────┬──────────┘             │
│                                               │                         │
│                                               ▼                         │
│                                    ┌─────────────────────┐             │
│                                    │ Return Chunks       │             │
│                                    │ + metadata          │             │
│                                    │ + content_hash      │             │
│                                    │ + file_size_bytes   │             │
│                                    └──────────┬──────────┘             │
└────────────────────────────────────────────────┼──────────────────────┘
                                                 │
                                                 │ 2. Chunks Ready
                                                 │
                                                 ▼
                                          ┌─────────────┐
                                          │  Frontend   │
                                          │  (User)     │
                                          └──────┬──────┘
                                                 │
                                                 │ 3. Upload to KB
                                                 │ POST /kb/upload-to-kb
                                                 ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 2: KNOWLEDGE BASE UPLOAD (upload-to-kb endpoint)                   │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                      WEAVIATE (Vector DB)                        │    │
│  │  ┌──────────────────────────────────────────────────────────┐   │    │
│  │  │ Document Collection (Minimal Metadata)                   │   │    │
│  │  │  - file_name                                             │   │    │
│  │  │  - page_count                                            │   │    │
│  │  │  - metadata (object)                                     │   │    │
│  │  └──────────────────────────────────────────────────────────┘   │    │
│  │                           │                                      │    │
│  │                           │ References                           │    │
│  │                           ▼                                      │    │
│  │  ┌──────────────────────────────────────────────────────────┐   │    │
│  │  │ KnowledgeBase Collection (Chunks + Vectors)              │   │    │
│  │  │  - chunk_id, text, type, section, context               │   │    │
│  │  │  - tags[], page, created_at                             │   │    │
│  │  │  - vector[1536] (OpenAI embeddings)                     │   │    │
│  │  │  - ofDocument → Reference to Document                   │   │    │
│  │  └──────────────────────────────────────────────────────────┘   │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                           │
│                                  +                                        │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │              SQLite Database (Complete Tracking)                 │    │
│  │  ┌──────────────────────────────────────────────────────────┐   │    │
│  │  │ documents table                                          │   │    │
│  │  │  - doc_id (UUID - separate from Weaviate)               │   │    │
│  │  │  - file_name                                             │   │    │
│  │  │  - upload_date                                           │   │    │
│  │  │  - file_size_bytes                                       │   │    │
│  │  │  - chunks (count)                                        │   │    │
│  │  │  - uploaded_by                                           │   │    │
│  │  │  - content_hash (SHA256 for duplicate detection)         │   │    │
│  │  │  - page_count                                            │   │    │
│  │  │  - weaviate_doc_id (reference to Weaviate)               │   │    │
│  │  │  - metadata (JSON string)                                │   │    │
│  │  └──────────────────────────────────────────────────────────┘   │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                           │
│                                  │                                        │
│                                  ▼                                        │
│                         ┌────────────────┐                               │
│                         │ Return Success │                               │
│                         │ - doc_id       │                               │
│                         │ - weaviate_id  │                               │
│                         │ - action       │                               │
│                         └────────────────┘                               │
└──────────────────────────────────────────────────────────────────────────┘
```

### **Data Storage Architecture**
```
┌─────────────────────────────────────────────────────────────────────────┐
│                      DUAL STORAGE STRATEGY                              │
└─────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────┐       ┌──────────────────────────────┐
│   WEAVIATE (Vector Database)     │       │   SQLite (Local Database)    │
│   Purpose: Vector Search         │       │   Purpose: Metadata Tracking │
├──────────────────────────────────┤       ├──────────────────────────────┤
│                                  │       │                              │
│  ✓ Minimal metadata storage      │       │  ✓ Complete tracking data    │
│  ✓ Vector embeddings (1536-dim) │       │  ✓ File size & hash          │
│  ✓ Semantic search capability    │       │  ✓ User information          │
│  ✓ Cloud-hosted (Weaviate Cloud) │       │  ✓ Upload timestamps         │
│  ✓ Scalable to millions of docs │       │  ✓ Fast duplicate detection  │
│                                  │       │  ✓ Local file (documents.db) │
│  Stores:                         │       │                              │
│  • file_name                     │       │  Stores:                     │
│  • page_count                    │       │  • doc_id                    │
│  • chunk text & vectors          │       │  • file_name                 │
│                                  │       │  • upload_date               │
│  Cost: ~6-8KB per chunk          │       │  • file_size_bytes           │
│                                  │       │  • uploaded_by               │
│                                  │       │  • content_hash              │
│                                  │       │  • page_count                │
│                                  │       │  • weaviate_doc_id           │
│                                  │       │  • metadata                  │
│                                  │       │                              │
│                                  │       │  Size: ~1-2KB per document   │
└──────────────────────────────────┘       └──────────────────────────────┘
         │                                            │
         │                                            │
         └────────────────┬───────────────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  Linked by:           │
              │  weaviate_doc_id      │
              │  (UUID reference)     │
              └───────────────────────┘
```

### **Duplicate Detection Flow**
```
┌──────────────────────────────────────────────────────────────────────┐
│          EARLY DUPLICATE DETECTION (Before Parsing)                  │
│          Location: /pdf/parse-pdf endpoint                           │
└──────────────────────────────────────────────────────────────────────┘

    User Uploads PDF
          │
          ▼
    ┌──────────────┐
    │ Calculate    │
    │ SHA256 Hash  │
    └──────┬───────┘
           │
           ▼
    ┌─────────────────────────────┐
    │ Check SQLite Database       │
    │                             │
    │ 1. Query by filename        │
    │    SELECT * FROM documents  │
    │    WHERE file_name = ?      │
    │                             │
    │ 2. Query by content_hash    │
    │    SELECT * FROM documents  │
    │    WHERE content_hash = ?   │
    └──────────┬──────────────────┘
               │
      ┌────────┴────────┐
      │                 │
   Found?           Not Found
      │                 │
      ▼                 ▼
┌─────────────┐   ┌──────────────────┐
│ Return 409  │   │ Continue with    │
│ Conflict    │   │ Expensive Parse  │
│             │   │                  │
│ Cost Saved: │   │ • PDF Extract    │
│ $0.05-0.20  │   │ • AI Chunking    │
│ 10-25 sec   │   │ • Anchoring      │
└─────────────┘   └──────────────────┘

Benefits:
✓ Checks BEFORE expensive OpenAI API calls
✓ Fast SQLite queries (~10ms)
✓ Catches renamed duplicates (hash comparison)
✓ Saves processing time and API costs
```

### **Processing Pipeline Detail**
```
┌──────────────────────────────────────────────────────────────────────┐
│                   PDF PROCESSING PIPELINE                            │
└──────────────────────────────────────────────────────────────────────┘

 PDF File (2.5MB)
      │
      ▼
┌─────────────────────┐
│ 1. PDF Extraction   │  ~2-5 seconds
│    (pdfplumber +    │
│     PyMuPDF)        │
└──────┬──────────────┘
       │
       ├─→ Text Lines (font, size, position)
       ├─→ Images (base64 encoded)
       └─→ Tables (structured cells)
       │
       ▼
┌─────────────────────┐
│ 2. Build Simplified │  ~100ms
│    View (text repr) │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ 3. AI Text Chunking │  ~3-8 seconds
│    (GPT-4)          │  3,000-5,000 tokens
│    - Structure      │
│    - Semantics      │
│    - Context        │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ 4. AI Image         │  ~2-5 seconds per image
│    Analysis         │  1,000 tokens per image
│    (GPT-4 Vision)   │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ 5. Merge Chunks     │  ~100ms
│    Sort by page     │
│    Assign IDs       │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ 6. Anchor to PDF    │  ~1-3 seconds
│    Coordinates      │  Text matching
│    - Match text     │  Bounding boxes
│    - Calculate box  │
└──────┬──────────────┘
       │
       ▼
   8 Chunks with
   coordinates,
   metadata, and
   content_hash

Total: 10-25 seconds for typical PDF
```

---

## System Components

### 1. **FastAPI Application** (`app.py`)
- **Role**: Entry point, initializes the application
- **Responsibilities**:
  - Starts FastAPI server on port 8009
  - Registers all API routes (PDF, KB, Chat)
  - Configures CORS, security middleware, rate limiting
  - Manages Weaviate connection lifecycle

### 2. **API Routes**

#### **PDF Routes** (`api/pdf_routes.py`)
- **Role**: Handle PDF file uploads and parsing
- **Key Endpoints**:
  - `POST /pdf/parse-pdf` - Upload and parse PDF, return chunks

#### **KB Routes** (`api/kb_routes.py`)
- **Role**: Knowledge base management
- **Key Endpoints**:
  - `POST /kb/upload-to-kb` - Upload chunks to vector database
  - `GET /kb/list-kb` - List uploaded documents
  - `POST /kb/query` - Query knowledge base
- **Note**: Duplicate checking now happens exclusively in `/pdf/parse-pdf` endpoint to save parsing costs

### 3. **Security Middleware** (`middleware/security_middleware.py`)
- **Role**: Input validation and security
- **Functions**:
  - File type validation (PDF only)
  - File size limits (10MB default)
  - Filename sanitization
  - Rate limiting enforcement
  - String length validation

### 4. **PDF Processing Pipeline**

#### **PDF Service** (`services/pdf_service.py`)
- **Role**: Orchestrates entire PDF processing pipeline
- **Process**: Coordinates extraction → chunking → anchoring

#### **PDF Extractor** (`core/pdf_extractor.py`)
- **Role**: Low-level PDF parsing
- **Functions**:
  - Extract text lines with fonts, sizes, positions
  - Extract images with coordinates
  - Extract tables with structure
  - Build element-level representation

#### **Table Processor** (`core/table_processor.py`)
- **Role**: Table detection and extraction
- **Functions**:
  - Detect table boundaries
  - Extract cell content
  - Preserve table structure

### 5. **AI Chunking Services**

#### **Chunking Service** (`services/chunking_service.py`)
- **Role**: AI-powered semantic chunking
- **Two-Pass Algorithm**:
  1. **Text-only pass**: Analyze text structure
  2. **Image-only pass**: Process images with context
  3. **Merge pass**: Combine into coherent chunks

#### **Anchoring Service** (`services/anchoring_service.py`)
- **Role**: Map AI chunks back to PDF coordinates
- **Functions**:
  - Match chunk text to PDF lines
  - Calculate bounding boxes
  - Preserve spatial relationships

### 6. **OpenAI Service** (`services/openai_service.py`)
- **Role**: AI model integration
- **Functions**:
  - Text chunking with GPT-4
  - Image analysis with vision models
  - Embedding generation

### 7. **Duplicate Detection**

#### **Document Database** (`database/document_db.py`)
- **Role**: Prevent duplicate uploads via local SQLite database
- **Location**: Duplicate checking happens ONLY in `/pdf/parse-pdf` endpoint (before expensive parsing)
- **Validation Methods**:
  - **Filename check**: Fast lookup by name in SQLite database
  - **Content hash check**: SHA256-based duplicate detection in SQLite database
  - **Combined validation**: Multi-layered approach saves ~$0.05-0.20 per duplicate avoided

### 8. **Vector Database**

#### **Weaviate Client** (`database/weaviate_client.py`)
- **Role**: Vector database connection
- **Collections**:
  - **Document**: Minimal file metadata (file_name, page_count only)
  - **KnowledgeBase**: Chunks with embeddings
- **Note**: Document tracking metadata (content_hash, file_size_bytes, uploaded_by, etc.) stored in local SQLite database

#### **Operations** (`database/operations.py`)
- **Role**: CRUD operations for documents
- **Functions**:
  - `insert_document()` - Add new document
  - `delete_document_and_chunks()` - Remove document
  - `replace_document()` - Update existing document

### 9. **Utilities**

#### **File Utils** (`utils/file_utils.py`)
- JSON file operations
- Filename generation
- Backup storage

#### **Text Utils** (`utils/text_utils.py`)
- Text normalization
- Matching algorithms
- String comparisons

#### **Coordinate Utils** (`utils/coordinate_utils.py`)
- Bounding box calculations
- Coordinate transformations
- Spatial matching

---

## Complete Data Flow: PDF Upload → Vector Storage

### **Step 1: User Uploads PDF**

**Frontend Request:**
```javascript
POST /pdf/parse-pdf
Headers: {
  'Content-Type': 'multipart/form-data'
}
Body: FormData {
  file: <PDF binary data>
}
```

**Input:**
- PDF file (max 10MB)
- Filename: `"company_policy.pdf"`
- Size: 2.5MB (2,621,440 bytes)

---

### **Step 2: Security Validation**

**Process:**
```python
# middleware/security_middleware.py

# 1. Validate filename exists
if not file.filename:
    raise HTTPException(400, "No filename provided")

# 2. Sanitize filename (remove special characters)
sanitized = sanitize_filename("company_policy.pdf")
# Output: "company_policy.pdf"

# 3. Validate file type
if not validate_file_type(sanitized, ['.pdf']):
    raise HTTPException(400, "Only PDF files allowed")

# 4. Read file bytes
file_bytes = await file.read()  # Binary PDF data

# 5. Validate file size
file_size_mb = len(file_bytes) / (1024 * 1024)
if file_size_mb > 10:
    raise HTTPException(413, "File exceeds 10MB limit")

# 6. Validate minimum size (corrupted file check)
if len(file_bytes) < 100:
    raise HTTPException(400, "File appears empty or corrupted")
```

**Output:**
- Sanitized filename: `"company_policy.pdf"`
- File bytes: `<2,621,440 bytes of PDF data>`
- Validation passed ✅

---

### **Step 3: Calculate Content Hash**

**Purpose:** Enable duplicate detection by content

**Process:**
```python
# database/document_validator.py
import hashlib

content_hash = hashlib.sha256(file_bytes).hexdigest()
```

**Output:**
```python
{
  'content_hash': 'a3f5b8c2d1e4f6a9b7c8d2e3f4a5b6c7d8e9f1a2b3c4d5e6f7a8b9c1d2e3f4a5',
  'file_size_bytes': 2621440
}
```

---

### **Step 4: PDF Extraction**

**Process:**
```python
# services/pdf_service.py → core/pdf_extractor.py

import pdfplumber
import fitz  # PyMuPDF

# Open PDF with pdfplumber for text extraction
with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
    for i, page in enumerate(pdf.pages):
        # Extract structured elements
        page_elements = assemble_elements(file_bytes, page, i)
```

#### **4a. Extract Text Lines**

**Process:**
```python
# core/pdf_extractor.py → lines_from_chars()

# Group characters into lines
chars = page.chars  # All characters with positions
lines = group_chars_into_lines(chars, line_tolerance=5)

# Build line objects with metadata
for line in lines:
    line_obj = {
        "type": "line",
        "text": "Refund Policy: Returns accepted within 30 days",
        "box": {"l": 72, "t": 150, "r": 540, "b": 165},
        "font_size": 14.0,
        "bold": True,
        "italic": False,
        "spacing_before": 20,
        "spacing_after": 10,
        "page": 1,
        "words": [
            {
                "text": "Refund",
                "font_size": 14.0,
                "bold": True,
                "box": {"l": 72, "t": 150, "r": 120, "b": 165}
            },
            # ... more words
        ]
    }
```

#### **4b. Extract Images**

**Process:**
```python
# Extract images using PyMuPDF
doc = fitz.open(stream=file_bytes, filetype="pdf")
page = doc[page_num]

for img_idx, img in enumerate(page.get_images()):
    xref = img[0]
    pix = fitz.Pixmap(doc, xref)
    
    # Convert to base64 for AI processing
    img_bytes = pix.tobytes("png")
    img_b64 = base64.b64encode(img_bytes).decode('utf-8')
    
    # Get image position on page
    img_bbox = page.get_image_bbox(img)
    
    image_obj = {
        "type": "image",
        "image_b64": img_b64,
        "box": {
            "l": img_bbox.x0,
            "t": img_bbox.y0,
            "r": img_bbox.x1,
            "b": img_bbox.y1
        },
        "page": page_num + 1,
        "id": f"img_{page_num}_{img_idx}"
    }
```

#### **4c. Extract Tables**

**Process:**
```python
# core/table_processor.py

# Detect tables using pdfplumber
tables = page.find_tables()

for table in tables:
    # Extract cell content
    table_data = table.extract()
    
    table_obj = {
        "type": "table",
        "box": table.bbox,  # (x0, y0, x1, y1)
        "page": page_num + 1,
        "rows": len(table_data),
        "cols": len(table_data[0]) if table_data else 0,
        "cells": [
            [cell or "" for cell in row]
            for row in table_data
        ],
        "id": f"table_{page_num}_{table_idx}"
    }
```

**Structured Output (all elements):**
```python
structured = [
    {
        "type": "line",
        "text": "Company Refund Policy",
        "page": 1,
        "box": {"l": 72, "t": 100, "r": 300, "b": 120},
        "font_size": 18.0,
        "bold": True,
        "id": "line_0_0"
    },
    {
        "type": "line",
        "text": "All purchases are eligible for return within 30 days...",
        "page": 1,
        "box": {"l": 72, "t": 150, "r": 540, "b": 165},
        "font_size": 12.0,
        "id": "line_0_1"
    },
    {
        "type": "image",
        "image_b64": "iVBORw0KGgoAAAANSUhEUg...",
        "page": 1,
        "box": {"l": 100, "t": 200, "r": 500, "b": 400},
        "id": "img_0_0"
    },
    {
        "type": "table",
        "page": 2,
        "box": {"l": 72, "t": 100, "r": 540, "b": 300},
        "cells": [
            ["Product", "Price", "Refund Period"],
            ["Electronics", "$100+", "30 days"],
            ["Clothing", "Any", "60 days"]
        ],
        "id": "table_1_0"
    },
    # ... more elements (total: ~150 for 5-page PDF)
]
```

---

### **Step 5: Build Simplified View**

**Purpose:** Create text-based representation for AI processing

**Process:**
```python
# core/pdf_extractor.py → build_simplified_view_from_elements()

simplified_view = ""

for element in structured:
    if element["type"] == "line":
        # Add text with formatting markers
        text = element["text"]
        if element.get("bold"):
            text = f"*{text}*"
        if element.get("italic"):
            text = f"_{text}_"
        if element.get("font_size", 12) > 14:
            text = f"<s={element['font_size']}>{text}"
        
        simplified_view += text + "\n"
        
    elif element["type"] == "image":
        # Add image marker with position
        box = element["box"]
        simplified_view += f"[IMAGE page={element['page']} l={box['l']:.1f} t={box['t']:.1f} r={box['r']:.1f} b={box['b']:.1f}]\n"
        
    elif element["type"] == "table":
        # Add table marker
        simplified_view += f"[TABLE page={element['page']} rows={element['rows']} cols={element['cols']}]\n"
        # Add cell content
        for row in element["cells"]:
            simplified_view += "  | " + " | ".join(row) + " |\n"
```

**Output:**
```
<s=18>*Company Refund Policy*

All purchases are eligible for return within 30 days of purchase.
Items must be in original condition with all tags attached.

[IMAGE page=1 l=100.0 t=200.0 r=500.0 b=400.0]

*Return Process:*
1. Contact customer support
2. Provide order number
3. Ship item back with prepaid label

[TABLE page=2 rows=3 cols=3]
  | Product | Price | Refund Period |
  | Electronics | $100+ | 30 days |
  | Clothing | Any | 60 days |

For questions, email support@company.com or call 1-800-SUPPORT.
```

---

### **Step 6: AI Chunking - Text Pass**

**Purpose:** Identify logical text structure and create meaningful chunks

**Process:**
```python
# services/chunking_service.py → process_text_only()

client = get_openai_client()

# Remove image markers for clean text analysis
clean_text = simplified_view.replace("[IMAGE ...]", "[IMAGE_PLACEHOLDER]")

prompt = """You are a PDF text analyzer that outputs structured JSON.
Your task is to:
1. Analyze the text content and identify its logical structure
2. Split it into meaningful chunks (paragraphs, sections, lists, tables)
3. Preserve context and relationships

Output Schema:
{
  "chunks": [
    {
      "text": "chunk content",
      "metadata": {
        "type": "heading|paragraph|list|table",
        "section": "section name",
        "context": "surrounding context",
        "page": 1,
        "tags": ["keyword1", "keyword2"]
      }
    }
  ]
}
"""

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": prompt},
        {"role": "user", "content": clean_text}
    ],
    response_format={"type": "json_object"},
    temperature=0.3
)

text_result = json.loads(response.choices[0].message.content)
```

**Output:**
```python
{
  "chunks": [
    {
      "text": "Company Refund Policy",
      "metadata": {
        "type": "heading",
        "section": "Refund Policy",
        "context": "Main document heading",
        "page": 1,
        "tags": ["refund", "policy", "heading"]
      }
    },
    {
      "text": "All purchases are eligible for return within 30 days of purchase. Items must be in original condition with all tags attached.",
      "metadata": {
        "type": "paragraph",
        "section": "Refund Policy",
        "context": "Eligibility requirements for refunds",
        "page": 1,
        "tags": ["refund", "eligibility", "30 days", "returns"]
      }
    },
    {
      "text": "Return Process:\n1. Contact customer support\n2. Provide order number\n3. Ship item back with prepaid label",
      "metadata": {
        "type": "list",
        "section": "Refund Policy",
        "context": "Step-by-step return instructions",
        "page": 1,
        "tags": ["return", "process", "instructions"]
      }
    },
    {
      "text": "Product | Price | Refund Period\nElectronics | $100+ | 30 days\nClothing | Any | 60 days",
      "metadata": {
        "type": "table",
        "section": "Refund Policy",
        "context": "Refund period by product category",
        "page": 2,
        "tags": ["refund", "period", "products", "table"]
      }
    },
    {
      "text": "For questions, email support@company.com or call 1-800-SUPPORT.",
      "metadata": {
        "type": "paragraph",
        "section": "Contact Information",
        "context": "Customer support contact details",
        "page": 2,
        "tags": ["contact", "support", "email", "phone"]
      }
    }
  ]
}
```

---

### **Step 7: AI Chunking - Image Pass**

**Purpose:** Analyze images with surrounding context

**Process:**
```python
# services/chunking_service.py → process_images_only()

for image in images:
    # Get surrounding text context
    marker_pos = simplified_view.find(f"[IMAGE page={image['page']}")
    context_start = max(0, marker_pos - 200)
    context_end = min(len(simplified_view), marker_pos + 200)
    context_text = simplified_view[context_start:context_end]
    
    # Analyze image with GPT-4 Vision
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"""Analyze this image from a PDF document.

Surrounding context:
{context_text}

Describe:
1. What the image shows
2. How it relates to the document
3. Key visual elements
4. Relevant text or labels

Output format:
{{
  "description": "detailed description",
  "type": "diagram|photo|chart|logo|illustration",
  "key_elements": ["element1", "element2"],
  "relationship": "how it relates to document"
}}"""
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image['image_b64']}"
                        }
                    }
                ]
            }
        ],
        temperature=0.3
    )
    
    image_analysis = json.loads(response.choices[0].message.content)
```

**Output:**
```python
{
  "chunks": [
    {
      "text": "Image showing company return shipping label with barcode, tracking number, and return address. Label displays company logo and instructions for package preparation.",
      "metadata": {
        "type": "image",
        "section": "Refund Policy",
        "context": "Example of prepaid return label provided for returns",
        "page": 1,
        "tags": ["return", "shipping", "label", "barcode"],
        "box": {"l": 100, "t": 200, "r": 500, "b": 400},
        "image_type": "illustration",
        "key_elements": ["barcode", "tracking number", "company logo", "return address"]
      }
    }
  ]
}
```

---

### **Step 8: Merge Text and Image Chunks**

**Process:**
```python
# services/chunking_service.py → merge_text_and_image_chunks()

# Combine chunks from both passes
all_chunks = text_chunks + image_chunks

# Sort by page and position
all_chunks.sort(key=lambda c: (
    c['metadata']['page'],
    c['metadata'].get('box', {}).get('t', 0)
))

# Assign unique IDs
for i, chunk in enumerate(all_chunks):
    chunk['id'] = f"chunk-{i}-{str(uuid.uuid4())[:8]}"
    chunk['chunk_id'] = chunk['id']
    chunk['metadata']['created_at'] = datetime.now().isoformat()
```

**Output:**
```python
merged_result = {
  "chunks": [
    {
      "id": "chunk-0-a1b2c3d4",
      "chunk_id": "chunk-0-a1b2c3d4",
      "text": "Company Refund Policy",
      "metadata": {
        "type": "heading",
        "section": "Refund Policy",
        "context": "Main document heading",
        "page": 1,
        "tags": ["refund", "policy"],
        "created_at": "2025-11-21T10:30:45.123456"
      }
    },
    {
      "id": "chunk-1-e5f6g7h8",
      "chunk_id": "chunk-1-e5f6g7h8",
      "text": "All purchases are eligible for return within 30 days...",
      "metadata": {
        "type": "paragraph",
        "section": "Refund Policy",
        "page": 1,
        "tags": ["refund", "eligibility"]
      }
    },
    {
      "id": "chunk-2-i9j0k1l2",
      "chunk_id": "chunk-2-i9j0k1l2",
      "text": "Image showing company return shipping label...",
      "metadata": {
        "type": "image",
        "page": 1,
        "box": {"l": 100, "t": 200, "r": 500, "b": 400}
      }
    },
    # ... more chunks (total: 8 for this example)
  ],
  "document_metadata": {
    "total_pages": 2,
    "total_elements": 15,
    "text_chunks": 7,
    "image_chunks": 1,
    "table_chunks": 0
  }
}
```

---

### **Step 9: Anchor Chunks to PDF Coordinates**

**Purpose:** Map AI-generated chunks back to exact PDF positions

**Process:**
```python
# services/anchoring_service.py → anchor_chunks_to_pdf()

# Build searchable list of PDF lines
pdf_lines = []
for element in structured:
    if element["type"] == "line":
        pdf_lines.append({
            "text": element["text"],
            "box": element["box"],
            "page": element["page"],
            "id": element["id"]
        })

# Match each chunk to PDF lines
for chunk in chunks:
    if chunk['metadata']['type'] == 'image':
        # Images already have coordinates
        chunk['metadata']['anchored'] = True
        continue
    
    # Split chunk text into lines
    chunk_lines = chunk['text'].split('\n')
    
    # Find matching lines in PDF
    matched_lines = []
    for chunk_line in chunk_lines:
        # Normalize text for matching
        normalized_chunk = normalize_text(chunk_line)
        
        # Search PDF lines
        for pdf_line in pdf_lines:
            normalized_pdf = normalize_text(pdf_line['text'])
            
            # Calculate similarity score
            score = calculate_match_score(normalized_chunk, normalized_pdf)
            
            if score > 0.8:  # 80% match threshold
                matched_lines.append(pdf_line)
                break
    
    if matched_lines:
        # Calculate bounding box encompassing all matched lines
        chunk['metadata']['box'] = calculate_chunk_box(matched_lines)
        chunk['metadata']['anchored'] = True
        chunk['metadata']['line_ids'] = [l['id'] for l in matched_lines]
    else:
        chunk['metadata']['anchored'] = False
```

**Output (Anchored Chunks):**
```python
anchored_chunks = [
    {
        "id": "chunk-0-a1b2c3d4",
        "text": "Company Refund Policy",
        "metadata": {
            "type": "heading",
            "section": "Refund Policy",
            "page": 1,
            "box": {"l": 72, "t": 100, "r": 300, "b": 120},
            "anchored": True,
            "line_ids": ["line_0_0"],
            "tags": ["refund", "policy"]
        }
    },
    {
        "id": "chunk-1-e5f6g7h8",
        "text": "All purchases are eligible for return within 30 days...",
        "metadata": {
            "type": "paragraph",
            "page": 1,
            "box": {"l": 72, "t": 150, "r": 540, "b": 180},
            "anchored": True,
            "line_ids": ["line_0_1", "line_0_2"],
            "tags": ["refund", "eligibility"]
        }
    },
    # ... more anchored chunks
]
```

---

### **Step 10: Return Parse Result**

**HTTP Response:**
```json
{
  "chunks": [
    {
      "id": "chunk-0-a1b2c3d4",
      "chunk_id": "chunk-0-a1b2c3d4",
      "text": "Company Refund Policy",
      "metadata": {
        "type": "heading",
        "section": "Refund Policy",
        "context": "Main document heading",
        "page": 1,
        "box": {"l": 72, "t": 100, "r": 300, "b": 120},
        "anchored": true,
        "tags": ["refund", "policy"],
        "created_at": "2025-11-21T10:30:45.123456"
      }
    },
    {
      "id": "chunk-1-e5f6g7h8",
      "chunk_id": "chunk-1-e5f6g7h8",
      "text": "All purchases are eligible for return within 30 days of purchase. Items must be in original condition with all tags attached.",
      "metadata": {
        "type": "paragraph",
        "section": "Refund Policy",
        "page": 1,
        "box": {"l": 72, "t": 150, "r": 540, "b": 180},
        "anchored": true,
        "tags": ["refund", "eligibility", "30 days"]
      }
    }
  ],
  "document_metadata": {
    "total_pages": 2,
    "total_chunks": 8,
    "text_chunks": 7,
    "image_chunks": 1,
    "table_chunks": 0,
    "source_filename": "company_policy.pdf"
  },
  "content_hash": "a3f5b8c2d1e4f6a9b7c8d2e3f4a5b6c7d8e9f1a2b3c4d5e6f7a8b9c1d2e3f4a5",
  "file_size_bytes": 2621440
}
```

**Frontend saves this data for next step: Upload to KB**

---

### **Step 11: User Uploads to Knowledge Base**

**Frontend Request:**
```javascript
POST /kb/upload-to-kb
Headers: {
  'Content-Type': 'application/json'
}
Body: {
  "chunks": [/* all chunks from parse-pdf */],
  "document_metadata": {
    "total_pages": 2,
    "total_chunks": 8
  },
  "source_filename": "company_policy.pdf",
  "content_hash": "a3f5b8c2...",
  "file_size_bytes": 2621440,
  "force_replace": false
}
```

---

### **Step 12: Duplicate Detection (Already Done in parse-pdf)**

**Important:** Duplicate detection now happens exclusively in the `/pdf/parse-pdf` endpoint BEFORE expensive parsing operations.

**Process (in pdf_routes.py):**
```python
# api/pdf_routes.py → parse_pdf()

# Calculate content hash for duplicate detection
content_hash = calculate_file_hash(file_bytes)
file_size_bytes = len(file_bytes)

# ==================== DUPLICATE CHECK BEFORE PARSING ====================
# This saves expensive OpenAI API calls and processing time
if not force_reparse:
    doc_db = DocumentDatabase()  # Local SQLite database
    
    # Check by filename first (fastest)
    existing_by_name = doc_db.check_duplicate_by_filename(sanitized_filename)
    if existing_by_name:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_filename",
                "message": f"Document '{sanitized_filename}' has already been uploaded and parsed.",
                "existing_doc": existing_by_name,
                "suggestion": "Use force_reparse=true to parse again, or use the existing parsed data.",
                "cost_saved": "Avoided re-parsing. Saved ~$0.05-0.20 in OpenAI API costs."
            }
        )
    
    # Check by content hash (detects renamed duplicates)
    existing_by_hash = doc_db.check_duplicate_by_hash(content_hash)
    if existing_by_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_content",
                "message": f"This file content has already been uploaded as '{existing_by_hash['file_name']}'.",
                "existing_doc": existing_by_hash,
                "suggestion": "This is a renamed duplicate. Use the existing parsed data.",
                "cost_saved": "Avoided re-parsing identical content. Saved ~$0.05-0.20 in OpenAI API costs."
            }
        )
```

**Duplicate Detection Methods (Local SQLite Database):**

#### **Method 1: Filename Check**
```python
# database/document_db.py → check_duplicate_by_filename()

cursor = self.conn.cursor()
cursor.execute(
    "SELECT * FROM documents WHERE file_name = ? LIMIT 1",
    (filename,)
)
row = cursor.fetchone()

if row:
    return {
        "doc_id": row[0],
        "file_name": row[1],
        "upload_date": row[2],
        "file_size_bytes": row[3],
        "chunks": row[4]
    }

return None  # No duplicate found
```

#### **Method 2: Content Hash Check**
```python
# database/document_db.py → check_duplicate_by_hash()

cursor = self.conn.cursor()
cursor.execute(
    "SELECT * FROM documents WHERE content_hash = ? LIMIT 1",
    (content_hash,)
)
row = cursor.fetchone()

if row:
    return {
        "doc_id": row[0],
        "file_name": row[1],
        "content_hash": row[6],
        "upload_date": row[2]
    }

return None  # No duplicate found
```

**Benefits:**
- ✅ **Early detection**: Checks BEFORE expensive parsing (saves 10-25 seconds per duplicate)
- ✅ **Cost savings**: Avoids OpenAI API calls (~$0.05-0.20 per duplicate)
- ✅ **Fast lookups**: SQLite indexed queries (~10ms vs 10-25 seconds parsing)
- ✅ **Catches renamed duplicates**: Content hash comparison
- ✅ **Maintains data integrity**: Prevents duplicate embeddings in Weaviate

---

### **Step 13: Prepare Document Metadata**

**Process:**
```python
# Prepare metadata for Weaviate Document collection (minimal fields only)
file_metadata = {
    "file_name": "company_policy.pdf",
    "page_count": 2
}

# Additional tracking metadata saved to local SQLite database
db_metadata = {
    "doc_id": str(uuid.uuid4()),
    "file_name": "company_policy.pdf",
    "file_size_bytes": 2621440,
    "chunks": 8,
    "uploaded_by": "user@example.com",
    "content_hash": "a3f5b8c2d1e4...",
    "page_count": 2,
    "weaviate_doc_id": weaviate_doc_id,
    "metadata": document_metadata
}

# Generate document ID
doc_id = str(uuid.uuid4())  # "d7e8f9a0-b1c2-3d4e-5f6a-7b8c9d0e1f2a"
```

---

### **Step 14: Insert Document into Weaviate**

**Process:**
```python
# database/operations.py → insert_document()

client = get_weaviate_client()

# 1. Insert parent Document
documents = client.collections.get("Document")
documents.data.insert(
    properties=file_metadata,
    uuid=doc_id
)

print(f"✅ Inserted Document: {file_metadata['file_name']}")
```

**Weaviate Document Collection:**
```json
{
  "id": "d7e8f9a0-b1c2-3d4e-5f6a-7b8c9d0e1f2a",
  "properties": {
    "file_name": "company_policy.pdf",
    "page_count": 2
  }
}
```

**Local SQLite Database Record:**
```json
{
  "doc_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "file_name": "company_policy.pdf",
  "upload_date": "2025-11-21T10:31:00.123456",
  "file_size_bytes": 2621440,
  "chunks": 8,
  "uploaded_by": "user@example.com",
  "content_hash": "a3f5b8c2d1e4f6a9b7c8d2e3f4a5b6c7...",
  "page_count": 2,
  "weaviate_doc_id": "d7e8f9a0-b1c2-3d4e-5f6a-7b8c9d0e1f2a",
  "metadata": "{\"total_pages\": 2, \"total_chunks\": 8}"
}
```

---

### **Step 15: Insert Chunks into Weaviate**

**Process:**
```python
# database/operations.py → insert_document() (continued)

# 2. Insert child chunks with vectorization
chunks_collection = client.collections.get("KnowledgeBase")

with chunks_collection.batch.fixed_size(batch_size=100) as batch:
    for chunk in chunks:
        meta = chunk.get("metadata", {})
        
        # Prepare chunk object
        chunk_obj = {
            "text": chunk["text"],
            "type": meta.get("type", "text"),
            "section": meta.get("section", ""),
            "context": meta.get("context", ""),
            "tags": meta.get("tags", []),
            "page": meta.get("page", 1),
            "chunk_id": chunk.get("chunk_id"),
            "created_at": meta.get("created_at", "")
        }
        
        # Add chunk with reference to parent document
        batch.add_object(
            properties=chunk_obj,
            references={"ofDocument": doc_id}
        )

print(f"✅ Inserted {len(chunks)} chunks")
```

**What Happens in Weaviate:**

1. **Text Vectorization**:
   - Weaviate sends chunk text to OpenAI `text-embedding-3-small`
   - OpenAI returns 1536-dimensional vector
   - Example: `[0.0234, -0.0123, 0.0456, ..., 0.0789]` (1536 values)

2. **Chunk Storage**:
```json
{
  "id": "c1a2b3c4-d5e6-7f8a-9b0c-1d2e3f4a5b6c",
  "properties": {
    "chunk_id": "chunk-0-a1b2c3d4",
    "text": "Company Refund Policy",
    "type": "heading",
    "section": "Refund Policy",
    "context": "Main document heading",
    "tags": ["refund", "policy"],
    "page": 1,
    "created_at": "2025-11-21T10:30:45.123456"
  },
  "vector": [0.0234, -0.0123, 0.0456, ..., 0.0789],
  "references": {
    "ofDocument": "d7e8f9a0-b1c2-3d4e-5f6a-7b8c9d0e1f2a"
  }
}
```

**Weaviate Schema Visualization:**
```
Document Collection (Vector Database)
└── id: d7e8f9a0-b1c2-3d4e-5f6a-7b8c9d0e1f2a
    ├── file_name: "company_policy.pdf"
    └── page_count: 2

Local SQLite Database (Tracking & Metadata)
└── doc_id: a1b2c3d4-e5f6-7890-abcd-ef1234567890
    ├── file_name: "company_policy.pdf"
    ├── upload_date: "2025-11-21T10:31:00.123456" (ISO format with time)
    ├── file_size_bytes: 2621440
    ├── chunks: 8
    ├── uploaded_by: "user@example.com"
    ├── content_hash: "a3f5b8c2..."
    ├── page_count: 2
    ├── weaviate_doc_id: "d7e8f9a0-b1c2-3d4e-5f6a-7b8c9d0e1f2a"
    └── metadata: {...}

KnowledgeBase Collection
├── Chunk 1
│   ├── id: c1a2b3c4-d5e6-7f8a-9b0c-1d2e3f4a5b6c
│   ├── text: "Company Refund Policy"
│   ├── vector: [1536 dimensions]
│   └── ofDocument → d7e8f9a0-b1c2-3d4e-5f6a-7b8c9d0e1f2a
├── Chunk 2
│   ├── id: c2b3c4d5-e6f7-8a9b-0c1d-2e3f4a5b6c7d
│   ├── text: "All purchases are eligible..."
│   ├── vector: [1536 dimensions]
│   └── ofDocument → d7e8f9a0-b1c2-3d4e-5f6a-7b8c9d0e1f2a
└── ... (6 more chunks)
```

---

### **Step 16: Save to Local Database**

**Purpose:** Track document metadata in local SQLite database

**Process:**
```python
# api/kb_routes.py → upload_to_kb()

# Save to document tracking database
doc_id = str(uuid.uuid4())  # Separate ID for our database
doc_db.insert_document({
    "doc_id": doc_id,
    "file_name": request.source_filename,
    "file_size_bytes": request.file_size_bytes or 0,
    "chunks": len(request.chunks),
    "uploaded_by": uploaded_by,
    "content_hash": request.content_hash or "",
    "page_count": file_metadata["page_count"],
    "weaviate_doc_id": weaviate_doc_id,
    "metadata": request.document_metadata
})
```

**Database Record:** Stored in `documents.db` SQLite file

**Note:** JSON backup files are no longer created. The local SQLite database serves as the single source of truth for document tracking metadata.

---

### **Step 17: Return Success Response**

**HTTP Response:**
```json
{
  "success": true,
  "message": "Successfully uploaded 8 chunks to knowledge base",
  "doc_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "weaviate_doc_id": "d7e8f9a0-b1c2-3d4e-5f6a-7b8c9d0e1f2a",
  "action": "uploaded"
}
```

**Frontend receives confirmation and can now:**
- Show success message to user
- Query the knowledge base
- Search for document content
- Use chunks in AI chat

---

## Vector Search Architecture

### **How Documents Become Searchable**

Once uploaded, documents can be queried using:

#### **1. Hybrid Search** (Recommended)
Combines semantic (vector) and keyword (BM25) search:

```python
# services/weaviate_search_service.py

response = collection.query.hybrid(
    query="What is the refund policy?",
    limit=5,
    alpha=0.5  # 0.5 = 50% vector + 50% keyword
)
```

**Search Process:**
1. **Vector Search**:
   - Query → OpenAI embedding → `[1536 dimensions]`
   - Compare with chunk vectors using cosine similarity
   - Find semantically similar chunks

2. **BM25 Search**:
   - Traditional keyword matching
   - Ranks by term frequency/inverse document frequency
   - Finds exact keyword matches

3. **Fusion**:
   - Combines both scores
   - Returns unified ranking

**Example Results:**
```python
[
    {
        'chunk_id': 'chunk-1-e5f6g7h8',
        'text': 'All purchases are eligible for return within 30 days...',
        'document_name': 'company_policy.pdf',
        'page': 1,
        'score': 0.89,  # Combined relevance score
        'type': 'paragraph'
    },
    {
        'chunk_id': 'chunk-3-m9n0p1q2',
        'text': 'Return Process: 1. Contact customer support...',
        'document_name': 'company_policy.pdf',
        'page': 1,
        'score': 0.85
    }
]
```

#### **2. Semantic Search**
Pure vector similarity:

```python
response = collection.query.near_text(
    query="refund eligibility requirements",
    limit=5
)
```

---

## Data Models & Schemas

### **Document Model** (Weaviate - Minimal Fields)
```python
{
  'id': str,                    # UUID
  'file_name': str,             # Original filename
  'page_count': int             # Number of pages
}
```

### **Document Model** (Local SQLite Database - Complete Tracking)
```python
{
  'doc_id': str,                # UUID (separate from Weaviate ID)
  'file_name': str,             # Original filename
  'upload_date': str,           # ISO datetime with time (e.g., "2025-11-21T10:31:00.123456")
  'file_size_bytes': int,       # File size
  'chunks': int,                # Number of chunks
  'uploaded_by': str,           # User identifier
  'content_hash': str,          # SHA256 hash for duplicate detection
  'page_count': int,            # Number of pages
  'weaviate_doc_id': str,       # Reference to Weaviate document ID
  'metadata': str               # JSON string of additional metadata
}
```

### **KnowledgeBase Chunk Model** (Weaviate)
```python
{
  'id': str,                    # UUID (auto-generated)
  'chunk_id': str,              # Custom chunk ID
  'text': str,                  # Chunk content
  'type': str,                  # 'text', 'heading', 'list', 'table', 'image'
  'section': str,               # Document section name
  'context': str,               # Surrounding context
  'tags': List[str],            # Keywords/topics
  'page': int,                  # Page number
  'created_at': str,            # ISO datetime
  'vector': List[float],        # 1536-dimensional embedding
  'ofDocument': Reference       # Reference to Document
}
```

### **Backup JSON Structure** (DEPRECATED - No Longer Used)
**Note:** JSON backup files (kb_*.json) are no longer created as of the latest version. Document metadata is now stored exclusively in the local SQLite database (documents.db).

**Previous Structure (for reference):**
```python
{
  'document_metadata': {
    'total_pages': int,
    'total_chunks': int,
    'text_chunks': int,
    'image_chunks': int
  },
  'source_filename': str,
  'upload_timestamp': str,
  'doc_id': str,
  'content_hash': str,
  'file_size_bytes': int,
  'chunks': List[Dict]
}
```

---

## Performance Characteristics

### **Typical Processing Times**
```
Security Validation:       ~50ms
PDF Extraction:            ~2-5 seconds  (depends on PDF size)
AI Text Chunking:          ~3-8 seconds  (OpenAI API)
AI Image Analysis:         ~2-5 seconds per image
Anchoring:                 ~1-3 seconds
Duplicate Check:           ~50-100ms
Weaviate Upload:           ~2-5 seconds  (includes vectorization)
Backup Save:               ~100ms
──────────────────────────────────────
Total Processing Time:     ~10-25 seconds for typical PDF
```

### **Token Usage (OpenAI)**
Per document upload:
- **Text Chunking**: ~3,000-5,000 tokens
- **Image Analysis**: ~1,000 tokens per image
- **Embeddings**: Automatic (pay per chunk)

### **Storage Costs**
- **Weaviate Vector Storage**: ~6KB per chunk (1536 floats)
- **Text Storage**: ~0.5-2KB per chunk
- **Total per chunk**: ~6.5-8KB
- **Example**: 100 chunks = ~700KB in Weaviate

### **Scaling Considerations**
- **Single PDF**: 10-25 seconds
- **Concurrent uploads**: Rate limited (20 uploads/hour default)
- **Weaviate capacity**: Millions of chunks
- **OpenAI limits**: 10,000 requests per minute

---

## Error Handling

### **Common Errors**

1. **400 Bad Request**
   - Invalid file type (not PDF)
   - File too large (>10MB)
   - Empty/corrupted file
   - Invalid JSON in upload request

2. **409 Conflict**
   - Duplicate filename detected
   - Duplicate content detected (same hash)
   - Solution: Set `force_replace=true` to overwrite

3. **413 Payload Too Large**
   - File exceeds 10MB limit
   - Solution: Compress PDF or split into smaller files

4. **500 Internal Server Error**
   - PDF parsing failed
   - OpenAI API error
   - Weaviate connection failed
   - Chunking service error

### **Retry Logic**
- **OpenAI**: 3 retries with exponential backoff
- **Weaviate**: Connection pool with auto-reconnect
- **File operations**: Single attempt (no retry)

---

## Security Features

### **Input Validation**
```python
# File Security
✓ File type whitelist (PDF only)
✓ File size limit (10MB default)
✓ Filename sanitization (remove special characters)
✓ Empty file detection
✓ Corrupted file detection

# Request Validation
✓ String length limits (filenames, queries)
✓ Chunk count limits (max 10,000 per document)
✓ Pydantic schema validation
✓ Rate limiting (20 uploads/hour)
```

### **Duplicate Prevention**
```python
# Multi-layered checks
✓ Filename uniqueness
✓ Content hash uniqueness (SHA256)
✓ Force replace option for updates
✓ Conflict error with details
```

### **Data Integrity**
```python
# Safeguards
✓ UUID-based document IDs
✓ Parent-child references (Document → Chunks)
✓ Cascade delete support
✓ Backup JSON files
✓ Upload timestamps
```

---

## Configuration

### **Environment Variables** (`.env`)
```bash
# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
TEMPERATURE=0.3

# Weaviate
WEAVIATE_URL=https://your-cluster.weaviate.network
WEAVIATE_API_KEY=your-api-key

# Upload Limits
MAX_FILE_SIZE_MB=10
ALLOWED_FILE_TYPES=[".pdf"]
MAX_FILENAME_LENGTH=255
BATCH_SIZE=100

# Rate Limiting
RATE_LIMIT_ENABLED=true
UPLOADS_PER_HOUR=20
```

### **Chunking Parameters**
```python
# In services/chunking_service.py
CHUNK_STRATEGY = "semantic"      # AI-powered chunking
MAX_CHUNK_SIZE = 1000            # Characters per chunk
OVERLAP_SIZE = 100               # Overlap between chunks
MIN_CHUNK_SIZE = 50              # Minimum chunk size
```

---

## Monitoring & Debugging

### **Console Output Format**
```
[DEBUG] Starting parse-pdf endpoint
[DEBUG] Processing uploaded file: company_policy.pdf
[DEBUG] Extracted structure: 150 elements
[DEBUG] Simplified view length: 3450 characters
[DEBUG] Detection result: False (confidence: 65.0%)
[DEBUG] Found 1 images with base64 data
[DEBUG] Using STANDARD two-pass processing
[DEBUG] Text-only processing: 7 chunks created
[DEBUG] Image analysis for 1 images
[DEBUG] Merged result: 8 total chunks
[DEBUG] Anchoring 8 chunks to PDF coordinates
[DEBUG] Anchored 7/8 chunks successfully
✅ Inserted Document company_policy.pdf with 8 chunks
[INFO] Successfully uploaded 8 chunks to knowledge base
```

### **Debug Files Created**
```
structured_output_v3.json        # Raw PDF elements
text_only_chunks.json            # Text chunking result
image_only_chunks.json           # Image analysis result
two_pass_final_result.json       # Merged chunks
final_anchored_result.json       # Anchored chunks
kb_20251121_103100_*.json        # Backup file
```

---

## API Endpoints Summary

### **Upload Pipeline**
```
1. POST /pdf/parse-pdf
   Input:  PDF file (multipart/form-data)
   Output: Chunks with metadata, content_hash, file_size
   Note:   Duplicate detection happens HERE (before parsing)

2. POST /kb/upload-to-kb
   Input:  Chunks, metadata, hash, size
   Output: Success, doc_id, weaviate_doc_id, action

3. GET /kb/list-kb
   Output: List of uploaded documents from SQLite database
```

### **Management Endpoints**
```
GET  /kb/list-kb              # List all documents (from SQLite database)
POST /kb/query                # Query knowledge base (Weaviate vector search)
```

**Note:** Duplicate checking is integrated into `/pdf/parse-pdf` and is no longer a separate endpoint.

---

## Future Enhancements

1. **Advanced Chunking**
   - Layout-aware chunking
   - Multi-column support
   - Header/footer detection
   - Footnote handling

2. **File Format Support**
   - Microsoft Word (.docx)
   - PowerPoint (.pptx)
   - HTML/Markdown
   - Images (OCR)

3. **Processing Options**
   - Custom chunking strategies
   - Language detection
   - OCR for scanned PDFs
   - Metadata extraction (author, date)

4. **Optimization**
   - Async processing (background jobs)
   - Batch uploads
   - Streaming responses
   - Caching frequently accessed documents

5. **Analytics**
   - Upload statistics
   - Processing time metrics
   - Storage usage tracking
   - Popular documents

---

## Troubleshooting

### **PDF Parsing Fails**
**Symptoms**: 500 error, "Failed to process PDF"
**Causes**:
- Corrupted PDF file
- Encrypted/password-protected PDF
- Unsupported PDF version
- Missing fonts

**Solutions**:
- Validate PDF with Adobe Reader
- Remove encryption
- Re-save PDF in compatible format
- Check server logs for details

### **Slow Processing**
**Symptoms**: Upload takes >60 seconds
**Causes**:
- Large PDF (many pages/images)
- High-resolution images
- Complex tables
- OpenAI API latency

**Solutions**:
- Compress images before PDF creation
- Split large PDFs
- Reduce image count
- Check OpenAI API status

### **Duplicate Errors**
**Symptoms**: 409 Conflict error
**Causes**:
- File already uploaded
- Renamed duplicate (same content)

**Solutions**:
- Use different filename
- Set `force_replace=true` to overwrite
- Check existing documents first

### **Chunks Not Anchored**
**Symptoms**: `anchored: false` in metadata
**Causes**:
- Text heavily modified by AI
- Formatting differences
- Special characters

**Solutions**:
- Check match threshold settings
- Review normalized text
- Manually verify chunk positions

---

**Last Updated**: November 21, 2025
**Version**: 2.0

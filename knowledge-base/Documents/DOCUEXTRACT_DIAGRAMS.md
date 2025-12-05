# DocuExtract System Diagrams

> **Last Updated:** November 30, 2025

---

## Table of Contents

1. [Activity Diagrams](#activity-diagrams)
   - [Document Upload Activity](#1-document-upload-activity-diagram)
   - [Duplicate Override Activity](#2-duplicate-override-activity-diagram)
   - [Query/Search Activity](#3-querysearch-activity-diagram)
2. [System Sequence Diagrams (SSD)](#system-sequence-diagrams)
   - [Document Upload SSD](#1-document-upload-sequence)
   - [Duplicate Override SSD](#2-duplicate-override-sequence)
   - [Version History SSD](#3-version-history-retrieval-sequence)
   - [Document Search SSD](#4-document-search-sequence)

---

## Activity Diagrams

### 1. Document Upload Activity Diagram

```
                                    ┌─────────────────┐
                                    │     START       │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │  User selects   │
                                    │   PDF file      │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │ Send file to    │
                                    │ /pdf/parse-pdf  │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │ Calculate       │
                                    │ content hash    │
                                    └────────┬────────┘
                                             │
                                             ▼
                              ┌──────────────────────────────┐
                              │    Check for duplicates      │
                              │  (filename & content_hash)   │
                              └──────────────┬───────────────┘
                                             │
                                             ▼
                                    ◇─────────────────◇
                                   ╱                   ╲
                                  ╱   Is duplicate?     ╲
                                 ╱                       ╲
                                ◇─────────────────────────◇
                               │                           │
                          [YES]│                           │[NO]
                               ▼                           ▼
                      ┌─────────────────┐        ┌─────────────────┐
                      │ Return 409      │        │ Parse PDF       │
                      │ Conflict with   │        │ Extract text    │
                      │ existing doc    │        │ & tables        │
                      └────────┬────────┘        └────────┬────────┘
                               │                          │
                               ▼                          ▼
                      ┌─────────────────┐        ┌─────────────────┐
                      │ Show Duplicate  │        │ Create chunks   │
                      │ Modal to user   │        │ with metadata   │
                      └────────┬────────┘        └────────┬────────┘
                               │                          │
                               ▼                          ▼
                      ◇─────────────────◇        ┌─────────────────┐
                     ╱                   ╲       │ Return chunks   │
                    ╱  User chooses       ╲      │ to frontend     │
                   ╱   action?             ╲     └────────┬────────┘
                  ◇─────────────────────────◇            │
                 │              │            │            ▼
           [Cancel]       [Override]    [View History]    │
                 │              │            │            │
                 ▼              ▼            ▼            │
         ┌───────────┐  ┌───────────┐  ┌───────────┐     │
         │   Close   │  │  Show     │  │  Fetch &  │     │
         │   modal   │  │ Confirm   │  │  show     │     │
         │           │  │  Modal    │  │ versions  │     │
         └─────┬─────┘  └─────┬─────┘  └─────┬─────┘     │
               │              │              │            │
               │              ▼              │            │
               │      ◇───────────────◇      │            │
               │     ╱                 ╲     │            │
               │    ╱  User confirms?   ╲    │            │
               │   ◇─────────────────────◇   │            │
               │   │                     │   │            │
               │ [NO]                 [YES]  │            │
               │   │                     │   │            │
               │   ▼                     ▼   │            ▼
               │ ┌───────┐      ┌─────────────────┐  ┌─────────────────┐
               │ │ Close │      │ Go to Override  │  │ User reviews    │
               │ │ modal │      │ Flow (see next) │  │ chunks in UI    │
               │ └───┬───┘      └────────┬────────┘  └────────┬────────┘
               │     │                   │                    │
               │     │                   │                    ▼
               │     │                   │           ┌─────────────────┐
               │     │                   │           │ User clicks     │
               │     │                   │           │ "Upload to KB"  │
               │     │                   │           └────────┬────────┘
               │     │                   │                    │
               │     │                   │                    ▼
               │     │                   │           ┌─────────────────┐
               │     │                   │           │ POST /kb/       │
               │     │                   │           │ upload-to-kb    │
               │     │                   │           └────────┬────────┘
               │     │                   │                    │
               │     │                   │                    ▼
               │     │                   │           ┌─────────────────┐
               │     │                   │           │ Insert to       │
               │     │                   │           │ Weaviate        │
               │     │                   │           └────────┬────────┘
               │     │                   │                    │
               │     │                   │                    ▼
               │     │                   │           ┌─────────────────┐
               │     │                   │           │ Save to SQLite  │
               │     │                   │           │ documents table │
               │     │                   │           └────────┬────────┘
               │     │                   │                    │
               │     │                   │                    ▼
               │     │                   │           ┌─────────────────┐
               │     │                   │           │ Show Success    │
               │     │                   │           │ Modal           │
               └─────┴───────────────────┴───────────┴────────┬────────┘
                                                              │
                                                              ▼
                                                     ┌─────────────────┐
                                                     │      END        │
                                                     └─────────────────┘
```

---

### 2. Duplicate Override Activity Diagram (Updated)

> **Key Change:** Override now re-parses the PDF before uploading.

```
                                    ┌─────────────────┐
                                    │     START       │
                                    │ (from Duplicate │
                                    │   Detection)    │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │ User clicks     │
                                    │ "Override"      │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │ Show Override   │
                                    │ Confirmation    │
                                    │ Modal           │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ◇─────────────────◇
                                   ╱                   ╲
                                  ╱  User confirms?     ╲
                                 ╱                       ╲
                                ◇─────────────────────────◇
                               │                           │
                          [NO] │                           │ [YES]
                               ▼                           ▼
                      ┌─────────────────┐        ┌─────────────────┐
                      │ Close modal     │        │ Close both      │
                      │ Return to       │        │ modals          │
                      │ duplicate modal │        └────────┬────────┘
                      └────────┬────────┘                 │
                               │                          ▼
                               │                 ┌─────────────────┐
                               │                 │ Set state:      │
                               │                 │ forceReplaceMode│
                               │                 │ = true          │
                               │                 └────────┬────────┘
                               │                          │
                               │                          ▼
                               │                 ┌─────────────────┐
                               │                 │ RE-PARSE PDF:   │
                               │                 │ POST /pdf/      │
                               │                 │ parse-pdf with  │
                               │                 │ force_reparse   │
                               │                 │ = "true"        │
                               │                 └────────┬────────┘
                               │                          │
                               │                          ▼
                               │                 ┌─────────────────┐
                               │                 │ Backend skips   │
                               │                 │ duplicate check │
                               │                 │ Parses PDF      │
                               │                 └────────┬────────┘
                               │                          │
                               │                          ▼
                               │                 ┌─────────────────┐
                               │                 │ Display chunks  │
                               │                 │ for review      │
                               │                 │ Save to         │
                               │                 │ localStorage    │
                               │                 └────────┬────────┘
                               │                          │
                               │                          ▼
                               │                 ┌─────────────────┐
                               │                 │ User clicks     │
                               │                 │ "Upload to KB"  │
                               │                 └────────┬────────┘
                               │                          │
                               │                          ▼
                               │                 ┌─────────────────┐
                               │                 │ POST /kb/       │
                               │                 │ upload-to-kb    │
                               │                 │ force_replace   │
                               │                 │ = true          │
                               │                 └────────┬────────┘
                               │                          │
                               │                          ▼
                               │                 ┌─────────────────┐
                               │                 │ BACKEND:        │
                               │                 │ Archive version │
                               │                 │ Delete old from │
                               │                 │ SQLite+Weaviate │
                               │                 └────────┬────────┘
                               │                          │
                               │                          ▼
                               │                 ┌─────────────────┐
                               │                 │ Calculate next  │
                               │                 │ version number  │
                               │                 └────────┬────────┘
                               │                          │
                               │                          ▼
                               │                 ┌─────────────────┐
                               │                 │ Delete old doc  │
                               │                 │ from SQLite &   │
                               │                 │ Weaviate        │
                               │                 └────────┬────────┘
                               │                          │
                               │                          ▼
                               │                 ┌─────────────────┐
                               │                 │ Insert new doc  │
                               │                 │ to Weaviate     │
                               │                 │ (with new       │
                               │                 │ embeddings)     │
                               │                 └────────┬────────┘
                               │                          │
                               │                          ▼
                               │                 ┌─────────────────┐
                               │                 │ Save new doc    │
                               │                 │ to SQLite with  │
                               │                 │ new version #   │
                               │                 └────────┬────────┘
                               │                          │
                               │                          ▼
                               │                 ┌─────────────────┐
                               │                 │ Return response │
                               │                 │ with version    │
                               │                 │ info            │
                               │                 └────────┬────────┘
                               │                          │
                               │                          ▼
                               │                 ┌─────────────────┐
                               │                 │ Show Success    │
                               │                 │ Modal with      │
                               │                 │ version details │
                               │                 └────────┬────────┘
                               │                          │
                               └──────────────────────────┤
                                                          │
                                                          ▼
                                                 ┌─────────────────┐
                                                 │      END        │
                                                 └─────────────────┘
```

---

### 3. Query/Search Activity Diagram

```
                                    ┌─────────────────┐
                                    │     START       │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │ User enters     │
                                    │ search query    │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │ POST /chat/send │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │ Generate query  │
                                    │ embedding via   │
                                    │ OpenAI API      │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │ Vector search   │
                                    │ in Weaviate     │
                                    │ (cosine sim.)   │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │ Retrieve top-k  │
                                    │ similar chunks  │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │ Rank & filter   │
                                    │ chunks by       │
                                    │ relevance       │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │ Build context   │
                                    │ from chunks     │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │ Send context +  │
                                    │ query to GPT    │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │ Generate AI     │
                                    │ response        │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │ Return response │
                                    │ to frontend     │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │ Display in      │
                                    │ chat interface  │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │      END        │
                                    └─────────────────┘
```

---

## System Sequence Diagrams

### 1. Document Upload Sequence

```
┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐
│  User    │          │ Frontend │          │ Backend  │          │  SQLite  │          │ Weaviate │
│          │          │ (React)  │          │ (FastAPI)│          │          │          │          │
└────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │                     │                     │
     │ 1. Select PDF       │                     │                     │                     │
     │────────────────────>│                     │                     │                     │
     │                     │                     │                     │                     │
     │                     │ 2. POST /pdf/parse-pdf                    │                     │
     │                     │     (multipart/form-data)                 │                     │
     │                     │────────────────────>│                     │                     │
     │                     │                     │                     │                     │
     │                     │                     │ 3. Calculate SHA256 │                     │
     │                     │                     │    content_hash     │                     │
     │                     │                     │─────────┐           │                     │
     │                     │                     │         │           │                     │
     │                     │                     │<────────┘           │                     │
     │                     │                     │                     │                     │
     │                     │                     │ 4. SELECT by filename & hash             │
     │                     │                     │────────────────────>│                     │
     │                     │                     │                     │                     │
     │                     │                     │ 5. Return: no duplicate                  │
     │                     │                     │<────────────────────│                     │
     │                     │                     │                     │                     │
     │                     │                     │ 6. Parse PDF        │                     │
     │                     │                     │    Extract & chunk  │                     │
     │                     │                     │─────────┐           │                     │
     │                     │                     │         │           │                     │
     │                     │                     │<────────┘           │                     │
     │                     │                     │                     │                     │
     │                     │ 7. Return: {chunks, document_metadata,    │                     │
     │                     │     content_hash, file_size_bytes}        │                     │
     │                     │<────────────────────│                     │                     │
     │                     │                     │                     │                     │
     │ 8. Display chunks   │                     │                     │                     │
     │    preview          │                     │                     │                     │
     │<────────────────────│                     │                     │                     │
     │                     │                     │                     │                     │
     │ 9. Click "Upload    │                     │                     │                     │
     │    to KB"           │                     │                     │                     │
     │────────────────────>│                     │                     │                     │
     │                     │                     │                     │                     │
     │                     │ 10. POST /kb/upload-to-kb                 │                     │
     │                     │     {chunks, metadata, filename,          │                     │
     │                     │      content_hash, file_size_bytes}       │                     │
     │                     │────────────────────>│                     │                     │
     │                     │                     │                     │                     │
     │                     │                     │ 11. Insert Document & DocumentChunks     │
     │                     │                     │────────────────────────────────────────────>
     │                     │                     │                     │                     │
     │                     │                     │ 12. Return: weaviate_doc_id              │
     │                     │                     │<────────────────────────────────────────────
     │                     │                     │                     │                     │
     │                     │                     │ 13. INSERT INTO documents                │
     │                     │                     │────────────────────>│                     │
     │                     │                     │                     │                     │
     │                     │                     │ 14. Return: success │                     │
     │                     │                     │<────────────────────│                     │
     │                     │                     │                     │                     │
     │                     │ 15. Return: {success, doc_id,             │                     │
     │                     │      weaviate_doc_id, action, version}    │                     │
     │                     │<────────────────────│                     │                     │
     │                     │                     │                     │                     │
     │ 16. Show Success    │                     │                     │                     │
     │     Modal           │                     │                     │                     │
     │<────────────────────│                     │                     │                     │
     │                     │                     │                     │                     │
```

---

### 2. Duplicate Override Sequence (Updated)

> **Key Change:** Override now re-parses the PDF before uploading.

```
┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐
│  User    │          │ Frontend │          │ Backend  │          │  SQLite  │          │ Weaviate │
│          │          │ (React)  │          │ (FastAPI)│          │          │          │          │
└────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │                     │                     │
     │ [Duplicate Modal    │                     │                     │                     │
     │  is showing]        │                     │                     │                     │
     │                     │                     │                     │                     │
     │ 1. Click "Override" │                     │                     │                     │
     │────────────────────>│                     │                     │                     │
     │                     │                     │                     │                     │
     │ 2. Show Confirm     │                     │                     │                     │
     │    Modal            │                     │                     │                     │
     │<────────────────────│                     │                     │                     │
     │                     │                     │                     │                     │
     │ 3. Click "Yes,      │                     │                     │                     │
     │    Override"        │                     │                     │                     │
     │────────────────────>│                     │                     │                     │
     │                     │                     │                     │                     │
     │                     │ 4. Close modals, set forceReplaceMode=true                      │
     │                     │─────────┐           │                     │                     │
     │                     │         │           │                     │                     │
     │                     │<────────┘           │                     │                     │
     │                     │                     │                     │                     │
     │                     │ 5. POST /pdf/parse-pdf                    │                     │
     │                     │    {file, force_reparse: "true"}          │                     │
     │                     │────────────────────>│                     │                     │
     │                     │                     │                     │                     │
     │                     │                     │ 6. Skip duplicate check (force_reparse)  │
     │                     │                     │    Parse PDF, create chunks               │
     │                     │                     │─────────┐           │                     │
     │                     │                     │         │           │                     │
     │                     │                     │<────────┘           │                     │
     │                     │                     │                     │                     │
     │                     │ 7. Return: {chunks, document_metadata,    │                     │
     │                     │     content_hash, file_size_bytes}        │                     │
     │                     │<────────────────────│                     │                     │
     │                     │                     │                     │                     │
     │                     │ 8. Save to localStorage                   │                     │
     │                     │    Display chunks for review              │                     │
     │                     │─────────┐           │                     │                     │
     │                     │<────────┘           │                     │                     │
     │                     │                     │                     │                     │
     │ 9. Review/edit      │                     │                     │                     │
     │    chunks           │                     │                     │                     │
     │<────────────────────│                     │                     │                     │
     │                     │                     │                     │                     │
     │ 10. Click "Upload   │                     │                     │                     │
     │     to KB"          │                     │                     │                     │
     │────────────────────>│                     │                     │                     │
     │                     │                     │                     │                     │
     │                     │ 11. POST /kb/upload-to-kb                 │                     │
     │                     │    {chunks, ..., force_replace: true}     │                     │
     │                     │────────────────────>│                     │                     │
     │                     │                     │                     │                     │
     │                     │                     │ 12. SELECT existing doc by filename      │
     │                     │                     │────────────────────>│                     │
     │                     │                     │                     │                     │
     │                     │                     │ 13. Return existing doc (with weaviate_doc_id)
     │                     │                     │<────────────────────│                     │
     │                     │                     │                     │                     │
     │                     │                     │ 14. INSERT INTO document_versions        │
     │                     │                     │    (archive current version)             │
     │                     │                     │────────────────────>│                     │
     │                     │                     │                     │                     │
     │                     │                     │ 15. DELETE FROM documents (old doc)      │
     │                     │                     │────────────────────>│                     │
     │                     │                     │                     │                     │
     │                     │                     │ 16. DELETE Document & Chunks using       │
     │                     │                     │     weaviate_doc_id (NOT doc_id)         │
     │                     │                     │────────────────────────────────────────────>
     │                     │                     │                     │                     │
     │                     │                     │ 17. INSERT new Document & Chunks         │
     │                     │                     │────────────────────────────────────────────>
     │                     │                     │                     │                     │
     │                     │                     │ 18. Return: new weaviate_doc_id          │
     │                     │                     │<────────────────────────────────────────────
     │                     │                     │                     │                     │
     │                     │                     │ 19. INSERT INTO documents                │
     │                     │                     │     (new doc with new version)           │
     │                     │                     │────────────────────>│                     │
     │                     │                     │                     │                     │
     │                     │ 20. Return: {success, doc_id, action:"replaced",               │
     │                     │     version: 2, version_info: {previous_version: {...}}}       │
     │                     │<────────────────────│                     │                     │
     │                     │                     │                     │                     │
     │                     │ 21. Clear localStorage                    │                     │
     │                     │─────────┐           │                     │                     │
     │                     │<────────┘           │                     │                     │
     │                     │                     │                     │                     │
     │ 22. Show Success    │                     │                     │                     │
     │     Modal with      │                     │                     │                     │
     │     version info    │                     │                     │                     │
     │<────────────────────│                     │                     │                     │
     │                     │                     │                     │                     │
```

---

### 3. Version History Retrieval Sequence

```
┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐
│  User    │          │ Frontend │          │ Backend  │          │  SQLite  │
│          │          │ (React)  │          │ (FastAPI)│          │          │
└────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │                     │
     │ 1. Click "View      │                     │                     │
     │    Version History" │                     │                     │
     │────────────────────>│                     │                     │
     │                     │                     │                     │
     │                     │ 2. GET /kb/document-versions/{file_name}  │
     │                     │────────────────────>│                     │
     │                     │                     │                     │
     │                     │                     │ 3. SELECT FROM documents                 │
     │                     │                     │    WHERE file_name = ?                   │
     │                     │                     │────────────────────>│
     │                     │                     │                     │
     │                     │                     │ 4. Return current_doc                    │
     │                     │                     │<────────────────────│
     │                     │                     │                     │
     │                     │                     │ 5. SELECT FROM document_versions         │
     │                     │                     │    WHERE file_name = ?                   │
     │                     │                     │    ORDER BY version_number DESC          │
     │                     │                     │────────────────────>│
     │                     │                     │                     │
     │                     │                     │ 6. Return versions []                    │
     │                     │                     │<────────────────────│
     │                     │                     │                     │
     │                     │ 7. Return: {success, file_name,           │
     │                     │     current_version: {...},               │
     │                     │     version_history: [...],               │
     │                     │     total_versions: N}                    │
     │                     │<────────────────────│                     │
     │                     │                     │                     │
     │ 8. Show Version     │                     │                     │
     │    History Modal    │                     │                     │
     │<────────────────────│                     │                     │
     │                     │                     │                     │
```

---

### 4. Document Search Sequence

```
┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐
│  User    │          │ Frontend │          │ Backend  │          │  OpenAI  │          │ Weaviate │
│          │          │ (React)  │          │ (FastAPI)│          │   API    │          │          │
└────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │                     │                     │
     │ 1. Enter search     │                     │                     │                     │
     │    query            │                     │                     │                     │
     │────────────────────>│                     │                     │                     │
     │                     │                     │                     │                     │
     │                     │ 2. POST /chat/send  │                     │                     │
     │                     │    {query: "..."}   │                     │                     │
     │                     │────────────────────>│                     │                     │
     │                     │                     │                     │                     │
     │                     │                     │ 3. POST /v1/embeddings                   │
     │                     │                     │    {model: "text-embedding-3-small",     │
     │                     │                     │     input: "user query"}                 │
     │                     │                     │────────────────────>│                     │
     │                     │                     │                     │                     │
     │                     │                     │ 4. Return: embedding                     │
     │                     │                     │    [1536 floats]    │                     │
     │                     │                     │<────────────────────│                     │
     │                     │                     │                     │                     │
     │                     │                     │ 5. nearVector search in                  │
     │                     │                     │    DocumentChunk collection              │
     │                     │                     │────────────────────────────────────────────>
     │                     │                     │                     │                     │
     │                     │                     │ 6. Return: top-k chunks                  │
     │                     │                     │    with similarity scores                │
     │                     │                     │<────────────────────────────────────────────
     │                     │                     │                     │                     │
     │                     │                     │ 7. Build context from chunks             │
     │                     │                     │─────────┐           │                     │
     │                     │                     │         │           │                     │
     │                     │                     │<────────┘           │                     │
     │                     │                     │                     │                     │
     │                     │                     │ 8. POST /v1/chat/completions             │
     │                     │                     │    {messages: [system, context, query]}  │
     │                     │                     │────────────────────>│                     │
     │                     │                     │                     │                     │
     │                     │                     │ 9. Return: AI response                   │
     │                     │                     │<────────────────────│                     │
     │                     │                     │                     │                     │
     │                     │ 10. Return: {response, chunks_used}       │                     │
     │                     │<────────────────────│                     │                     │
     │                     │                     │                     │                     │
     │ 11. Display AI      │                     │                     │                     │
     │     response in chat│                     │                     │                     │
     │<────────────────────│                     │                     │                     │
     │                     │                     │                     │                     │
```

---

## Legend

### Activity Diagram Symbols

| Symbol | Meaning |
|--------|---------|
| `┌────┐` / `└────┘` | Activity/Action node |
| `◇────◇` | Decision diamond |
| `[YES]` / `[NO]` | Decision branch labels |
| `────>` | Flow direction |
| `START` / `END` | Start/End nodes |

### Sequence Diagram Symbols

| Symbol | Meaning |
|--------|---------|
| `│` | Lifeline |
| `────>` | Synchronous message |
| `<────` | Return message |
| `─────┐` `│` `<────┘` | Self-call (internal processing) |

---

*See [DOCUEXTRACT_ARCHITECTURE.md](./DOCUEXTRACT_ARCHITECTURE.md) for detailed architecture documentation.*

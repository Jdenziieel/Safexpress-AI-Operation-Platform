# Chapter 4: System Architecture & Design

**Document Version**: 1.0  
**Date**: November 24, 2025  
**System**: Knowledge Base Management System with AI-Powered Chat

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Use Case Diagrams](#2-use-case-diagrams)
3. [System Requirements](#3-system-requirements)
4. [System Sequence Diagrams](#4-system-sequence-diagrams)
5. [Database Design](#5-database-design)
6. [Network Architecture](#6-network-architecture)
7. [Security Architecture](#7-security-architecture)

---

## 1. System Overview

### 1.1 System Purpose

The Knowledge Base Management System is an AI-powered document management and chat system that enables users to:
- Upload and process PDF documents with AI-powered chunking
- Store documents in a vector database for semantic search
- Query documents through an intelligent chatbot interface
- Manage chat sessions with conversation history
- Track document uploads and prevent duplicates

### 1.2 Technology Stack

**Backend**:
- **Framework**: FastAPI (Python 3.x)
- **Web Server**: Uvicorn ASGI server
- **Databases**: 
  - SQLite (Chat sessions, Document metadata)
  - Weaviate Cloud (Vector database for semantic search)
- **AI Services**: OpenAI GPT-4o, text-embedding-3-small
- **Authentication**: JWT (JSON Web Tokens) with HS256

**Frontend**:
- **Framework**: React 18.x with Vite
- **Routing**: React Router v6
- **HTTP Client**: Axios
- **UI Components**: Lucide React Icons
- **Styling**: CSS Modules

**Infrastructure**:
- **Port**: 8009 (Backend), 5173 (Frontend Dev)
- **CORS**: Configured for localhost development
- **File Processing**: PyMuPDF, pdf2image, pytesseract

### 1.3 System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT LAYER                              │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  React Frontend (Port 5173)                              │   │
│  │  - Document Upload Interface                             │   │
│  │  - Chat Interface (SFXBot)                               │   │
│  │  - Document Processing History                           │   │
│  └──────────────────────────────────────────────────────────┘   │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTPS/REST API
                             │ JWT Authentication
┌────────────────────────────┴────────────────────────────────────┐
│                    API GATEWAY LAYER                             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  FastAPI Application (Port 8009)                         │   │
│  │  - CORS Middleware                                       │   │
│  │  - Security Headers Middleware                           │   │
│  │  - Rate Limiting Middleware                              │   │
│  │  - JWT Authentication Middleware                         │   │
│  └──────────────────────────────────────────────────────────┘   │
└────────────────────────────┬────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
┌───────▼────────┐  ┌───────▼────────┐  ┌───────▼────────┐
│  PDF Routes    │  │  KB Routes     │  │  Chat Routes   │
│  /pdf/*        │  │  /kb/*         │  │  /chat/*       │
└───────┬────────┘  └───────┬────────┘  └───────┬────────┘
        │                    │                    │
┌───────▼────────────────────▼────────────────────▼────────┐
│                    SERVICE LAYER                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ PDF Service  │  │ Weaviate     │  │ Chat Service │   │
│  │              │  │ Service      │  │              │   │
│  ├──────────────┤  ├──────────────┤  ├──────────────┤   │
│  │ Chunking     │  │ OpenAI       │  │ Query        │   │
│  │ Service      │  │ Service      │  │ Processor    │   │
│  ├──────────────┤  ├──────────────┤  ├──────────────┤   │
│  │ Anchoring    │  │ Weaviate     │  │ Context      │   │
│  │ Service      │  │ Search Svc   │  │ Manager      │   │
│  └──────────────┘  └──────────────┘  └──────────────┘   │
└────────────────────────┬──────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
┌───────▼────────┐  ┌───▼────────┐  ┌───▼────────────┐
│ SQLite DBs     │  │ Weaviate   │  │ OpenAI API     │
│ - chat_        │  │ Cloud      │  │ - GPT-4o       │
│   sessions.db  │  │ - Document │  │ - Embeddings   │
│ - documents.db │  │ - Knowledge│  │ - Vision       │
│                │  │   Base     │  │                │
└────────────────┘  └────────────┘  └────────────────┘
```

---

## 2. Use Case Diagrams

### 2.1 Primary Actors

1. **End User** - Person using the system to upload documents and ask questions
2. **System Administrator** - Manages system configuration and monitoring
3. **OpenAI Service** - External AI service for embeddings and responses
4. **Weaviate Service** - External vector database service

### 2.2 Use Case Diagram: Document Management

```
                    ┌─────────────────────────────────┐
                    │  Document Management System     │
                    │                                 │
┌──────────┐        │  ┌──────────────────────────┐  │
│          │        │  │  Upload PDF Document     │  │
│          │◄───────┼──┤  - Validate file type    │  │
│          │        │  │  - Check duplicates      │  │
│  End     │        │  │  - Extract content       │  │
│  User    │        │  └──────────────────────────┘  │
│          │        │           │                     │
│          │        │           │ includes            │
│          │        │           ▼                     │
│          │        │  ┌──────────────────────────┐  │
│          │◄───────┼──┤  Process with AI         │  │
│          │        │  │  - Two-pass chunking     │  │
│          │        │  │  - Image analysis        │  │
│          │        │  │  - Semantic tagging      │  │
│          │        │  └──────────────────────────┘  │
│          │        │           │                     │
│          │        │           │ includes            │
│          │        │           ▼                     │
│          │        │  ┌──────────────────────────┐  │
│          │◄───────┼──┤  Upload to KB            │  │
│          │        │  │  - Store in Weaviate     │  │
│          │        │  │  - Save metadata         │  │
│          │        │  │  - Track upload          │  │
│          │        │  └──────────────────────────┘  │
│          │        │           │                     │
│          │        │           │ extends             │
│          │        │           ▼                     │
│          │        │  ┌──────────────────────────┐  │
│          │◄───────┼──┤  View Processing History │  │
│          │        │  │  - List documents        │  │
│          │        │  │  - Filter by user        │  │
│          │        │  │  - Sort & paginate       │  │
│          │        │  └──────────────────────────┘  │
│          │        │           │                     │
│          │        │           │ extends             │
│          │        │           ▼                     │
│          │◄───────┼──┤  Delete Document         │  │
└──────────┘        │  │  - Remove from Weaviate  │  │
                    │  │  - Delete metadata       │  │
                    │  └──────────────────────────┘  │
                    │                                 │
                    └─────────────────────────────────┘
```

### 2.3 Use Case Diagram: Chat System

```
                    ┌─────────────────────────────────┐
                    │      Chat System                │
                    │                                 │
┌──────────┐        │  ┌──────────────────────────┐  │
│          │        │  │  Create Chat Session     │  │
│          │◄───────┼──┤  - Generate session ID   │  │
│          │        │  │  - Auto-title from msg   │  │
│  End     │        │  └──────────────────────────┘  │
│  User    │        │           │                     │
│          │        │           │ includes            │
│          │        │           ▼                     │
│          │        │  ┌──────────────────────────┐  │
│          │◄───────┼──┤  Send Message            │  │
│          │        │  │  - Process query         │  │
│          │        │  │  - Search knowledge base │  │
│          │        │  │  - Generate AI response  │  │
│          │        │  └──────────────────────────┘  │
│          │        │           │                     │
│          │        │           │ includes            │
│          │        │           ▼                     │
│          │        │  ┌──────────────────────────┐  │
│          │◄───────┼──┤  View Chat History       │  │
│          │        │  │  - Load messages         │  │
│          │        │  │  - Display sources       │  │
│          │        │  └──────────────────────────┘  │
│          │        │           │                     │
│          │        │           │ extends             │
│          │        │           ▼                     │
│          │        │  ┌──────────────────────────┐  │
│          │◄───────┼──┤  Manage Sessions         │  │
│          │        │  │  - List all sessions     │  │
│          │        │  │  - Edit title            │  │
│          │        │  │  - Delete session        │  │
│          │        │  │  - View token usage      │  │
│          │        │  └──────────────────────────┘  │
│          │        │           │                     │
│          │        │           │ extends             │
│          │        │           ▼                     │
│          │◄───────┼──┤  Switch Thread           │  │
└──────────┘        │  │  - Load conversation     │  │
                    │  │  - Update context        │  │
                    │  └──────────────────────────┘  │
                    │                                 │
                    └─────────────────────────────────┘
```

---

## 3. System Requirements

### 3.1 Functional Requirements

#### FR-1: Document Upload & Processing
- **FR-1.1**: System shall accept PDF files up to 10MB
- **FR-1.2**: System shall validate file type (PDF only)
- **FR-1.3**: System shall detect duplicate documents by filename and content hash
- **FR-1.4**: System shall extract text, tables, and images from PDFs
- **FR-1.5**: System shall process documents using two-pass AI chunking (text + images)
- **FR-1.6**: System shall generate semantic metadata (section, context, tags) for each chunk
- **FR-1.7**: System shall store chunks in Weaviate vector database with embeddings

#### FR-2: Knowledge Base Management
- **FR-2.1**: System shall maintain document metadata in SQLite database
- **FR-2.2**: System shall track uploaded_by, upload_date, file_size, and chunk count
- **FR-2.3**: System shall allow users to view processing history with pagination
- **FR-2.4**: System shall support filtering by uploader and sorting by date
- **FR-2.5**: System shall allow deletion of documents from knowledge base
- **FR-2.6**: System shall prevent duplicate uploads (409 Conflict response)

#### FR-3: Chat System
- **FR-3.1**: System shall create chat sessions with unique session IDs
- **FR-3.2**: System shall auto-generate session titles from first user message
- **FR-3.3**: System shall allow users to manually edit session titles
- **FR-3.4**: System shall store all messages (user and assistant) with timestamps
- **FR-3.5**: System shall perform hybrid search (semantic + keyword) on knowledge base
- **FR-3.6**: System shall use OpenAI GPT-4o for response generation
- **FR-3.7**: System shall provide source citations with page numbers
- **FR-3.8**: System shall maintain conversation context for follow-up questions
- **FR-3.9**: System shall track token usage and costs per session
- **FR-3.10**: System shall allow deletion of chat sessions

#### FR-4: Authentication & Authorization
- **FR-4.1**: System shall authenticate users via JWT tokens
- **FR-4.2**: System shall verify JWT signatures using shared secret key
- **FR-4.3**: System shall extract user identity (name, user_id) from JWT payload
- **FR-4.4**: System shall enforce session ownership (users can only access their sessions)
- **FR-4.5**: System shall support optional authentication for document uploads

#### FR-5: Search & Query
- **FR-5.1**: System shall support hybrid search (vector + BM25)
- **FR-5.2**: System shall rerank results using OpenAI
- **FR-5.3**: System shall handle follow-up questions with reference resolution
- **FR-5.4**: System shall expand queries with context from conversation history
- **FR-5.5**: System shall filter results by document names (optional)

### 3.2 Non-Functional Requirements

#### NFR-1: Performance
- **NFR-1.1**: API response time shall be < 2 seconds for document list queries
- **NFR-1.2**: PDF parsing shall complete within 30 seconds for documents < 10MB
- **NFR-1.3**: Chat responses shall be generated within 5 seconds
- **NFR-1.4**: System shall support 100 concurrent users
- **NFR-1.5**: Vector search shall return results within 1 second

#### NFR-2: Scalability
- **NFR-2.1**: System shall support up to 10,000 documents in knowledge base
- **NFR-2.2**: System shall handle 1,000 chat sessions per user
- **NFR-2.3**: Weaviate shall support millions of chunks

#### NFR-3: Security
- **NFR-3.1**: All API endpoints shall use HTTPS in production
- **NFR-3.2**: JWT tokens shall have 24-hour expiration
- **NFR-3.3**: Passwords/secrets shall not be logged or exposed
- **NFR-3.4**: Rate limiting shall prevent abuse (configurable)
- **NFR-3.5**: Security headers shall be applied to all responses
- **NFR-3.6**: File uploads shall be sanitized to prevent directory traversal
- **NFR-3.7**: SQL injection shall be prevented via parameterized queries

#### NFR-4: Reliability
- **NFR-4.1**: System uptime shall be 99.5%
- **NFR-4.2**: Database backups shall be automated daily
- **NFR-4.3**: System shall handle OpenAI API failures gracefully
- **NFR-4.4**: Weaviate connection shall auto-reconnect on failure

#### NFR-5: Usability
- **NFR-5.1**: Chat interface shall be similar to ChatGPT
- **NFR-5.2**: Document upload shall provide visual feedback (progress bars)
- **NFR-5.3**: Error messages shall be user-friendly and actionable
- **NFR-5.4**: Session titles shall auto-update from first message

#### NFR-6: Maintainability
- **NFR-6.1**: Code shall follow PEP 8 style guidelines
- **NFR-6.2**: All functions shall have docstrings
- **NFR-6.3**: API endpoints shall be versioned
- **NFR-6.4**: Logging shall be comprehensive for debugging

### 3.3 System Constraints

- **C-1**: System requires external OpenAI API access
- **C-2**: System requires Weaviate Cloud instance
- **C-3**: PDF processing requires system OCR capabilities (tesseract)
- **C-4**: System runs on Python 3.8+
- **C-5**: Frontend requires modern browser (ES6+ support)
- **C-6**: JWT secret key must be shared between authentication server and this system

---

## 4. System Sequence Diagrams

### 4.1 Document Upload Flow

```
User          Frontend       PDF Routes     PDF Service    Chunking Svc   Doc DB    Weaviate    OpenAI
 │                │               │              │              │            │          │          │
 │─Select PDF────>│               │              │              │            │          │          │
 │                │               │              │              │            │          │          │
 │                │─POST /pdf/───>│              │              │            │          │          │
 │                │  parse-pdf    │              │              │            │          │          │
 │                │               │              │              │            │          │          │
 │                │               │─Read file───>│              │            │          │          │
 │                │               │  bytes       │              │            │          │          │
 │                │               │              │              │            │          │          │
 │                │               │              │─Calculate───>│            │          │          │
 │                │               │              │  hash        │            │          │          │
 │                │               │              │              │            │          │          │
 │                │               │              │─Check────────────────────>│          │          │
 │                │               │              │  duplicate                │          │          │
 │                │               │              │                           │          │          │
 │                │               │              │<──No duplicate────────────┤          │          │
 │                │               │              │              │            │          │          │
 │                │               │              │─Extract text/tables──────>│          │          │
 │                │               │              │  & images   │             │          │          │
 │                │               │              │             │             │          │          │
 │                │               │              │─Process text───────────────────────────────────>│
 │                │               │              │  (1st pass)                          │          │
 │                │               │              │                                      │          │
 │                │               │              │<──Structured chunks─────────────────────────────┤
 │                │               │              │                                      │          │
 │                │               │              │─Process images─────────────────────────────────>│
 │                │               │              │  (2nd pass)                          │          │
 │                │               │              │                                      │          │
 │                │               │              │<──Image descriptions────────────────────────────┤
 │                │               │              │               │                      │          │
 │                │               │              │─Merge chunks─>│           │          │          │
 │                │               │              │               │           │          │          │
 │                │               │<──Chunks + metadata──────────┤           │          │          │
 │                │               │                                          │          │          │
 │                │<──200 OK──────┤                                          │          │          │
 │                │  chunks[]     │                                          │          │          │
 │                │               │                                          │          │          │
 │<─Display chunks┤               │                                          │          │          │
 │                │               │                                          │          │          │
 │─Click "Upload─>│               │                                          │          │          │
 │  to KB"        │               │                                          │          │          │
 │                │               │                                          │          │          │
 │                │─POST /kb/──────────────────────────────────>│            │          │          │
 │                │  upload-to-kb │              │              │            │          │          │
 │                │               │              │              │            │          │          │
 │                │               │              │<─Save document metadata───┤          │          │
 │                │               │              │                           │          │          │
 │                │               │              │─Insert chunks───────────────────────>│          │
 │                │               │              │  with embeddings          │          │          │
 │                │               │              │                           │          │<─Generate─┤
 │                │               │              │                           │          │  embeddings│
 │                │               │              │                           │          │          │
 │                │               │              │<──Success────────────────────────────┤          │
 │                │               │              │                           │          │          │
 │                │<──200 OK───────────────────────────────────┤             │          │          │
 │                │  doc_id, action                            │             │          │          │
 │                │               │                            │             │          │          │
 │<─Show success──┤               │                            │             │          │          │
 │  modal         │               │                            │             │          │          │
```

### 4.2 Chat Message Flow

```
User       Frontend    Chat Routes   Chat Svc   Query Proc  Weaviate Srch  Context Mgr  Chat DB  Weaviate  OpenAI
 │             │            │            │           │            │             │          │         │        │
 │─Type msg───>│            │            │           │            │             │          │         │        │
 │             │            │            │           │            │             │          │         │        │
 │             │─POST /chat/message─────>│           │            │             │          │         │        │
 │             │            │            │           │            │             │          │         │        │
 │             │            │            │─Validate ownership─────────────────────────────>│         │        │
 │             │            │            │                        │             │          │         │        │
 │             │            │            │─Save user msg──────────────────────────────────>│         │        │
 │             │            │            │                        │             │          │         │        │
 │             │            │            │─Get conversation context───────────────────────>│         │        │
 │             │            │            │                        │             │          │         │        │
 │             │            │            │<──Recent messages──────────────────────── ──────┤         │        │
 │             │            │            │                        │             │          │         │        │
 │             │            │            │─Process query─────────>│            │             │          │         │        │
 │             │            │            │                        │            │             │          │         │        │
 │             │            │            │                        │─Expand query─────────────────────────────────>│
 │             │            │            │                        │  with context│           │          │         │        │
 │             │            │            │                        │            │             │          │         │        │
 │             │            │            │                        │<──Enhanced query────────────────────────│─────┤
 │             │            │            │                        │            │             │          │         │        │
 │             │            │            │<──Processed query──────┤            │             │          │         │        │
 │             │            │            │                        │            │             │          │         │        │
 │             │            │            │─Hybrid search──────────────────────>│             │          │         │        │
 │             │            │            │                        │            │             │          │         │        │
 │             │            │            │                        │            │─Query KB─────────────────>│        │
 │             │            │            │                        │            │             │          │         │        │
 │             │            │            │                        │            │<──Chunks (vector+BM25)────┤        │
 │             │            │            │                        │            │             │          │         │        │
 │             │            │            │                        │            │─Rerank───────────────────────────────────>│
 │             │            │            │                        │            │             │          │         │        │
 │             │            │            │                        │            │<──Scores──────────────────────────────────┤
 │             │            │            │                        │            │             │          │         │        │
 │             │            │            │<──Top chunks────────────────────────┤             │          │         │        │
 │             │            │            │                        │            │             │          │         │        │
 │             │            │            │─Build KB context─────────────────────────────────>│          │         │        │
 │             │            │            │                        │            │             │          │         │        │
 │             │            │            │<──Formatted context───────────────────────────────┤          │         │        │
 │             │            │            │                        │            │             │          │         │        │
 │             │            │            │─Generate response──────────────────────────────────────────────────────────────>│
 │             │            │            │  (system prompt +                   │             │          │         │        │
 │             │            │            │   KB context +                      │             │          │         │        │
 │             │            │            │   conversation +                    │             │          │         │        │
 │             │            │            │   user message)                     │             │          │         │        │
 │             │            │            │                        │            │             │          │         │        │
 │             │            │            │<──AI response with citations───────────────────────────────────────────────────┤
 │             │            │            │                        │            │             │          │         │        │
 │             │            │            │─Save assistant msg──────────────────────── ─────────────────>│         │        │
 │             │            │            │  with sources          │            │             │          │         │        │
 │             │            │            │                        │            │             │          │         │        │
 │             │            │            │─Update session───────────────────────────────── ────────────>│         │        │
 │             │            │            │  title (if 1st msg)    │            │             │          │         │        │
 │             │            │            │                        │            │             │          │         │        │
 │             │            │            │─Track tokens───────────────────────── ──────────────────────>│         │        │
 │             │            │            │                        │            │             │          │         │        │
 │             │            │<──Response with sources───────── ───┤            │             │          │         │        │
 │             │            │            │                        │            │             │          │         │        │
 │             │<──200 OK with message───┤                        │            │             │          │         │        │
 │             │            │                                     │            │             │          │         │        │
 │<─Display────┤            │                                     │            │             │          │         │        │
 │  response   │            │                                     │            │             │          │         │        │
```

### 4.3 Session Management Flow

```
User       Frontend    Chat Routes    Chat Service    Chat DB
 │             │            │               │            │
 │─Create new─>│            │               │            │
 │  session    │            │               │            │
 │             │            │               │            │
 │             │─POST /chat/session/new────>│            │
 │             │            │               │            │
 │             │            │               │─Create────>│
 │             │            │               │  session   │
 │             │            │               │  (UUID)    │
 │             │            │               │            │
 │             │            │               │<──session──┤
 │             │            │               │   data     │
 │             │            │               │            │
 │             │            │<──session_id──┤            │
 │             │            │               │            │
 │             │<──200 OK───┤               │            │
 │             │  session_id│               │            │
 │             │            │               │            │
 │<─Switch to──┤            │               │            │
 │  new thread │            │               │            │
 │             │            │               │            │
 │─View all────>│            │               │            │
 │  sessions   │            │               │            │
 │             │            │               │            │
 │             │─GET /chat/sessions──────────>│            │
 │             │            │               │            │
 │             │            │               │─Get user───>│
 │             │            │               │  sessions  │
 │             │            │               │            │
 │             │            │               │<──sessions─┤
 │             │            │               │   list     │
 │             │            │               │            │
 │             │            │<──sessions────┤            │
 │             │            │               │            │
 │             │<──200 OK───┤               │            │
 │             │  sessions[]│               │            │
 │             │            │               │            │
 │<─Display────┤            │               │            │
 │  sidebar    │            │               │            │
 │             │            │               │            │
 │─Edit title──>│            │               │            │
 │             │            │               │            │
 │             │─PATCH /chat/session/{id}/title──>│      │
 │             │            │               │            │
 │             │            │               │─Validate───>│
 │             │            │               │  ownership │
 │             │            │               │            │
 │             │            │               │─Update─────>│
 │             │            │               │  title     │
 │             │            │               │            │
 │             │            │               │<──success──┤
 │             │            │               │            │
 │             │            │<──200 OK──────┤            │
 │             │            │               │            │
 │             │<──success──┤               │            │
 │             │            │               │            │
 │<─Update UI──┤            │               │            │
```

### 4.4 Authentication Flow

```
User       Frontend    Auth Server    Chat Routes    JWT Middleware
 │             │            │               │                │
 │─Login───────>│            │               │                │
 │             │            │               │                │
 │             │─POST /auth/login────────────>│                │
 │             │            │               │                │
 │             │            │<──JWT token───┤                │
 │             │            │               │                │
 │             │<──Store────┤               │                │
 │             │  in localStorage            │                │
 │             │            │               │                │
 │─Access chat─>│            │               │                │
 │             │            │               │                │
 │             │─POST /chat/message──────────>│                │
 │             │  Authorization:             │                │
 │             │  Bearer <token>             │                │
 │             │            │               │                │
 │             │            │               │─Verify JWT─────>│
 │             │            │               │                │
 │             │            │               │                │─Decode token
 │             │            │               │                │─Verify signature
 │             │            │               │                │─Check expiration
 │             │            │               │                │─Extract user_id
 │             │            │               │                │
 │             │            │               │<──current_user─┤
 │             │            │               │                │
 │             │            │               │─Process────────────────>│
 │             │            │               │  request       │        │
 │             │            │               │  with user_id  │        │
 │             │            │               │                │        │
 │             │            │<──Response────┤                │        │
 │             │            │               │                │        │
 │             │<──200 OK───┤               │                │        │
 │             │            │               │                │        │
 │─Token expires────────────────────────────────────────────────────>│
 │             │            │               │                │        │
 │             │─Request─────────────────────>│                │        │
 │             │  (expired token)            │                │        │
 │             │            │               │                │        │
 │             │            │               │─Verify JWT─────>│        │
 │             │            │               │                │        │
 │             │            │               │<──401 Error────┤        │
 │             │            │               │  (Expired)     │        │
 │             │            │               │                │        │
 │             │<──401──────┤               │                │        │
 │             │            │               │                │        │
 │<─Redirect───┤            │               │                │        │
 │  to login   │            │               │                │        │
```

---

## 5. Database Design

### 5.1 Database Overview

The system uses a hybrid database architecture:
- **SQLite** (2 databases): Relational data for chat and document metadata
- **Weaviate Cloud**: Vector database for semantic search

### 5.2 SQLite Database: chat_sessions.db

#### 5.2.1 Sessions Table

```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,          -- UUID v4
    user_id TEXT NOT NULL,                -- From JWT token
    title TEXT,                           -- Auto-generated or manual
    created_at TEXT NOT NULL,             -- ISO 8601 timestamp
    updated_at TEXT NOT NULL,             -- ISO 8601 timestamp
    message_count INTEGER DEFAULT 0,      -- Count of messages
    total_tokens_used INTEGER DEFAULT 0,  -- Cumulative tokens
    total_cost_usd REAL DEFAULT 0.0,      -- Cumulative cost
    last_token_update TEXT,               -- Last token tracking time
    metadata TEXT                         -- JSON: additional data
);

CREATE INDEX idx_session_user ON sessions(user_id);
```

**Sample Data**:
```json
{
  "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_id": "user123",
  "title": "What are the company policies on remote work?",
  "created_at": "2025-11-24T10:30:00Z",
  "updated_at": "2025-11-24T10:35:00Z",
  "message_count": 5,
  "total_tokens_used": 2500,
  "total_cost_usd": 0.0375,
  "last_token_update": "2025-11-24T10:35:00Z",
  "metadata": "{}"
}
```

#### 5.2.2 Messages Table

```sql
CREATE TABLE messages (
    message_id TEXT PRIMARY KEY,          -- UUID v4
    session_id TEXT NOT NULL,             -- Foreign key
    role TEXT NOT NULL,                   -- 'user' | 'assistant' | 'system'
    content TEXT NOT NULL,                -- Message text
    timestamp TEXT NOT NULL,              -- ISO 8601 timestamp
    sources TEXT,                         -- JSON: array of source chunks
    metadata TEXT,                        -- JSON: tokens, processing time
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE INDEX idx_message_session ON messages(session_id);
CREATE INDEX idx_message_timestamp ON messages(timestamp);
```

**Sample Data**:
```json
{
  "message_id": "msg-123",
  "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "role": "user",
  "content": "What are the company policies on remote work?",
  "timestamp": "2025-11-24T10:30:00Z",
  "sources": null,
  "metadata": "{}"
},
{
  "message_id": "msg-124",
  "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "role": "assistant",
  "content": "According to the employee handbook, the company offers...",
  "timestamp": "2025-11-24T10:30:05Z",
  "sources": "[{\"chunk_id\":\"chunk-789\",\"document_name\":\"handbook.pdf\",\"page\":5}]",
  "metadata": "{\"tokens\":450,\"processing_time_ms\":3200}"
}
```

### 5.3 SQLite Database: documents.db

#### 5.3.1 Documents Table

```sql
CREATE TABLE documents (
    doc_id TEXT PRIMARY KEY,              -- UUID v4
    file_name TEXT NOT NULL,              -- Original filename
    upload_date TEXT NOT NULL,            -- ISO 8601 timestamp
    file_size_bytes INTEGER NOT NULL,     -- File size
    chunks INTEGER NOT NULL,              -- Number of chunks
    uploaded_by TEXT,                     -- User name from JWT
    content_hash TEXT UNIQUE NOT NULL,    -- SHA256 hash
    page_count INTEGER,                   -- Number of pages
    weaviate_doc_id TEXT,                 -- Weaviate Document UUID
    metadata TEXT                         -- JSON: additional data
);

CREATE UNIQUE INDEX idx_file_name ON documents(file_name);
CREATE UNIQUE INDEX idx_content_hash ON documents(content_hash);
CREATE INDEX idx_uploaded_by ON documents(uploaded_by);
CREATE INDEX idx_upload_date ON documents(upload_date);
```

**Sample Data**:
```json
{
  "doc_id": "doc-456",
  "file_name": "employee_handbook.pdf",
  "upload_date": "2025-11-24T09:00:00Z",
  "file_size_bytes": 2621440,
  "chunks": 25,
  "uploaded_by": "John Doe",
  "content_hash": "a3f5b8c2d9e1f0a4b7c5d8e2f1a0b3c6d9e2f5a8b1c4d7e0f3a6b9c2d5e8f1a4",
  "page_count": 50,
  "weaviate_doc_id": "d7e8f9a0-b1c2-3d4e-5f6a-7b8c9d0e1f2a",
  "metadata": "{\"total_pages\":50,\"total_chunks\":25}"
}
```

### 5.4 Weaviate Collections

#### 5.4.1 Document Collection

```python
{
  "class": "Document",
  "description": "Parent document metadata",
  "properties": [
    {
      "name": "file_name",
      "dataType": ["text"],
      "description": "Original PDF filename"
    },
    {
      "name": "upload_date",
      "dataType": ["text"],
      "description": "ISO 8601 upload timestamp"
    },
    {
      "name": "page_count",
      "dataType": ["int"],
      "description": "Total pages in document"
    },
    {
      "name": "chunk_count",
      "dataType": ["int"],
      "description": "Total chunks created"
    }
  ]
}
```

#### 5.4.2 KnowledgeBase Collection

```python
{
  "class": "KnowledgeBase",
  "description": "Document chunks with semantic search",
  "vectorizer": "text2vec-openai",
  "moduleConfig": {
    "text2vec-openai": {
      "model": "text-embedding-3-small",
      "dimensions": 1536,
      "type": "text"
    }
  },
  "properties": [
    {
      "name": "chunk_id",
      "dataType": ["text"],
      "description": "Unique chunk identifier"
    },
    {
      "name": "text",
      "dataType": ["text"],
      "description": "Chunk content"
    },
    {
      "name": "type",
      "dataType": ["text"],
      "description": "heading|paragraph|list|table|image"
    },
    {
      "name": "page",
      "dataType": ["int"],
      "description": "Page number"
    },
    {
      "name": "section",
      "dataType": ["text"],
      "description": "Document section name"
    },
    {
      "name": "context",
      "dataType": ["text"],
      "description": "One-sentence context description"
    },
    {
      "name": "tags",
      "dataType": ["text[]"],
      "description": "Semantic tags"
    },
    {
      "name": "ofDocument",
      "dataType": ["Document"],
      "description": "Reference to parent Document"
    }
  ]
}
```

**Sample Chunk**:
```json
{
  "chunk_id": "chunk-789",
  "text": "The company offers flexible remote work options for all employees. Employees may work remotely up to 3 days per week...",
  "type": "paragraph",
  "page": 5,
  "section": "Remote Work Policy",
  "context": "Company policy on remote work flexibility and requirements",
  "tags": ["remote work", "policy", "flexibility", "work-from-home"],
  "ofDocument": {
    "beacon": "weaviate://localhost/Document/d7e8f9a0-b1c2-3d4e-5f6a-7b8c9d0e1f2a"
  },
  "_vector": [0.123, 0.456, 0.789, ...] // 1536 dimensions
}
```

### 5.5 Entity Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         SQLite Databases                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────┐         ┌─────────────────────┐   │
│  │      Sessions           │         │     Messages        │   │
│  ├─────────────────────────┤         ├─────────────────────┤   │
│  │ PK session_id (TEXT)    │         │ PK message_id (TEXT)│   │
│  │    user_id (TEXT)       │◄────────┤ FK session_id (TEXT)│   │
│  │    title (TEXT)         │   1:N   │    role (TEXT)      │   │
│  │    created_at (TEXT)    │         │    content (TEXT)   │   │
│  │    updated_at (TEXT)    │         │    timestamp (TEXT) │   │
│  │    message_count (INT)  │         │    sources (TEXT)   │   │
│  │    total_tokens (INT)   │         │    metadata (TEXT)  │   │
│  │    total_cost (REAL)    │         └─────────────────────┘   │
│  │    metadata (TEXT)      │                                    │
│  └─────────────────────────┘                                    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                      Documents                          │   │
│  ├─────────────────────────────────────────────────────────┤   │
│  │ PK doc_id (TEXT)                                        │   │
│  │    file_name (TEXT) UNIQUE                              │   │
│  │    upload_date (TEXT)                                   │   │
│  │    file_size_bytes (INT)                                │   │
│  │    chunks (INT)                                         │   │
│  │    uploaded_by (TEXT)                                   │   │
│  │    content_hash (TEXT) UNIQUE                           │   │
│  │    page_count (INT)                                     │   │
│  │    weaviate_doc_id (TEXT) ──────────────┐               │   │
│  │    metadata (TEXT)                      │               │   │
│  └─────────────────────────────────────────┼───────────────┘   │
│                                            │                    │
└────────────────────────────────────────────┼────────────────────┘
                                             │
                                             │ References
                                             │
┌────────────────────────────────────────────▼────────────────────┐
│                    Weaviate Cloud Database                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────┐         ┌─────────────────────┐   │
│  │      Document           │         │   KnowledgeBase     │   │
│  ├─────────────────────────┤         ├─────────────────────┤   │
│  │ UUID (auto)             │         │ UUID (auto)         │   │
│  │ file_name (text)        │◄────────┤ chunk_id (text)     │   │
│  │ upload_date (text)      │   1:N   │ text (text)         │   │
│  │ page_count (int)        │         │ type (text)         │   │
│  │ chunk_count (int)       │         │ page (int)          │   │
│  └─────────────────────────┘         │ section (text)      │   │
│                                      │ context (text)      │   │
│                                      │ tags (text[])       │   │
│                                      │ ofDocument (ref)    │   │
│                                      │ _vector (number[])  │   │
│                                      └─────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. Network Architecture

### 6.1 Network Topology

```
┌───────────────────────────────────────────────────────────────┐
│                         Internet                              │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           │ HTTPS (Production)
                           │ HTTP (Development)
                           │
┌──────────────────────────▼────────────────────────────────────┐
│                     Load Balancer                             │
│                   (Future: nginx/HAProxy)                     │
└──────────────────────────┬────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
┌────────▼────────┐ ┌──────▼─────────┐ ┌───▼──────────┐
│  Frontend       │ │  FastAPI       │ │  FastAPI     │
│  (React)        │ │  Instance 1    │ │  Instance N  │
│  Port: 5173     │ │  Port: 8009    │ │  Port: 800X  │
│  (Dev Server)   │ │                │ │              │
└─────────────────┘ └────────┬───────┘ └──────┬───────┘
                             │                 │
                    ┌────────┴─────────────────┘
                    │
         ┌──────────┼──────────┐
         │          │          │
┌────────▼────┐ ┌──▼───────┐ ┌▼────────────┐
│  SQLite     │ │ Weaviate │ │  OpenAI API │
│  (Local)    │ │  Cloud   │ │  (External) │
│             │ │          │ │             │
│ - chat_     │ │ HTTPS    │ │ HTTPS       │
│   sessions  │ │ Port:443 │ │ Port: 443   │
│ - documents │ │          │ │             │
└─────────────┘ └──────────┘ └─────────────┘
```

### 6.2 Port Configuration

| Service | Port | Protocol | Description |
|---------|------|----------|-------------|
| Frontend (Dev) | 5173 | HTTP | Vite development server |
| Frontend (Prod) | 80/443 | HTTP/HTTPS | Static file server (nginx) |
| Backend API | 8009 | HTTP/HTTPS | FastAPI application |
| Weaviate | 443 | HTTPS | Cloud service |
| OpenAI | 443 | HTTPS | External API |

### 6.3 API Endpoint Structure

**Base URL**: `http://localhost:8009` (Development)

#### PDF Processing Endpoints
- `POST /pdf/parse-pdf` - Parse and chunk PDF
- **Input**: multipart/form-data (PDF file)
- **Output**: JSON (chunks array)

#### Knowledge Base Endpoints
- `POST /kb/upload-to-kb` - Upload chunks to Weaviate
- `GET /kb/list-kb` - List documents with pagination
- `POST /kb/query` - Query knowledge base
- `DELETE /kb/delete/{doc_id}` - Delete document

#### Chat Endpoints
- `POST /chat/session/new` - Create chat session
- `POST /chat/message` - Send message
- `GET /chat/session/{id}/history` - Get conversation
- `GET /chat/sessions` - List user sessions
- `PATCH /chat/session/{id}/title` - Update title
- `DELETE /chat/session/{id}` - Delete session
- `GET /chat/session/{id}/tokens` - Get token usage
- `GET /chat/user/tokens` - Get total user tokens

### 6.4 CORS Configuration

```python
allowed_origins = [
    "http://localhost:5173",  # Frontend dev
    "http://localhost:3000",  # Alternative port
    # Production origins added via environment
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
```

---

## 7. Security Architecture

### 7.1 Authentication Flow

```
┌──────────────────────────────────────────────────────────────┐
│                  Authentication Server                        │
│                  (External Django Service)                    │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           │ 1. User Login
                           │ POST /auth/login
                           │ {username, password}
                           │
                           │ 2. JWT Token Response
                           │ {
                           │   "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
                           │   "user": {
                           │     "name": "John Doe",
                           │     "user_id": "123",
                           │     "email": "john@example.com"
                           │   }
                           │ }
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                       Frontend                                │
│  - Stores JWT in localStorage                                │
│  - Includes in Authorization header:                         │
│    Authorization: Bearer <token>                             │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           │ All API Requests
                           │ Authorization: Bearer <token>
                           │
┌──────────────────────────▼───────────────────────────────────┐
│              JWT Middleware (FastAPI)                         │
│                                                               │
│  1. Extract token from Authorization header                  │
│  2. Decode JWT using shared secret key                       │
│  3. Verify signature (HS256 algorithm)                       │
│  4. Check expiration timestamp                               │
│  5. Extract user_id from 'sub' or 'user_id' claim          │
│  6. Inject current_user into request                        │
│                                                               │
│  If invalid: 401 Unauthorized                                │
│  If expired: 401 with "Token expired" message               │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           │ Authenticated Request
                           │ current_user = {
                           │   "sub": "user123",
                           │   "name": "John Doe",
                           │   "exp": 1732473600
                           │ }
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                    Protected Endpoints                        │
│                                                               │
│  - Validate session ownership                                │
│  - Filter data by user_id                                   │
│  - Track uploaded_by field                                  │
└───────────────────────────────────────────────────────────────┘
```

### 7.2 Security Layers

#### Layer 1: Network Security
- **CORS**: Whitelist allowed origins
- **HTTPS**: TLS 1.2+ in production
- **Rate Limiting**: Configurable per environment
- **Security Headers**: 
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `X-XSS-Protection: 1; mode=block`
  - `Strict-Transport-Security` (HTTPS only)

#### Layer 2: Authentication & Authorization
- **JWT Tokens**: HS256 signed tokens
- **Token Expiration**: 24-hour lifetime
- **Session Ownership**: Users can only access their own sessions
- **Optional Auth**: Document uploads work with/without JWT

#### Layer 3: Input Validation
- **File Upload**:
  - Type validation (PDF only)
  - Size limit (10 MB max)
  - Filename sanitization (prevent directory traversal)
  - Empty file detection
- **Text Input**:
  - Length limits (MAX_MESSAGE_LENGTH: 10,000 chars)
  - XSS prevention (sanitization)
  - SQL injection prevention (parameterized queries)
- **Pydantic Models**: Type validation for all API inputs

#### Layer 4: Data Protection
- **SQL Injection**: Parameterized queries, no string concatenation
- **Password Storage**: Not stored (external auth server)
- **Secrets Management**: Environment variables, never committed
- **Content Hash**: SHA256 for duplicate detection

### 7.3 Security Configuration

```python
# config.py
class Config:
    # JWT
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")  # Required
    
    # Environment
    ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")
    
    # Rate Limiting
    RATE_LIMIT_ENABLED = os.environ.get("RATE_LIMIT_ENABLED", "true")
    
    # HTTPS/TLS
    USE_HTTPS = os.environ.get("USE_HTTPS", "false")
    SSL_CERTFILE = os.environ.get("SSL_CERTFILE")
    SSL_KEYFILE = os.environ.get("SSL_KEYFILE")
```

### 7.4 Threat Model

| Threat | Mitigation | Status |
|--------|-----------|--------|
| **SQL Injection** | Parameterized queries | ✅ Implemented |
| **XSS** | Input sanitization, CSP headers | ✅ Implemented |
| **CSRF** | JWT tokens (stateless), CORS | ✅ Implemented |
| **Directory Traversal** | Filename sanitization | ✅ Implemented |
| **DDoS** | Rate limiting, load balancer | ⚠️ Partial |
| **Unauthorized Access** | JWT verification, session ownership | ✅ Implemented |
| **Token Theft** | HTTPS only, HttpOnly cookies | ⚠️ localStorage (improvement needed) |
| **Brute Force** | Rate limiting on auth server | ✅ External |
| **Man-in-the-Middle** | HTTPS/TLS in production | ⚠️ Development HTTP |
| **API Key Exposure** | Environment variables, .gitignore | ✅ Implemented |

---

## Appendix A: Technology Versions

| Component | Version | Notes |
|-----------|---------|-------|
| Python | 3.8+ | Backend language |
| FastAPI | Latest | Web framework |
| Uvicorn | Latest | ASGI server |
| SQLite | 3.x | Embedded database |
| Weaviate | Cloud | Vector database |
| OpenAI API | GPT-4o, text-embedding-3-small | AI services |
| React | 18.x | Frontend framework |
| Vite | Latest | Build tool |
| Node.js | 16+ | Frontend runtime |

---

## Appendix B: Glossary

- **Chunk**: Semantic unit of text from a document (paragraph, table, etc.)
- **Embedding**: Vector representation of text (1536 dimensions)
- **Hybrid Search**: Combination of vector (semantic) + BM25 (keyword) search
- **JWT**: JSON Web Token for authentication
- **Reranking**: Re-scoring search results using AI for better relevance
- **Session**: Chat conversation thread with unique ID
- **Vector Database**: Database optimized for similarity search on embeddings
- **Weaviate**: Cloud-hosted vector database service

---

**End of Chapter 4: System Architecture & Design**

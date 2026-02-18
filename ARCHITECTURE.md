# LynxGPT — Complete Architecture Deep-Dive

LynxGPT is an **AI-powered academic assistant** built for NIT Trichy students. It uses a **LangGraph agent** with an intelligent router to handle question papers, circulars/course plans, resume-to-job matching, subject Q&A, and conversational memory — all wrapped in a chat-based UI.

---

## High-Level System Architecture

```mermaid
graph TB
    subgraph "Frontend (Vite + React)"
        UI["ChatBotUI.jsx"]
        HIST["HistorySection"]
    end

    subgraph "Backend (FastAPI)"
        API["main.py<br/>REST API Layer"]
        AGENT["agent.py<br/>LangGraph State Machine"]
    end

    subgraph "Data Layer"
        REDIS["Redis<br/>Session Cache (24h TTL)"]
        MONGO["MongoDB<br/>Persistent Storage"]
        SUPA["Supabase<br/>Vector DB + Object Storage"]
        PG["PostgreSQL<br/>Circulars PDF Store"]
    end

    subgraph "External Services"
        GEMINI["Google Gemini 2.5 Flash<br/>Router + Memory + Resume QA"]
        GROQ["Groq API<br/>RAG QA + Metadata Extraction"]
        NITT["cp.nitt.edu<br/>Circulars Source"]
        HF["HuggingFace<br/>Embeddings API"]
    end

    UI -- "HTTP REST" --> API
    HIST -- "HTTP REST" --> API
    API --> AGENT
    API -- "R/W messages" --> REDIS
    API -- "Persist on end_session" --> MONGO
    AGENT -- "Route: subject_qa" --> SUPA
    AGENT -- "Route: question_paper" --> SUPA
    AGENT -- "Route: course_plan" --> PG
    AGENT -- "Route: resume_qa" --> GEMINI
    AGENT -- "Route: memory" --> GEMINI
    AGENT --> GROQ
    AGENT --> HF
```

---

## The LangGraph Agent — The Brain

The core intelligence lives in [agent.py](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/backend/agent.py). It's a **finite state machine** built with LangGraph.

### State Definition

```python
class State(TypedDict):
    messages: List[BaseMessage]       # Full conversation history
    current_input: str                # Latest user query
    route: Literal[...]               # Chosen route label
    last_result: Optional[Any]        # Structured result (e.g. links)
    resume_context: Optional[Dict]    # Parsed resume data from Dreamer
```

### Router Flow

```mermaid
graph LR
    START(["User Query"]) --> CLASSIFIER["classifier_node<br/>Gemini 2.5 Flash<br/>(Structured Output)"]
    
    CLASSIFIER -- "question_paper" --> QP["question_paper_node"]
    CLASSIFIER -- "course_plan" --> CP["course_plan_node"]
    CLASSIFIER -- "memory" --> MEM["memory_node"]
    CLASSIFIER -- "resume_qa" --> RES["resume_qa_node"]
    CLASSIFIER -- "subject_qa" --> SQA["subject_qa_node"]
    CLASSIFIER -- "out_of_scope" --> OOS["out_of_scope_node"]
    
    QP --> END_STATE(["END"])
    CP --> END_STATE
    MEM --> END_STATE
    RES --> END_STATE
    SQA --> END_STATE
    OOS --> END_STATE
```

### How Routing Works

1. **Gemini with structured output** — The LLM is constrained to output a `Route` Pydantic model with exactly 1 of 6 labels
2. **Follow-up detection** — Before calling the LLM, it checks if the last bot message contained "please specify" → auto-routes back to `question_paper`
3. **The route label** is stored in `state["route"]`, and `route_decider()` returns it to LangGraph's conditional edge system

### The `invoker()` Function

This is the **single entry point** called by `main.py`:

```mermaid
sequenceDiagram
    participant API as main.py
    participant INV as invoker()
    participant R as Redis
    participant G as LangGraph

    API->>INV: invoker(text, history, resume_ctx)
    
    alt History provided (stateless)
        INV->>INV: Convert dict history → LangChain messages
    else Session ID provided (stateful/CLI)
        INV->>R: Fetch chat history
        R-->>INV: List of message dicts
    end
    
    INV->>INV: Append HumanMessage(user_input)
    INV->>G: graph.invoke(init_state)
    G-->>INV: Final state with AI messages
    
    alt Structured result (dict with links)
        INV-->>API: Return dict {answer, links}
    else Plain text
        INV-->>API: Return last message content
    end
```

---

## The FastAPI Layer — `main.py`

[main.py](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/backend/main.py) is the REST API that the frontend talks to.

### API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Docker healthcheck |
| `/conversations` | GET | List all conversations |
| `/conversations` | POST | Create new conversation |
| `/conversations/{id}` | PATCH | Rename conversation |
| `/conversations/{id}` | DELETE | Delete conversation |
| `/conversations/{id}/star` | PATCH | Toggle star/favorite |
| `/conversations/{id}/messages` | GET | Get messages (Redis → Mongo fallback) |
| `/conversations/{id}/messages` | POST | **Send a message** (triggers agent) |
| `/conversations/{id}/end` | POST | Flush Redis → MongoDB |
| `/conversations/{id}/upload_pdf/{type}` | POST | Upload PDF (Resume or QP) |
| `/conversations/purge-empty` | POST | Clean up empty conversations |

### Message Flow (the critical path)

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant API as main.py
    participant R as Redis
    participant AG as agent.invoker()
    participant MG as MongoDB

    FE->>API: POST /conversations/{id}/messages {sender:"user", text:"..."}
    API->>R: Get chat history
    API->>R: Get resume context (if any)
    API->>R: Store user message
    API->>AG: invoker(text, history, resume_ctx)
    AG-->>API: Response (string or dict)
    
    alt Dict response (has links)
        API->>R: Store answer message
        API->>R: Store each link as separate message
    else String response
        API->>R: Store bot message
    end
    
    API-->>FE: {messages: [user_msg, ...bot_msgs]}
```

### PDF Upload Flow

```mermaid
graph TD
    UPLOAD["POST /upload_pdf/{type}"] --> CHECK{PDF Type?}
    
    CHECK -- "QuestionPapersPDF" --> QP_PROC["pdf_processor.process_single_pdf()"]
    QP_PROC --> OCR["OCR + Text Extract"]
    OCR --> DEDUP["Duplicate Check<br/>(SHA-256 + Vector Similarity)"]
    DEDUP --> META["LLM Metadata Extraction<br/>(Groq)"]
    META --> STORE["Upload to Supabase Bucket<br/>+ Insert Metadata"]
    
    CHECK -- "ResumePDF" --> SAVE["Save to uploads/"]
    SAVE --> DREAMER["run_resume_pipeline()"]
    DREAMER --> PARSE["Parse PDF → Text"]
    PARSE --> EXTRACT["LLM Extract Info<br/>(Gemini)"]
    EXTRACT --> MATCH["Vector Similarity Search<br/>(Supabase RPCs)"]
    MATCH --> RANK["Rank & Return Top 5 Jobs"]
    RANK --> REDIS_SAVE["Save candidate_info to Redis"]
```

---

## Module Deep-Dives

### 1. QuestionPapers Module

Located in [QuestionPapers/](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/backend/QuestionPapers).

**Two files, two roles:**

| File | Role |
|---|---|
| [pdf_processor.py](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/backend/QuestionPapers/pdf_processor.py) | **Ingestion** — Process uploaded PDFs |
| [query_processor.py](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/backend/QuestionPapers/query_processor.py) | **Retrieval** — Search for question papers by query |

**Ingestion Pipeline (`pdf_processor.py`):**
1. OCR text extraction (PyMuPDF + Tesseract)
2. **First duplicate check** → SHA-256 hash against Supabase
3. **Second duplicate check** → Vector similarity of embeddings (HuggingFace API)
4. **Metadata extraction** → Groq LLM extracts: department, subject, year, exam type
5. Upload PDF bytes to Supabase Storage bucket
6. Insert metadata + embedding into Supabase DB

**Query Pipeline (`query_processor.py`):**
1. Groq LLM extracts metadata from natural language query
2. Build Supabase query with strict AND matching
3. If no results → fallback to fuzzy OR matching on subject words
4. Return `{answer: "...", links: [...pdf_urls]}`

---

### 2. Circulars Module

Located in [Circulars/](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/backend/Circulars). Handles **course plans, syllabus, and circulars from NIT Trichy**.

| File | Role |
|---|---|
| [scraper.py](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/backend/Circulars/scraper.py) | Crawls `cp.nitt.edu` and downloads PDFs to PostgreSQL |
| [append_data.py](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/backend/Circulars/append_data.py) | OCRs PDFs, extracts course metadata via Groq, chunks text, and embeds into PostgreSQL (pgvector) |
| [retriever.py](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/backend/Circulars/retriever.py) | RAG retrieval chain — semantic search + Gemini LLM answer generation |

**Data Pipeline:**

```mermaid
graph LR
    NITT["cp.nitt.edu"] --> SCRAPE["scraper.py<br/>Crawl folders recursively"]
    SCRAPE --> PG["PostgreSQL<br/>circulars table<br/>(filename, url, data)"]
    PG --> APPEND["append_data.py<br/>OCR + Groq metadata<br/>+ Chunking + Embedding"]
    APPEND --> PG2["PostgreSQL<br/>circular_chunks table<br/>(text, embedding, metadata)"]
```

**Retrieval Path:**
1. LLM extracts `course_code` and `course_name` from the user query
2. Semantic vector search on `circular_chunks` using `pgvector`
3. If results found → passes chunks to a Gemini RAG chain for answer generation
4. Returns `{answer: "...", links: [...pdf_urls]}`

---

### 3. Dreamer Module (Resume → Job Matching)

Located in [Dreamer/dreamer/](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/backend/Dreamer/dreamer). This is the most complex module.

**Architecture:**

```mermaid
graph TD
    PDF["Resume PDF"] --> PARSER["resume_parser.py<br/>PyMuPDF → Text<br/>Clean + Normalize"]
    PARSER --> EXTRACTOR["info_extractor.py<br/>Gemini LLM<br/>Extract: Title, Skills, Description,<br/>Experience, Education"]
    EXTRACTOR --> SIMILARITY["similarity.py<br/>SentenceTransformer Embeddings"]
    
    SIMILARITY --> RPC1["Supabase RPC: match_title"]
    SIMILARITY --> RPC2["Supabase RPC: match_skills"]
    SIMILARITY --> RPC3["Supabase RPC: match_desc"]
    
    RPC1 --> COMBINE["Weighted Score Combination<br/>w_title × sim_title +<br/>w_skills × sim_skills +<br/>w_desc × sim_desc"]
    RPC2 --> COMBINE
    RPC3 --> COMBINE
    
    COMBINE --> RANK["Rank & Return Top N Jobs"]
```

**Key files:**

| File | Purpose |
|---|---|
| [pipeline.py](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/backend/Dreamer/dreamer/pipeline.py) | Orchestrator — calls parse → extract → match |
| [resume_parser.py](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/backend/Dreamer/dreamer/resume_parser.py) | PDF → cleaned text via PyMuPDF |
| [info_extractor.py](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/backend/Dreamer/dreamer/info_extractor.py) | Gemini LLM → structured JSON (Title, Skills, Description, Experience, Education) |
| [similarity.py](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/backend/Dreamer/dreamer/similarity.py) | SentenceTransformer embeddings → 3 Supabase RPCs → weighted scoring |
| [database.py](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/backend/Dreamer/dreamer/database.py) | Supabase CRUD for jobs table + candidate criteria filtering |
| [Scrape.py](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/backend/Dreamer/dreamer/Scrape.py) | Async job scraper → embeds jobs → upserts to Supabase |
| [app.py](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/backend/Dreamer/dreamer/app.py) | Standalone FastAPI app (also used as importable module) |

---

### 4. RAG / Subject QA Module

Located in [RAG/rag_engine.py](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/backend/RAG/rag_engine.py). Handles **subject-specific academic questions** using hybrid search.

**How Hybrid Search Works:**

```mermaid
graph LR
    Q["User Query"] --> EMB["HuggingFace<br/>all-MiniLM-L6-v2<br/>Embedding"]
    Q --> BM25["BM25 Text<br/>Matching"]
    EMB --> RPC["Supabase RPC:<br/>match_documents_hybrid"]
    BM25 --> RPC
    RPC --> RRF["Reciprocal Rank Fusion<br/>(RRF Score)"]
    RRF --> DOCS["Top-K Documents"]
    DOCS --> PROMPT["RAG Prompt"]
    PROMPT --> GROQ["Groq LLM<br/>gpt-oss-20b"]
    GROQ --> ANS["Answer"]
```

Key design: `CustomSupabaseVectorStore` overrides LangChain's default to pass **both** the query embedding AND raw query text to the Supabase RPC function, enabling hybrid BM25 + semantic search with RRF score fusion.

---

### 5. Redis Session Layer

[redis_client.py](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/backend/database/redis_client.py) manages **ephemeral session state** with a graceful fallback.

```mermaid
graph TD
    REQ["API Request"] --> RC["RedisClient"]
    RC --> CHECK{Redis Available?}
    CHECK -- "Yes" --> REDIS["Redis<br/>Keys: chat:{id}:messages<br/>chat:{id}:resume<br/>TTL: 24 hours"]
    CHECK -- "No" --> MEM["In-Memory Dict<br/>(Fallback)"]
```

**Methods:**
- `get_chat_history(conv_id)` → List of message dicts
- `add_message(conv_id, msg)` → Append + set 24h TTL
- `save_resume_context(conv_id, ctx)` → Save parsed resume
- `get_resume_context(conv_id)` → Retrieve parsed resume
- `clear_conversation(conv_id)` → Delete all session data

---

## Frontend Architecture

A **React + Vite** SPA with a dark, glassmorphic design.

```mermaid
graph TD
    MAIN["main.jsx<br/>Dynamic Accent Colors<br/>+ Ethereal Orb Animations"] --> APP["App.jsx<br/>State: conversations, selectedId"]
    
    APP --> HIST["HistorySection"]
    APP --> CONV["ConversationSection"]
    APP --> BANNER["BottomBanner"]
    
    HIST --> HEADER["Header.jsx"]
    HIST --> LIST["list_items.jsx<br/>Conversation List"]
    HIST --> CONTENT["Content.jsx"]
    HIST --> FOOTER["Footer.jsx"]
    
    CONV --> CHAT["ChatBotUI.jsx<br/>Message Display + Input<br/>PDF Upload + Link Rendering"]
```

**Notable design decisions:**
- **Dynamic theming** — On every page load, a random accent color is picked from 7 options (deep-violet, hot-pink, sky-blue, etc.)
- **Ethereal orbs** — 7 animated gradient blobs at strategic positions for ambient lighting
- **Conversation persistence** — `selectedId` saved to `localStorage`
- **Limits enforced** — Max 64 normal + 32 starred conversations

---

## Docker / Infrastructure

The [docker-compose.yaml](file:///e:/lynx_gpt_main_2/final_lynx/LynxGPT/docker-compose.yaml) orchestrates 4 services:

```mermaid
graph TB
    subgraph "Docker Compose"
        FE["frontend<br/>:3000<br/>(Nginx)"]
        BE["backend<br/>:8000<br/>(Uvicorn)"]
        REDIS["redis:alpine<br/>:6379"]
        MONGO["mongo:6.0<br/>:27017"]
    end

    FE -- "depends_on" --> BE
    FE -- "depends_on" --> MONGO
    BE -- "depends_on" --> MONGO
    BE -- "depends_on" --> REDIS
```

All services have **healthchecks** and **restart policies** (`unless-stopped`). Volumes persist MongoDB data and Redis snapshots.

---

## Data Flow — Complete Request Lifecycle

Here's what happens when a user types **"Show me CSE question papers from 2023"**:

```mermaid
sequenceDiagram
    participant U as User
    participant FE as React Frontend
    participant API as FastAPI (main.py)
    participant R as Redis
    participant AG as LangGraph Agent
    participant RTR as Gemini Router
    participant QP as query_processor.py
    participant GQ as Groq LLM
    participant SB as Supabase

    U->>FE: Types message + Enter
    FE->>API: POST /conversations/{id}/messages
    API->>R: Fetch chat history
    API->>R: Store user message
    API->>AG: invoker("Show me CSE papers from 2023", history)
    AG->>RTR: Classify query (structured output)
    RTR-->>AG: {choice: "question_paper"}
    AG->>QP: get_link("Show me CSE papers from 2023")
    QP->>GQ: Extract metadata from query
    GQ-->>QP: {dept: "CSE", year: "2023", ...}
    QP->>SB: Query questionpapers table
    SB-->>QP: [matching records with PDF URLs]
    QP-->>AG: {answer: "Found 3 papers", links: [...]}
    AG-->>API: Dict response
    API->>R: Store answer + each link as message
    API-->>FE: {messages: [user_msg, answer_msg, link1, link2...]}
    FE->>U: Render answer + clickable PDF links
```

---

## External Dependencies Summary

| Service | Used For | Used By |
|---|---|---|
| **Google Gemini 2.5 Flash** | Query routing, Memory/Chat, Resume QA, Circulars retrieval | `agent.py`, `retriever.py`, `resume_parser.py`, `info_extractor.py` |
| **Groq API** | Subject QA (RAG), Metadata extraction from PDFs/queries | `rag_engine.py`, `query_processor.py`, `pdf_processor.py`, `append_data.py` |
| **Supabase** | Vector storage, Question paper storage, Job listings DB | `rag_engine.py`, `pdf_processor.py`, `query_processor.py`, `similarity.py` |
| **PostgreSQL** | Circulars PDF + chunk storage with pgvector | `scraper.py`, `append_data.py`, `retriever.py` |
| **HuggingFace** | Embeddings (all-MiniLM-L6-v2, SentenceTransformer) | `rag_engine.py`, `retriever.py`, `append_data.py`, `pdf_processor.py` |
| **MongoDB** | Conversation persistence | `main.py` |
| **Redis** | Session cache (24h TTL) | `main.py`, `agent.py` |

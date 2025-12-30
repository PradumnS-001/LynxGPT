# LynxGPT 🐆

> **AI-Powered Chatbot for NITT Students** — Get answers about circulars, question papers, and job recommendations!

---

## 🎯 Features

| Feature | Description |
|---------|-------------|
| **📚 Circular Q&A** | Ask questions about NITT circulars and get AI-powered answers with source links |
| **📝 Question Papers** | Upload question papers and retrieve relevant documents |
| **💼 Resume Matching** | Upload your resume to get personalized job recommendations |
| **💬 Chat Interface** | Beautiful React-based chat UI with conversation history |

---

## 🏗️ Architecture

```
LynxGPT/
├── backend/                     # FastAPI Backend
│   ├── main.py                  # Main API endpoints
│   ├── agent.py                 # LangGraph routing agent
│   ├── Circulars/               # Circular scraping & retrieval
│   │   ├── scraper.py           # Web scraper for circulars
│   │   ├── retriever.py         # RAG-based Q&A
│   │   └── append_data.py       # Data ingestion
│   ├── QuestionPapers/          # Question paper processing
│   │   ├── pdf_processor.py     # PDF text extraction
│   │   └── query_processor.py   # Query handling
│   ├── Dreamer/                 # Resume-Job Matching
│   │   └── dreamer/
│   │       ├── app.py           # Resume upload API
│   │       ├── pipeline.py      # Core matching pipeline
│   │       ├── resume_parser.py # PDF + LLM extraction
│   │       ├── similarity.py    # Job ranking
│   │       └── database.py      # Supabase integration
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/LynxGPT/            # React Frontend
│   ├── src/
│   ├── Dockerfile
│   └── nginx.conf
├── docker-compose.yaml
└── .env
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | FastAPI, LangGraph, LangChain |
| **LLM** | Google Gemini 2.5 Flash |
| **Database** | MongoDB (conversations), Supabase (jobs) |
| **Frontend** | React, Vite |
| **Deployment** | Docker, Docker Compose, Nginx |

---

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- Google API Key (Gemini)
- MongoDB connection string
- Supabase credentials (for job matching)

### 1. Clone & Configure

```bash
git clone https://github.com/your-repo/LynxGPT.git
cd LynxGPT

# Copy and edit environment variables
cp env.example .env
```

**Required `.env` variables:**

```env
GOOGLE_API_KEY=your_gemini_api_key
MONGODB=mongodb://mongo:27017
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
```

### 2. Run with Docker Compose

```bash
docker compose up -d --build
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:80 |
| Backend API | http://localhost:8000 |
| MongoDB | localhost:27017 |

### 3. Health Check

```bash
curl http://localhost:8000/health
# {"status": "healthy"}
```

---

## 📡 API Endpoints

### Conversations

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/conversations` | List all conversations |
| `POST` | `/conversations` | Create new conversation |
| `GET` | `/conversations/{id}/messages` | Get messages |
| `POST` | `/conversations/{id}/messages` | Send message (triggers AI) |

### PDF Upload

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/conversations/{id}/upload_pdf/ResumePDF` | Upload resume for job matching |
| `POST` | `/conversations/{id}/upload_pdf/QuestionPapersPDF` | Upload question paper |

---

## 🔧 Development

### Local Backend (without Docker)

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Local Frontend

```bash
cd frontend/LynxGPT
npm install
npm run dev
```

---

## 🤖 Agent Routing

LynxGPT uses a **LangGraph-based agent** that routes queries to the appropriate handler:

```
User Query
    │
    ▼
┌─────────────┐
│  Classifier │ (Gemini LLM)
└─────────────┘
    │
    ├── answer_question → Circulars RAG
    ├── get_docs → Question Papers
    └── out_of_scope → Default response
```

---

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

---

**Made with ❤️ for NITT Students**

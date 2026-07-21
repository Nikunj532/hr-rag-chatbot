# 🏢 HR Policy RAG Chatbot

A production-grade RAG-based chatbot for HR policy management.
Upload PDF, DOCX, or TXT policies, auto-track versions, get AI-generated diff summaries, and chat naturally.

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | Groq — `llama-3.3-70b-versatile` |
| Embeddings | Local (free) — `sentence-transformers/all-MiniLM-L6-v2` via HuggingFace |
| Vector Store | ChromaDB (persistent, with rich metadata) |
| Orchestration | LangChain 0.3 + LangGraph 0.2 |
| Backend API | FastAPI + Uvicorn |
| Database | PostgreSQL (via SQLAlchemy) |
| Email | Gmail SMTP (App Password) |
| Frontend | Streamlit |

---

## Folder Structure

```
hr-rag-chatbot/
├── backend/
│   ├── main.py                    # FastAPI app entry point
│   ├── requirements.txt
│   ├── core/
│   │   ├── config.py              # Pydantic settings (reads .env)
│   │   └── constants.py           # Model names, chunk sizes, thresholds
│   ├── db/
│   │   └── models.py              # SQLAlchemy models + init_db()
│   ├── services/
│   │   ├── document_parser.py     # PDF/DOCX/TXT text + table extraction
│   │   ├── diff_service.py        # Paragraph + table diff engine
│   │   ├── email_service.py       # Gmail SMTP notification
│   │   ├── vector_store.py        # ChromaDB ingest + retrieval
│   │   └── history_service.py     # Conversation history + summarisation
│   ├── workflows/
│   │   └── rag_workflow.py        # LangGraph RAG graph
│   └── api/
│       ├── upload.py              # Upload + policies + diffs endpoints
│       └── chat.py                # Chat + conversation history endpoints
│
├── frontend/
│   ├── app.py                     # Streamlit entry point + sidebar nav
│   ├── requirements.txt
│   ├── styles.py                  # Custom CSS + helper render functions
│   ├── api_client.py              # HTTP client for FastAPI backend
│   ├── .streamlit/config.toml     # Dark theme config
│   └── pages/
│       ├── chat_page.py           # Conversational chat UI
│       ├── upload_page.py         # Multi-format upload (policy name + file)
│       ├── policies_page.py       # Ingested policies browser
│       └── diffs_page.py          # Policy change log viewer
│
├── scripts/
│   └── init_db.sql                # PostgreSQL DB creation script
└── .env.example
```

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- PostgreSQL running locally
- Gmail account with App Password enabled
- Groq API key (free at console.groq.com)

### 2. Clone & Configure

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 3. Initialise PostgreSQL

```bash
psql -U postgres -f scripts/init_db.sql
```

### 4. Install Backend Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 5. Install Frontend Dependencies

```bash
cd frontend
pip install -r requirements.txt
```

### 6. Start the Backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

API docs at http://localhost:8000/docs

### 7. Start the Frontend

```bash
cd frontend
streamlit run app.py
```

UI at http://localhost:8501

---

## How It Works

### Policy Upload & Version Detection

Upload PDF, DOCX, or TXT files under a **policy name** you choose (e.g. "Leave Policy") —
no filename convention required.

1. First upload under a name → parsed, chunked, embedded, stored as **v1**
2. Next upload under the same name → auto-assigned **v2**, and the system:
   - Hashes the file content and skips it if identical to the latest version (duplicate guard)
   - Computes a paragraph-level diff (difflib.SequenceMatcher)
   - Computes a table-level diff (rows added/removed, headers changed)
   - Groq generates a human-readable Markdown summary
   - Saves the diff to the Postgres `policy_diffs` table
   - Sends an email notification via Gmail SMTP

### Deleting Policies

- Delete a single version: `DELETE /api/policies/{base_name}/versions/{version}`
- Delete an entire policy (all versions + diff history): `DELETE /api/policies/{base_name}`
- Both are also available from the **Policies** tab in the UI, with a confirm step.

### LangGraph Workflow

```
START → classify_query → [check_diff | retrieve] → generate → END
```

- classify_query: detects if user asks about changes vs general policy
- check_diff: loads stored diff summary from Postgres
- retrieve: ChromaDB MMR retrieval with metadata filtering
- generate: Groq LLM with history + context

### Conversational History

- All messages persisted to Postgres
- After 200 messages: older messages summarised by Groq, stored compressed
- Recent 20 messages always kept verbatim for continuity

---

## Environment Variables

```env
GROQ_API_KEY=gsk_...
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=hr_chatbot
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
CHROMA_PERSIST_DIR=./chroma_store
GMAIL_SENDER=your_email@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
GMAIL_NOTIFY_RECIPIENT=hr_admin@company.com
BACKEND_URL=http://localhost:8000
CONVERSATION_SUMMARY_THRESHOLD=200
```

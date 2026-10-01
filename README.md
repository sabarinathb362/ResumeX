# ResumeIQ v2.0

**Privacy-preserving, local-first resume analysis engine.**

ATS compatibility scoring, hybrid job matching with skill taxonomy, and evidence-grounded feedback — all running entirely on your machine. No data ever leaves your device.

## Quick Start

### 1. Backend (FastAPI + Python)

```bash
# Install dependencies
pip install -r requirements.txt

# Run the backend server
python -m uvicorn backend.main:app --reload --port 8000
```

### 2. Frontend (React + Vite)

```bash
cd frontend
npm install
npm run dev
```

Then open **http://localhost:5173** in your browser.

### 3. Run Tests

```bash
python -m pytest tests/ -v
```

## Architecture

```
resumeiq/
├── backend/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py             # All tunable settings (weights, limits, etc.)
│   ├── database.py           # SQLite / SQLAlchemy setup
│   ├── api/                  # REST API routes
│   │   ├── resume.py         # POST /api/resume/upload
│   │   ├── jd.py             # POST /api/jd/analyze
│   │   ├── analysis.py       # POST /api/analysis/run, GET /api/analysis/{id}
│   │   └── jobs.py           # SSE progress streaming
│   ├── ingestion/            # PDF & DOCX extraction (Phase 1)
│   │   ├── pdf.py            # PyMuPDF extraction with layout metadata
│   │   └── docx_extractor.py # python-docx extraction
│   ├── ats/                  # Deterministic ATS rule engine (Phase 2)
│   │   └── rules.py          # 9 weighted scoring dimensions
│   ├── parsing/              # JD parsing (Phase 3)
│   │   └── jd_parser.py      # Requirement classification
│   ├── nlp/                  # Skill normalization (Phase 3)
│   │   └── skills.py         # 150+ aliases, taxonomy, match classification
│   ├── matching/             # Hybrid matching (Phase 4)
│   │   └── hybrid.py         # 7 match dimensions with evidence tracing
│   ├── schemas/              # Pydantic data models
│   ├── models/               # SQLAlchemy ORM models
│   └── jobs/                 # Background job queue (Phase 0)
├── frontend/
│   └── src/
│       ├── App.jsx           # Main dashboard UI
│       ├── api/client.js     # Backend API client
│       └── components/       # ScoreCircle, WarningList, SkillMatchList, FileUpload
├── tests/
│   └── test_smoke.py         # 16 smoke tests (all passing)
├── knowledge_base/           # RAG corpus (Phase 6)
└── requirements.txt
```

## Project Status & Implementation Phases

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 0 | Repository scaffold, CI, job queue, SSE | ✅ Done |
| Phase 1 | PDF/DOCX ingestion with layout metadata | ✅ Done |
| Phase 2 | ATS rule engine (9 dimensions) + dashboard | ✅ Done |
| Phase 3 | JD parsing + skill normalization (150+ aliases) | ✅ Done |
| Phase 4 | Hybrid semantic matching (7 dimensions) | ✅ Done |
| Phase 5 | Real embedding matching (BGE-small, sentence-transformers) | ✅ Done |
| Phase 6 | RAG Knowledge Base & Hybrid Retrieval (BM25 + Dense) | ✅ Done |
| Phase 7 | Local LLM Integration (Ollama / GBNF / Delimited Prompts) | ✅ Done |
| Phase 8 | Grounded Feedback & Factual Bullet Rewriting (XYZ Formula) | ✅ Done |
| Phase 9 | AI-Likeness, Generic Writing & Placeholder / Lorem Ipsum Detector | ✅ Done |
| Phase 10 | Readability Scoring (RRI, 6 dimensions, 100-pt rubric) | ✅ Done |
| Phase 11 | General Recommendation Engine (No JD Provided) | ✅ Done |
| Phase 12 | JD-Based Feedback & AI Match Percentage (Judge + Uplift) | ✅ Done |
| Phase 13 | Skill-Gap Analysis & Project Recommendation Engine | ✅ Done |
| Phase 14 | LaTeX / Overleaf Source Parser & Layout Risk Detection | ✅ Done |
| Phase 15 | Evaluation Benchmark & Ablation Suite | ✅ Done |
| Phase 16 | UI Polish, Interactive Rewriter, Project Cards, Export & Privacy Controls | ✅ Done |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/resume/upload` | POST | Upload and parse resume (PDF, DOCX, LaTeX `.tex`) |
| `/api/jd/analyze` | POST | Parse job description (text or file) |
| `/api/analysis/run` | POST | Run ATS + match + readability analysis |
| `/api/analysis/{id}` | GET | Get full analysis results |
| `/api/analysis/{id}/ats` | GET | Get ATS results only |
| `/api/analysis/{id}/match` | GET | Get match results only |
| `/api/analysis/{id}/readability` | GET | Get readability results only |
| `/api/knowledge/search` | GET | Hybrid RAG search over role norms, skills, and projects |
| `/api/rewrite` | POST | Factually validated bullet rewriter with Google XYZ formula |
| `/api/recommendations/general` | POST | Inferred role & prioritized resume recommendations |
| `/api/recommendations/jd` | POST | AI Match % evaluation, per-requirement judge, and section uplift |
| `/api/projects/recommend` | POST | Recommended project archetypes addressing candidate skill gaps |
| `/api/jobs/{id}/events` | GET | SSE progress stream |
| `/health` | GET | Health check (includes embedding & LLM status) |
| `/health/embeddings` | GET | Embedding model availability |

## Tech Stack

- **Backend**: Python 3.13, FastAPI, SQLAlchemy, SQLite
- **Parsers**: PyMuPDF (PDF), python-docx (DOCX)
- **Embeddings**: sentence-transformers (BGE-small-en-v1.5), CUDA-accelerated
- **Frontend**: React 19, Vite 8
- **Target Hardware**: i7 / RTX 4060 8GB / 24GB RAM

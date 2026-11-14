# ResumeX

**Local-first, privacy-preserving resume intelligence platform.**

ResumeX analyses a résumé on two independent axes — machine parseability (ATS Compatibility) and human readability (Recruiter Readability Index) — then matches it against a job description using a fine-tuned embedding model and a hybrid retrieval engine. Every score is deterministic, versioned, and reproducible. Local language models (via Ollama) are used only for grounded rewrites, grading labels, and mock interview evaluation, and every rewrite must pass a strict fact-checker that rejects any metric, tool, or claim not already present in the résumé.

**All processing happens on your machine. No résumé data ever leaves your device.**

---

## Features

| Area | Description |
|------|-------------|
| **Parsing** | Layout-aware PDF extraction (PyMuPDF) with sections → entries → statements and bounding-box anchors; DOCX, LaTeX (`.tex`), and Typst (`.typ`) support |
| **ATS Compatibility** | 9 deterministic rules, 100-point rubric: text extractability, section structure, formatting safety, contact info, standard headings, date consistency, skill visibility, link validity, parsing risk |
| **Recruiter Readability Index (RRI)** | 7 dimensions, 100-point rubric, A–D grade per bullet (action verb tier, specificity, outcome, metric density) |
| **ATS 2.0** | 7-second recruiter attention simulation, Verifiable Impact Quotient (VIQ), and "what a naive ATS actually sees" parser degradation view |
| **Job Matching** | 7-dimension hybrid fit score: exact, alias (168+ aliases), and taxonomy skill matching plus semantic similarity from a fine-tuned `bge-small` encoder |
| **RAG Knowledge Base** | Hybrid retriever (0.65 dense + 0.35 BM25) over role norms, skill relationships, writing guidance, and project archetypes — every result is chunk-cited |
| **Grounded Rewrites** | Fact-checker rejects numbers by value and entities through an alias/hypernym taxonomy; blocked suggestions shown with specific rejection reasons |
| **Interactive Editor** | Edit text directly on your own PDF with layout, fonts, and spacing preserved; apply suggestions in one click; export with edits in-place or as DOCX / LaTeX / TXT |
| **Mock Interview Arena** | 3-round simulation grounded in your résumé, the JD, and company signals; STAR grading with verbatim-quote verification, all computed locally |
| **Integrity Checks** | Hidden-text detection (white, invisible, tiny, off-page), timeline consistency validation, optional GitHub claim verification |
| **Company Intelligence** | JD-driven company profile: tech stack, culture signals, hiring patterns, and resume optimisation tips |
| **Optional Accounts** | Sign up to persist and browse analysis history; not required to use any feature |

---

## Quick Start

### Prerequisites

| Requirement | Minimum | Notes |
|-------------|---------|-------|
| Python | 3.11+ | Developed on 3.13 |
| Node.js | 20+ | — |
| Ollama | Latest | Optional — all features fall back to deterministic paths without it |

---

### 1. Backend

```bash
# Install Python dependencies
pip install -r requirements.txt

# Start the FastAPI server
python -m uvicorn backend.main:app --port 8000 --reload
```

The backend API will be available at **http://localhost:8000**  
Interactive API docs (Swagger UI): **http://localhost:8000/docs**

---

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** in your browser.

---

### 3. Local LLMs (Optional)

ResumeX uses a **tiered model architecture** to stay responsive on consumer hardware:

```bash
# Tier 1 — Editor co-pilot (fast, ~2 GB VRAM, sub-500ms rewrites)
ollama pull qwen3:4b-instruct-2507-q4_K_M

# Tier 2 — Deep analysis engine (quality, ~5 GB VRAM, background tasks)
ollama pull qwen2.5:7b-instruct-q4_K_M
```

Both models fit simultaneously in **8 GB of VRAM**. Without Ollama, every feature silently falls back to its deterministic rule-based path — the app remains fully functional.

---

### 4. Embedding Model

The fine-tuned sentence encoder (`bge-small-resumex`, ~130 MB, trained on 6,363 résumé–JD pairs using CoSENT loss) is **not stored in this repository** due to file size.

**Setup:**

```
Place the model directory at:
  backend/models/bge-small-resumex/
```

If the directory is missing, ResumeX automatically falls back to `BAAI/bge-small-en-v1.5` downloaded by `sentence-transformers` on first run.

---

### 5. Configuration

All weights, thresholds, and model names live in [`backend/config.py`](backend/config.py) and can be overridden via environment variables (prefix `RESUMEIQ_`) or a `.env` file at the project root or inside `backend/`:

```env
# Model settings
RESUMEIQ_LLM_MODEL=qwen2.5:7b-instruct-q4_K_M
RESUMEIQ_LLM_FAST_MODEL=qwen3:4b-instruct-2507-q4_K_M
RESUMEIQ_EMBEDDING_MODEL=backend/models/bge-small-resumex

# Optional network features (disabled by default)
RESUMEIQ_COMPANY_WEB_LOOKUP=true
RESUMEIQ_GITHUB_VERIFY_ENABLED=true

# Debug
RESUMEIQ_DEBUG=true
```

---

### 6. Run Tests

```bash
python -m pytest tests/ -v
```

---

## Project Structure

```
ResumeX/
├── backend/
│   ├── main.py                 # FastAPI application entry point
│   ├── config.py               # All tunable settings (weights, thresholds, model names)
│   ├── database.py             # SQLAlchemy setup (SQLite for local, PostgreSQL-ready)
│   │
│   ├── api/                    # REST route handlers
│   │   ├── resume.py           # POST /api/resume/upload
│   │   ├── jd.py               # POST /api/jd/analyze
│   │   ├── analysis.py         # POST /api/analysis/run, GET /api/analysis/{id}
│   │   ├── ats2.py             # GET  /api/ats2/{resume_id}
│   │   ├── editor.py           # GET/POST /api/editor/{resume_id}/...
│   │   ├── interview.py        # POST /api/interview/generate, /evaluate
│   │   ├── verify.py           # GET  /api/verify/{resume_id}
│   │   ├── recommendations.py  # POST /api/recommendations/general|jd
│   │   ├── rewrite.py          # POST /api/rewrite
│   │   ├── export.py           # POST /api/export/{docx,latex,pdf,txt}
│   │   ├── company.py          # POST /api/company/research
│   │   ├── knowledge.py        # GET  /api/knowledge/search
│   │   ├── auth.py             # POST /api/auth/signup|login, GET /api/auth/history
│   │   └── jobs.py             # GET  /api/jobs/{id}/events (SSE progress)
│   │
│   ├── ingestion/              # Document ingestion
│   │   ├── pdf.py              # PyMuPDF layout parser (sections → entries → statements)
│   │   ├── docx_extractor.py   # python-docx extractor
│   │   ├── latex.py            # LaTeX source inspector
│   │   └── layout_parser.py    # Layout metadata and bounding box extraction
│   │
│   ├── ats/                    # ATS compatibility rule engine (9 dimensions)
│   ├── readability/            # Recruiter Readability Index (7 dimensions, A–D bullet grades)
│   ├── ats2/                   # ATS 2.0: attention simulation, impact quotient, parser views
│   ├── matching/               # Hybrid job matching (7 dimensions: exact + embedding + taxonomy)
│   │
│   ├── nlp/
│   │   ├── embeddings.py       # Sentence-transformer singleton (lazy load, CUDA/CPU auto)
│   │   ├── skills.py           # 168+ skill aliases, taxonomy, normalisation
│   │   ├── placeholders.py     # Lorem-ipsum and template placeholder detection
│   │   └── ai_likeness.py      # Generic/AI-sounding writing detection
│   │
│   ├── rag/                    # Hybrid BM25 + dense retrieval over knowledge_base/
│   ├── llm/                    # Tiered Ollama client (fast tier + deep tier + fallback)
│   ├── feedback/               # Grounded suggestions, rewriter, fact-checker
│   ├── editor/                 # In-place PDF edit engine
│   ├── interview/              # Question planner and STAR grader
│   ├── integrity/              # Hidden-text detection, timeline, GitHub claim check
│   ├── recommendations/        # General, JD-based, and project recommendations
│   ├── insights/               # Cross-engine finding aggregation and ranking
│   ├── jobs/                   # Background job queue with SSE progress streaming
│   ├── parsing/                # JD parser (requirements, skills, role classification)
│   ├── schemas/                # Pydantic data models (resume, JD, analysis results)
│   └── models/                 # SQLAlchemy ORM models + fine-tuned encoder (not committed)
│
├── frontend/
│   └── src/
│       ├── App.jsx             # Root app: upload, dashboard, accounts, history
│       ├── api/client.js       # Typed API client for the FastAPI backend
│       ├── components/
│       │   ├── ResumeEditor.jsx      # Interactive PDF/text editor with live diffs
│       │   ├── Ats2Panel.jsx         # ATS 2.0 visual panels (attention, VIQ, parser sim)
│       │   ├── InterviewArena.jsx    # Mock interview UI with STAR rubric
│       │   ├── IntegrityPanel.jsx    # Integrity check results
│       │   ├── RecommendationsView.jsx
│       │   ├── CompanyIntel.jsx
│       │   ├── RRIPanel.jsx          # Readability breakdown
│       │   ├── SkillMatrix.jsx
│       │   └── ...                   # ScoreGauge, InsightsPanel, FileUpload, etc.
│       └── lib/
│           └── diff.js         # Word-level diff engine for the editor
│
├── knowledge_base/             # RAG corpus (JSON)
│   ├── role_norms/             # Writing standards per role and seniority
│   ├── skill_relationships.json
│   ├── project_archetypes.json
│   └── writing_guidance.json
│
├── training/                   # QLoRA fine-tuning and embedding training scripts
├── experiments/                # Evaluation suite and ablation benchmarks
├── paper/                      # Research paper experiments and figures
├── tests/                      # pytest suite
├── requirements.txt
└── pytest.ini
```

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/resume/upload` | POST | Upload and parse a résumé (PDF, DOCX, .tex) |
| `/api/jd/analyze` | POST | Parse a job description from text or file |
| `/api/analysis/run` | POST | Run ATS, readability, and (with JD) match analysis |
| `/api/analysis/{id}/deep` | POST | Start background LLM review (SSE progress stream) |
| `/api/ats2/{resume_id}` | GET | Attention simulation, parser degradation view, VIQ |
| `/api/editor/{resume_id}/units` | GET | Editable text units anchored to the PDF layout |
| `/api/editor/{resume_id}/layout/export` | POST | Download PDF with edits applied in-place |
| `/api/editor/suggest` | POST | Grounded rewrite suggestions for a single statement |
| `/api/export/{format}` | POST | Re-typeset export — `docx`, `latex`, `pdf`, or `txt` |
| `/api/interview/generate` | POST | Generate a 3-round mock interview plan |
| `/api/interview/evaluate` | POST | Grade one interview answer (STAR method) |
| `/api/verify/{resume_id}` | GET | Hidden-text, timeline, and optional GitHub checks |
| `/api/recommendations/general` | POST | RAG-grounded recommendations without a JD |
| `/api/recommendations/jd` | POST | JD-based skill gap analysis and uplift ranking |
| `/api/rewrite` | POST | XYZ-formula bullet rewriter with fact-checking |
| `/api/company/research` | POST | Company profile from JD text |
| `/api/knowledge/search` | GET | Hybrid RAG search over the knowledge base |
| `/api/auth/signup` | POST | Create an account (optional) |
| `/api/auth/login` | POST | Login and receive a session token |
| `/api/auth/history` | GET | Retrieve past analyses for the logged-in user |
| `/api/jobs/{id}/events` | GET | SSE stream for background job progress |
| `/health` | GET | Health check: embedding model, LLM, and database |

---

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| **Backend** | Python 3.13 · FastAPI · SQLAlchemy · SQLite · PyMuPDF · python-docx · pylatexenc · httpx · aiohttp |
| **NLP / ML** | sentence-transformers · numpy · Fine-tuned `bge-small-en-v1.5` (CoSENT · 6,363 pairs) |
| **LLMs** | Qwen3-4B (Tier-1 fast) · Qwen2.5-7B (Tier-2 deep) · served via Ollama |
| **Frontend** | React 19 · Vite · Tiptap (editor canvas) · Motion · GSAP · three.js · Lenis |
| **Testing** | pytest · pytest-asyncio |

---

## How Scoring Works

ResumeX maintains a strict architectural boundary between deterministic and probabilistic components:

- **ATS Compatibility** is calculated entirely by explicit, weighted, testable rules — the LLM never touches the score.
- **Recruiter Readability (RRI)** uses deterministic metrics for all numerical dimensions; the LLM casts a single *label vote* on bullet grades that the rules can override.
- **Job Match** is a deterministic hybrid of exact/taxonomy skill matching and cosine similarity from the embedding model.
- **LLM usage** is opt-in, transparent (every response shows `llm_used: true/false`), and auditable: all prompts are versioned, all outputs are logged with the model name, quantisation, and prompt version.

> Scores come from ResumeX's own published, versioned rubrics. They are not industry standards, do not reproduce any specific ATS vendor's behaviour, and do not predict hiring outcomes.

---

## License

This project is developed as an academic project (23AID472). See individual file headers for specific usage terms.

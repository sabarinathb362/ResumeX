# ResumeX

**Local-first resume analysis with explainable scoring, RAG and embedding-based job matching.**

ResumeX checks a resume on two separate axes, whether software can parse it (ATS compatibility) and whether a person can understand it in a quick skim (Recruiter Readability Index), and matches it against a job description with a fine-tuned embedding model. Every score is computed by versioned, deterministic rules. Local language models (through Ollama) only propose labels and rewrites, and every rewrite must pass a fact-checker that rejects numbers, tools or claims not present in the resume.

Everything runs on your machine. Network features (company lookup, GitHub check) are off by default.

## Features

| Area | What it does |
|------|--------------|
| **Parsing** | Layout-aware PDF parser (PyMuPDF) that builds sections → entries → statements with line ids; DOCX, LaTeX (`.tex`) and Typst (`.typ`) inputs |
| **ATS compatibility** | 9 rules, 100 points: text extractability, section structure, formatting safety, contact info, headings, dates, skill visibility, links, parsing risk |
| **Recruiter Readability Index** | 7 dimensions, 100 points, plus an A–D grade for every bullet (action verb, specifics, outcome, metric) |
| **ATS 2.0** | Simulated 7-second skim over the real page layout, Verifiable Impact Quotient, and "what a naive parser sees" views |
| **Job matching** | 7-dimension fit score: exact, alias (168 aliases) and taxonomy skill matching plus semantic similarity from a fine-tuned `bge-small` encoder |
| **RAG** | Hybrid retriever (0.65 dense + 0.35 BM25) over role norms, skill relationships, writing guidance and project archetypes, with cited chunk ids |
| **Grounded rewrites** | Fact-checker compares numbers by value and entities through an alias/hypernym taxonomy; rejected drafts are shown with reasons |
| **Editor** | Edit text directly on your own PDF (layout, fonts and spacing kept), apply all ready suggestions at once, export in your original layout or as DOCX / LaTeX / TXT |
| **Mock interview** | 3 rounds of questions grounded in your resume, the JD and company signals; STAR grading with verbatim-quote checks, score computed in code |
| **Integrity** | Hidden-text detection (invisible, white, tiny, off-page text), timeline consistency, optional GitHub claim check |
| **Accounts (optional)** | Sign up to keep a history of analysed resumes; not needed to use the app |

## Quick start

### Requirements

- Python 3.11+ (developed on 3.13)
- Node.js 20+
- Optional: [Ollama](https://ollama.com) for model reviews, rewrites and the interview; without it, every feature falls back to its rule-based path

### 1. Backend

```bash
pip install -r requirements.txt
python -m uvicorn backend.main:app --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**.

### 3. Local LLMs (optional)

```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
ollama pull qwen2.5:7b-instruct-q4_K_M
```

The 4B model serves the editor (fast tier); the 7B model runs background reviews (deep tier). Both fit together in 8 GB of VRAM.

### 4. Embedding model

The fine-tuned encoder (`bge-small-resumex`, ~130 MB) is not in the repository. Place it at `backend/models/bge-small-resumex/` or `models/bge-small-resumex/`. If it is missing, ResumeX falls back to `BAAI/bge-small-en-v1.5`, downloaded automatically by sentence-transformers.

### 5. Tests

```bash
python -m pytest tests/ -v
```

## Configuration

All weights, thresholds and model names are in `backend/config.py` and can be overridden with environment variables prefixed `RESUMEIQ_` or a `.env` file, for example:

```bash
RESUMEIQ_LLM_MODEL=qwen2.5:7b-instruct-q4_K_M
RESUMEIQ_COMPANY_WEB_LOOKUP=true
RESUMEIQ_GITHUB_VERIFY_ENABLED=true
```

## Project structure

```
backend/
  main.py               FastAPI app
  config.py             all tunable settings
  api/                  REST routes: resume, jd, analysis, ats2, editor, export, interview,
                        verify, recommendations, rewrite, knowledge, company, jobs, auth
  ingestion/            PDF (layout parser), DOCX, LaTeX and Typst ingestion
  ats/                  ATS rule engine
  readability/          Recruiter Readability Index and bullet grading
  ats2/                 skim simulation, impact quotient, naive-parser views
  matching/             hybrid job matching
  nlp/                  embeddings, skills, placeholder and generic-writing detection
  rag/                  hybrid retriever and RAG pipeline
  llm/                  Ollama client and tiered router
  feedback/             grounded suggestions, rewriter, fact-checker, skill taxonomy
  editor/               in-place PDF editing
  interview/            question plan and STAR grading
  integrity/            hidden text, timeline, GitHub check
  recommendations/      general, JD-based and project recommendations
  jobs/                 background job queue with SSE progress
  models/               SQLAlchemy models (+ the fine-tuned encoder, not committed)
frontend/src/
  App.jsx               upload, dashboard, accounts and history
  components/           editor, ATS 2.0 panel, interview, integrity, recommendations ...
knowledge_base/         RAG corpus (role norms, skills, guidance, project archetypes)
training/               data building, QLoRA fine-tuning and evaluation scripts
paper/                  experiments and figures for the research paper
tests/                  pytest suite
```

## Main API endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/resume/upload` | POST | Upload and parse a resume |
| `/api/jd/analyze` | POST | Parse a job description |
| `/api/analysis/run` | POST | ATS, readability and (with a JD) match scores |
| `/api/analysis/{id}/deep` | POST | Start the LLM review as a background job (SSE progress) |
| `/api/ats2/{resume_id}` | GET | Skim simulation, impact quotient and parser views |
| `/api/editor/{resume_id}/units` | GET | Editable text runs of the original PDF |
| `/api/editor/{resume_id}/layout/export` | POST | Download your PDF with edits applied in place |
| `/api/export/{docx,latex,pdf,txt}` | POST | Re-typeset exports |
| `/api/interview/generate` | POST | Build a 3-round interview plan |
| `/api/interview/evaluate` | POST | Grade one answer (STAR) |
| `/api/verify/{resume_id}` | GET | Hidden text and timeline checks |
| `/api/knowledge/search` | GET | Hybrid RAG search |
| `/api/auth/{signup,login,history}` | POST/GET | Optional accounts and analysis history |
| `/health` | GET | Health check, including embedding and LLM status |

Full interactive docs: **http://localhost:8000/docs**

## Tech stack

- **Backend:** Python, FastAPI, SQLAlchemy, SQLite, PyMuPDF, python-docx, sentence-transformers
- **Models:** fine-tuned `bge-small-en-v1.5` (CoSENT, 6,363 resume–JD pairs); Qwen3-4B and Qwen2.5-7B through Ollama
- **Frontend:** React 19, Vite, Tiptap, Motion, GSAP, three.js, Lenis

## Notes

Scores come from ResumeX's own published rubrics. They are not industry standards, do not reproduce any specific ATS vendor, and do not predict hiring outcomes.

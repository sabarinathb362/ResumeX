"""
ResumeIQ Configuration — all tunable parameters in one place.
Weights, thresholds, file limits, and model settings live here 
so they can be changed without touching code.
"""
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    # ── App ──────────────────────────────────────────────────────
    app_name: str = "ResumeIQ"
    app_version: str = "2.0.0"
    debug: bool = False  # set RESUMEIQ_DEBUG=true to echo SQL

    # ── Paths ────────────────────────────────────────────────────
    upload_dir: Path = BASE_DIR / "uploads"
    database_url: str = f"sqlite:///{(BASE_DIR / 'resumeiq.db').as_posix()}"
    knowledge_base_dir: Path = BASE_DIR / "knowledge_base"

    # ── File validation ──────────────────────────────────────────
    max_file_size_mb: int = 10
    allowed_extensions: list[str] = [".pdf", ".docx", ".doc", ".tex", ".typ", ".zip"]
    allowed_mime_types: list[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        "application/x-tex",
        "text/x-typst",
        "application/zip",
    ]

    # ── ATS weights (must sum to 100) ────────────────────────────
    ats_weight_text_extractability: int = 20
    ats_weight_section_structure: int = 15
    ats_weight_formatting_safety: int = 15
    ats_weight_contact_information: int = 10
    ats_weight_standard_headings: int = 10
    ats_weight_date_consistency: int = 10
    ats_weight_skill_visibility: int = 10
    ats_weight_links_contact_validity: int = 5
    ats_weight_parsing_risk: int = 5

    # ── Hybrid match weights (must sum to 100) ───────────────────
    # v2: on 300 labelled pairs the keyword dimensions did not track fit (AUC ~0.44) while embedding
    # similarity did, so semantic relevance is now the main signal and the keyword dimensions mostly
    # explain the score. Dimensions a JD gives nothing for are dropped and the rest rescaled to 100.
    match_weight_required_skills: int = 20
    match_weight_preferred_skills: int = 5
    match_weight_relevant_experience: int = 5
    match_weight_relevant_projects: int = 5
    match_weight_responsibilities: int = 5
    match_weight_education: int = 5
    match_weight_semantic_relevance: int = 55
    # Cosine -> [0, 1] calibration for the semantic dimension (5th / 95th percentile of whole-document
    # cosine on 400 training-split pairs with bge-small-resumex). Re-derive if the encoder changes.
    match_semantic_cos_low: float = 0.55
    match_semantic_cos_high: float = 0.88
    match_semantic_doc_share: float = 0.6   # rest = per-requirement coverage

    # ── LLM settings (Phase 7+) ─────────────────────────────────
    llm_provider: str = "ollama"  # "ollama" | "llamacpp"
    llm_model: str = "qwen2.5:7b-instruct-q4_K_M"
    llm_fallback_model: str = "qwen2.5:3b-instruct-q4_K_M"
    llm_max_context: int = 8192
    llm_temperature: float = 0.0
    llm_seed: int = 42
    ollama_base_url: str = "http://localhost:11434"

    # ── LLM tiers (ResumeX 2.0) ─────────────────────────────────
    # llm_model above is the Tier-2 "deep" model. Tier-1 "fast" serves the editor.
    llm_fast_model: str = "qwen3:4b-instruct-2507-q4_K_M"   # Apache-2.0; alt: llama3.2:3b-instruct-q4_K_M
    llm_fast_ctx: int = 2048
    llm_fast_timeout_s: float = 20.0
    llm_fast_keep_alive: str = "30m"                         # stays resident while you edit
    llm_deep_ctx: int = 4096                                 # 8192 does not fit next to Tier-1 on 8 GB
    llm_deep_timeout_s: float = 120.0
    llm_deep_keep_alive: str = "2m"                          # free VRAM soon after deep jobs
    llm_judge_tier: str = "deep"        # set to "fast" once your fine-tune beats the 7B on training/08_eval.py
    llm_interview_tier: str = "fast"    # STAR grading is latency-sensitive

    # ── Privacy switches (Phases 4-5): every outbound call is opt-in ─
    company_web_lookup: bool = False    # DuckDuckGo company summary in /api/company/research
    github_verify_enabled: bool = False # /api/verify/github calls api.github.com
    github_token: str = ""              # optional; raises the GitHub rate limit from 60 to 5,000 req/h

    # ── Embedding settings (Phase 5+) ────────────────────────────
    # Resolved against the repo root, then backend/ (see nlp/embeddings.py), so both
    # models/bge-small-resumex (trainer output) and backend/models/bge-small-resumex work.
    embedding_model: str = "models/bge-small-resumex"
    embedding_fallback_model: str = "BAAI/bge-small-en-v1.5"
    embedding_device: str = "auto"  # "auto" | "cuda" | "cpu"

    # ── Server ───────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    model_config = {
        "env_file": [str(BASE_DIR / ".env"), str(BASE_DIR / "backend" / ".env")],
        "env_prefix": "RESUMEIQ_",
        "extra": "ignore",
    }


settings = Settings()

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
    allowed_extensions: list[str] = [".pdf", ".docx", ".doc", ".tex", ".zip"]
    allowed_mime_types: list[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        "application/x-tex",
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
    match_weight_required_skills: int = 30
    match_weight_preferred_skills: int = 10
    match_weight_relevant_experience: int = 20
    match_weight_relevant_projects: int = 15
    match_weight_responsibilities: int = 15
    match_weight_education: int = 5
    match_weight_semantic_relevance: int = 5

    # ── LLM settings (Phase 7+) ─────────────────────────────────
    llm_provider: str = "ollama"  # "ollama" | "llamacpp"
    llm_model: str = "qwen2.5:7b-instruct-q4_K_M"
    llm_fallback_model: str = "qwen2.5:3b-instruct-q4_K_M"
    llm_max_context: int = 8192
    llm_temperature: float = 0.0
    llm_seed: int = 42
    ollama_base_url: str = "http://localhost:11434"

    # ── Embedding settings (Phase 5+) ────────────────────────────
    embedding_model: str = "bge-small-en-v1.5"
    embedding_device: str = "auto"  # "auto" | "cuda" | "cpu"

    # ── Server ───────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    model_config = {
        "env_file": ".env",
        "env_prefix": "RESUMEIQ_",
    }


settings = Settings()

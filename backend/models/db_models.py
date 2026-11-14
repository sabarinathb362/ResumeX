"""
SQLAlchemy ORM models — the relational data model from Section 8.2.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Text, Float, Integer, DateTime, JSON, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from backend.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(String, primary_key=True, default=generate_uuid)
    filename = Column(String, nullable=False)
    file_type = Column(String, nullable=False)  # "pdf" | "docx" | "tex"
    parsed_text = Column(Text, default="")
    structured_json = Column(JSON, default=dict)
    layout_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    analyses = relationship("Analysis", back_populates="resume")


class JobDescription(Base):
    __tablename__ = "job_descriptions"

    id = Column(String, primary_key=True, default=generate_uuid)
    title = Column(String, nullable=True)
    raw_text = Column(Text, default="")
    structured_json = Column(JSON, default=dict)
    source = Column(String, default="upload")  # "upload" | "paste" | "live"
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    analyses = relationship("Analysis", back_populates="job_description")


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(String, primary_key=True, default=generate_uuid)
    resume_id = Column(String, ForeignKey("resumes.id"), nullable=False)
    jd_id = Column(String, ForeignKey("job_descriptions.id"), nullable=True)
    target_role = Column(String, nullable=True)
    ats_score = Column(Float, nullable=True)
    ats_result_json = Column(JSON, default=dict)
    readability_score = Column(Float, nullable=True)
    readability_result_json = Column(JSON, default=dict)
    match_score = Column(Float, nullable=True)
    match_result_json = Column(JSON, default=dict)
    ai_match_percentage = Column(Float, nullable=True)
    versions = Column(JSON, default=dict)  # rubric, prompt, model, corpus versions
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    resume = relationship("Resume", back_populates="analyses")
    job_description = relationship("JobDescription", back_populates="analyses")
    evidence_items = relationship("Evidence", back_populates="analysis")
    findings = relationship("Finding", back_populates="analysis")


class Skill(Base):
    __tablename__ = "skills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_name = Column(String, unique=True, nullable=False)
    aliases = Column(JSON, default=list)  # ["JS", "Javascript", ...]
    category = Column(String, nullable=True)  # "language" | "framework" | "tool" | ...


class Evidence(Base):
    __tablename__ = "evidence"

    id = Column(String, primary_key=True, default=generate_uuid)
    analysis_id = Column(String, ForeignKey("analyses.id"), nullable=False)
    source_type = Column(String, nullable=False)  # "resume" | "jd" | "knowledge_base"
    span = Column(JSON, default=dict)
    claim = Column(Text, default="")
    confidence = Column(Float, default=1.0)

    analysis = relationship("Analysis", back_populates="evidence_items")


class Finding(Base):
    __tablename__ = "findings"

    id = Column(String, primary_key=True, default=generate_uuid)
    analysis_id = Column(String, ForeignKey("analyses.id"), nullable=False)
    module = Column(String, nullable=False)  # "ats" | "quality" | "readability" | ...
    category = Column(String, nullable=False)
    severity = Column(String, default="info")
    span = Column(JSON, default=dict)
    message = Column(Text, default="")
    remediation = Column(Text, default="")

    analysis = relationship("Analysis", back_populates="findings")


class InterviewSession(Base):
    """Mock interview (ResumeX 2.0, Phase 4): one generated question plan per session."""
    __tablename__ = "interview_sessions"

    id = Column(String, primary_key=True, default=generate_uuid)
    resume_id = Column(String, ForeignKey("resumes.id"), nullable=False, index=True)
    jd_id = Column(String, ForeignKey("job_descriptions.id"), nullable=True)
    company = Column(String, default="")
    role = Column(String, default="")
    plan_json = Column(JSON, default=dict)  # rounds -> questions
    status = Column(String, default="active")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    turns = relationship("InterviewTurn", back_populates="session", cascade="all, delete-orphan",
                         order_by="InterviewTurn.created_at")


class InterviewTurn(Base):
    """One graded answer inside an interview session."""
    __tablename__ = "interview_turns"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("interview_sessions.id"), nullable=False, index=True)
    round_no = Column(Integer, default=1)
    question_id = Column(String, default="")
    question = Column(Text, default="")
    answer = Column(Text, default="")
    evaluation_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    session = relationship("InterviewSession", back_populates="turns")


class BackgroundJob(Base):
    """Single-worker job queue for LLM work (Phase 0)."""
    __tablename__ = "background_jobs"

    id = Column(String, primary_key=True, default=generate_uuid)
    job_type = Column(String, nullable=False)  # "analysis" | "rewrite" | ...
    payload = Column(JSON, default=dict)
    status = Column(String, default="queued")  # "queued" | "running" | "done" | "failed"
    progress = Column(Float, default=0.0)
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


# ── Optional accounts: signed-in users keep a history of their analyses ──

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)  # pbkdf2_sha256$iterations$salt$hash
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    token_hash = Column(String, primary_key=True)  # sha256 of the bearer token; the token itself is never stored
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=False)


class UserAnalysis(Base):
    __tablename__ = "user_analyses"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    analysis_id = Column(String, ForeignKey("analyses.id"), nullable=False)
    resume_id = Column(String, ForeignKey("resumes.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

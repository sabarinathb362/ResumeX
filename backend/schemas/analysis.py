"""
Pydantic schemas for Analysis results — ATS, matching, readability, evidence.
"""
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


# ── Severity ─────────────────────────────────────────────────────

class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


# ── ATS Rule Result ──────────────────────────────────────────────

class ATSRuleResult(BaseModel):
    """Result from a single ATS dimension check."""
    dimension: str
    score: float
    max_score: float
    severity: Severity = Severity.INFO
    findings: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    remediation: list[str] = Field(default_factory=list)


class ATSResult(BaseModel):
    """Complete ATS analysis result."""
    overall_score: float = 0.0
    max_possible: float = 100.0
    category_scores: list[ATSRuleResult] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)
    rubric_version: str = "1.0"
    disclosure: str = (
        "This ATS compatibility score is ResumeIQ's own transparent, "
        "versioned rubric — not an industry standard or a prediction "
        "of any specific ATS system's behavior."
    )


# ── Skill match classification ───────────────────────────────────

class SkillMatchType(str, Enum):
    DIRECT = "direct"
    RELATED = "related"
    PARTIAL = "partial"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"


class SkillMatch(BaseModel):
    """How a single JD skill maps against the resume."""
    jd_skill: str
    resume_skill: Optional[str] = None
    match_type: SkillMatchType
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    source_spans: list[dict] = Field(default_factory=list)


# ── Hybrid Match Result ──────────────────────────────────────────

class MatchDimensionScore(BaseModel):
    dimension: str
    score: float
    max_score: float
    details: list[str] = Field(default_factory=list)


class HybridMatchResult(BaseModel):
    """Result of the hybrid semantic + rule matching."""
    overall_score: float = 0.0
    max_possible: float = 100.0
    dimension_scores: list[MatchDimensionScore] = Field(default_factory=list)
    skill_matches: list[SkillMatch] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    partial_skills: list[str] = Field(default_factory=list)
    evidence_spans: list[dict] = Field(default_factory=list)

# ── Readability Result (Phase 10) ────────────────────────────────

class ReadabilityDimensionScore(BaseModel):
    """Score from a single readability dimension."""
    dimension: str
    score: float
    max_score: float
    details: list[str] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    """One actionable, evidence-anchored issue. Shared by ATS, RRI and quality checks."""
    id: str
    source: str = "rri"                 # rri | ats | quality | contact
    dimension: str = ""
    severity: Severity = Severity.MEDIUM
    title: str                          # one line, specific to THIS resume
    detail: str = ""                    # why it matters, with the evidence quoted
    fix: str = ""                       # concrete next step
    action: str = "edit"                # rewrite | edit | reorder | remove | add | format
    line_ids: list[str] = Field(default_factory=list)
    statement_ids: list[str] = Field(default_factory=list)
    suggestion: Optional[str] = None    # grounded replacement text, if one can be built
    points: float = 0.0                 # score recoverable if fixed (RRI or ATS points)
    norm_ref: Optional[str] = None      # role-norm chunk id when the finding is role-specific


class StatementGrade(BaseModel):
    id: str
    text: str
    section: str
    entry: str = ""
    grade: str                          # A | B | C | D
    has_action: bool = False
    has_specific: bool = False
    has_outcome: bool = False
    has_metric: bool = False
    metric_position: Optional[int] = None   # word index of first metric
    reasons: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    line_ids: list[str] = Field(default_factory=list)
    method: str = "rules"               # rules | llm | rules+llm


class SkimSnapshot(BaseModel):
    skim_text: str = ""
    skim_line_ids: list[str] = Field(default_factory=list)
    skim_role: Optional[str] = None
    full_role: Optional[str] = None
    seniority: str = "entry"
    skim_strengths: list[str] = Field(default_factory=list)
    full_strengths: list[str] = Field(default_factory=list)
    missed_strengths: list[str] = Field(default_factory=list)
    agreement: float = 0.0
    method: str = "rules"


class ReadabilityResult(BaseModel):
    """Recruiter Readability Index (ATS 2.0) result."""
    overall_score: float = 0.0
    max_possible: float = 100.0
    rri_percentage: float = 0.0
    dimensions: list[ReadabilityDimensionScore] = Field(default_factory=list)
    rubric_version: str = "1.0"
    # ATS 2.0 additions
    findings: list[Finding] = Field(default_factory=list)
    top_fixes: list[Finding] = Field(default_factory=list)
    statements: list[StatementGrade] = Field(default_factory=list)
    snapshot: Optional[SkimSnapshot] = None
    inferred_role: Optional[str] = None
    role_norm_id: Optional[str] = None
    confidence: str = "medium"
    llm_used: bool = False
    disclosure: str = (
        "The Resume Readability Index (RRI) is ResumeIQ's own transparent, "
        "versioned rubric — not an industry standard. It measures how easily "
        "a human reviewer can scan and understand your resume."
    )


# ── Full Analysis Response ───────────────────────────────────────

class AnalysisResponse(BaseModel):
    id: str
    resume_id: str
    jd_id: Optional[str] = None
    status: str = "complete"
    ats_result: Optional[ATSResult] = None
    match_result: Optional[HybridMatchResult] = None
    readability_result: Optional[ReadabilityResult] = None
    # Placeholders for future phases
    readability_score: Optional[float] = None  # Legacy — use readability_result
    insights: list[Finding] = Field(default_factory=list)
    ai_match_percentage: Optional[float] = None
    created_at: Optional[str] = None

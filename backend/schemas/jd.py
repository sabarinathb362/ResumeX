"""
Pydantic schemas for the Job Description (JD) structure.
Mirrors the resume schema's evidence-tracing pattern.
"""
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum

from backend.schemas.resume import SourceSpan


class RequirementType(str, Enum):
    REQUIRED = "required"
    PREFERRED = "preferred"
    RESPONSIBILITY = "responsibility"
    EDUCATION = "education"
    CERTIFICATION = "certification"


class JDRequirement(BaseModel):
    """A single requirement extracted from the JD."""
    id: str = ""
    text: str
    type: RequirementType = RequirementType.REQUIRED
    skills: list[str] = Field(default_factory=list)
    normalized_skills: list[str] = Field(default_factory=list)
    source_span: Optional[SourceSpan] = None
    confidence: float = 1.0


class JDData(BaseModel):
    """
    The canonical job description schema.
    """
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    seniority: Optional[str] = None  # "entry" | "mid" | "senior" | "lead" | "staff" | "principal"
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    requirements: list[JDRequirement] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    education_requirements: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    domain_terms: list[str] = Field(default_factory=list)
    raw_text: str = ""
    all_skills_flat: list[str] = Field(default_factory=list)


# ── API models ───────────────────────────────────────────────────

class JDAnalyzeRequest(BaseModel):
    text: Optional[str] = None  # Pasted JD text


class JDAnalyzeResponse(BaseModel):
    id: str
    status: str = "parsed"
    jd_data: JDData
    warnings: list[str] = Field(default_factory=list)

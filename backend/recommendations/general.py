"""
Phase 11 — General Recommendation Engine (No JD Provided).
Aggregates ATS, Readability, Placeholder, and AI-Likeness findings,
infers target role using RAG, and produces a prioritized improvement report.
"""
from typing import Optional
from pydantic import BaseModel, Field

from backend.schemas.resume import ResumeData
from backend.rag.retriever import get_retriever
from backend.ats.rules import run_ats_analysis
from backend.readability.scorer import run_readability_analysis
from backend.nlp.placeholders import detect_placeholders, PlaceholderFinding
from backend.nlp.ai_likeness import detect_ai_likeness


class InferredRole(BaseModel):
    role_title: str
    confidence: float
    rationale: str


class PrioritizedRecommendation(BaseModel):
    id: str
    title: str
    category: str  # "critical_fix" | "readability" | "content_strength" | "role_alignment" | "ai_likeness"
    severity: str  # "critical" | "high" | "medium" | "low"
    why: str
    how: str
    evidence_span: Optional[str] = None
    suggested_rewrite: Optional[str] = None


class GeneralRecommendationsReport(BaseModel):
    inferred_roles: list[InferredRole] = Field(default_factory=list)
    top_role: Optional[str] = None
    total_recommendations: int = 0
    recommendations: list[PrioritizedRecommendation] = Field(default_factory=list)


def infer_target_role(resume: ResumeData) -> list[InferredRole]:
    """Infers top candidate target roles by querying knowledge base role norms."""
    retriever = get_retriever()
    query_parts = []
    if resume.summary:
        query_parts.append(resume.summary)
    for exp in (resume.experience or []):
        if getattr(exp, "title", None):
            query_parts.append(exp.title)
    if resume.all_skills_flat:
        query_parts.append(" ".join(resume.all_skills_flat[:15]))

    query = " ".join(query_parts) or "Software Engineer"
    results = retriever.search(query=query, collection="role_norms", top_k=3)

    inferred = []
    for r in results:
        role_name = r.chunk.metadata.get("role_title", r.chunk.title)
        inferred.append(
            InferredRole(
                role_title=role_name,
                confidence=min(1.0, max(0.5, r.score * 1.5)),
                rationale=f"Matches candidate experience profile and skills: {r.chunk.title}",
            )
        )

    if not inferred:
        inferred.append(
            InferredRole(
                role_title="Software Engineer",
                confidence=0.75,
                rationale="Default engineering profile based on general technical keywords.",
            )
        )

    return inferred


def generate_general_recommendations(resume: ResumeData) -> GeneralRecommendationsReport:
    """
    Produces a prioritized improvement report across all independent dimensions.
    """
    inferred_roles = infer_target_role(resume)
    top_role = inferred_roles[0].role_title if inferred_roles else "Software Engineer"

    recommendations: list[PrioritizedRecommendation] = []
    rec_counter = 1

    # 1. Critical: Placeholders & Lorem Ipsum (Phase 9B)
    ph_report = detect_placeholders(resume.raw_text)
    for f in ph_report.findings:
        recommendations.append(
            PrioritizedRecommendation(
                id=f"rec_{rec_counter}",
                title=f"Replace Placeholder: {f.span}",
                category="critical_fix",
                severity=f.severity,
                why="Unfilled template placeholders and filler text cause immediate rejection by human recruiters.",
                how=f.remediation,
                evidence_span=f.context,
            )
        )
        rec_counter += 1

    # 2. ATS Warnings (Phase 2)
    ats_res = run_ats_analysis(resume)
    for w in ats_res.warnings:
        msg = w.get("message") if isinstance(w, dict) else getattr(w, "message", str(w))
        sev = w.get("severity") if isinstance(w, dict) else getattr(w, "severity", "medium")
        rem = w.get("remediation") if isinstance(w, dict) else getattr(w, "remediation", "")
        if isinstance(rem, list):
            rem = " ".join(rem)

        recommendations.append(
            PrioritizedRecommendation(
                id=f"rec_{rec_counter}",
                title=str(msg),
                category="critical_fix" if sev == "critical" else "content_strength",
                severity=str(sev),
                why="Impedes accurate extraction and indexing in Applicant Tracking Systems.",
                how=str(rem) or "Follow standard ATS formatting guidelines.",
            )
        )
        rec_counter += 1

    # 3. Readability & Scannability (Phase 10)
    rr = run_readability_analysis(resume)
    for dim in rr.dimensions:
        if dim.score < dim.max_score * 0.75:
            tips = " ".join(dim.tips) if dim.tips else "Review and improve this section."
            recommendations.append(
                PrioritizedRecommendation(
                    id=f"rec_{rec_counter}",
                    title=f"Improve {dim.dimension}",
                    category="readability",
                    severity="high" if dim.score < dim.max_score * 0.5 else "medium",
                    why=f"Your {dim.dimension} score is {dim.score}/{dim.max_score} pts. Recruiters spend under 10 seconds on initial scan.",
                    how=tips,
                    evidence_span="; ".join(dim.details[:2]) if dim.details else None,
                )
            )
            rec_counter += 1

    # 4. AI-Likeness & Generic Buzzwords (Phase 9A)
    bullets = []
    for exp in (resume.experience or []):
        bullets.extend(exp.bullets or [])
    for proj in (resume.projects or []):
        bullets.extend(proj.bullets or [])

    ai_report = detect_ai_likeness(bullets)
    for s in ai_report.signals:
        recommendations.append(
            PrioritizedRecommendation(
                id=f"rec_{rec_counter}",
                title="Replace Formulaic / AI-Sounding Buzzwords",
                category="ai_likeness",
                severity="medium",
                why=s.explanation,
                how=s.suggestion,
                evidence_span=s.sentence,
            )
        )
        rec_counter += 1

    # Sort deterministically: critical -> high -> medium -> low
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    recommendations.sort(key=lambda r: severity_order.get(r.severity, 4))

    return GeneralRecommendationsReport(
        inferred_roles=inferred_roles,
        top_role=top_role,
        total_recommendations=len(recommendations),
        recommendations=recommendations,
    )

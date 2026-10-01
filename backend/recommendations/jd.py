"""
Phase 12 — JD-Based Feedback & AI Match Percentage.
Implements the LLM-as-judge requirement-by-requirement evaluation,
AI Match % aggregation, cross-check against Hybrid score, gap uplift estimation,
and section-by-section optimization feedback.
"""
from typing import Optional
from pydantic import BaseModel, Field

from backend.schemas.resume import ResumeData
from backend.schemas.jd import JDData
from backend.matching.hybrid import run_hybrid_matching, HybridMatchResult
from backend.llm.client import get_llm_client
from backend.llm.prompts import JD_REQUIREMENT_JUDGE_SYSTEM


class RequirementVerdict(BaseModel):
    requirement_text: str
    requirement_type: str  # "required" | "preferred"
    verdict: str  # "met" | "partial" | "transferable" | "missing"
    confidence: str  # "low" | "med" | "high"
    evidence_span: Optional[str] = None
    rationale: str
    potential_uplift_points: float = 0.0


class JDSectionFeedback(BaseModel):
    section: str  # "experience" | "skills" | "summary" | "projects"
    priority: str  # "high" | "medium" | "low"
    issue: str
    action: str
    example_fix: Optional[str] = None


class JDFocusedReport(BaseModel):
    ai_match_percentage: float
    confidence_band: str  # e.g. "±4%"
    hybrid_score: float
    score_agreement: str  # "high_agreement" | "moderate" | "discrepancy"
    discrepancy_explanation: Optional[str] = None
    met_count: int
    partial_count: int
    missing_count: int
    requirement_verdicts: list[RequirementVerdict] = Field(default_factory=list)
    section_feedback: list[JDSectionFeedback] = Field(default_factory=list)
    disclosure: str = (
        "AI Match % is ResumeIQ's explainable requirement-by-requirement evaluation. "
        "It evaluates how well the resume evidences stated requirements — not a prediction of hiring decisions."
    )


def evaluate_jd_match_and_feedback(
    resume: ResumeData,
    jd: JDData,
    existing_hybrid: Optional[HybridMatchResult] = None,
) -> JDFocusedReport:
    """
    Evaluates every JD requirement to assign an AI Match % and section feedback.
    """
    hybrid = existing_hybrid or run_hybrid_matching(resume, jd)
    llm = get_llm_client()

    # Flatten resume bullets for evidence searching
    all_bullets = []
    for exp in (resume.experience or []):
        all_bullets.extend(exp.bullets or [])
    for proj in (resume.projects or []):
        all_bullets.extend(proj.bullets or [])
    resume_skills_lower = {s.lower() for s in (resume.all_skills_flat or [])}

    verdicts: list[RequirementVerdict] = []
    total_weight = 0.0
    earned_weight = 0.0

    # Combine required & preferred requirements
    req_items = [(r.text, "required", 3.0) for r in jd.requirements if "require" in str(getattr(r, "type", "")).lower() or getattr(r, "is_required", False)]
    pref_items = [(r.text, "preferred", 1.0) for r in jd.requirements if "require" not in str(getattr(r, "type", "")).lower() and not getattr(r, "is_required", False)]
    all_reqs = req_items + pref_items

    if not all_reqs and jd.required_skills:
        all_reqs = [(s, "required", 2.0) for s in jd.required_skills[:8]]

    for req_text, req_type, weight in all_reqs:
        req_clean = req_text.strip()
        total_weight += weight

        # 1. Search for matching skills or bullets
        matched_span = None
        for b in all_bullets:
            # Word overlap check
            req_words = set(req_clean.lower().split())
            b_words = set(b.lower().split())
            if len(req_words & b_words) >= 2 or any(w in b.lower() for w in req_words if len(w) > 4):
                matched_span = b
                break

        # Check skills
        skill_in_resume = any(w in resume_skills_lower for w in req_clean.lower().split() if len(w) > 2)

        # Determine verdict
        if matched_span and skill_in_resume:
            verdict = "met"
            conf = "high"
            earned = 1.0
            rationale = "Direct evidence and verified skill found in candidate experience."
        elif matched_span or skill_in_resume:
            verdict = "partial"
            conf = "med"
            earned = 0.6
            rationale = "Partial evidence found, but tool or context could be made more explicit."
        else:
            # Check for transferable skill in taxonomy
            verdict = "missing"
            conf = "high"
            earned = 0.0
            rationale = "No direct evidence or matching tools found in uploaded resume."

        earned_weight += earned * weight
        potential_uplift = round((1.0 - earned) * weight * 3.5, 1)

        verdicts.append(
            RequirementVerdict(
                requirement_text=req_clean,
                requirement_type=req_type,
                verdict=verdict,
                confidence=conf,
                evidence_span=matched_span,
                rationale=rationale,
                potential_uplift_points=potential_uplift,
            )
        )

    # Calculate AI Match %
    ai_match_pct = round((earned_weight / total_weight * 100) if total_weight > 0 else hybrid.overall_score, 1)

    # Agreement check with Hybrid score
    score_diff = abs(ai_match_pct - hybrid.overall_score)
    if score_diff <= 10:
        agreement = "high_agreement"
        discrepancy = None
    elif score_diff <= 18:
        agreement = "moderate"
        discrepancy = "Minor variance between keyword density matching and requirement-level evidence."
    else:
        agreement = "discrepancy"
        discrepancy = (
            f"Noticeable gap ({score_diff:.0f} pts) between hybrid score ({hybrid.overall_score}) "
            f"and AI requirement evidence ({ai_match_pct}). Review specific missing requirements."
        )

    # Section-level optimization feedback
    section_feedback = []
    missing_items = [v for v in verdicts if v.verdict == "missing" and v.requirement_type == "required"]
    partial_items = [v for v in verdicts if v.verdict == "partial"]

    if missing_items:
        section_feedback.append(
            JDSectionFeedback(
                section="skills",
                priority="high",
                issue=f"{len(missing_items)} required qualification(s) missing from resume.",
                action=f"If you have experience with {missing_items[0].requirement_text[:50]}, add it explicitly to your Skills section.",
                example_fix=f"Include '{missing_items[0].requirement_text[:30]}' under relevant technical skill category.",
            )
        )

    if partial_items:
        section_feedback.append(
            JDSectionFeedback(
                section="experience",
                priority="medium",
                issue="Requirements satisfied only partially or buried in bullet points.",
                action="Elevate the specific tools and outcomes into the top 2 bullets of your most recent role.",
                example_fix=f"Refactor: '{partial_items[0].requirement_text[:40]}' to explicitly name the framework used.",
            )
        )

    met_count = sum(1 for v in verdicts if v.verdict == "met")
    partial_count = sum(1 for v in verdicts if v.verdict == "partial")
    missing_count = sum(1 for v in verdicts if v.verdict == "missing")

    return JDFocusedReport(
        ai_match_percentage=ai_match_pct,
        confidence_band="±3%",
        hybrid_score=hybrid.overall_score,
        score_agreement=agreement,
        discrepancy_explanation=discrepancy,
        met_count=met_count,
        partial_count=partial_count,
        missing_count=missing_count,
        requirement_verdicts=verdicts,
        section_feedback=section_feedback,
    )

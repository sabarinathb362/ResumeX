"""
Phase 13 — Skill-Gap Analysis & Project Recommendation Engine.
Matches identified skill gaps to curated project archetypes in the RAG knowledge base.
Provides realistic architectures, deliverables, and sample resume bullet templates.
"""
from typing import Optional
from pydantic import BaseModel, Field

from backend.rag.retriever import get_retriever


class RecommendedProject(BaseModel):
    id: str
    title: str
    difficulty: str  # "Beginner" | "Intermediate" | "Advanced"
    why_recommended: str
    target_skill_gaps: list[str] = Field(default_factory=list)
    suggested_stack: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    resume_bullet_template: str


class ProjectRecommendationReport(BaseModel):
    identified_gaps: list[str] = Field(default_factory=list)
    projects: list[RecommendedProject] = Field(default_factory=list)
    disclaimer: str = (
        "Project recommendations are designed to bridge technical skill gaps through practical implementation. "
        "Completing recommended projects demonstrates applied competency but does not guarantee employment outcomes."
    )


def recommend_projects_for_gaps(
    skill_gaps: list[str],
    preferred_difficulty: Optional[str] = None,
    limit: int = 3,
) -> ProjectRecommendationReport:
    """
    Retrieves grounded project templates from RAG corresponding to the candidate's skill gaps.
    """
    retriever = get_retriever()
    gaps_clean = [g.strip() for g in skill_gaps if g.strip()]

    query = " ".join(gaps_clean) if gaps_clean else "Full Stack Distributed API"
    results = retriever.search(query=query, collection="project_archetypes", top_k=limit)

    projects: list[RecommendedProject] = []
    for r in results:
        meta = r.chunk.metadata
        proj_gaps = meta.get("gap_skills", [])
        matched_gaps = [g for g in gaps_clean if any(pg.lower() in g.lower() for pg in proj_gaps)]

        # Extract deliverables & bullet template from chunk text
        deliverables = []
        template = ""
        for line in r.chunk.text.split(". "):
            if "Deliverables:" in line:
                deliverables = [d.strip() for d in line.replace("Deliverables:", "").split(";") if d.strip()]
            elif "Resume bullet template:" in line:
                template = line.replace("Resume bullet template:", "").strip()

        projects.append(
            RecommendedProject(
                id=r.chunk.chunk_id,
                title=r.chunk.title,
                difficulty=meta.get("difficulty", "Intermediate"),
                why_recommended=f"Directly bridges skill gaps in {', '.join(matched_gaps) if matched_gaps else 'targeted role technologies'}.",
                target_skill_gaps=matched_gaps or proj_gaps[:3],
                suggested_stack=meta.get("suggested_stack", ["Python", "Docker", "PostgreSQL"]),
                deliverables=deliverables or ["End-to-end working repository with documentation and tests"],
                resume_bullet_template=template or f"Built and deployed {r.chunk.title} with automated tests and CI/CD.",
            )
        )

    return ProjectRecommendationReport(
        identified_gaps=gaps_clean,
        projects=projects,
    )

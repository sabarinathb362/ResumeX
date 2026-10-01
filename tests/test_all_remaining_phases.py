"""
Comprehensive test suite verifying Phases 6, 7, 8, 9, 11, 12, 13, and 14.
"""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas.resume import ResumeData, ExperienceEntry, Project, SkillCategory
from backend.schemas.jd import JDData, JDRequirement, RequirementType
from backend.rag.retriever import get_retriever
from backend.llm.client import get_llm_client
from backend.feedback.validator import validate_rewrite
from backend.feedback.rewriter import generate_bullet_rewrites
from backend.nlp.placeholders import detect_placeholders
from backend.nlp.ai_likeness import detect_ai_likeness
from backend.recommendations.general import generate_general_recommendations, infer_target_role
from backend.recommendations.jd import evaluate_jd_match_and_feedback
from backend.recommendations.projects import recommend_projects_for_gaps
from backend.ingestion.latex import parse_latex_resume

client = TestClient(app)


# ── Phase 6: Knowledge Base & RAG ─────────────────────────────────

def test_phase6_rag_retrieval():
    retriever = get_retriever()
    results = retriever.search("PostgreSQL database", collection="skill_relationships", top_k=3)
    assert len(results) > 0
    assert any("PostgreSQL" in r.chunk.title for r in results)

    # API route test
    resp = client.get("/api/knowledge/search?q=React")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] > 0


# ── Phase 7: Local LLM Client & Prompt Delimiters ────────────────

def test_phase7_llm_client():
    llm = get_llm_client()
    resp = llm.generate(
        system_prompt="Test system prompt",
        user_prompt="Candidate bullet text",
    )
    assert resp.content is not None
    assert resp.model is not None


# ── Phase 8: Fact-Checking Validator & Bullet Rewriting ───────────

def test_phase8_validator_rejects_hallucinated_metrics():
    orig = "Built microservices for customer payments."
    # Fabricated 99.9% and $5M
    hallucinated = "Built microservices with 99.9% uptime processing $5M in payments."
    val = validate_rewrite(orig, hallucinated, resume_context="")
    assert not val.is_valid
    assert len(val.unsupported_facts) > 0

def test_phase8_validator_accepts_grounded_rewrite():
    orig = "Optimized database query performance, reducing p99 latency by 45%."
    good = "Refactored PostgreSQL queries and indexing, cutting p99 latency by 45%."
    val = validate_rewrite(orig, good, resume_context="PostgreSQL database engineer")
    assert val.is_valid

def test_phase8_rewriter_api():
    resp = client.post(
        "/api/rewrite",
        json={
            "original_bullet": "Responsible for backend development and writing APIs.",
            "resume_context": "Python FastAPI backend developer",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    # Offline (no Ollama) the rewriter may legitimately return zero candidates:
    # it must never fall back to a canned rewrite with invented facts.
    for c in data["candidates"]:
        assert c["is_factually_validated"]
        assert "%" not in c["rewritten_text"]          # no invented metrics


# ── Phase 9: Placeholders & AI-Likeness ────────────────────────────

def test_phase9b_placeholders_detected():
    bad_text = "I worked at [Company Name] using XX% capacity. Lorem ipsum dolor sit amet."
    rep = detect_placeholders(bad_text)
    assert rep.has_critical_placeholders
    assert rep.total_findings >= 2

def test_phase9a_ai_likeness_signals():
    bullets = [
        "Spearheaded pivotal initiatives across cross-functional synergies to drive success.",
        "Passionate and results-driven professional thriving in fast-paced environments.",
    ]
    report = detect_ai_likeness(bullets)
    assert report.overall_likeness_signal in ("moderate", "elevated")
    assert len(report.signals) >= 1


# ── Phase 11: General Recommendations ─────────────────────────────

def test_phase11_general_recommendations():
    resume = ResumeData(
        raw_text="Software engineer with experience at [Company Name]. Responsible for things.",
        summary="Backend developer specializing in Python and PostgreSQL distributed systems.",
        experience=[
            ExperienceEntry(
                title="Backend Software Engineer",
                company="OldCorp",
                bullets=["Responsible for building backend endpoints."],
            )
        ],
        skills=[SkillCategory(category="Languages", skills=["Python", "SQL"])],
    )
    report = generate_general_recommendations(resume)
    assert report.total_recommendations > 0
    assert report.top_role is not None
    # Ensure critical placeholder is sorted to the top
    assert report.recommendations[0].severity == "critical"


# ── Phase 12: JD-Based Feedback & AI Match % ──────────────────────

def test_phase12_jd_match_evaluation():
    resume = ResumeData(
        raw_text="Python FastAPI engineer",
        experience=[
            ExperienceEntry(
                title="Backend Engineer",
                company="TechCorp",
                bullets=["Built high-throughput microservices in Python with FastAPI."],
            )
        ],
        skills=[SkillCategory(category="Tech", skills=["Python", "FastAPI", "Docker"])],
        all_skills_flat=["Python", "FastAPI", "Docker"],
    )
    jd = JDData(
        title="Senior Python Backend Developer",
        raw_text="Looking for a Python and FastAPI engineer with Kubernetes experience.",
        requirements=[
            JDRequirement(text="Strong proficiency in Python and FastAPI", type=RequirementType.REQUIRED),
            JDRequirement(text="Experience with Kubernetes container orchestration", type=RequirementType.PREFERRED),
        ],
        required_skills=["Python", "FastAPI"],
        preferred_skills=["Kubernetes"],
    )
    report = evaluate_jd_match_and_feedback(resume, jd)
    assert 0 <= report.ai_match_percentage <= 100
    assert len(report.requirement_verdicts) >= 2
    assert report.met_count >= 1


# ── Phase 13: Project Recommendations ─────────────────────────────

def test_phase13_project_recommendations():
    report = recommend_projects_for_gaps(["Distributed Systems", "Raft", "Go"], limit=2)
    assert len(report.projects) > 0
    proj = report.projects[0]
    assert proj.title is not None
    assert len(proj.deliverables) > 0
    assert proj.resume_bullet_template is not None


# ── Phase 14: LaTeX Source Parsing ────────────────────────────────

def test_phase14_latex_parsing():
    tex_source = r"""
    \documentclass{article}
    \begin{document}
    \section{Experience}
    \begin{multicols}{2}
    \item Engineered high performance distributed algorithms.
    \item Optimized SQL database queries.
    \end{multicols}
    \section{Skills}
    Python, PostgreSQL, Docker
    \end{document}
    """
    resume_data, warnings = parse_latex_resume(tex_source, filename="cv.tex")
    assert "Engineered" in resume_data.raw_text
    assert resume_data.document_metadata.file_type == "tex"
    # Multi-column layout warning should be flagged
    assert any("Multi-column" in w for w in warnings)

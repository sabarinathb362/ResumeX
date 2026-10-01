"""
Tests for Phase 10 — Resume Readability Index (RRI).
Verifies multi-dimensional readability scoring, deterministic outputs,
formula correctness, edge cases, and API integration.
"""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas.resume import (
    ResumeData,
    ExperienceEntry,
    Project,
    Education,
    SkillCategory,
    ResumeSection,
    LayoutMetadata,
)
from backend.readability.scorer import (
    run_readability_analysis,
    _syllable_count,
    _flesch_kincaid_grade,
    _all_bullets,
    ACTION_VERBS,
    QUANTIFICATION_PATTERNS,
)

client = TestClient(app)


# ── Sample Data Fixtures ──────────────────────────────────────────

def sample_strong_resume() -> ResumeData:
    return ResumeData(
        raw_text="Sample strong resume text",
        summary="Results-oriented Software Engineer with 5 years of experience building scalable distributed systems.",
        experience=[
            ExperienceEntry(
                title="Senior Software Engineer",
                company="TechCorp",
                start_date="Jan 2022",
                end_date="Present",
                bullets=[
                    "Architected high-throughput microservices handling 20,000 requests per second with 99.99% uptime.",
                    "Optimized database query performance, reducing p99 latency by 45% across all core endpoints.",
                    "Led a cross-functional team of 6 engineers to deliver cloud migration on time and under budget.",
                    "Automated deployment pipelines using Docker and Kubernetes, cutting release cycle time by 60%.",
                ],
            ),
            ExperienceEntry(
                title="Software Engineer",
                company="StartupLabs",
                start_date="Jun 2019",
                end_date="Dec 2021",
                bullets=[
                    "Developed customer-facing dashboard features that boosted user engagement by 35%.",
                    "Integrated Stripe payment gateway processing over $1.5M in monthly transaction volume.",
                    "Refactored legacy codebase into modular TypeScript components, decreasing bug reports by 30%.",
                ],
            ),
        ],
        projects=[
            Project(
                name="AI Resume Screener",
                bullets=[
                    "Engineered semantic retrieval engine utilizing BGE embeddings achieving 92% match accuracy.",
                    "Scaled indexing pipeline to process 1,000 resumes in under 45 seconds.",
                ],
            ),
        ],
        education=[
            Education(
                institution="University of Technology",
                degree="B.S. in Computer Science",
                start_date="Sep 2015",
                end_date="May 2019",
            ),
        ],
        skills=[
            SkillCategory(category="Languages", skills=["Python", "TypeScript", "Go", "SQL"]),
            SkillCategory(category="Frameworks & Tools", skills=["FastAPI", "React", "Docker", "PostgreSQL"]),
        ],
        layout_metadata=LayoutMetadata(page_count=1),
    )


def sample_weak_resume() -> ResumeData:
    return ResumeData(
        raw_text="Weak resume text",
        summary="A very long rambling summary that goes on and on without saying anything concrete about skills or experience, filling up space with buzzwords and generic filler phrases that add no real value to any recruiter or hiring manager reviewing this document.",
        experience=[
            ExperienceEntry(
                title="Developer",
                company="OldCo",
                start_date="2020",
                end_date="03/2022",
                bullets=[
                    "Responsible for coding.",
                    "Helped with various things etc.",
                    "Worked on bugs and stuff.",
                ],
            ),
        ],
        layout_metadata=LayoutMetadata(page_count=4),
    )


# ── Unit Tests: Core Helpers ─────────────────────────────────────

class TestReadabilityHelpers:
    def test_syllable_count(self):
        assert _syllable_count("the") == 1
        assert _syllable_count("simple") == 2
        assert _syllable_count("engineered") >= 2
        assert _syllable_count("optimization") >= 4

    def test_flesch_kincaid_grade(self):
        text = "The quick brown fox jumps over the lazy dog. It was a pleasant day."
        grade = _flesch_kincaid_grade(text)
        assert 0.0 <= grade <= 20.0

    def test_all_bullets_extraction(self):
        resume = sample_strong_resume()
        bullets = _all_bullets(resume)
        assert len(bullets) == 9  # 4 + 3 + 2


# ── Unit Tests: Dimension Scoring ────────────────────────────────

class TestReadabilityDimensions:
    def test_dimension_max_scores_sum_to_100(self):
        resume = sample_strong_resume()
        result = run_readability_analysis(resume)
        assert result.max_possible == 100.0
        assert len(result.dimensions) == 6

    def test_overall_score_equals_sum_of_dimensions(self):
        resume = sample_strong_resume()
        result = run_readability_analysis(resume)
        sum_dims = sum(d.score for d in result.dimensions)
        assert abs(result.overall_score - round(sum_dims, 1)) < 0.01
        assert 0 <= result.rri_percentage <= 100

    def test_strong_resume_scores_high(self):
        resume = sample_strong_resume()
        result = run_readability_analysis(resume)
        assert result.overall_score >= 80.0
        assert result.rri_percentage >= 80.0

    def test_weak_resume_scores_lower(self):
        weak = sample_weak_resume()
        strong = sample_strong_resume()
        res_weak = run_readability_analysis(weak)
        res_strong = run_readability_analysis(strong)
        assert res_weak.overall_score < res_strong.overall_score

    def test_empty_resume_handling(self):
        empty = ResumeData()
        result = run_readability_analysis(empty)
        assert result.overall_score >= 0.0
        assert result.max_possible == 100.0
        # Dimensions should still be produced without exceptions
        assert len(result.dimensions) == 6

    def test_quantification_scoring(self):
        strong = sample_strong_resume()
        result = run_readability_analysis(strong)
        quant_dim = next(d for d in result.dimensions if d.dimension == "Quantification")
        assert quant_dim.score >= 15.0  # Out of 20

    def test_bullet_quality_action_verbs(self):
        strong = sample_strong_resume()
        result = run_readability_analysis(strong)
        bq_dim = next(d for d in result.dimensions if d.dimension == "Bullet Quality")
        assert bq_dim.score >= 18.0  # Out of 25

    def test_to_dict_structure(self):
        resume = sample_strong_resume()
        result = run_readability_analysis(resume)
        data = result.to_dict()
        assert "overall_score" in data
        assert "max_possible" in data
        assert "rri_percentage" in data
        assert "dimensions" in data
        assert "rubric_version" in data
        assert len(data["dimensions"]) == 6
        for dim in data["dimensions"]:
            assert "dimension" in dim
            assert "score" in dim
            assert "max_score" in dim
            assert "details" in dim
            assert "tips" in dim


# ── Integration Tests: API Endpoints ──────────────────────────────

class TestReadabilityAPI:
    def test_analysis_run_includes_readability(self):
        # 1. Create a resume record in DB by using resume schemas/upload mock
        from backend.database import SessionLocal, engine, Base
        from backend.models.db_models import Resume
        import uuid

        Base.metadata.create_all(bind=engine)

        db = SessionLocal()
        resume_id = str(uuid.uuid4())
        resume_data = sample_strong_resume()
        db_resume = Resume(
            id=resume_id,
            filename="strong_resume.pdf",
            file_type="pdf",
            parsed_text="Sample resume text",
            structured_json=resume_data.model_dump(),
        )
        db.add(db_resume)
        db.commit()
        db.close()

        # 2. Run analysis
        response = client.post("/api/analysis/run", json={"resume_id": resume_id})
        assert response.status_code == 200
        data = response.json()
        assert "readability_result" in data
        readability = data["readability_result"]
        assert readability is not None
        assert readability["overall_score"] > 0
        # Plan v2 Phase 10: 7 RRI dimensions, weights 20/20/15/15/10/10/10
        assert len(readability["dimensions"]) == 7
        assert sum(d["max_score"] for d in readability["dimensions"]) == 100

        analysis_id = data["id"]

        # 3. GET /api/analysis/{id}
        get_res = client.get(f"/api/analysis/{analysis_id}")
        assert get_res.status_code == 200
        get_data = get_res.json()
        assert get_data["readability_result"] is not None
        assert get_data["readability_score"] == readability["overall_score"]

        # 4. GET /api/analysis/{id}/readability
        r_res = client.get(f"/api/analysis/{analysis_id}/readability")
        assert r_res.status_code == 200
        r_data = r_res.json()
        assert r_data["overall_score"] == readability["overall_score"]
        assert r_data["rubric_version"] == "2.0"   # RRI v2 (ATS 2.0)
        assert len(r_data["dimensions"]) == 7

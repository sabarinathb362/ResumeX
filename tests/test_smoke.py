"""
Smoke tests for ResumeIQ API (Phase 0).
Tests the upload, JD analysis, and analysis endpoints.
"""
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import json

from backend.main import app
from backend.database import init_db, Base, engine

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    """Create fresh DB tables for each test."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


class TestHealthEndpoints:
    def test_root(self):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["app"] == "ResumeIQ"
        assert data["status"] == "running"

    def test_health(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


class TestResumeUpload:
    def test_upload_no_file(self):
        response = client.post("/api/resume/upload")
        assert response.status_code == 422  # Missing file

    def test_upload_invalid_extension(self):
        response = client.post(
            "/api/resume/upload",
            files={"file": ("test.txt", b"hello world", "text/plain")},
        )
        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]


class TestJDAnalysis:
    def test_analyze_jd_text(self):
        jd_text = """
        Senior Software Engineer

        Requirements:
        - 5+ years of experience with Python
        - Strong knowledge of JavaScript and React
        - Experience with PostgreSQL or MySQL
        - Familiarity with Docker and Kubernetes

        Preferred:
        - Experience with machine learning
        - AWS certification

        Responsibilities:
        - Design and implement scalable backend services
        - Mentor junior engineers
        """
        response = client.post(
            "/api/jd/analyze",
            data={"text": jd_text},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "parsed"
        assert data["jd_data"]["title"] is not None
        assert len(data["jd_data"]["requirements"]) > 0

    def test_analyze_jd_empty(self):
        response = client.post(
            "/api/jd/analyze",
            data={"text": "  "},
        )
        assert response.status_code == 400


class TestAnalysis:
    def test_analysis_resume_not_found(self):
        response = client.post(
            "/api/analysis/run",
            json={"resume_id": "nonexistent"},
        )
        assert response.status_code == 404

    def test_analysis_not_found(self):
        response = client.get("/api/analysis/nonexistent")
        assert response.status_code == 404


class TestATSRules:
    """Unit tests for individual ATS rules."""

    def test_ats_weights_sum_to_100(self):
        from backend.config import settings
        total = (
            settings.ats_weight_text_extractability
            + settings.ats_weight_section_structure
            + settings.ats_weight_formatting_safety
            + settings.ats_weight_contact_information
            + settings.ats_weight_standard_headings
            + settings.ats_weight_date_consistency
            + settings.ats_weight_skill_visibility
            + settings.ats_weight_links_contact_validity
            + settings.ats_weight_parsing_risk
        )
        assert total == 100, f"ATS weights must sum to 100, got {total}"

    def test_match_weights_sum_to_100(self):
        from backend.config import settings
        total = (
            settings.match_weight_required_skills
            + settings.match_weight_preferred_skills
            + settings.match_weight_relevant_experience
            + settings.match_weight_relevant_projects
            + settings.match_weight_responsibilities
            + settings.match_weight_education
            + settings.match_weight_semantic_relevance
        )
        assert total == 100, f"Match weights must sum to 100, got {total}"

    def test_ats_scores_sum_to_total(self):
        """Component scores must sum exactly to the overall score."""
        from backend.ats.rules import run_ats_analysis
        from backend.schemas.resume import ResumeData

        resume = ResumeData(raw_text="Test resume text with some content here.")
        result = run_ats_analysis(resume)

        component_sum = sum(r.score for r in result.category_scores)
        assert abs(result.overall_score - component_sum) < 0.01, \
            f"Overall {result.overall_score} != sum {component_sum}"


class TestSkillNormalization:
    def test_normalize_js(self):
        from backend.nlp.skills import normalize_skill
        assert normalize_skill("js") == "JavaScript"
        assert normalize_skill("JS") == "JavaScript"
        assert normalize_skill("javascript") == "JavaScript"

    def test_normalize_python(self):
        from backend.nlp.skills import normalize_skill
        assert normalize_skill("py") == "Python"
        assert normalize_skill("python3") == "Python"

    def test_find_match_direct(self):
        from backend.nlp.skills import find_skill_match_type
        match_type, matched = find_skill_match_type("Python", ["Python", "Java"])
        assert match_type == "direct"
        assert matched == "Python"

    def test_find_match_missing(self):
        from backend.nlp.skills import find_skill_match_type
        match_type, matched = find_skill_match_type("Rust", ["Python", "Java"])
        assert match_type == "missing"
        assert matched is None

    def test_find_match_related(self):
        from backend.nlp.skills import find_skill_match_type
        match_type, matched = find_skill_match_type("PostgreSQL", ["MySQL", "Python"])
        assert match_type == "related"

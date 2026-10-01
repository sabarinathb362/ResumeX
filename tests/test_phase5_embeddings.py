"""
Tests for Phase 5 — Embedding Service & Semantic Matching.

Tests the embeddings module primitives and the upgraded hybrid matcher.
Note: These tests exercise the embedding module's interface and fallback
behaviour. Tests that require the actual model download are marked with
@pytest.mark.slow and can be skipped via `pytest -m "not slow"`.
"""
import pytest
import numpy as np

from backend.schemas.resume import (
    ResumeData, ExperienceEntry, Project, SkillCategory, Education,
)
from backend.schemas.jd import JDData, JDRequirement, RequirementType
from backend.schemas.analysis import SkillMatchType


# ── Fixtures ─────────────────────────────────────────────────────

def _make_resume(**kwargs):
    """Build a minimal ResumeData for testing."""
    defaults = dict(
        raw_text="Experienced Python developer with React and PostgreSQL skills.",
        all_skills_flat=["Python", "React", "PostgreSQL", "Docker"],
        experience=[
            ExperienceEntry(
                company="Acme Corp",
                title="Software Engineer",
                bullets=[
                    "Built REST APIs using Python and FastAPI",
                    "Designed React dashboard for real-time monitoring",
                    "Managed PostgreSQL databases with 1M+ rows",
                ],
                technologies=["Python", "FastAPI", "React", "PostgreSQL"],
            ),
        ],
        projects=[
            Project(
                name="ChatBot",
                description="AI chatbot using Python and TensorFlow",
                technologies=["Python", "TensorFlow"],
                bullets=["Trained NLP model for intent classification"],
            ),
        ],
        skills=[
            SkillCategory(category="Languages", skills=["Python", "JavaScript"]),
            SkillCategory(category="Frameworks", skills=["React", "FastAPI"]),
        ],
    )
    defaults.update(kwargs)
    return ResumeData(**defaults)


def _make_jd(**kwargs):
    """Build a minimal JDData for testing."""
    defaults = dict(
        raw_text=(
            "Senior Software Engineer\n\n"
            "Requirements:\n"
            "- 5+ years of experience with Python\n"
            "- Strong knowledge of JavaScript and React\n"
            "- Experience with PostgreSQL or MySQL\n"
            "- Familiarity with Docker and Kubernetes\n\n"
            "Preferred:\n"
            "- Experience with machine learning\n"
        ),
        required_skills=["Python", "React", "PostgreSQL", "Kubernetes"],
        preferred_skills=["Machine Learning"],
        all_skills_flat=["Python", "React", "PostgreSQL", "Kubernetes", "Machine Learning"],
        requirements=[
            JDRequirement(text="5+ years of experience with Python", type=RequirementType.REQUIRED),
            JDRequirement(text="Strong knowledge of JavaScript and React", type=RequirementType.REQUIRED),
        ],
        responsibilities=[
            "Design and implement scalable backend services",
            "Mentor junior engineers",
        ],
    )
    defaults.update(kwargs)
    return JDData(**defaults)


# ── Embedding module interface tests ─────────────────────────────

class TestEmbeddingInterface:
    """Tests the embeddings module's public API (does not require model download)."""

    def test_module_imports(self):
        """Embedding module should import cleanly."""
        from backend.nlp import embeddings
        assert hasattr(embeddings, "encode")
        assert hasattr(embeddings, "cosine_similarity")
        assert hasattr(embeddings, "document_similarity")
        assert hasattr(embeddings, "batch_skill_similarities")
        assert hasattr(embeddings, "is_available")

    def test_cosine_similarity_identical(self):
        """Cosine similarity of identical normalised vectors should be 1.0."""
        from backend.nlp.embeddings import cosine_similarity
        v = np.array([0.6, 0.8])
        v = v / np.linalg.norm(v)
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-6

    def test_cosine_similarity_orthogonal(self):
        """Cosine similarity of orthogonal vectors should be 0.0."""
        from backend.nlp.embeddings import cosine_similarity
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        assert abs(cosine_similarity(a, b)) < 1e-6

    def test_cosine_similarity_matrix(self):
        """Batch cosine similarity matrix should have correct shape."""
        from backend.nlp.embeddings import cosine_similarity_matrix
        a = np.random.randn(3, 128)
        b = np.random.randn(5, 128)
        a = a / np.linalg.norm(a, axis=1, keepdims=True)
        b = b / np.linalg.norm(b, axis=1, keepdims=True)
        result = cosine_similarity_matrix(a, b)
        assert result.shape == (3, 5)

    def test_batch_skill_similarities_empty(self):
        """Empty input lists should return empty results."""
        from backend.nlp.embeddings import batch_skill_similarities
        result = batch_skill_similarities([], ["Python"])
        assert result == []
        result = batch_skill_similarities(["Python"], [])
        assert result == []


# ── Hybrid matcher with embeddings tests ─────────────────────────

class TestHybridMatcherPhase5:
    """Tests the upgraded hybrid matcher Phase 5 logic."""

    def test_match_skills_direct(self):
        """Direct skill matches should still work as before."""
        from backend.matching.hybrid import _match_skills
        resume = _make_resume()
        jd = _make_jd(required_skills=["Python"], preferred_skills=[], all_skills_flat=["Python"])
        matches = _match_skills(jd, resume)
        assert len(matches) == 1
        assert matches[0].match_type == SkillMatchType.DIRECT
        assert matches[0].confidence == 1.0

    def test_match_skills_missing(self):
        """Skills not in the resume should be classified as missing (or semantic)."""
        from backend.matching.hybrid import _match_skills
        resume = _make_resume(all_skills_flat=["Python"])
        jd = _make_jd(
            required_skills=["Rust"],
            preferred_skills=[],
            all_skills_flat=["Rust"],
        )
        matches = _match_skills(jd, resume)
        assert len(matches) == 1
        # Should be missing (no related/partial/semantic match for Rust -> Python)
        assert matches[0].match_type in (SkillMatchType.MISSING, SkillMatchType.RELATED)

    def test_match_skills_deduplication(self):
        """Duplicate skills should be deduplicated."""
        from backend.matching.hybrid import _match_skills
        resume = _make_resume()
        jd = _make_jd(
            required_skills=["Python", "python"],
            preferred_skills=["Python"],
            all_skills_flat=["Python"],
        )
        matches = _match_skills(jd, resume)
        assert len(matches) == 1

    def test_find_evidence(self):
        """Evidence extraction should find skills in resume bullets."""
        from backend.matching.hybrid import _find_evidence
        resume = _make_resume()
        evidence = _find_evidence("Python", resume)
        assert len(evidence) > 0
        assert any("Python" in e for e in evidence)

    def test_find_evidence_no_match(self):
        """Skills not in any bullets should return empty evidence."""
        from backend.matching.hybrid import _find_evidence
        resume = _make_resume()
        evidence = _find_evidence("Haskell", resume)
        assert evidence == []

    def test_run_hybrid_matching_full(self):
        """Full pipeline should return all 7 dimensions."""
        from backend.matching.hybrid import run_hybrid_matching
        resume = _make_resume()
        jd = _make_jd()
        result = run_hybrid_matching(resume, jd)

        assert result.overall_score >= 0
        assert result.max_possible == 100
        assert len(result.dimension_scores) == 7

        # Check dimension names
        dim_names = [d.dimension for d in result.dimension_scores]
        assert "Required Skills" in dim_names
        assert "Semantic/Domain Relevance" in dim_names

    def test_semantic_score_with_empty_jd(self):
        """Empty JD text should give full semantic score."""
        from backend.matching.hybrid import _score_semantic_relevance
        resume = _make_resume()
        jd = _make_jd(raw_text="")
        result = _score_semantic_relevance(resume, jd)
        assert result.score == result.max_score

    def test_semantic_score_fallback_or_real(self):
        """Semantic score should use either embeddings or word overlap."""
        from backend.matching.hybrid import _score_semantic_relevance
        resume = _make_resume()
        jd = _make_jd()
        result = _score_semantic_relevance(resume, jd)

        assert result.score >= 0
        assert result.max_score > 0
        assert len(result.details) > 0

        # Should mention either 'Embedding' or 'Word overlap'
        detail_text = " ".join(result.details)
        assert "Embedding" in detail_text or "Word overlap" in detail_text

    def test_extract_chunks(self):
        """Chunk extraction should pull bullets from experience and projects."""
        from backend.matching.hybrid import _extract_chunks
        resume = _make_resume()
        chunks = _extract_chunks(resume)
        assert len(chunks) > 0
        assert any("Python" in c for c in chunks)

    def test_extract_jd_chunks(self):
        """JD chunk extraction should pull from requirements and responsibilities."""
        from backend.matching.hybrid import _extract_jd_chunks
        jd = _make_jd()
        chunks = _extract_jd_chunks(jd)
        assert len(chunks) > 0


# ── Embedding model integration tests (slow) ────────────────────

@pytest.mark.slow
class TestEmbeddingModel:
    """Tests that require the actual embedding model to be downloaded.
    Run with: pytest -m slow
    """

    def test_model_loads(self):
        from backend.nlp import embeddings
        assert embeddings.is_available()

    def test_encode_returns_vectors(self):
        from backend.nlp import embeddings
        if not embeddings.is_available():
            pytest.skip("Embedding model not available")
        vectors = embeddings.encode(["Python programming", "JavaScript development"])
        assert vectors is not None
        assert vectors.shape[0] == 2
        assert vectors.shape[1] > 0

    def test_document_similarity_related(self):
        from backend.nlp import embeddings
        if not embeddings.is_available():
            pytest.skip("Embedding model not available")
        sim = embeddings.document_similarity(
            "Python developer with machine learning experience",
            "Looking for a Python ML engineer",
        )
        assert sim is not None
        assert sim > 0.5  # Related texts should have high similarity

    def test_document_similarity_unrelated(self):
        from backend.nlp import embeddings
        if not embeddings.is_available():
            pytest.skip("Embedding model not available")
        sim = embeddings.document_similarity(
            "Python developer with machine learning experience",
            "Fresh organic strawberries on sale at the farmers market",
        )
        assert sim is not None
        assert sim < 0.5  # Unrelated texts should have low similarity

    def test_skill_similarity(self):
        from backend.nlp import embeddings
        if not embeddings.is_available():
            pytest.skip("Embedding model not available")
        sim = embeddings.skill_similarity("Python", "Django")
        assert sim is not None
        assert sim > 0.3  # Related skills

    def test_batch_skill_similarities(self):
        from backend.nlp import embeddings
        if not embeddings.is_available():
            pytest.skip("Embedding model not available")
        results = embeddings.batch_skill_similarities(
            ["Python", "React"],
            ["Django", "Flask", "Vue.js", "Angular"],
            threshold=0.3,
        )
        assert results is not None
        assert len(results) > 0
        # Python should match Django or Flask
        python_match = next((r for r in results if r["jd_skill"] == "Python"), None)
        assert python_match is not None
        assert python_match["resume_skill"] in ("Django", "Flask")

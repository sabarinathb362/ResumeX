"""Regression tests for the ATS 2.0 overhaul: parser, fabrication gate, RRI."""
from pathlib import Path
import pytest

from backend.feedback.validator import validate_rewrite
from backend.readability.rri import run_rri, grade_statement

RESUME = Path(__file__).resolve().parents[1] / "uploads" / "0a2bf14d-d518-4199-b489-c601b1222d00.pdf"


@pytest.mark.skipif(not RESUME.exists(), reason="sample resume not present")
def test_layout_parser_recovers_real_sections():
    from backend.ingestion.layout_parser import parse_pdf
    r = parse_pdf(str(RESUME))
    headings = {s.heading.lower() for s in r.doc_sections}
    # The old parser turned the name / school / project titles into "sections".
    assert not any("sabarinath" in h or "amrita" in h for h in headings)
    assert len(r.education) >= 1 and len(r.projects) >= 3 and len(r.experience) >= 1
    assert all(st.line_ids for s in r.doc_sections for e in s.entries for st in e.statements)


@pytest.mark.skipif(not RESUME.exists(), reason="sample resume not present")
def test_rri_is_reproducible_without_llm():
    from backend.ingestion.layout_parser import parse_pdf
    r = parse_pdf(str(RESUME))
    a, b = run_rri(r, use_llm=False), run_rri(r, use_llm=False)
    assert a.overall_score == b.overall_score
    assert len(a.dimensions) == 7
    assert all(f.line_ids or f.statement_ids or f.dimension for f in a.findings)


@pytest.mark.parametrize("bad", [
    "Improved throughput by 30% using Kubernetes.",
    "Served 10k users at Google.",
])
def test_validator_blocks_invented_facts(bad):
    original = "Worked on backend services for the team."
    assert not validate_rewrite(original, bad, original).is_valid


def test_validator_allows_reordering_existing_metric():
    original = "Built a CNN for fruit freshness detection achieving 96.3% accuracy."
    v = validate_rewrite(original, "Achieved 96.3% accuracy on fruit freshness detection with a CNN.", original)
    assert v.is_valid


def _grade(text):
    from backend.schemas.resume import Statement, DocSection, DocEntry
    st = Statement(id="s1", text=text, line_ids=[], path=["experience", 0, "bullets", 0])
    entry = DocEntry(id="e1", title="Intern", statements=[st])
    sec = DocSection(id="sec1", heading="Experience", kind="experience", entries=[entry])
    return grade_statement(st, sec, entry, current=False).grade


def test_bullet_grades():
    assert _grade("Working on LLMs and related research.") in ("C", "D")
    assert _grade("Reduced inference latency 40% by quantizing a PyTorch ResNet model "
                  "for edge deployment.") in ("A", "B")

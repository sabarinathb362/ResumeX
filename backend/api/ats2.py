"""
API routes — ATS 2.0 (simulated skim, naive-parser view, impact quotient).
GET /api/ats2/{resume_id}?analysis_id=...   all three reports in one call
"""
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models.db_models import Analysis, Resume
from backend.schemas.resume import ResumeData
from backend.schemas.analysis import ReadabilityResult
from backend.ats2.attention import simulate_attention
from backend.ats2.impact import impact_quotient
from backend.ats2.parser_sim import simulate_parsers

router = APIRouter(prefix="/api/ats2", tags=["ats2"])


@router.get("/{resume_id}", summary="Simulated skim, naive-parser view and impact quotient")
def ats2_report(resume_id: str, analysis_id: Optional[str] = None, db: Session = Depends(get_db)):
    row = db.query(Resume).filter(Resume.id == resume_id).first()
    if not row:
        raise HTTPException(404, "Resume not found")
    data = ResumeData.model_validate(row.structured_json)

    grades = None
    if analysis_id:
        a = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if a and a.readability_result_json:
            grades = ReadabilityResult.model_validate(a.readability_result_json).statements
    if grades is None:
        from backend.readability.rri import run_rri
        grades = run_rri(data, use_llm=False).statements

    parser = None
    pdf = settings.upload_dir / f"{resume_id}.pdf"
    if row.file_type == "pdf" and pdf.exists():
        reference = "\n".join(l.text for l in data.lines) or data.raw_text
        parser = asdict(simulate_parsers(str(pdf), reference, data.contact.model_dump()))

    # .tex/.typ uploads have no page geometry, so there is nothing to skim-simulate
    attention = asdict(simulate_attention(data, grades)) if data.page_sizes else None
    statements = sum(len(e.statements) for s in data.doc_sections for e in s.entries)
    return {"attention": attention,
            "impact": asdict(impact_quotient(grades)),
            "parser": parser,
            "file_type": row.file_type,
            "pages": len(data.page_sizes),
            "graded_bullets": len(grades),
            "total_statements": statements}

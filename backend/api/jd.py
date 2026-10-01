"""
API routes — JD analysis (Phase 3).
POST /api/jd/analyze
"""
import uuid
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from sqlalchemy.orm import Session
from typing import Optional
from pathlib import Path

from backend.database import get_db
from backend.models.db_models import JobDescription
from backend.schemas.jd import JDAnalyzeRequest, JDAnalyzeResponse
from backend.parsing.jd_parser import parse_jd
from backend.ingestion.pdf import extract_from_pdf
from backend.ingestion.docx_extractor import extract_from_docx

router = APIRouter(prefix="/api/jd", tags=["job-description"])


@router.post(
    "/analyze",
    response_model=JDAnalyzeResponse,
    summary="Parse and analyze a job description",
)
async def analyze_jd(
    text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    """
    Parse a job description from pasted text or an uploaded file.
    Returns the structured JD with classified requirements.
    """
    jd_text = ""

    if text:
        jd_text = text
    elif file:
        ext = Path(file.filename or "").suffix.lower()
        content = await file.read()

        if ext == ".pdf":
            # Save temp, extract text, clean up
            import tempfile, os
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                resume_data = extract_from_pdf(tmp_path)
                jd_text = resume_data.raw_text
            finally:
                os.unlink(tmp_path)
        elif ext in (".docx", ".doc"):
            import tempfile, os
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                resume_data = extract_from_docx(tmp_path)
                jd_text = resume_data.raw_text
            finally:
                os.unlink(tmp_path)
        elif ext == ".txt" or not ext:
            jd_text = content.decode("utf-8", errors="replace")
        else:
            raise HTTPException(400, f"Unsupported file type for JD: {ext}")
    else:
        raise HTTPException(400, "Provide either 'text' or a file upload")

    if not jd_text.strip():
        raise HTTPException(400, "Job description text is empty")

    # Parse
    try:
        jd_data = parse_jd(jd_text)
    except Exception as e:
        raise HTTPException(422, f"Failed to parse JD: {str(e)}")

    # Persist
    jd_id = str(uuid.uuid4())
    db_jd = JobDescription(
        id=jd_id,
        title=jd_data.title,
        raw_text=jd_text,
        structured_json=jd_data.model_dump(),
        source="paste" if text else "upload",
    )
    db.add(db_jd)
    db.commit()

    warnings = []
    if not jd_data.required_skills:
        warnings.append("No required skills detected — the JD may be too brief or unstructured")
    if not jd_data.title:
        warnings.append("Could not extract a job title")

    return JDAnalyzeResponse(
        id=jd_id,
        status="parsed",
        jd_data=jd_data,
        warnings=warnings,
    )


@router.get("/{jd_id}", summary="Get parsed JD by ID")
async def get_jd(jd_id: str, db: Session = Depends(get_db)):
    db_jd = db.query(JobDescription).filter(JobDescription.id == jd_id).first()
    if not db_jd:
        raise HTTPException(404, "Job description not found")
    return {
        "id": db_jd.id,
        "title": db_jd.title,
        "jd_data": db_jd.structured_json,
        "created_at": str(db_jd.created_at),
    }

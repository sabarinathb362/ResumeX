"""
API routes — In-app resume editor.
GET  /api/editor/{resume_id}/page/{page}.png   rendered page image for overlays
GET  /api/editor/{resume_id}/document          lines + sections + page sizes
POST /api/editor/suggest                       grounded suggestions for one statement
"""
from typing import Optional

import pymupdf
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models.db_models import Resume, JobDescription
from backend.schemas.resume import ResumeData
from backend.feedback.grounded import suggest_for_statement, SuggestResponse

router = APIRouter(prefix="/api/editor", tags=["editor"])


def _load(db: Session, resume_id: str) -> tuple[Resume, ResumeData]:
    row = db.query(Resume).filter(Resume.id == resume_id).first()
    if not row:
        raise HTTPException(404, "Resume not found")
    return row, ResumeData.model_validate(row.structured_json)


@router.get("/{resume_id}/page/{page}.png", summary="Render a resume page as PNG")
def render_page(resume_id: str, page: int, scale: float = 2.0, db: Session = Depends(get_db)):
    row, _ = _load(db, resume_id)
    if row.file_type != "pdf":
        raise HTTPException(415, "Page rendering is available for PDF uploads")
    path = settings.upload_dir / f"{resume_id}.pdf"
    if not path.exists():
        raise HTTPException(404, "Original file no longer on disk")
    scale = max(0.5, min(scale, 3.0))
    with pymupdf.open(path) as doc:
        if page < 0 or page >= len(doc):
            raise HTTPException(404, "Page out of range")
        pix = doc[page].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        png = pix.tobytes("png")
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=3600"})


@router.get("/{resume_id}/document", summary="Layout-anchored document model")
def get_document(resume_id: str, db: Session = Depends(get_db)):
    row, data = _load(db, resume_id)
    return {
        "resume_id": resume_id,
        "file_type": row.file_type,
        "renderable": row.file_type == "pdf" and bool(data.page_sizes),
        "page_sizes": data.page_sizes,
        "lines": [l.model_dump() for l in data.lines],
        "sections": [s.model_dump() for s in data.doc_sections],
        "parser_version": data.parser_version,
    }


class SuggestRequest(BaseModel):
    resume_id: str
    statement_id: str
    jd_id: Optional[str] = None
    jd_requirement: Optional[str] = None
    user_facts: Optional[str] = None


@router.post("/suggest", response_model=SuggestResponse, summary="Grounded rewrite options for one bullet")
def suggest(req: SuggestRequest, db: Session = Depends(get_db)):
    _, data = _load(db, req.resume_id)
    try:
        return suggest_for_statement(data, req.statement_id, req.jd_requirement, req.user_facts)
    except KeyError:
        raise HTTPException(404, "Statement not found")

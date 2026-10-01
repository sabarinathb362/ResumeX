"""
API routes — Resume upload and parsing (Phase 1).
POST /api/resume/upload
"""
import os
import uuid
import shutil
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models.db_models import Resume
from backend.schemas.resume import ResumeUploadResponse, ResumeData, ErrorResponse
from backend.ingestion.pdf import extract_from_pdf
from backend.ingestion.docx_extractor import extract_from_docx
from backend.ingestion.latex import parse_latex_resume

router = APIRouter(prefix="/api/resume", tags=["resume"])


def _validate_file(file: UploadFile) -> str:
    """Validate file type and size. Returns the file extension."""
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in settings.allowed_extensions:
        raise HTTPException(
            400,
            f"Unsupported file type: {ext}. Allowed: {settings.allowed_extensions}"
        )

    return ext


@router.post(
    "/upload",
    response_model=ResumeUploadResponse,
    responses={400: {"model": ErrorResponse}},
    summary="Upload and parse a resume",
)
async def upload_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Upload a PDF or DOCX resume for parsing.
    Returns the canonical structured resume data with layout metadata.
    """
    ext = _validate_file(file)

    # Save uploaded file
    file_id = str(uuid.uuid4())
    upload_dir = settings.upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"{file_id}{ext}"

    try:
        with open(file_path, "wb") as f:
            content = await file.read()

            # Check file size
            if len(content) > settings.max_file_size_mb * 1024 * 1024:
                raise HTTPException(
                    400,
                    f"File too large. Maximum size: {settings.max_file_size_mb} MB"
                )

            f.write(content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to save file: {str(e)}")

    # Parse the file
    warnings = []
    try:
        if ext == ".pdf":
            resume_data = extract_from_pdf(str(file_path))
        elif ext in (".docx", ".doc"):
            resume_data = extract_from_docx(str(file_path))
        elif ext == ".tex":
            text_str = content.decode("utf-8", errors="replace")
            resume_data, tex_warnings = parse_latex_resume(text_str, filename=file.filename or "resume.tex")
            warnings.extend(tex_warnings)
        else:
            raise HTTPException(400, f"Parser not yet implemented for {ext}")

        # Update metadata
        resume_data.document_metadata.filename = file.filename or ""
        resume_data.document_metadata.file_size_bytes = len(content)

    except HTTPException:
        raise
    except Exception as e:
        # Graceful failure with structured error
        raise HTTPException(
            422,
            f"Failed to parse {ext} file: {str(e)}"
        )

    # Persist to database
    db_resume = Resume(
        id=file_id,
        filename=file.filename or "",
        file_type=ext.lstrip("."),
        parsed_text=resume_data.raw_text,
        structured_json=resume_data.model_dump(),
        layout_metadata=resume_data.layout_metadata.model_dump(),
    )
    db.add(db_resume)
    db.commit()

    return ResumeUploadResponse(
        id=file_id,
        filename=file.filename or "",
        file_type=ext.lstrip("."),
        status="parsed",
        resume_data=resume_data,
        warnings=warnings,
    )


@router.get("/{resume_id}", summary="Get parsed resume by ID")
async def get_resume(resume_id: str, db: Session = Depends(get_db)):
    """Retrieve a previously parsed resume."""
    db_resume = db.query(Resume).filter(Resume.id == resume_id).first()
    if not db_resume:
        raise HTTPException(404, "Resume not found")

    return {
        "id": db_resume.id,
        "filename": db_resume.filename,
        "file_type": db_resume.file_type,
        "resume_data": db_resume.structured_json,
        "created_at": str(db_resume.created_at),
    }

"""
API routes — Integrity checks (Phase 5).
GET  /api/verify/{resume_id}?jd_id=...   hidden text (PDF), timeline, LaTeX/Typst source findings
POST /api/verify/{resume_id}/github      opt-in GitHub claim check (sends only username + repo names)
"""
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models.db_models import JobDescription, Resume
from backend.schemas.resume import ResumeData

router = APIRouter(prefix="/api/verify", tags=["verify"])


class GithubRequest(BaseModel):
    consent: bool = False
    username: Optional[str] = None


def _resume(db: Session, resume_id: str):
    row = db.query(Resume).filter(Resume.id == resume_id).first()
    if not row:
        raise HTTPException(404, "Resume not found")
    return row, ResumeData.model_validate(row.structured_json)


@router.get("/{resume_id}", summary="Hidden text, timeline and source checks")
async def integrity(resume_id: str, jd_id: Optional[str] = None, db: Session = Depends(get_db)):
    from backend.integrity.stealth import scan_pdf
    from backend.integrity.timeline import check_timeline
    row, data = _resume(db, resume_id)
    jd_skills: list[str] = []
    if jd_id:
        j = db.query(JobDescription).filter(JobDescription.id == jd_id).first()
        if j:
            jd_skills = (j.structured_json or {}).get("all_skills_flat", [])

    stealth = None
    pdf = settings.upload_dir / f"{resume_id}.pdf"
    if row.file_type == "pdf" and pdf.exists():
        stealth = asdict(await run_in_threadpool(scan_pdf, str(pdf), jd_skills))

    source = None
    if row.file_type in ("tex", "typ"):
        src_path = settings.upload_dir / f"{resume_id}.{row.file_type}"
        if src_path.exists():
            from backend.ingestion.source_resume import inspect_source
            _, _, rep = await run_in_threadpool(inspect_source, src_path.read_text(encoding="utf-8", errors="replace"),
                                                row.file_type)
            source = asdict(rep)

    return {"stealth": stealth, "timeline": check_timeline(data), "source": source,
            "github_enabled": settings.github_verify_enabled}


@router.post("/{resume_id}/github", summary="Check project claims against public GitHub repos (opt-in)")
async def github(resume_id: str, req: GithubRequest, db: Session = Depends(get_db)):
    if not settings.github_verify_enabled:
        raise HTTPException(403, "GitHub checks are off. Set RESUMEIQ_GITHUB_VERIFY_ENABLED=true in .env to allow them.")
    if not req.consent:
        raise HTTPException(400, "Confirm that ResumeX may send your GitHub username and repo names to api.github.com.")
    from backend.integrity.github import check_github
    _, data = _resume(db, resume_id)
    rep = await run_in_threadpool(check_github, data, req.username, settings.github_token)
    return asdict(rep)

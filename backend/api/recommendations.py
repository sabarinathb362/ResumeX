"""
API routes — Recommendations (Phases 11, 12, 13).
POST /api/recommendations/general
POST /api/recommendations/jd
POST /api/projects/recommend
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.db_models import Resume, JobDescription
from backend.schemas.resume import ResumeData
from backend.schemas.jd import JDData
from backend.recommendations.general import (
    generate_general_recommendations,
    GeneralRecommendationsReport,
)
from backend.recommendations.jd import (
    evaluate_jd_match_and_feedback,
    JDFocusedReport,
)
from backend.recommendations.projects import (
    recommend_projects_for_gaps,
    ProjectRecommendationReport,
)

router = APIRouter(prefix="/api", tags=["Recommendations"])


class GeneralRecRequest(BaseModel):
    resume_id: str


class JDRecRequest(BaseModel):
    resume_id: str
    jd_id: str


class ProjectRecRequest(BaseModel):
    skill_gaps: list[str] = Field(default_factory=list)
    difficulty: Optional[str] = None
    limit: int = 3


@router.post("/recommendations/general", response_model=GeneralRecommendationsReport, summary="Get general prioritized resume recommendations (no JD)")
def get_general_recommendations(req: GeneralRecRequest, db: Session = Depends(get_db)):
    db_resume = db.query(Resume).filter(Resume.id == req.resume_id).first()
    if not db_resume:
        raise HTTPException(404, "Resume not found")

    resume_data = ResumeData.model_validate(db_resume.structured_json)
    return generate_general_recommendations(resume_data)


@router.post("/recommendations/jd", response_model=JDFocusedReport, summary="Get JD-based feedback and AI Match %")
def get_jd_recommendations(req: JDRecRequest, db: Session = Depends(get_db)):
    db_resume = db.query(Resume).filter(Resume.id == req.resume_id).first()
    if not db_resume:
        raise HTTPException(404, "Resume not found")

    db_jd = db.query(JobDescription).filter(JobDescription.id == req.jd_id).first()
    if not db_jd:
        raise HTTPException(404, "Job Description not found")

    resume_data = ResumeData.model_validate(db_resume.structured_json)
    jd_data = JDData.model_validate(db_jd.structured_json)

    return evaluate_jd_match_and_feedback(resume_data, jd_data)


@router.post("/projects/recommend", response_model=ProjectRecommendationReport, summary="Recommend projects for skill gaps")
def get_project_recommendations(req: ProjectRecRequest):
    return recommend_projects_for_gaps(
        skill_gaps=req.skill_gaps,
        preferred_difficulty=req.difficulty,
        limit=req.limit,
    )

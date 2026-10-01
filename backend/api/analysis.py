"""
API routes — Analysis: ATS + Hybrid Matching + Readability (Phases 2, 4, 10).
POST /api/analysis/run
GET  /api/analysis/{id}
GET  /api/analysis/{id}/ats
GET  /api/analysis/{id}/match
GET  /api/analysis/{id}/readability
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from backend.database import get_db
from backend.models.db_models import Analysis, Resume, JobDescription
from backend.schemas.resume import ResumeData
from backend.schemas.jd import JDData
from backend.schemas.analysis import (
    AnalysisResponse, ATSResult, HybridMatchResult, ReadabilityResult,
)
from backend.ats.rules import run_ats_analysis
from backend.matching.hybrid import run_hybrid_matching
from backend.readability.rri import run_rri
from backend.insights.engine import build_insights
from backend.schemas.analysis import Finding

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


class RunAnalysisRequest(BaseModel):
    resume_id: str
    jd_id: Optional[str] = None
    use_llm: bool = True


@router.post(
    "/run",
    response_model=AnalysisResponse,
    summary="Run complete analysis on a resume (optionally with a JD)",
)
async def run_analysis(
    request: RunAnalysisRequest,
    db: Session = Depends(get_db),
):
    """
    Run the full analysis pipeline:
    1. ATS compatibility scoring (always)
    2. Readability scoring (always)
    3. Hybrid match scoring (only if JD provided)
    """
    # Load resume
    db_resume = db.query(Resume).filter(Resume.id == request.resume_id).first()
    if not db_resume:
        raise HTTPException(404, "Resume not found")

    resume_data = ResumeData.model_validate(db_resume.structured_json)

    # Run ATS analysis (always)
    ats_result = run_ats_analysis(resume_data)

    # Run matching if JD provided
    match_result = None
    jd_data = None
    jd_reqs = None
    if request.jd_id:
        db_jd = db.query(JobDescription).filter(JobDescription.id == request.jd_id).first()
        if not db_jd:
            raise HTTPException(404, "Job description not found")

        jd_data = JDData.model_validate(db_jd.structured_json)
        match_result = run_hybrid_matching(resume_data, jd_data)
        jd_reqs = [r.text for r in getattr(jd_data, "requirements", []) or [] if getattr(r, "text", None)] \
            or list(getattr(jd_data, "required_skills", []) or [])

    # Readability Reviewer — ATS 2.0 (always). Uses the local LLM for label votes if it is up.
    readability_result = run_rri(resume_data, jd_requirements=jd_reqs, use_llm=request.use_llm)

    # One ranked, line-anchored list for the dashboard and editor
    insights = build_insights(resume_data, ats_result, readability_result)

    # Persist analysis
    analysis_id = str(uuid.uuid4())
    db_analysis = Analysis(
        id=analysis_id,
        resume_id=request.resume_id,
        jd_id=request.jd_id,
        ats_score=ats_result.overall_score,
        ats_result_json=ats_result.model_dump(),
        readability_score=readability_result.overall_score,
        readability_result_json={**readability_result.model_dump(mode="json"),
                                 "insights": [f.model_dump(mode="json") for f in insights]},
        match_score=match_result.overall_score if match_result else None,
        match_result_json=match_result.model_dump() if match_result else {},
        status="complete",
        versions={
            "ats_rubric": ats_result.rubric_version,
            "readability_rubric": readability_result.rubric_version,
            "parser": resume_data.parser_version,
            "rri_llm_used": readability_result.llm_used,
            "app_version": "2.1.0",
        },
    )
    db.add(db_analysis)
    db.commit()

    return AnalysisResponse(
        id=analysis_id,
        resume_id=request.resume_id,
        jd_id=request.jd_id,
        status="complete",
        ats_result=ats_result,
        readability_result=readability_result,
        readability_score=readability_result.overall_score,
        match_result=match_result,
        insights=insights,
        created_at=str(datetime.now(timezone.utc)),
    )


@router.get("/{analysis_id}", summary="Get full analysis results")
async def get_analysis(analysis_id: str, db: Session = Depends(get_db)):
    db_analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not db_analysis:
        raise HTTPException(404, "Analysis not found")

    return AnalysisResponse(
        id=db_analysis.id,
        resume_id=db_analysis.resume_id,
        jd_id=db_analysis.jd_id,
        status=db_analysis.status,
        ats_result=ATSResult.model_validate(db_analysis.ats_result_json) if db_analysis.ats_result_json else None,
        match_result=HybridMatchResult.model_validate(db_analysis.match_result_json) if db_analysis.match_result_json else None,
        readability_result=ReadabilityResult.model_validate(db_analysis.readability_result_json) if db_analysis.readability_result_json else None,
        readability_score=db_analysis.readability_score,
        insights=[Finding.model_validate(f) for f in (db_analysis.readability_result_json or {}).get("insights", [])],
        created_at=str(db_analysis.created_at),
    )


@router.get("/{analysis_id}/ats", summary="Get ATS results only")
async def get_ats_results(analysis_id: str, db: Session = Depends(get_db)):
    db_analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not db_analysis:
        raise HTTPException(404, "Analysis not found")
    if not db_analysis.ats_result_json:
        raise HTTPException(404, "ATS results not available")

    return ATSResult.model_validate(db_analysis.ats_result_json)


@router.get("/{analysis_id}/match", summary="Get match results only")
async def get_match_results(analysis_id: str, db: Session = Depends(get_db)):
    db_analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not db_analysis:
        raise HTTPException(404, "Analysis not found")
    if not db_analysis.match_result_json:
        raise HTTPException(404, "Match results not available — no JD was provided")

    return HybridMatchResult.model_validate(db_analysis.match_result_json)


@router.get("/{analysis_id}/readability", summary="Get readability results only")
async def get_readability_results(analysis_id: str, db: Session = Depends(get_db)):
    db_analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not db_analysis:
        raise HTTPException(404, "Analysis not found")
    if not db_analysis.readability_result_json:
        raise HTTPException(404, "Readability results not available")

    return ReadabilityResult.model_validate(db_analysis.readability_result_json)

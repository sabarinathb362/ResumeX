"""
API routes — Mock Interview Arena (Phase 4).
POST /api/interview/generate          build a 3-round plan from resume + optional JD + company
POST /api/interview/evaluate          grade one answer (STAR labels -> weighted score in code)
GET  /api/interview/sessions/{id}     plan + every graded turn
All processing is local; no question bank is scraped and nothing is sent to the web.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.db_models import Analysis, InterviewSession, InterviewTurn, JobDescription, Resume
from backend.schemas.analysis import ReadabilityResult
from backend.schemas.jd import JDData
from backend.schemas.resume import ResumeData
from backend.interview.engine import build_plan, evidence_for, grade_answer

router = APIRouter(prefix="/api/interview", tags=["interview"])


class GenerateRequest(BaseModel):
    resume_id: str
    jd_id: Optional[str] = None
    analysis_id: Optional[str] = None
    company: str = ""
    role: str = ""


class EvaluateRequest(BaseModel):
    session_id: str
    question_id: str
    answer: str = Field(min_length=1, max_length=6000)


def _load_resume(db: Session, resume_id: str) -> ResumeData:
    row = db.query(Resume).filter(Resume.id == resume_id).first()
    if not row:
        raise HTTPException(404, "Resume not found")
    return ResumeData.model_validate(row.structured_json)


def _grades(db: Session, data: ResumeData, analysis_id: Optional[str]):
    if analysis_id:
        a = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if a and a.readability_result_json:
            return ReadabilityResult.model_validate(a.readability_result_json).statements
    from backend.readability.rri import run_rri
    return run_rri(data, use_llm=False).statements


def _find_question(plan: dict, qid: str):
    for rnd in plan.get("rounds", []):
        for q in rnd.get("questions", []):
            if q.get("id") == qid:
                return rnd["round"], q
    return None, None


@router.post("/generate", summary="Create an interview session with three rounds of questions")
def generate(req: GenerateRequest, db: Session = Depends(get_db)):
    data = _load_resume(db, req.resume_id)
    grades = _grades(db, data, req.analysis_id)
    jd, signals, company, role = None, [], req.company, req.role
    if req.jd_id:
        jrow = db.query(JobDescription).filter(JobDescription.id == req.jd_id).first()
        if not jrow:
            raise HTTPException(404, "Job description not found")
        jd = JDData.model_validate(jrow.structured_json)
        from backend.api.company import build_company_intel_from_jd, extract_company_name
        company = company or jd.company or extract_company_name(jrow.raw_text) or ""
        role = role or jd.title or ""
        signals = build_company_intel_from_jd(jrow.raw_text, company).culture_signals   # offline, JD text only
    plan = build_plan(data, grades, jd=jd, company=company, role=role, signals=signals)
    s = InterviewSession(resume_id=req.resume_id, jd_id=req.jd_id, company=company, role=role, plan_json=plan)
    db.add(s)
    db.commit()
    return {"session_id": s.id, **plan}


@router.post("/evaluate", summary="Grade one answer with STAR")
def evaluate(req: EvaluateRequest, db: Session = Depends(get_db)):
    s = db.query(InterviewSession).filter(InterviewSession.id == req.session_id).first()
    if not s:
        raise HTTPException(404, "Session not found")
    round_no, q = _find_question(s.plan_json, req.question_id)
    if not q:
        raise HTTPException(404, "Question not in this session")
    data = _load_resume(db, s.resume_id)
    evidence = evidence_for(q, data)
    result = grade_answer(q["text"], req.answer, evidence)
    db.add(InterviewTurn(session_id=s.id, round_no=round_no, question_id=q["id"], question=q["text"],
                         answer=req.answer, evaluation_json=result))
    db.commit()
    return {"question_id": q["id"], "round": round_no, **result}


@router.get("/sessions/{session_id}", summary="Plan and graded turns")
def get_session(session_id: str, db: Session = Depends(get_db)):
    s = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
    if not s:
        raise HTTPException(404, "Session not found")
    return {"session_id": s.id, "company": s.company, "role": s.role, "plan": s.plan_json,
            "turns": [{"question_id": t.question_id, "round": t.round_no, "question": t.question,
                       "answer": t.answer, "evaluation": t.evaluation_json} for t in s.turns]}

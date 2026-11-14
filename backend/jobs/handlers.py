"""
Background handlers (ResumeX 2.0).

deep_review: the slow, LLM-heavy part of an analysis. /api/analysis/run now returns the
deterministic result in ~1 s (use_llm=False); the UI then starts this job, shows progress
over SSE, and re-fetches the analysis when it finishes.
"""
from __future__ import annotations

from backend.config import settings
from backend.database import SessionLocal
from backend.models.db_models import Analysis, Resume, JobDescription
from backend.schemas.resume import ResumeData
from backend.schemas.jd import JDData
from backend.schemas.analysis import ATSResult


def deep_review(payload: dict, progress) -> dict:
    from backend.readability.rri import run_rri
    from backend.insights.engine import build_insights
    from backend.recommendations.jd import evaluate_jd_match_and_feedback

    db = SessionLocal()
    try:
        a = db.get(Analysis, payload["analysis_id"])
        if a is None:
            raise KeyError("analysis not found")
        resume = ResumeData.model_validate(db.get(Resume, a.resume_id).structured_json)
        jd = None
        if a.jd_id:
            row = db.get(JobDescription, a.jd_id)
            jd = JDData.model_validate(row.structured_json) if row else None
        reqs = [r.text for r in jd.requirements] if jd else None

        from backend.llm.client import get_llm_client
        online = get_llm_client().is_online()
        deep_model = settings.llm_model
        judge_model = settings.llm_fast_model if settings.llm_judge_tier == "fast" else settings.llm_model
        from backend.readability.rri import GRADED_KINDS
        n_bullets = sum(len(e.statements) for s in resume.doc_sections if s.kind in GRADED_KINDS for e in s.entries)

        progress(0.1, f"{deep_model} is grading {n_bullets} bullets and running the skim test" if online
                 else "Ollama is not running: re-checking with rules only")
        rri = run_rri(resume, jd_requirements=reqs, use_llm=True)
        insights = build_insights(resume, ATSResult.model_validate(a.ats_result_json), rri)

        ai_match, judge_used = None, False
        if jd is not None:
            progress(0.6, f"{judge_model} is judging {len(jd.requirements)} job requirements" if online
                     else "Checking job requirements with rules")
            report = evaluate_jd_match_and_feedback(resume, jd, use_llm=True)
            judge_used = report.judge == "rules+llm"
            ai_match = report.ai_match_percentage
            a.match_result_json = {**(a.match_result_json or {}), "ai_judge": report.model_dump(mode="json")}

        a.readability_score = rri.overall_score
        a.readability_result_json = {**rri.model_dump(mode="json"),
                                     "insights": [f.model_dump(mode="json") for f in insights]}
        llm_graded = sum(1 for s in rri.statements if "llm" in (s.method or ""))
        # Which model did what. A key is present only if that model's output was actually used.
        llm_models = {**({"bullet_grades": deep_model, "skim_test": deep_model} if rri.llm_used else {}),
                      **({"requirement_judge": judge_model} if judge_used else {})}
        a.versions = {**(a.versions or {}), "deep_review": True, "rri_llm_used": rri.llm_used,
                      "llm_models": llm_models, "llm_graded_bullets": llm_graded, "llm_provider": "ollama"}
        db.commit()
        progress(1.0, "Done")
        return {"analysis_id": a.id, "readability_score": rri.overall_score, "ai_match_percentage": ai_match,
                "llm_used": bool(rri.llm_used or judge_used), "llm_models": llm_models}
    finally:
        db.close()


def register_handlers(queue) -> None:
    queue.register_handler("deep_review", deep_review)

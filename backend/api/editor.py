"""
API routes — In-app resume editor.
GET  /api/editor/{resume_id}/page/{page}.png   rendered page image for overlays
GET  /api/editor/{resume_id}/document          lines + sections + page sizes
GET  /api/editor/{resume_id}/sidebar           JD gaps + strategy recommendations, anchored to statements
POST /api/editor/suggest                       grounded suggestions for one statement (rules, optional sync LLM)
POST /api/editor/suggest/stream                SSE: rules instantly, then Tier-1 LLM tokens + validated candidates
"""
import json
from typing import Optional

import pymupdf
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models.db_models import Resume, JobDescription
from backend.schemas.resume import ResumeData
from backend.feedback.grounded import (suggest_for_statement, SuggestResponse, build_context,
                                       rules_response, stream_llm_candidates)
from backend.llm.router import get_router

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
    current_text: Optional[str] = None   # the bullet as it currently reads in the editor
    use_llm: bool = True                 # the 2.0 UI sends False here and streams the LLM separately


@router.post("/suggest", response_model=SuggestResponse, summary="Grounded rewrite options for one bullet")
def suggest(req: SuggestRequest, db: Session = Depends(get_db)):
    _, data = _load(db, req.resume_id)
    try:
        return suggest_for_statement(data, req.statement_id, req.jd_requirement, req.user_facts,
                                     use_llm=req.use_llm, current_text=req.current_text)
    except KeyError:
        raise HTTPException(404, "Statement not found")


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/suggest/stream", summary="Stream grounded rewrites (SSE)")
async def suggest_stream(req: SuggestRequest, request: Request, db: Session = Depends(get_db)):
    _, data = _load(db, req.resume_id)
    try:
        ctx = build_context(data, req.statement_id, req.current_text, req.user_facts, req.jd_requirement)
    except KeyError:
        raise HTTPException(404, "Statement not found")
    rules = rules_response(ctx)

    async def events():
        yield _sse("rules", rules.model_dump())
        if req.use_llm:
            try:
                async for ev in stream_llm_candidates(ctx, get_router()):
                    if await request.is_disconnected():
                        return          # client aborted: closing the generator stops the Ollama stream
                    yield _sse(ev["event"], ev["data"])
            except Exception as e:      # never turn a half-sent stream into a 500
                yield _sse("status", {"llm": "error", "message": str(e)})
        yield _sse("done", {})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{resume_id}/sidebar", summary="JD gaps and strategy items anchored to statements")
def sidebar(resume_id: str, jd_id: Optional[str] = None, db: Session = Depends(get_db)):
    from backend.recommendations.anchor import statement_index, anchor_text
    from backend.recommendations.general import generate_general_recommendations
    _, data = _load(db, resume_id)
    idx = statement_index(data)

    general = generate_general_recommendations(data)
    strategy = []
    for r in general.recommendations:
        sids, lids = anchor_text(idx, r.evidence_span)
        strategy.append({**r.model_dump(), "statement_ids": sids, "line_ids": lids})

    jd = None
    if jd_id:
        from backend.schemas.jd import JDData
        from backend.recommendations.jd import evaluate_jd_match_and_feedback
        row = db.query(JobDescription).filter(JobDescription.id == jd_id).first()
        if not row:
            raise HTTPException(404, "Job description not found")
        rep = evaluate_jd_match_and_feedback(data, JDData.model_validate(row.structured_json))
        # Use the judge's statement ids directly; fall back to text anchoring only when there are none.
        lines_of = {sid: lids for sid, lids, _, _ in idx}
        reqs = []
        for v in rep.requirement_verdicts:
            sids = [s for s in v.evidence_statement_ids if s in lines_of]
            lids = [l for s in sids for l in lines_of[s]]
            if not sids:
                sids, lids = anchor_text(idx, v.evidence_span)
            reqs.append({**v.model_dump(), "statement_ids": sids, "line_ids": lids})
        order = {"missing": 0, "partial": 1, "transferable": 2, "met": 3}
        reqs.sort(key=lambda x: (order.get(x["verdict"], 9), x["requirement_type"] != "required"))
        jd = {"ai_match_percentage": rep.ai_match_percentage, "met": rep.met_count,
              "partial": rep.partial_count, "missing": rep.missing_count, "requirements": reqs,
              "section_feedback": [f.model_dump() for f in rep.section_feedback]}

    return {"resume_id": resume_id, "inferred_role": general.top_role, "strategy": strategy, "jd": jd}


# ── In-place editing on the original PDF layout ──────────────────

class LayoutEdit(BaseModel):
    key: str                      # statement id or unit id: echoed back in the result
    unit_ids: list[str]
    text: str


class LayoutRequest(BaseModel):
    edits: list[LayoutEdit] = []
    scale: float = 2.0


def _pdf_path(row: Resume, resume_id: str):
    if row.file_type != "pdf":
        raise HTTPException(415, "Editing in the original layout is available for PDF uploads")
    path = settings.upload_dir / f"{resume_id}.pdf"
    if not path.exists():
        raise HTTPException(404, "Original file no longer on disk")
    return path


@router.get("/{resume_id}/units", summary="Editable text runs on each page of the original PDF")
def get_units(resume_id: str, db: Session = Depends(get_db)):
    from dataclasses import asdict
    from backend.editor.inplace import document_units
    row, data = _load(db, resume_id)
    with pymupdf.open(_pdf_path(row, resume_id)) as doc:
        units = document_units(doc, data.lines)
    return {"resume_id": resume_id, "units": [asdict(u) for u in units]}


def _apply_layout(resume_id: str, req: LayoutRequest, db: Session):
    from backend.editor.inplace import apply_edits, document_units
    row, data = _load(db, resume_id)
    doc = pymupdf.open(_pdf_path(row, resume_id))
    units = document_units(doc, data.lines)
    results = apply_edits(doc, units, [e.model_dump() for e in req.edits])
    return doc, results


@router.post("/{resume_id}/layout/preview", summary="Render pages with edits typeset into the original layout")
def layout_preview(resume_id: str, req: LayoutRequest, db: Session = Depends(get_db)):
    import base64
    from dataclasses import asdict
    doc, results = _apply_layout(resume_id, req, db)
    try:
        scale = max(0.5, min(req.scale, 3.0))
        pages = {}
        for pno in sorted({p for r in results if r.ok for p in r.pages}):
            png = doc[pno].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png")
            pages[str(pno)] = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        return {"results": [asdict(r) for r in results], "pages": pages}
    finally:
        doc.close()


@router.post("/{resume_id}/layout/export", summary="Download the original PDF with edits applied in place")
def layout_export(resume_id: str, req: LayoutRequest, db: Session = Depends(get_db)):
    doc, results = _apply_layout(resume_id, req, db)
    try:
        pdf = doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()
    skipped = sum(1 for r in results if not r.ok)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="resume_edited.pdf"',
                             "X-ResumeX-Skipped-Edits": str(skipped),
                             "Access-Control-Expose-Headers": "X-ResumeX-Skipped-Edits"})

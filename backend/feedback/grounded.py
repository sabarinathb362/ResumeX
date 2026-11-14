"""
Grounded suggestions for one statement (used by the in-app editor).

ResumeX 2.0 changes
  * Works on the CURRENT text of the bullet (after the user's accepted edits), not only
    the stored original, so suggestions can be chained.
  * Ground truth = the bullet + its entry header (title, org, dates, tags) + the other
    bullets of the SAME entry + user facts. Facts are still never borrowed across entries.
  * Two paths: rules_response() is instant (no LLM); stream_llm_candidates() streams
    Tier-1 tokens and validates each finished candidate. suggest_for_statement() keeps
    the old synchronous behaviour for /api/editor/suggest and the tests.

Every rules/LLM candidate passes the hard validator; failures are returned separately
(so the UI can show *why* something was blocked) but never offered.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from pydantic import BaseModel, Field

from backend.schemas.resume import ResumeData, DocSection, DocEntry, Statement
from backend.schemas.analysis import StatementGrade
from backend.feedback.validator import validate_rewrite
from backend.readability.rri import (grade_statement, front_load, trim_filler, _template_for,
                                     _question_for, _identity_line, infer_resume_role)


class Suggestion(BaseModel):
    text: str
    why: str
    source: str                # rules | llm | template
    needs_input: bool = False  # contains [blanks] the user must fill
    warnings: list[str] = Field(default_factory=list)
    angle: Optional[str] = None


class SuggestResponse(BaseModel):
    statement_id: str
    original: str
    current: str = ""
    grade: str
    reasons: list[str] = Field(default_factory=list)
    question: str = ""
    suggestions: list[Suggestion] = Field(default_factory=list)
    rejected: list[dict] = Field(default_factory=list)
    llm_used: bool = False


@dataclass
class StatementContext:
    resume: ResumeData
    section: DocSection
    entry: DocEntry
    statement: Statement
    current: str
    grade: StatementGrade
    user_facts: str = ""
    jd_requirement: str = ""
    siblings: list[str] = field(default_factory=list)

    @property
    def is_summary(self) -> bool:
        return self.section.kind == "summary"

    @property
    def ground(self) -> str:
        if self.is_summary:
            # A profile line may summarise facts from anywhere in the resume.
            return f"{self.resume.raw_text or ''} {self.current} {self.user_facts}"
        e = self.entry
        return " ".join([self.statement.text, self.current, e.title, e.subtitle, e.dates,
                         " ".join(e.tags), " ".join(self.siblings), self.user_facts])

    @property
    def allowed(self) -> set[str]:
        return {self.user_facts} if self.user_facts else set()


def _find(resume: ResumeData, statement_id: str):
    for sec in resume.doc_sections:
        for e in sec.entries:
            for st in e.statements:
                if st.id == statement_id:
                    return sec, e, st
    return None


def build_context(resume: ResumeData, statement_id: str, current_text: Optional[str] = None,
                  user_facts: Optional[str] = None, jd_requirement: Optional[str] = None) -> StatementContext:
    found = _find(resume, statement_id)
    if not found:
        raise KeyError(statement_id)
    sec, e, st = found
    current = (current_text or st.text).strip()
    is_current = bool(re.search(r"present|current", e.dates or "", re.I))
    graded = st.model_copy(update={"text": current})
    g = grade_statement(graded, sec, e, is_current)
    siblings = [s.text for s in e.statements if s.id != st.id]
    return StatementContext(resume=resume, section=sec, entry=e, statement=st, current=current, grade=g,
                            user_facts=(user_facts or "").strip(), jd_requirement=(jd_requirement or "").strip(),
                            siblings=siblings)


def _offer(ctx: StatementContext, resp: SuggestResponse, seen: set, text: Optional[str], why: str,
           source: str, angle: Optional[str] = None) -> Optional[Suggestion]:
    if not text or text.strip().lower() in seen:
        return None
    v = validate_rewrite(ctx.current, text, ctx.ground, ctx.allowed)
    if v.is_valid:
        seen.add(text.strip().lower())
        s = Suggestion(text=text.strip(), why=why, source=source, warnings=v.warnings, angle=angle)
        resp.suggestions.append(s)
        return s
    resp.rejected.append({"text": text, "source": source, "problems": v.unsupported_facts, "angle": angle})
    return None


def rules_response(ctx: StatementContext) -> SuggestResponse:
    """Instant suggestions: word-preserving transforms + a fill-in template. No LLM."""
    g = ctx.grade
    resp = SuggestResponse(statement_id=ctx.statement.id, original=ctx.statement.text, current=ctx.current,
                           grade=g.grade, reasons=g.reasons, question=_question_for(g))
    seen = {ctx.current.lower()}
    if ctx.is_summary:
        resp.grade = "-"
        resp.reasons = ["Profile lines are judged on whether they state who you are and your strongest proof."]
        resp.question = "Who are you professionally, what do you build, and what is your single best result?"
        if ctx.statement is ctx.section.entries[0].statements[0]:
            _offer(ctx, resp, seen, _identity_line(ctx.resume, infer_resume_role(ctx.resume)),
                   "Identity + focus + strongest proof, assembled only from your resume.", "rules")
        _offer(ctx, resp, seen, trim_filler(ctx.current), "Removed generic phrases; meaning unchanged.", "rules")
        return resp
    _offer(ctx, resp, seen, front_load(ctx.current, ctx.entry.tags),
           "Same facts, result first — visible in the first 8 words.", "rules")
    _offer(ctx, resp, seen, trim_filler(ctx.current), "Removed filler words; meaning unchanged.", "rules")
    tpl = _template_for(g, ctx.entry)
    if tpl and "[" in tpl:
        resp.suggestions.append(Suggestion(
            text=tpl, why="Fill the [ ] with your real details — the app won't guess them.",
            source="template", needs_input=True))
    return resp


# ── Tier-1 streaming rewrites ────────────────────────────────────

STREAM_REWRITE_SYSTEM = """You rewrite ONE resume bullet so a reviewer sees its value in the first 8 words.
HARD RULES:
1. Use ONLY facts in ORIGINAL, ENTRY_CONTEXT, SAME_ENTRY_BULLETS or USER_FACTS. Never add numbers, tools,
   team sizes, users, companies or outcomes that are not written there. If the result is unknown, leave it out.
2. 15-30 words, one sentence, past tense for past roles, no first person, no filler.
3. TARGET_REQUIREMENT is context only: reuse its wording ONLY for things ORIGINAL already describes.
4. Output the rewritten bullet as plain text on one line. No quotes, no bullet symbol, no explanation."""

ANGLES = {
    "result-first": "Lead with the result if ORIGINAL states one; otherwise lead with a strong verb and the concrete object.",
    "tighter": "Make it shorter and more specific: cut filler words, keep every fact.",
    "jd-aligned": "Phrase it so the overlap with TARGET_REQUIREMENT is obvious, without adding any fact.",
}


def _llm_prompt(ctx: StatementContext, angle: str) -> str:
    e = ctx.entry
    return json.dumps({
        "ORIGINAL": ctx.current,
        "ENTRY_CONTEXT": {"title": e.title, "org_or_degree": e.subtitle, "dates": e.dates,
                          "tools": e.tags, "section": ctx.section.heading},
        "SAME_ENTRY_BULLETS": ctx.siblings[:6],
        "USER_FACTS": ctx.user_facts,
        "TARGET_REQUIREMENT": ctx.jd_requirement,
        "WEAKNESSES": ctx.grade.reasons,
        "STYLE": ANGLES[angle],
    }, ensure_ascii=False)


def clean_line(text: str) -> str:
    t = text.strip().splitlines()[0] if text.strip() else ""
    t = re.sub(r"^[\s\-•*·\d.)]+", "", t).strip().strip('"“”\'')
    return re.sub(r"\s+", " ", t)


async def stream_llm_candidates(ctx: StatementContext, router, angles: Optional[list[str]] = None
                                ) -> AsyncIterator[dict]:
    """Yields SSE-ready events: status, start, token, candidate, rejected."""
    from backend.llm.router import LLMUnavailable
    if not await router.is_online():
        yield {"event": "status", "data": {"llm": "offline"}}
        return
    model = router._model_for("fast") if hasattr(router, "_model_for") else None
    yield {"event": "status", "data": {"llm": "online", "model": model}}
    angles = angles or (["result-first", "jd-aligned"] if ctx.jd_requirement else ["result-first", "tighter"])
    resp = SuggestResponse(statement_id=ctx.statement.id, original=ctx.statement.text, grade=ctx.grade.grade)
    seen = {ctx.current.lower()}
    for angle in angles:
        yield {"event": "start", "data": {"angle": angle}}
        buf = []
        try:
            async for piece in router.stream_chat("fast", STREAM_REWRITE_SYSTEM, _llm_prompt(ctx, angle),
                                                  temperature=0.3, max_tokens=90):
                buf.append(piece)
                yield {"event": "token", "data": {"angle": angle, "text": piece}}
        except LLMUnavailable as e:
            yield {"event": "status", "data": {"llm": "error", "message": str(e)}}
            return
        text = clean_line("".join(buf))
        before = len(resp.suggestions)
        _offer(ctx, resp, seen, text, ANGLES[angle], "llm", angle)
        if len(resp.suggestions) > before:
            yield {"event": "candidate", "data": resp.suggestions[-1].model_dump()}
        elif resp.rejected and resp.rejected[-1].get("angle") == angle:
            yield {"event": "rejected", "data": resp.rejected[-1]}


# ── Synchronous API (kept for /api/editor/suggest and tests) ─────

def suggest_for_statement(resume: ResumeData, statement_id: str,
                          jd_requirement: Optional[str] = None,
                          user_facts: Optional[str] = None,
                          use_llm: bool = True,
                          current_text: Optional[str] = None) -> SuggestResponse:
    ctx = build_context(resume, statement_id, current_text, user_facts, jd_requirement)
    resp = rules_response(ctx)
    if not use_llm:
        return resp
    try:
        from backend.llm.client import get_llm_client
        from backend.llm.prompts import GROUNDED_REWRITE_SYSTEM
        client = get_llm_client()
        if client.is_online():
            e = ctx.entry
            prompt = json.dumps({
                "ORIGINAL": ctx.current,
                "ENTRY_CONTEXT": {"title": e.title, "org_or_degree": e.subtitle, "tools": e.tags,
                                  "dates": e.dates, "section": ctx.section.heading},
                "SAME_ENTRY_BULLETS": ctx.siblings[:6],
                "USER_FACTS": ctx.user_facts, "TARGET_REQUIREMENT": ctx.jd_requirement,
                "WEAKNESSES": ctx.grade.reasons,
            })
            schema = {"type": "object", "properties": {"candidates": {"type": "array", "items": {
                "type": "object", "properties": {"text": {"type": "string"}, "why": {"type": "string"}},
                "required": ["text"]}}}, "required": ["candidates"]}
            r = client.generate(GROUNDED_REWRITE_SYSTEM, prompt, json_schema=schema, temperature=0.2, tier="fast")
            if r.raw_json:
                resp.llm_used = True
                seen = {s.text.lower() for s in resp.suggestions} | {ctx.current.lower()}
                for c in r.raw_json.get("candidates", [])[:3]:
                    if isinstance(c, dict):
                        _offer(ctx, resp, seen, c.get("text", ""), c.get("why", "AI rewrite grounded in your text."), "llm")
    except Exception:
        pass
    return resp

"""
Grounded suggestions for one statement (used by the in-app editor).

Candidate sources, in order:
  1. rules  — word-preserving transforms (front-load the result, trim filler).
  2. llm    — local model with GROUNDED_REWRITE_SYSTEM, only if Ollama is up.
  3. template — the user's own sentence with [blanks] for missing facts.
Every rules/LLM candidate passes the hard validator; failures are returned
separately (so the UI can show *why* something was blocked) but never offered.
"""
from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field

from backend.schemas.resume import ResumeData
from backend.feedback.validator import validate_rewrite
from backend.readability.rri import (grade_statement, front_load, trim_filler, _template_for,
                                     _question_for, _identity_line, infer_resume_role)


class Suggestion(BaseModel):
    text: str
    why: str
    source: str               # rules | llm | template
    needs_input: bool = False  # contains [blanks] the user must fill


class SuggestResponse(BaseModel):
    statement_id: str
    original: str
    grade: str
    reasons: list[str] = Field(default_factory=list)
    question: str = ""
    suggestions: list[Suggestion] = Field(default_factory=list)
    rejected: list[dict] = Field(default_factory=list)
    llm_used: bool = False


def _find(resume: ResumeData, statement_id: str):
    for sec in resume.doc_sections:
        for e in sec.entries:
            for st in e.statements:
                if st.id == statement_id:
                    return sec, e, st
    return None


def suggest_for_statement(resume: ResumeData, statement_id: str,
                          jd_requirement: Optional[str] = None,
                          user_facts: Optional[str] = None,
                          use_llm: bool = True) -> SuggestResponse:
    found = _find(resume, statement_id)
    if not found:
        raise KeyError(statement_id)
    sec, e, st = found
    import re
    current = bool(re.search(r"present|current", e.dates or "", re.I))
    g = grade_statement(st, sec, e, current)
    context = " ".join([e.title, e.subtitle, " ".join(e.tags)])
    ground = f"{context} {user_facts or ''}"
    allowed = {user_facts} if user_facts else set()

    resp = SuggestResponse(statement_id=st.id, original=st.text, grade=g.grade,
                           reasons=g.reasons, question=_question_for(g))
    seen = {st.text.strip().lower()}

    def offer(text, why, source):
        if not text or text.strip().lower() in seen:
            return
        v = validate_rewrite(st.text, text, ground, allowed)
        if v.is_valid:
            seen.add(text.strip().lower())
            resp.suggestions.append(Suggestion(text=text.strip(), why=why, source=source))
        else:
            resp.rejected.append({"text": text, "source": source, "problems": v.unsupported_facts})

    if sec.kind == "summary":
        # A profile line may summarise facts from anywhere in the resume (bullets may not
        # borrow facts from other bullets), so the whole resume is the ground truth here.
        ground = resume.raw_text or ground
        resp.grade = "-"
        resp.reasons = ["Profile lines are judged on whether they state who you are and your strongest proof."]
        resp.question = "Who are you professionally, what do you build, and what is your single best result?"
        if st is sec.entries[0].statements[0]:
            offer(_identity_line(resume, infer_resume_role(resume)),
                  "Identity + focus + strongest proof, assembled only from your resume.", "rules")
        offer(trim_filler(st.text), "Removed generic phrases; meaning unchanged.", "rules")
    else:
        offer(front_load(st.text, e.tags), "Same facts, result first — visible in the first 8 words.", "rules")
        offer(trim_filler(st.text), "Removed filler words; meaning unchanged.", "rules")

    if use_llm:
        try:
            from backend.llm.client import get_llm_client
            from backend.llm.prompts import GROUNDED_REWRITE_SYSTEM
            client = get_llm_client()
            if client.is_online():
                prompt = json.dumps({
                    "ORIGINAL": st.text,
                    "ENTRY_CONTEXT": {"title": e.title, "org_or_degree": e.subtitle, "tools": e.tags,
                                      "dates": e.dates, "section": sec.heading},
                    "USER_FACTS": user_facts or "",
                    "TARGET_REQUIREMENT": jd_requirement or "",
                    "WEAKNESSES": g.reasons,
                })
                schema = {"type": "object", "properties": {"candidates": {"type": "array", "items": {
                    "type": "object", "properties": {"text": {"type": "string"}, "why": {"type": "string"}},
                    "required": ["text"]}}}, "required": ["candidates"]}
                r = client.generate(GROUNDED_REWRITE_SYSTEM, prompt, json_schema=schema, temperature=0.2)
                if r.raw_json:
                    resp.llm_used = True
                    for c in r.raw_json.get("candidates", [])[:3]:
                        if isinstance(c, dict):
                            offer(c.get("text", ""), c.get("why", "AI rewrite grounded in your text."), "llm")
        except Exception:
            pass

    tpl = _template_for(g, e) if sec.kind != "summary" else None
    if tpl and "[" in tpl:
        resp.suggestions.append(Suggestion(
            text=tpl, why="Fill the [ ] with your real details — the app won't guess them.",
            source="template", needs_input=True))
    return resp

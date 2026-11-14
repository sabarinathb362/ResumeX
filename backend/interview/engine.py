"""
Mock interview engine: question plan + answer grading.

Questions come from three grounded sources, never from a scraped "real questions" corpus:
  resume      the candidate's own strongest claims (cited by statement id)
  role        the JD's requirements turned into scenarios
  behavioral  the company's culture signals from the JD, plus its published values when the
              user has added them to knowledge_base/company_values.json (with a source URL)
The LLM writes the questions when available; every question must cite a valid claim/requirement,
otherwise deterministic templates fill the round.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Optional

from backend.config import settings
from backend.interview.star import finalize, heuristic_labels

BEHAVIORAL_BANK = {
    "Fast-Paced / Startup": "Tell me about a time you shipped something before you had all the information. What did you decide and why?",
    "Collaborative": "Describe a time you disagreed with a teammate about an approach. How did you resolve it?",
    "Data-Driven": "Tell me about a decision you changed because of data. What did the data show?",
    "Growth-Oriented": "Tell me about something you had to learn quickly to finish a task.",
    "Innovation-Focused": "Describe something you improved that nobody asked you to improve.",
    "Remote-Friendly": "Tell me about a time you kept a project moving without being in the same room as your team.",
    "Enterprise / Established": "Tell me about a time you had to work within strict process or compliance rules.",
    "_default": "Tell me about a time something you built broke. What did you do?",
}


@lru_cache(maxsize=1)
def company_values() -> dict:
    path = settings.knowledge_base_dir / "company_values.json"
    try:
        return {k.lower(): v for k, v in json.loads(path.read_text(encoding="utf-8")).get("companies", {}).items()}
    except Exception:
        return {}


def resume_claims(resume, grades: list) -> list[dict]:
    """Strongest bullets first: A/B grades with a metric make the best probes."""
    order = {"A": 0, "B": 1, "C": 2, "D": 3}
    by_id = {g.id: g for g in grades or []}
    claims = []
    for sec in resume.doc_sections:
        if sec.kind not in ("experience", "projects", "publications", "leadership"):
            continue
        for e in sec.entries:
            for st in e.statements:
                g = by_id.get(st.id)
                claims.append({"id": st.id, "text": st.text, "where": f"{sec.heading} › {e.title}".strip(" ›"),
                               "rank": (order.get(g.grade, 4) if g else 4, 0 if (g and g.has_metric) else 1)})
    claims.sort(key=lambda c: c["rank"])
    return claims[:8]


def _template_plan(claims, reqs, signals, values) -> list[dict]:
    rounds = [{"round": 1, "name": "Resume deep-dive", "questions": []},
              {"round": 2, "name": "Role scenario", "questions": []},
              {"round": 3, "name": "Behavioral & values", "questions": []}]
    for i, c in enumerate(claims[:3]):
        rounds[0]["questions"].append({"id": f"r1q{i + 1}", "probes": c["id"], "why": "Probes your own claim",
                                       "text": f'You wrote: "{c["text"]}" Walk me through how you did it. '
                                               f'What was the hardest trade-off, and what would you change now?'})
    for i, r in enumerate(reqs[:2]):
        rounds[1]["questions"].append({"id": f"r2q{i + 1}", "probes": r, "why": "Built from a JD requirement",
                                       "text": f'This role asks for: "{r}". Describe a concrete situation where you '
                                               f'used this, or how you would approach a first task that needs it.'})
    picks = [v for v in values[:2]] or []
    for i, v in enumerate(picks):
        rounds[2]["questions"].append({"id": f"r3q{i + 1}", "probes": v, "why": "Company value (from its careers page)",
                                       "text": f'Tell me about a time you showed "{v}". What did you do, and what happened?'})
    for s in signals:
        if len(rounds[2]["questions"]) >= 2:
            break
        q = BEHAVIORAL_BANK.get(s)
        if q:
            rounds[2]["questions"].append({"id": f"r3q{len(rounds[2]['questions']) + 1}", "probes": s,
                                           "why": "Culture signal in the JD", "text": q})
    if not rounds[2]["questions"]:
        rounds[2]["questions"].append({"id": "r3q1", "probes": "general", "why": "General behavioral",
                                       "text": BEHAVIORAL_BANK["_default"]})
    return rounds


def _llm_questions(round_name: str, payload: dict, valid_probes: set[str]) -> list[dict]:
    from backend.llm.client import get_llm_client
    from backend.llm.prompts import INTERVIEW_QUESTION_SYSTEM
    client = get_llm_client()
    if not client.is_online():
        return []
    schema = {"type": "object", "properties": {"questions": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "text": {"type": "string"}, "probes": {"type": "string"}, "why": {"type": "string"}},
        "required": ["text", "probes"]}}}, "required": ["questions"]}
    r = client.generate(INTERVIEW_QUESTION_SYSTEM, json.dumps({**payload, "ROUND": round_name}, ensure_ascii=False),
                        json_schema=schema, temperature=0.4, tier="deep")
    out = []
    if r.fallback_used:
        return []
    for q in (r.raw_json or {}).get("questions", []):
        if isinstance(q, dict) and q.get("text") and (round_name == "behavioral" or q.get("probes") in valid_probes):
            out.append({"text": q["text"].strip(), "probes": q.get("probes", ""), "why": (q.get("why") or "")[:80]})
    return out


def build_plan(resume, grades: list, jd=None, company: str = "", role: str = "", signals: Optional[list] = None,
               use_llm: bool = True) -> dict:
    claims = resume_claims(resume, grades)
    reqs = [r.text for r in (jd.requirements if jd else []) if getattr(r, "text", "")][:6]
    vals_entry = company_values().get((company or "").lower(), {})
    values = vals_entry.get("values", [])
    signals = signals or []
    rounds = _template_plan(claims, reqs, signals, values)
    llm_rounds = 0
    if use_llm:
        payload = {"ROLE": role, "COMPANY": company, "JD_REQUIREMENTS": reqs, "COMPANY_SIGNALS": signals + values,
                   "RESUME_CLAIMS": [{"id": c["id"], "text": c["text"]} for c in claims]}
        for idx, (name, valid) in enumerate((("resume", {c["id"] for c in claims}), ("role", set(reqs)),
                                             ("behavioral", set()))):
            got = _llm_questions(name, payload, valid)[:3]
            if got:
                llm_rounds += 1
                rounds[idx]["questions"] = [{**q, "id": f"r{idx + 1}q{i + 1}"} for i, q in enumerate(got)]
    return {"company": company, "role": role, "rounds": rounds,
            "question_model": settings.llm_model if llm_rounds else None,   # None = built-in templates only
            "values_source": vals_entry.get("source_url"),
            "disclosure": "Questions are generated from your resume, this JD and the company's published values. "
                          "They are practice questions, not questions this company is known to ask."}


def grade_answer(question: str, answer: str, resume_evidence: list[str], use_llm: bool = True) -> dict:
    labels, method = None, "heuristic"
    if use_llm and answer.strip():
        from backend.llm.client import get_llm_client
        from backend.llm.prompts import STAR_GRADER_SYSTEM
        client = get_llm_client()
        if client.is_online():
            part = {"type": "object", "properties": {"present": {"type": "boolean"}, "quote": {"type": "string"},
                                                     "score": {"type": "number"}}, "required": ["present", "quote", "score"]}
            schema = {"type": "object", "properties": {**{p: part for p in ("situation", "task", "action", "result")},
                                                       "tip": {"type": "string"}, "stronger_answer": {"type": "string"}},
                      "required": ["situation", "task", "action", "result", "tip"]}
            r = client.generate(STAR_GRADER_SYSTEM,
                                json.dumps({"QUESTION": question, "ANSWER": answer, "RESUME_EVIDENCE": resume_evidence},
                                           ensure_ascii=False),
                                json_schema=schema, temperature=0.0, tier=settings.llm_interview_tier)
            if r.raw_json and not r.fallback_used:
                labels, method = r.raw_json, "llm"
    if labels is None:
        labels = heuristic_labels(answer)
    result = finalize(labels, answer, resume_evidence, method)
    tier_model = settings.llm_fast_model if settings.llm_interview_tier == "fast" else settings.llm_model
    result["model"] = tier_model if method == "llm" else None
    return result


def evidence_for(question: dict, resume) -> list[str]:
    """The claim a resume question probes, plus the rest of that entry, as grading evidence."""
    for sec in resume.doc_sections:
        for e in sec.entries:
            ids = {st.id for st in e.statements}
            if question.get("probes") in ids:
                return [st.text for st in e.statements]
    words = set(re.findall(r"[a-z]{4,}", (question.get("text") or "").lower()))
    scored = []
    for sec in resume.doc_sections:
        for e in sec.entries:
            for st in e.statements:
                s = len(words & set(re.findall(r"[a-z]{4,}", st.text.lower())))
                if s:
                    scored.append((s, st.text))
    return [t for _, t in sorted(scored, reverse=True)[:4]]

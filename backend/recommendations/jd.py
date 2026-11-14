"""
Phase 12 → ResumeX 2.0 — JD-based feedback and AI Match %.

What changed
  * Requirement types are read from the enum value (the old string test marked every
    requirement as "required").
  * Evidence retrieval is per requirement: each bullet is scored by canonical skill overlap
    (aliases count, see feedback/taxonomy.py) plus content-word overlap. Stop-words like
    "experience" or "strong" no longer count as a match.
  * With use_llm=True the Tier-2 model judges all requirements in ONE call. It may only cite
    evidence ids it was shown; a "met"/"partial" verdict without a valid citation is
    downgraded. Without the LLM the deterministic verdicts are used.
  * Every verdict carries statement ids, so the editor can highlight the evidence.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from pydantic import BaseModel, Field

from backend.config import settings
from backend.schemas.resume import ResumeData
from backend.schemas.jd import JDData, RequirementType
from backend.matching.hybrid import run_hybrid_matching, HybridMatchResult
from backend.feedback.taxonomy import grounded_canonicals
from backend.llm.prompts import JD_REQUIREMENT_JUDGE_SYSTEM


class RequirementVerdict(BaseModel):
    requirement_id: str = ""
    requirement_text: str
    requirement_type: str            # required | preferred | education | certification | responsibility
    verdict: str                     # met | partial | transferable | missing
    confidence: str                  # low | med | high
    evidence_span: Optional[str] = None
    evidence_statement_ids: list[str] = Field(default_factory=list)
    rationale: str
    potential_uplift_points: float = 0.0
    method: str = "rules"            # rules | llm


class JDSectionFeedback(BaseModel):
    section: str
    priority: str
    issue: str
    action: str
    example_fix: Optional[str] = None


class JDFocusedReport(BaseModel):
    ai_match_percentage: float
    confidence_band: str
    hybrid_score: float
    score_agreement: str             # high_agreement | moderate | discrepancy
    discrepancy_explanation: Optional[str] = None
    met_count: int
    partial_count: int
    missing_count: int
    requirement_verdicts: list[RequirementVerdict] = Field(default_factory=list)
    section_feedback: list[JDSectionFeedback] = Field(default_factory=list)
    judge: str = "rules"             # rules | rules+llm
    disclosure: str = (
        "AI Match % is ResumeX's explainable requirement-by-requirement evaluation. "
        "It measures how well the resume evidences stated requirements — not a prediction of hiring decisions."
    )


REQ_WEIGHT = {"required": 3.0, "education": 2.0, "certification": 2.0, "preferred": 1.0, "responsibility": 1.0}
EARNED = {"met": 1.0, "partial": 0.6, "transferable": 0.4, "missing": 0.0}
STOP = {
    "experience", "experienced", "years", "year", "strong", "knowledge", "understanding", "ability", "skills",
    "skill", "working", "work", "with", "and", "the", "for", "using", "including", "such", "good", "excellent",
    "familiarity", "proficiency", "proficient", "plus", "preferred", "required", "must", "have", "least",
    "minimum", "solid", "hands", "on", "in", "of", "to", "a", "an", "or", "is", "are", "be", "will", "you",
    "our", "we", "team", "teams", "environment", "related", "field", "etc", "other", "similar", "like",
}


def _req_kind(r) -> str:
    t = getattr(r, "type", None)
    return t.value if isinstance(t, RequirementType) else str(t or "required").lower()


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9+#.-]{2,}", text.lower()) if w not in STOP}


def _statements(resume: ResumeData) -> list[dict]:
    out = []
    if not resume.doc_sections:                      # DOCX/LaTeX/legacy rows: fall back to structured bullets
        groups = [("Experience", f"{x.title or ''} {x.company or ''} {' '.join(x.technologies)}", x.bullets, f"x{i}")
                  for i, x in enumerate(resume.experience or [])]
        groups += [("Projects", f"{p.name or ''} {' '.join(p.technologies)}", p.bullets, f"p{i}")
                   for i, p in enumerate(resume.projects or [])]
        for heading, head, bullets, key in groups:
            for j, b in enumerate(bullets):
                full = f"{b} {head}"
                out.append({"id": f"{key}b{j}", "text": b, "where": f"{heading} › {head.split('  ')[0].strip()}",
                            "skills": grounded_canonicals(full), "words": _content_words(full)})
        return out
    for sec in resume.doc_sections:
        if sec.kind in ("skills", "interests", "languages"):
            continue
        for e in sec.entries:
            head = f"{e.title} {e.subtitle} {' '.join(e.tags)}"
            for st in e.statements:
                full = f"{st.text} {head}"
                out.append({"id": st.id, "text": st.text, "where": f"{sec.heading} › {e.title}".strip(" ›"),
                            "skills": grounded_canonicals(full), "words": _content_words(full)})
    return out


def _retrieve(req_text: str, req_skills: set[str], stmts: list[dict], k: int = 3) -> list[tuple[float, dict]]:
    words = _content_words(req_text)
    scored = []
    for s in stmts:
        skill_hit = len(req_skills & s["skills"])
        word_hit = len(words & s["words"]) / max(1, len(words))
        score = 2.0 * skill_hit + word_hit
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    return scored[:k]


def _rules_verdict(req_skills: set[str], hits: list[tuple[float, dict]], listed: set[str]) -> tuple[str, str, str]:
    covered = set().union(*(h[1]["skills"] for h in hits)) if hits else set()
    if req_skills:
        in_bullets = req_skills & covered
        in_list = req_skills & listed
        if in_bullets == req_skills:
            return "met", "high", "Every named skill appears in a bullet: " + ", ".join(sorted(in_bullets)) + "."
        if in_bullets:
            missing = sorted(req_skills - in_bullets)
            return "partial", "med", "Shown in bullets: " + ", ".join(sorted(in_bullets)) + "; not shown: " + ", ".join(missing) + "."
        if in_list:
            return "partial", "low", "Listed in Skills but never shown in a bullet: " + ", ".join(sorted(in_list)) + "."
        try:
            from backend.nlp.skills import find_skill_match_type
            rel = [s for s in req_skills if find_skill_match_type(s, list(listed | covered))[0] == "related"]
            if rel:
                return "transferable", "low", "Related skills found for: " + ", ".join(sorted(rel)) + "."
        except Exception:
            pass
        return "missing", "high", "None of the named skills appear in the resume."
    if hits and hits[0][0] >= 0.5:
        return "partial", "low", "Some wording overlaps; the link is not explicit."
    return "missing", "med", "No bullet clearly addresses this."


def _llm_judge(reqs: list[dict], evidence: list[dict]) -> dict[str, dict]:
    from backend.llm.client import get_llm_client
    client = get_llm_client()
    if not client.is_online():
        return {}
    payload = {"requirements": [{"id": r["id"], "text": r["text"], "type": r["type"]} for r in reqs],
               "evidence": [{"id": e["id"], "where": e["where"], "text": e["text"]} for e in evidence]}
    schema = {"type": "object", "properties": {"verdicts": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"},
        "verdict": {"type": "string", "enum": ["met", "partial", "transferable", "missing"]},
        "confidence": {"type": "string", "enum": ["low", "med", "high"]},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"}}, "required": ["id", "verdict", "confidence", "evidence_ids"]}}},
        "required": ["verdicts"]}
    r = client.generate(JD_REQUIREMENT_JUDGE_SYSTEM, json.dumps(payload, ensure_ascii=False),
                        json_schema=schema, temperature=0.0, tier=settings.llm_judge_tier)
    if not r.raw_json:
        return {}
    return {v.get("id"): v for v in r.raw_json.get("verdicts", []) if isinstance(v, dict)}


def evaluate_jd_match_and_feedback(
    resume: ResumeData,
    jd: JDData,
    existing_hybrid: Optional[HybridMatchResult] = None,
    use_llm: bool = False,
) -> JDFocusedReport:
    hybrid = existing_hybrid or run_hybrid_matching(resume, jd)
    stmts = _statements(resume)
    by_id = {s["id"]: s for s in stmts}
    listed = {c for c in grounded_canonicals(" ".join(resume.all_skills_flat or []))}

    reqs = [{"id": r.id or f"r{i}", "text": r.text.strip(), "type": _req_kind(r),
             "skills": grounded_canonicals(" ".join([r.text, *r.normalized_skills, *r.skills]))}
            for i, r in enumerate(jd.requirements) if r.text.strip()]
    if not reqs and jd.required_skills:
        reqs = [{"id": f"s{i}", "text": s, "type": "required", "skills": grounded_canonicals(s)}
                for i, s in enumerate(jd.required_skills[:8])]

    for r in reqs:
        r["hits"] = _retrieve(r["text"], r["skills"], stmts)
        r["verdict"], r["confidence"], r["rationale"] = _rules_verdict(r["skills"], r["hits"], listed)
        r["evidence_ids"] = [h[1]["id"] for h in r["hits"] if r["verdict"] != "missing"][:2]
        r["method"] = "rules"

    judge = "rules"
    if use_llm and reqs:
        pool_ids = []
        for r in reqs:
            pool_ids += [h[1]["id"] for h in r["hits"]]
        pool = [by_id[i] for i in dict.fromkeys(pool_ids)][:30]       # fits the 4k Tier-2 context
        verdicts = _llm_judge(reqs, pool)
        if verdicts:
            judge = "rules+llm"
            valid = {e["id"] for e in pool}
            for r in reqs:
                v = verdicts.get(r["id"])
                if not v:
                    continue
                cited = [i for i in v.get("evidence_ids", []) if i in valid]
                verdict = v.get("verdict", "missing")
                if verdict in ("met", "partial", "transferable") and not cited:
                    continue                                          # uncited claim: keep the rules verdict
                r.update(verdict=verdict, confidence=v.get("confidence", "med"), evidence_ids=cited[:2],
                         rationale=(v.get("rationale") or r["rationale"])[:240], method="llm")

    verdict_models, total_w, earned_w = [], 0.0, 0.0
    for r in reqs:
        w = REQ_WEIGHT.get(r["type"], 1.0)
        total_w += w
        earned = EARNED.get(r["verdict"], 0.0)
        earned_w += earned * w
        ev = by_id.get(r["evidence_ids"][0])["text"] if r["evidence_ids"] else None
        verdict_models.append(RequirementVerdict(
            requirement_id=r["id"], requirement_text=r["text"], requirement_type=r["type"],
            verdict=r["verdict"], confidence=r["confidence"], evidence_span=ev,
            evidence_statement_ids=r["evidence_ids"], rationale=r["rationale"],
            potential_uplift_points=round((1.0 - earned) * w * 3.5, 1), method=r["method"]))

    ai_pct = round(earned_w / total_w * 100, 1) if total_w else hybrid.overall_score
    diff = abs(ai_pct - hybrid.overall_score)
    if diff <= 10:
        agreement, why = "high_agreement", None
    elif diff <= 18:
        agreement, why = "moderate", "Keyword matching and requirement-level evidence differ somewhat."
    else:
        agreement, why = "discrepancy", (f"Hybrid score {hybrid.overall_score} vs requirement evidence {ai_pct}: "
                                         "review the missing requirements below.")

    missing_req = [v for v in verdict_models if v.verdict == "missing" and v.requirement_type == "required"]
    partial = [v for v in verdict_models if v.verdict == "partial"]
    feedback = []
    if missing_req:
        feedback.append(JDSectionFeedback(
            section="experience", priority="high",
            issue=f"{len(missing_req)} required qualification(s) have no evidence in your bullets.",
            action="If you have done this, say where in a project or role bullet — a skills-list entry alone is weak evidence.",
            example_fix=f"[What you did] with {missing_req[0].requirement_text[:60]} [where], [result]."))
    if partial:
        feedback.append(JDSectionFeedback(
            section="experience", priority="medium",
            issue=f"{len(partial)} requirement(s) are only partly evidenced.",
            action="Name the exact tool and the outcome in the bullet that already describes this work.",
            example_fix=partial[0].rationale))

    n = len(verdict_models) or 1
    band = "±3%" if judge == "rules+llm" else f"±{min(10, round(30 / n ** 0.5))}%"
    return JDFocusedReport(
        ai_match_percentage=ai_pct, confidence_band=band, hybrid_score=hybrid.overall_score,
        score_agreement=agreement, discrepancy_explanation=why,
        met_count=sum(v.verdict == "met" for v in verdict_models),
        partial_count=sum(v.verdict in ("partial", "transferable") for v in verdict_models),
        missing_count=sum(v.verdict == "missing" for v in verdict_models),
        requirement_verdicts=verdict_models, section_feedback=feedback, judge=judge)

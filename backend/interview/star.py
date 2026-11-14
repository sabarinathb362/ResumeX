"""
Mock interview — STAR scoring that never trusts the model blindly.

The LLM (or the offline heuristic) returns per-part LABELS. This module:
  * checks every quote is a verbatim substring of the answer (an unverifiable quote caps that part at 3/10),
  * computes the weighted score in code: Situation 15, Task 15, Action 35, Result 35,
  * lists numbers the answer states that the resume does not (for "can you back this up?" prompts),
  * drops a "stronger answer" that adds facts the candidate never gave.
"""
from __future__ import annotations

import re
from typing import Optional

from backend.feedback.validator import extract_numbers, validate_rewrite

PARTS = ("situation", "task", "action", "result")
WEIGHTS = {"situation": 15, "task": 15, "action": 35, "result": 35}

_CUES = {
    "situation": re.compile(r"\b(when|while|at (?:my|our)|at \w+,? (?:our|my|the)|during|the (?:problem|issue|challenge)|"
                            r"our (?:team|system|app)|we had|there was|took|was (?:slow|failing|broken)|kept failing)\b", re.I),
    "task": re.compile(r"\b(i (?:was|had) to|my (?:goal|job|task|role|responsibility)|i needed to|i was (?:asked|responsible)|i owned)\b", re.I),
    "action": re.compile(r"\bi (?:built|wrote|designed|implemented|added|created|led|set up|migrated|refactored|tested|"
                         r"analy[sz]ed|automated|fixed|deployed|trained|measured|profiled|proposed|reduced|rewrote|introduced)\b", re.I),
    "result": re.compile(r"(\d+(?:\.\d+)?\s?%|\b(resulted|reduc\w+|improv\w+|increas\w+|cut|saved|fell|dropped|grew|"
                         r"so that|which meant|as a result|outcome|launched|shipped)\b)", re.I),
}


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip().lower()


def heuristic_labels(answer: str) -> dict:
    """Offline fallback: cue-phrase detection, conservative scores."""
    out = {}
    sentences = re.split(r"(?<=[.!?])\s+", answer.strip())
    for p in PARTS:
        hit = next((s for s in sentences if _CUES[p].search(s)), "")
        score = 0
        if hit:
            score = 6
            if p in ("action", "result") and re.search(r"\d", hit):
                score = 8
        out[p] = {"present": bool(hit), "quote": hit[:200], "score": score}
    gap = max(PARTS, key=lambda p: WEIGHTS[p] * (10 - out[p]["score"]))
    out["tip"] = {
        "result": "Finish with the result: what changed, by how much, and for whom.",
        "action": "Say what you personally did, step by step, instead of what the team did.",
        "task": "State your specific responsibility before describing the work.",
        "situation": "Open with one sentence of context: the system, the problem and the stakes.",
    }[gap]
    out["stronger_answer"] = ""
    return out


def finalize(labels: dict, answer: str, resume_evidence: list[str], method: str) -> dict:
    ans = _norm(answer)
    parts = {}
    for p in PARTS:
        raw = labels.get(p) or {}
        quote = (raw.get("quote") or "").strip()
        score = max(0.0, min(10.0, float(raw.get("score") or 0)))
        present = bool(raw.get("present")) and score > 0
        verified = (not quote) or _norm(quote) in ans
        if present and quote and not verified:
            score = min(score, 3.0)                    # the model quoted words that are not there
        parts[p] = {"present": present, "quote": quote if verified else "", "score": score,
                    "quote_verified": verified}
    overall = round(sum(WEIGHTS[p] * parts[p]["score"] / 10 for p in PARTS), 1)

    evidence = " ".join(resume_evidence)
    ev_nums = extract_numbers(evidence)
    unverified = sorted({f"{n:g}" for n in extract_numbers(answer) if n not in ev_nums and n >= 2})

    stronger: Optional[str] = (labels.get("stronger_answer") or "").strip() or None
    # [brackets] are placeholders for facts the candidate still has to supply, so they are not checked
    if stronger and not validate_rewrite(answer, re.sub(r"\[[^\]]*\]", "", stronger), evidence).is_valid:
        stronger = None
    return {"parts": parts, "overall": overall, "weights": WEIGHTS,
            "tip": (labels.get("tip") or "").strip()[:240],
            "stronger_answer": stronger,
            "numbers_not_on_resume": unverified,
            "method": method}

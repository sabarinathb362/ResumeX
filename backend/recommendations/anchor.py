"""
Anchor free-text recommendations to editor statements.

General (Phase 11) and JD (Phase 12) recommendations quote evidence as plain text
(`evidence_span`). The editor needs statement ids and line ids to highlight the page.
This maps each span to the best-matching statement by token overlap.
"""
from __future__ import annotations

import re
from typing import Optional

from backend.schemas.resume import ResumeData

_W = re.compile(r"[a-z0-9][a-z0-9+#.%-]*")


def _tokens(t: str) -> set[str]:
    return {w for w in _W.findall((t or "").lower()) if len(w) > 2}


def statement_index(resume: ResumeData) -> list[tuple[str, list[str], str, set[str]]]:
    out = []
    for sec in resume.doc_sections:
        for e in sec.entries:
            for st in e.statements:
                out.append((st.id, st.line_ids, st.text, _tokens(st.text)))
    return out


def anchor_text(index, span: Optional[str], min_overlap: float = 0.5) -> tuple[list[str], list[str]]:
    """Return (statement_ids, line_ids) for the statement that best contains `span`."""
    if not span:
        return [], []
    q = _tokens(span)
    if not q:
        return [], []
    best, best_score = None, 0.0
    for sid, lids, text, toks in index:
        if span.strip().lower() in text.lower():
            return [sid], list(lids)
        score = len(q & toks) / len(q)
        if score > best_score:
            best, best_score = (sid, lids), score
    if best and best_score >= min_overlap:
        return [best[0]], list(best[1])
    return [], []

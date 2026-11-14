"""
ATS 2.0 — Simulated 7-second skim ("gaze") over the real page layout.

This is a transparent heuristic, not eye tracking. It encodes what eye-tracking studies of
recruiters report qualitatively (Ladders 2012/2018: ~6-7.4 s first pass, F/E-shaped scanning,
most attention on job titles, clear headings and the top of page 1) as fixed, tunable weights,
then spends a fixed fixation budget over the lines of THIS resume.

Every number below is a model assumption you can tune; none is a measured constant.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

SKIM_SECONDS = 7.4                 # Ladders 2018 average first pass
FIXATIONS_PER_SECOND = 4.0         # typical reading rate assumption (~250 ms per fixation)
ROLE_WEIGHT = {"contact": 0.9, "heading": 1.0, "title": 1.0, "meta": 0.65, "statement": 0.55,
               "item": 0.45, "text": 0.4}
PAGE_DECAY = 0.55                  # page 2+ gets this share of page-1 attention
VERTICAL_DECAY = 1.6               # exp(-k * y/H): top of page dominates
LEFT_BIAS = 0.35                   # lines starting far from the left margin lose up to 35%
LONG_BULLET_DROP = 0.6             # 3rd+ line of a bullet keeps 60% (assumption, not a measured figure)
SKIM_WORDS = 8                     # a skimmer reads ~the first 8 words of a bullet (same as RRI)
SEEN_THRESHOLD = 0.6               # fixations a line needs to count as "seen"


@dataclass
class LineAttention:
    line_id: str
    page: int
    weight: float                  # 0..1, relative heat for the overlay
    fixations: float
    seen: bool
    hot_fraction: float = 1.0      # share of the line's width the eye covers (first ~8 words)


@dataclass
class AttentionReport:
    lines: list[LineAttention] = field(default_factory=list)
    seen_line_ids: list[str] = field(default_factory=list)
    budget_fixations: float = 0.0
    seen_share: float = 0.0
    seen_titles: list[str] = field(default_factory=list)
    seen_lines: list[dict] = field(default_factory=list)      # what the skim lands on, strongest first
    seen_by_role: dict = field(default_factory=dict)          # e.g. {"heading": 3, "title": 4, "statement": 2}
    total_lines: int = 0
    missed_strong: list[dict] = field(default_factory=list)   # strong bullets/entries a skimmer misses
    verdict: str = ""
    method: str = "simulated-layout-v1"
    disclosure: str = ("Simulated from your page layout with fixed, tunable weights. "
                       "It is not eye tracking and does not predict a specific reviewer.")


def _body_size(lines) -> float:
    sizes = sorted(round(l.size * 2) / 2 for l in lines if l.size)
    return sizes[len(sizes) // 2] if sizes else 10.0


def simulate_attention(resume, statement_grades: Optional[list] = None) -> AttentionReport:
    lines = list(resume.lines or [])
    if not lines or not resume.page_sizes:
        return AttentionReport(verdict="Page layout is not available for this file type.")
    body = _body_size(lines)
    stmt_of_line, stmt_lines = {}, {}
    for sec in resume.doc_sections:
        for e in sec.entries:
            for st in e.statements:
                stmt_lines[st.id] = list(st.line_ids)
                for i, lid in enumerate(st.line_ids):
                    stmt_of_line[lid] = (st, i)

    raw: dict[str, float] = {}
    for l in lines:
        w_page, h_page = resume.page_sizes[min(l.page, len(resume.page_sizes) - 1)]
        x0, y0, x1, y1 = l.bbox
        w = ROLE_WEIGHT.get(l.role, 0.4)
        w *= math.exp(-VERTICAL_DECAY * (y0 / max(1.0, h_page)))
        w *= PAGE_DECAY ** l.page
        w *= 1.0 - LEFT_BIAS * min(1.0, max(0.0, x0 / max(1.0, w_page) - 0.08) / 0.5)
        w *= 1.0 + 0.6 * max(0.0, (l.size or body) / body - 1.0)        # bigger type pulls the eye
        w *= 1.0 + 0.3 * (l.bold_ratio or 0.0)                           # bold anchors
        if re.search(r"\d+(?:\.\d+)?\s?%|\$\s?\d|\b\d{2,}\b", l.text):  # numbers are anchors
            w *= 1.15
        st_i = stmt_of_line.get(l.id)
        if st_i and st_i[1] >= 2:
            w *= LONG_BULLET_DROP
        raw[l.id] = w

    text_of = {l.id: l.text for l in lines}
    budget = SKIM_SECONDS * FIXATIONS_PER_SECOND
    total = sum(raw.values()) or 1.0
    peak = max(raw.values()) or 1.0
    out, seen = [], []
    for l in lines:
        fx = budget * raw[l.id] / total
        hot = 1.0
        st_i = stmt_of_line.get(l.id)
        if st_i:
            words_before = sum(len(text_of.get(x, "").split()) for x in stmt_lines[st_i[0].id][:st_i[1]])
            n = max(1, len(l.text.split()))
            hot = max(0.0, min(1.0, (SKIM_WORDS - words_before) / n))
        la = LineAttention(l.id, l.page, round(raw[l.id] / peak, 3), round(fx, 2), fx >= SEEN_THRESHOLD and hot > 0, round(hot, 2))
        out.append(la)
        if la.seen:
            seen.append(l.id)

    seen_set = set(seen)
    by_id = {l.id: l for l in lines}
    titles = [by_id[i].text for i in seen if by_id[i].role in ("title", "heading")][:6]
    missed = []
    for g in statement_grades or []:
        if g.grade in ("A", "B") and g.line_ids and g.line_ids[0] not in seen_set:
            missed.append({"statement_id": g.id, "entry": g.entry, "text": g.text, "grade": g.grade})
    ranked = sorted((la for la in out if la.seen), key=lambda la: -la.weight)
    seen_lines = [{"line_id": la.line_id, "text": by_id[la.line_id].text[:140], "role": by_id[la.line_id].role,
                   "weight": la.weight, "page": la.page} for la in ranked[:10]]
    roles = Counter(by_id[i].role for i in seen)
    report = AttentionReport(lines=out, seen_line_ids=seen, budget_fixations=round(budget, 1),
                             seen_share=round(len(seen) / len(lines), 2), seen_titles=titles, missed_strong=missed[:5],
                             seen_lines=seen_lines, seen_by_role=dict(roles), total_lines=len(lines))

    def n(count, word, many=None):
        return f"{count} {word if count == 1 else (many or word + 's')}"
    parts = []
    if roles.get("contact"):
        parts.append("your name and contact line")
    if roles.get("heading"):
        parts.append(n(roles["heading"], "section heading"))
    if roles.get("title") or roles.get("meta"):
        parts.append(n(roles.get("title", 0) + roles.get("meta", 0), "entry title line"))
    body = roles.get("statement", 0) + roles.get("item", 0) + roles.get("text", 0)
    if body:
        parts.append("the first words of " + n(body, "bullet or body line"))
    head = f"In a ~{SKIM_SECONDS:g}-second skim, about {len(seen)} of {len(lines)} lines get a look"
    if parts:
        head += ": " + (", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0])
    tail = ""
    if missed:
        names = sorted({m["entry"] or "a bullet" for m in missed})[:3]
        tail = f". Likely missed: {len(missed)} strong bullet(s) under " + ", ".join(names) + " — move them higher or lead with the result"
    report.verdict = head + tail + "."
    return report

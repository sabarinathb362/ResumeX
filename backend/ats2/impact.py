"""
ATS 2.0 — Verifiable Impact Quotient (VIQ).

VIQ = 100 x (bullets with an action, a named object AND a quantified outcome) / (graded bullets),
weighted by section (experience counts more than volunteering), reusing RRI's per-bullet labels so
the two scores can never disagree about what a bullet contains.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

TIER1 = {"architected", "spearheaded", "automated", "optimized", "optimised", "launched", "led", "reduced",
         "increased", "cut", "doubled", "tripled", "eliminated", "accelerated", "scaled", "migrated", "shipped",
         "founded", "negotiated", "won", "delivered", "pioneered", "redesigned", "saved"}
TIER3_RE = re.compile(r"^(assisted|helped|helping|worked on|working on|responsible for|participated|"
                      r"involved in|part of|tasked with|exposure to|familiar with|learned|learning)\b", re.I)
SECTION_WEIGHT = {"experience": 1.6, "projects": 1.0, "leadership": 0.6, "volunteer": 0.4, "extracurricular": 0.3}


@dataclass
class ImpactItem:
    statement_id: str
    tag: str          # green | amber | red
    verb: str
    tier: int         # 1 strong | 2 neutral | 3 passive
    why: str
    text: str = ""
    entry: str = ""
    section: str = ""
    grade: str = ""
    missing: list = field(default_factory=list)


@dataclass
class ImpactReport:
    viq: float = 0.0
    viq_weighted: float = 0.0
    counts: dict = field(default_factory=dict)
    items: list[ImpactItem] = field(default_factory=list)
    formula: str = "VIQ = 100 x quantified-outcome bullets / graded bullets (section-weighted variant shown too)"


def verb_tier(text: str) -> tuple[str, int]:
    t = text.strip()
    if TIER3_RE.match(t):
        return " ".join(t.split()[:2]).lower(), 3
    first = (re.findall(r"[A-Za-z][\w-]*", t) or [""])[0].lower()
    return first, 1 if first in TIER1 else 2


def impact_quotient(statement_grades: list) -> ImpactReport:
    if not statement_grades:
        return ImpactReport()
    items, n_green, w_total, w_green = [], 0, 0.0, 0.0
    counts = {"green": 0, "amber": 0, "red": 0}
    for g in statement_grades:
        verb, tier = verb_tier(g.text)
        quantified = g.has_action and g.has_specific and g.has_metric and g.has_outcome
        if quantified:
            tag, why = "green", "Action + named object + quantified outcome"
        elif g.has_action and tier < 3:
            tag, why = "amber", "Clear action, but the outcome is missing or not quantified"
        else:
            tag, why = "red", "Describes involvement or duties rather than what you achieved"
        counts[tag] += 1
        w = SECTION_WEIGHT.get(g.section, 1.0)
        w_total += w
        if tag == "green":
            n_green += 1
            w_green += w
        items.append(ImpactItem(g.id, tag, verb, tier, why, text=g.text, entry=getattr(g, "entry", "") or "",
                                section=getattr(g, "section", "") or "", grade=getattr(g, "grade", "") or "",
                                missing=list(getattr(g, "missing", []) or [])))
    return ImpactReport(viq=round(100 * n_green / len(statement_grades), 1),
                        viq_weighted=round(100 * w_green / w_total, 1) if w_total else 0.0,
                        counts=counts, items=items)

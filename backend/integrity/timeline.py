"""
Timeline consistency checks (Phase 5).

Turns every dated entry into a month interval and reports what a recruiter would question:
  end_before_start   a range that runs backwards (error)
  future             a finished role or project dated in the future (warning)
  overlap            two full-time roles at the same time for more than 2 months (warning)
  years_claim        "5+ years of experience" when the dated roles add up to less (warning)
  before_graduation  a full-time role that starts well before the degree ends (info)
  gap                more than 6 months between roles (info; there are many good reasons)
  undated            an experience entry with no dates (info)
Wording stays neutral: these are questions an interviewer may ask, not accusations.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
SEASONS = {"spring": (3, 5), "summer": (6, 8), "fall": (9, 11), "autumn": (9, 11), "winter": (12, 2)}
PRESENT = re.compile(r"\b(present|current|now|ongoing|till date|to date)\b", re.I)
EXPECTED = re.compile(r"\b(expected|exp\.?|anticipated|pursuing)\b", re.I)
PART_TIME = re.compile(r"\b(intern(ship)?|part[- ]time|freelance|contract(or)?|teaching assistant|\bta\b|research assistant|"
                       r"volunteer|trainee|apprentice|fellow(ship)?|co-?op)\b", re.I)
YEARS_CLAIM = re.compile(r"\b(\d{1,2})\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:professional\s+|industry\s+|hands-on\s+)?(?:experience|exp)\b", re.I)
TOKEN = re.compile(r"(?:(?<![a-z])(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*[',]?\s*(?P<y1>(?:19|20)?\d{2})\b)"
                   r"|(?:(?P<mm>0?[1-9]|1[0-2])\s*[/.-]\s*(?P<y2>(?:19|20)\d{2}))"
                   r"|(?:(?P<season>spring|summer|fall|autumn|winter)\s+(?P<y3>(?:19|20)\d{2}))"
                   r"|(?P<y4>\b(?:19|20)\d{2}\b)", re.I)


@dataclass
class Interval:
    entry_id: str
    section: str
    label: str
    start: Optional[int]           # months since year 0 (year*12 + month-1)
    end: Optional[int]
    present: bool = False
    expected: bool = False
    part_time: bool = False
    precise: bool = True           # False when a bound is a bare year ("2021 - 2023")
    raw: str = ""


@dataclass
class Finding:
    kind: str
    severity: str                  # error | warning | info
    message: str
    entry_ids: list[str] = field(default_factory=list)


def _year(y: str) -> int:
    y = int(y)
    return y + 2000 if y < 100 else y


def _tokens(text: str) -> list[tuple[int, int]]:
    """(first_month, last_month) for every date token, in order. A bare year spans Jan-Dec."""
    out = []
    for m in TOKEN.finditer(text):
        if m.group("mon"):
            v = _year(m.group("y1")) * 12 + MONTHS[m.group("mon").lower()[:3]] - 1
            out.append((v, v))
        elif m.group("mm"):
            v = int(m.group("y2")) * 12 + int(m.group("mm")) - 1
            out.append((v, v))
        elif m.group("season"):
            a, b = SEASONS[m.group("season").lower()]
            y = int(m.group("y3"))
            out.append((y * 12 + a - 1, (y + (1 if b < a else 0)) * 12 + b - 1))
        else:
            y = int(m.group("y4"))
            out.append((y * 12, y * 12 + 11))
    return out


def parse_range(text: str, today: date) -> tuple[Optional[int], Optional[int], bool, bool, bool]:
    """(start, end, present, expected, precise) in months; None when the text has no date."""
    toks = _tokens(text or "")
    present = bool(PRESENT.search(text or ""))
    expected = bool(EXPECTED.search(text or ""))
    now = today.year * 12 + today.month - 1
    if not toks:
        return None, None, present, expected, False
    precise = all(a == b or b - a < 11 for a, b in toks)
    start = toks[0][0]
    end = now if present else toks[-1][1]
    return start, end, present, expected, precise


def intervals(resume, today: date) -> list[Interval]:
    out = []
    for sec in resume.doc_sections:
        if sec.kind not in ("experience", "education", "projects", "leadership", "volunteer"):
            continue
        for e in sec.entries:
            s, en, pres, exp, precise = parse_range(e.dates, today)
            text = f"{e.title} {e.subtitle}"
            out.append(Interval(e.id, sec.kind, (e.title or e.subtitle or "Untitled")[:80], s, en, pres, exp,
                                bool(PART_TIME.search(text)) or sec.kind != "experience", precise, e.dates))
    return out


def _fmt(months: int) -> str:
    return f"{months // 12} yr {months % 12} mo" if months >= 12 else f"{months} mo"


def _union(ivs: list[Interval]) -> int:
    spans = sorted((i.start, i.end) for i in ivs if i.start is not None and i.end is not None and i.end >= i.start)
    total, cur = 0, None
    for a, b in spans:
        if cur and a <= cur[1] + 1:
            cur = (cur[0], max(cur[1], b))
        else:
            if cur:
                total += cur[1] - cur[0] + 1
            cur = (a, b)
    if cur:
        total += cur[1] - cur[0] + 1
    return total


def check_timeline(resume, today: Optional[date] = None) -> dict:
    today = today or date.today()
    now = today.year * 12 + today.month - 1
    ivs = intervals(resume, today)
    findings: list[Finding] = []
    jobs = [i for i in ivs if i.section == "experience"]

    for i in ivs:
        if i.start is not None and i.end is not None and i.end < i.start:
            findings.append(Finding("end_before_start", "error", f'"{i.label}" ends before it starts ({i.raw}).', [i.entry_id]))
        elif i.end is not None and i.end > now and not (i.present or i.expected or i.section == "education"):
            findings.append(Finding("future", "warning", f'"{i.label}" is dated in the future ({i.raw}). '
                                    f'If it has not happened yet, say "Expected" or "Upcoming".', [i.entry_id]))
    for i in jobs:
        if i.start is None:
            findings.append(Finding("undated", "info", f'"{i.label}" has no dates. Recruiters look for them first.', [i.entry_id]))

    valid = [i for i in jobs if i.start is not None and i.end is not None and i.end >= i.start]
    full = [i for i in valid if not i.part_time]
    for a_idx, a in enumerate(full):
        for b in full[a_idx + 1:]:
            ov = min(a.end, b.end) - max(a.start, b.start) + 1
            if ov > (2 if a.precise and b.precise else 12):     # "2020-2022" then "2022-2024" is not an overlap
                findings.append(Finding("overlap", "warning",
                                        f'"{a.label}" and "{b.label}" overlap by {_fmt(ov)} and both read as full-time. '
                                        f'If one was part-time, say so in the title.', [a.entry_id, b.entry_id]))

    dated = sorted(valid, key=lambda i: i.start)
    for prev, nxt in zip(dated, dated[1:]):
        gap = nxt.start - prev.end - 1
        if gap > (6 if prev.precise and nxt.precise else 12):
            findings.append(Finding("gap", "info", f"{_fmt(gap)} between \"{prev.label}\" and \"{nxt.label}\". "
                                    f"Be ready to say what you did then.", [prev.entry_id, nxt.entry_id]))

    grads = [i.end for i in ivs if i.section == "education" and i.end is not None]
    if grads:
        grad = max(grads)
        for i in full:
            if i.start is not None and grad - i.start > 6 and i.end is not None and i.end > i.start + 3:
                findings.append(Finding("before_graduation", "info",
                                        f'"{i.label}" starts {_fmt(grad - i.start)} before your degree ends and reads as '
                                        f'full-time. If it was an internship or part-time, say so.', [i.entry_id]))

    worked = _union([i for i in jobs if i.start is not None])
    claim_text = " ".join(st.text for sec in resume.doc_sections if sec.kind in ("summary", "experience")
                          for e in sec.entries for st in e.statements) + " " + (getattr(resume, "summary", "") or "")
    claims = [int(m.group(1)) for m in YEARS_CLAIM.finditer(claim_text)]
    if claims and max(claims) * 12 > worked + 12:
        findings.append(Finding("years_claim", "warning",
                                f"You claim {max(claims)}+ years of experience; the dated roles add up to {_fmt(worked)}. "
                                f"Count only what the dates show, or add the missing roles.", []))

    ids = [i.entry_id for i in ivs if i.start is not None and i.end is not None]
    by_id = {i.entry_id: i for i in ivs}
    matrix = [[max(0, min(by_id[a].end, by_id[b].end) - max(by_id[a].start, by_id[b].start) + 1) if a != b else 0
               for b in ids] for a in ids]
    order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: order[f.severity])
    return {"intervals": [asdict(i) for i in ivs], "overlap_matrix": {"ids": ids, "months": matrix},
            "experience_months": worked, "findings": [asdict(f) for f in findings],
            "today": today.isoformat()}

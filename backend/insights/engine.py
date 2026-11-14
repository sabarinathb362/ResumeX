"""
Unified insight engine.

Collects findings from the ATS rules, the Readability Reviewer (ATS 2.0) and
contact/quality checks into ONE list where every item:
  * says what is wrong in THIS resume (quotes the text, names the section),
  * says why it matters and exactly what to do,
  * points at line ids so the editor can highlight it on the page,
  * carries the points it is worth, so the list is ordered by payoff.
"""
from __future__ import annotations

import re

from backend.schemas.resume import ResumeData
from backend.schemas.analysis import ATSResult, ReadabilityResult, Finding, Severity

_SEV = {Severity.CRITICAL: 4, Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1, Severity.INFO: 0}


def _lines_with(resume: ResumeData, pattern: str, roles=None) -> list[str]:
    rx = re.compile(pattern, re.I)
    return [l.id for l in resume.lines if rx.search(l.text) and (roles is None or l.role in roles)]


def _ats_to_findings(resume: ResumeData, ats: ATSResult) -> list[Finding]:
    out: list[Finding] = []
    contact_ids = [l.id for l in resume.lines if l.role == "contact"]
    contact_text = " ".join(l.text for l in resume.lines if l.role == "contact")
    n = 0
    for cat in ats.category_scores:
        lost = round(cat.max_score - cat.score, 1)
        per = round(lost / max(1, len(cat.findings)), 1)
        for msg in cat.findings:
            n += 1
            f = Finding(id=f"ats{n}", source="ats", dimension=cat.dimension, title=msg,
                        detail="", fix="; ".join(cat.remediation[:1]), points=per,
                        severity=cat.severity if cat.severity != Severity.INFO else Severity.LOW)
            low = msg.lower()
            if "phone number not found" in low:
                f.title = "No phone number in the header"
                f.detail = ("Many recruiters shortlist by phone, and some application systems treat it as a required field."
                            + _placeholder_note(contact_text, r"phone(?: number)?|mobile"))
                f.fix = "Add a phone number with its country code to the contact line."
                f.line_ids, f.action, f.severity = contact_ids, "add", Severity.HIGH
            elif "email address not found" in low:
                f.title = "No email address in the header"
                f.detail = ("Email is how recruiters and applicant tracking systems reply; an application without "
                            "one usually cannot be progressed." + _placeholder_note(contact_text, r"e-?mail(?: address)?"))
                f.fix = "Add a personal, professional email address to the contact line."
                f.line_ids, f.action, f.severity = contact_ids, "add", Severity.CRITICAL
            elif "name not detected" in low:
                f.title = "No name found at the top of the resume"
                f.detail = "Parsers take the candidate's name from the first line. If it is inside an image or header box, it is lost."
                f.fix = "Put your name as plain text on the first line."
                f.line_ids, f.action, f.severity = contact_ids, "add", Severity.CRITICAL
            elif "no skills detected" in low or (low.startswith("missing essential sections") and "skills" in low):
                rest = [x.strip() for x in msg.split(":", 1)[1].split(",") if x.strip() != "skills"] if ":" in msg else []
                f.title = "No Skills section" + (f" (also missing: {', '.join(rest)})" if rest else "")
                f.detail = ("Applicant tracking systems match a job's required skills against a Skills section first. "
                            "Without one, a match depends on the parser finding each skill inside a sentence.")
                f.fix = "Add a Skills section listing the tools, methods and domain skills you have actually used."
                f.action = "add"
            elif low.startswith("missing essential sections"):
                names = msg.split(":", 1)[1].strip() if ":" in msg else ""
                f.title = f"Missing section: {names}"
                f.detail = "Parsers and reviewers both look for these standard sections by name."
                f.fix = f"Add a clearly labelled section for: {names}."
                f.action = "add"
            elif low.startswith("duplicate sections"):
                kinds = re.findall(r"'(\w+)'", msg)
                secs = [s for s in resume.doc_sections if s.kind in kinds]
                f.title = "Two sections cover the same thing: " + " and ".join(f'"{s.heading}"' for s in secs)
                f.detail = "Parsers and readers both expect one section per topic; split content looks disorganised."
                f.fix = "Merge them into one section (or remove the lower-value one)."
                f.line_ids = [s.heading_line_id for s in secs if s.heading_line_id]
                f.action = "reorder"
            elif low.startswith("non-standard headings"):
                names = [x.strip() for x in msg.split(":", 1)[1].split(",")]
                f.title = "Headings an ATS may not recognise: " + ", ".join(f'"{x}"' for x in names)
                f.detail = "ATS parsers map content by heading name; unusual names can drop the content into 'Other'."
                f.fix = "Use standard names: Experience, Projects, Education, Skills, Certifications, Activities."
                f.line_ids = [s.heading_line_id for s in resume.doc_sections if s.heading in names and s.heading_line_id]
                f.action = "edit"
            elif low.startswith("inconsistent date formats"):
                year_only = _lines_with(resume, r"(?<![A-Za-z]\s)\b(19|20)\d{2}\s*[–-]\s*(?:(19|20)\d{2}|Present)\b", roles={"title", "meta"})
                f.title = "Dates are written in two formats"
                f.detail = "Some entries use 'Mar 2026 – Present', others '2021 – 2023'. ATS date parsers and readers both prefer one style."
                f.fix = "Use 'Mon YYYY – Mon YYYY' everywhere (or year-only everywhere)."
                f.line_ids = year_only
                f.action = "format"
            elif "multi-column" in low:
                f.detail = "Your layout uses two columns. Many ATS read straight across the page and interleave both columns."
                f.fix = "Use a single-column layout for applications that go through an ATS."
                f.severity = Severity.HIGH
            elif low.startswith("future date"):
                f.severity = Severity.HIGH
            f.points = round(f.points, 1)
            out.append(f)
    return out


def _placeholder_note(contact_text: str, pattern: str) -> str:
    """If the header still holds template text such as 'Phone Number' or 'E-mail', say so."""
    m = re.search(rf"\b({pattern})\b", contact_text, re.I)
    return f' The header contains the template text "{m.group(1)}" where the real value should be.' if m else ""


def _quality_checks(resume: ResumeData) -> list[Finding]:
    out = []
    c = resume.contact
    contact_ids = [l.id for l in resume.lines if l.role == "contact"]
    if c.email and re.search(r"\.(edu|ac\.in|edu\.in)$|students?\.", c.email, re.I):
        out.append(Finding(id="q_email", source="contact", dimension="Contact Information",
                           title="College email may expire", severity=Severity.LOW, action="edit",
                           detail=f"{c.email} is an institutional address; it often stops working after graduation.",
                           fix="Use a personal email you will keep.", line_ids=contact_ids, points=0.5))
    if not c.location and resume.lines:
        out.append(Finding(id="q_loc", source="contact", dimension="Contact Information",
                           title="No location in the header", severity=Severity.LOW, action="add",
                           detail="Recruiters filter by location and relocation; without a city they have to guess.",
                           fix="Add 'City, State' (and 'Open to relocation' if true) to the contact line.",
                           line_ids=contact_ids, points=0.5))
    return out


def build_insights(resume: ResumeData, ats: ATSResult, rri: ReadabilityResult | None) -> list[Finding]:
    items = _ats_to_findings(resume, ats) + _quality_checks(resume)
    if rri:
        items += rri.findings
    # dedupe by title (two ATS rules can report the same gap, e.g. a missing Skills section);
    # sorting first keeps the more severe / higher-value copy
    items.sort(key=lambda f: (-_SEV[f.severity], -f.points))
    seen, out = set(), []
    for f in items:
        key = re.sub(r"\s*\(also missing.*\)$", "", f.title.lower())
        if key in seen:
            continue
        seen.add(key)
        f.points = round(f.points, 1)
        out.append(f)
    out.sort(key=lambda f: (-_SEV[f.severity], -f.points))
    return out

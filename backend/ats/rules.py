"""
Phase 2 — Deterministic ATS Rule Engine.
Nine independent, testable rules returning {score, max_score, severity, evidence, remediation}.
Weights are in config — never hardcoded. The LLM never alters a score.
"""
import re
from typing import Optional
from datetime import datetime

from backend.schemas.resume import ResumeData
from backend.schemas.analysis import ATSResult, ATSRuleResult, Severity
from backend.config import settings


# ── Standard headings that ATS systems expect ────────────────────

STANDARD_HEADINGS = {
    "summary", "education", "experience", "skills", "projects",
    "certifications", "achievements", "publications", "volunteer",
    "languages", "interests", "references", "courses", "training",
    "extracurricular", "leadership",
}


def _rule_text_extractability(resume: ResumeData) -> ATSRuleResult:
    """Check that text was extractable and intact."""
    max_score = settings.ats_weight_text_extractability
    findings = []
    evidence = []
    remediation = []
    score = max_score

    raw = resume.raw_text
    if not raw or len(raw.strip()) < 50:
        score = 0
        findings.append("No extractable text found in document")
        remediation.append("Ensure the PDF contains selectable text, not just images")
        return ATSRuleResult(
            dimension="Text Extractability", score=score, max_score=max_score,
            severity=Severity.CRITICAL, findings=findings, evidence=evidence,
            remediation=remediation,
        )

    # Check for garbled characters
    garbled_ratio = sum(1 for c in raw if ord(c) > 65535 or c == '\ufffd') / max(len(raw), 1)
    if garbled_ratio > 0.05:
        penalty = max_score * 0.5
        score -= penalty
        findings.append(f"~{garbled_ratio:.1%} of characters appear garbled/corrupted")
        remediation.append("Re-export the PDF with proper font embedding")

    # Check word count minimum
    word_count = getattr(resume.document_metadata, 'word_count', 0) or (len(resume.raw_text.split()) if resume.raw_text else 0)
    if word_count < 100:
        score -= max_score * 0.3
        findings.append(f"Very low word count ({word_count}) — likely incomplete extraction")
        remediation.append("Check if the resume uses images/graphics instead of text")

    # Check for missing page content
    page_count = getattr(resume.layout_metadata, 'page_count', 0) or getattr(resume.document_metadata, 'page_count', 0) or 0
    if page_count > 0:
        words_per_page = word_count / page_count
        if words_per_page < 50:
            score -= max_score * 0.2
            findings.append(f"Low text density ({words_per_page:.0f} words/page)")
            evidence.append(f"Pages: {page_count}, Words: {word_count}")

    return ATSRuleResult(
        dimension="Text Extractability",
        score=max(0, round(score, 1)),
        max_score=max_score,
        severity=Severity.CRITICAL if score < max_score * 0.5 else Severity.INFO,
        findings=findings, evidence=evidence, remediation=remediation,
    )


def _rule_section_structure(resume: ResumeData) -> ATSRuleResult:
    """Check that sections are properly structured with standard headings."""
    max_score = settings.ats_weight_section_structure
    findings = []
    evidence = []
    remediation = []
    score = max_score

    sections = resume.sections
    if not sections:
        score = max_score * 0.2
        findings.append("No clear section headings detected")
        remediation.append("Use standard headings like Education, Experience, Skills, Projects")
        return ATSRuleResult(
            dimension="Section Structure", score=score, max_score=max_score,
            severity=Severity.HIGH, findings=findings, evidence=evidence,
            remediation=remediation,
        )

    normalized_names = [s.normalized_name for s in sections]

    # Check for essential sections
    essential = {"experience", "education", "skills"}
    present = set(normalized_names) & essential
    missing = essential - present
    if missing:
        per_missing = max_score * 0.15
        score -= per_missing * len(missing)
        findings.append(f"Missing essential sections: {', '.join(missing)}")
        remediation.append(f"Add clearly labeled sections for: {', '.join(missing)}")

    # Check for duplicate sections
    from collections import Counter
    counts = Counter(normalized_names)
    duplicates = {name: cnt for name, cnt in counts.items() if cnt > 1 and name}
    if duplicates:
        score -= max_score * 0.1
        findings.append(f"Duplicate sections detected: {duplicates}")
        remediation.append("Consolidate duplicate sections into one")

    # Check section ordering (experience/education should come before interests/references)
    evidence.append(f"Detected sections: {[s.name for s in sections]}")

    return ATSRuleResult(
        dimension="Section Structure",
        score=max(0, round(score, 1)),
        max_score=max_score,
        severity=Severity.HIGH if score < max_score * 0.5 else Severity.INFO,
        findings=findings, evidence=evidence, remediation=remediation,
    )


def _rule_formatting_safety(resume: ResumeData) -> ATSRuleResult:
    """Check for layout elements that cause ATS parsing failures."""
    max_score = settings.ats_weight_formatting_safety
    findings = []
    evidence = []
    remediation = []
    score = max_score
    layout = resume.layout_metadata or LayoutMetadata()

    if getattr(layout, 'has_columns', False):
        score -= max_score * 0.3
        findings.append("Multi-column layout detected — many ATS systems read columns incorrectly")
        remediation.append("Use a single-column layout for maximum ATS compatibility")

    if layout.has_tables:
        score -= max_score * 0.2
        findings.append("Tables detected — some ATS systems cannot parse table content")
        remediation.append("Replace tables with simple bulleted lists or plain text")

    if layout.has_images:
        score -= max_score * 0.15
        findings.append("Images detected — ATS systems cannot read text in images")
        remediation.append("Remove images or ensure all information is also in text form")

    if layout.has_text_boxes:
        score -= max_score * 0.15
        findings.append("Text boxes detected — content may not be extracted by ATS")
        remediation.append("Move text box content into the main document flow")

    if layout.has_headers_footers:
        score -= max_score * 0.1
        findings.append("Headers/footers detected — some ATS systems skip this content")
        remediation.append("Move important information out of headers and footers")

    if not findings:
        evidence.append("Clean formatting — no ATS-risky layout elements detected")

    return ATSRuleResult(
        dimension="Formatting Safety",
        score=max(0, round(score, 1)),
        max_score=max_score,
        severity=Severity.HIGH if score < max_score * 0.5 else Severity.INFO,
        findings=findings, evidence=evidence, remediation=remediation,
    )


def _rule_contact_information(resume: ResumeData) -> ATSRuleResult:
    """Check for complete and valid contact information."""
    max_score = settings.ats_weight_contact_information
    findings = []
    evidence = []
    remediation = []
    score = max_score
    contact = resume.contact

    if not contact.name:
        score -= max_score * 0.3
        findings.append("Name not detected")
        remediation.append("Place your full name prominently at the top of the resume")

    if not contact.email:
        score -= max_score * 0.3
        findings.append("Email address not found")
        remediation.append("Include a professional email address")
    elif contact.email:
        evidence.append(f"Email: {contact.email}")
        # Check for unprofessional email patterns
        if any(w in contact.email.lower() for w in ["sexy", "hot", "cool", "420", "69"]):
            score -= max_score * 0.1
            findings.append("Email address may appear unprofessional")
            remediation.append("Use a professional email address (firstname.lastname@)")

    if not contact.phone:
        score -= max_score * 0.2
        findings.append("Phone number not found")
        remediation.append("Include a phone number for contact")

    if contact.linkedin:
        evidence.append(f"LinkedIn: {contact.linkedin}")
    if contact.github:
        evidence.append(f"GitHub: {contact.github}")

    return ATSRuleResult(
        dimension="Contact Information",
        score=max(0, round(score, 1)),
        max_score=max_score,
        severity=Severity.HIGH if score < max_score * 0.3 else Severity.INFO,
        findings=findings, evidence=evidence, remediation=remediation,
    )


def _rule_standard_headings(resume: ResumeData) -> ATSRuleResult:
    """Check that headings are recognizable by ATS systems."""
    max_score = settings.ats_weight_standard_headings
    findings = []
    evidence = []
    remediation = []
    score = max_score

    sections = resume.sections
    if not sections:
        score = 0
        findings.append("No section headings detected")
        remediation.append("Add clear section headings (Education, Experience, Skills, etc.)")
        return ATSRuleResult(
            dimension="Standard Headings", score=score, max_score=max_score,
            severity=Severity.HIGH, findings=findings, evidence=evidence,
            remediation=remediation,
        )

    recognized = 0
    unrecognized = []
    for section in sections:
        if section.normalized_name in STANDARD_HEADINGS:
            recognized += 1
        else:
            unrecognized.append(section.name)

    recognition_rate = recognized / len(sections) if sections else 0
    score = max_score * recognition_rate

    if unrecognized:
        findings.append(f"Non-standard headings: {', '.join(unrecognized[:5])}")
        remediation.append("Rename to standard ATS-recognized headings")

    evidence.append(f"{recognized}/{len(sections)} headings are ATS-standard")

    return ATSRuleResult(
        dimension="Standard Headings",
        score=max(0, round(score, 1)),
        max_score=max_score,
        severity=Severity.MEDIUM if score < max_score * 0.5 else Severity.INFO,
        findings=findings, evidence=evidence, remediation=remediation,
    )


def _rule_date_consistency(resume: ResumeData) -> ATSRuleResult:
    """Check for chronological consistency and date formatting."""
    max_score = settings.ats_weight_date_consistency
    findings = []
    evidence = []
    remediation = []
    score = max_score

    entries_with_dates = []

    for exp in resume.experience:
        if exp.start_date:
            entries_with_dates.append({
                "type": "experience",
                "title": exp.title,
                "start": exp.start_date,
                "end": exp.end_date or "Present",
            })

    for edu in resume.education:
        if edu.start_date:
            entries_with_dates.append({
                "type": "education",
                "title": edu.institution,
                "start": edu.start_date,
                "end": edu.end_date or "Present",
            })

    if not entries_with_dates:
        score -= max_score * 0.3
        findings.append("No dates found in experience or education entries")
        remediation.append("Add date ranges (e.g., 'Jan 2022 – Present') to all entries")
    else:
        evidence.append(f"Found {len(entries_with_dates)} entries with dates")

        # Check for future dates
        current_year = datetime.now().year
        for entry in entries_with_dates:
            for date_str in [entry["start"], entry["end"]]:
                years = re.findall(r"(\d{4})", date_str)
                for y in years:
                    if int(y) > current_year + 1:
                        score -= max_score * 0.2
                        findings.append(f"Future date detected: {date_str} in {entry['title']}")
                        remediation.append("Correct any future dates")

        # Check for inconsistent date formats
        formats_seen = set()
        for entry in entries_with_dates:
            if re.match(r"\w+\s+\d{4}", entry["start"]):
                formats_seen.add("month_year")
            elif re.match(r"\d{1,2}/\d{4}", entry["start"]):
                formats_seen.add("mm_yyyy")
            elif re.match(r"\d{4}", entry["start"]):
                formats_seen.add("year_only")

        if len(formats_seen) > 1:
            score -= max_score * 0.15
            findings.append(f"Inconsistent date formats: {formats_seen}")
            remediation.append("Use a consistent date format throughout (e.g., 'Month Year')")

    return ATSRuleResult(
        dimension="Date Consistency",
        score=max(0, round(score, 1)),
        max_score=max_score,
        severity=Severity.MEDIUM if score < max_score * 0.5 else Severity.INFO,
        findings=findings, evidence=evidence, remediation=remediation,
    )


def _rule_skill_visibility(resume: ResumeData) -> ATSRuleResult:
    """Check that skills are visible and in appropriate sections."""
    max_score = settings.ats_weight_skill_visibility
    findings = []
    evidence = []
    remediation = []
    score = max_score

    skills = resume.all_skills_flat
    skill_sections = [s for s in resume.sections if s.normalized_name == "skills"]

    if not skills:
        score = 0
        findings.append("No skills detected in the resume")
        remediation.append("Add a dedicated Skills section listing your technical and key skills")
        return ATSRuleResult(
            dimension="Skill Visibility", score=score, max_score=max_score,
            severity=Severity.HIGH, findings=findings, evidence=evidence,
            remediation=remediation,
        )

    if not skill_sections:
        score -= max_score * 0.4
        findings.append("No dedicated Skills section — skills may only appear in bullets")
        remediation.append("Create a separate Skills section for ATS keyword matching")

    evidence.append(f"Total unique skills found: {len(skills)}")
    if len(skills) < 5:
        score -= max_score * 0.2
        findings.append(f"Low skill count ({len(skills)}) — may miss ATS keyword filters")
        remediation.append("Add more relevant skills, especially technical tools and technologies")

    return ATSRuleResult(
        dimension="Skill Visibility",
        score=max(0, round(score, 1)),
        max_score=max_score,
        severity=Severity.MEDIUM if score < max_score * 0.5 else Severity.INFO,
        findings=findings, evidence=evidence, remediation=remediation,
    )


def _rule_links_contact_validity(resume: ResumeData) -> ATSRuleResult:
    """Check URL and email syntax."""
    max_score = settings.ats_weight_links_contact_validity
    findings = []
    evidence = []
    remediation = []
    score = max_score
    contact = resume.contact

    # Validate email format
    if contact.email:
        if not re.match(r"^[\w.+-]+@[\w-]+\.[\w.-]+$", contact.email):
            score -= max_score * 0.3
            findings.append(f"Email format appears invalid: {contact.email}")
            remediation.append("Use a valid email format (name@domain.com)")

    # Check URLs
    all_links = contact.links[:]
    if contact.linkedin:
        all_links.append(contact.linkedin)
    if contact.github:
        all_links.append(contact.github)
    if contact.portfolio:
        all_links.append(contact.portfolio)

    for link in all_links:
        if not re.match(r"^https?://", link, re.IGNORECASE):
            if not link.startswith("www."):
                score -= max_score * 0.1
                findings.append(f"Link may be malformed: {link}")
                remediation.append("Ensure all URLs start with https://")

    if all_links:
        evidence.append(f"Found {len(all_links)} links")

    return ATSRuleResult(
        dimension="Links & Contact Validity",
        score=max(0, round(score, 1)),
        max_score=max_score,
        severity=Severity.LOW if findings else Severity.INFO,
        findings=findings, evidence=evidence, remediation=remediation,
    )


def _rule_parsing_risk(resume: ResumeData) -> ATSRuleResult:
    """Overall parser confidence and unresolved content."""
    max_score = settings.ats_weight_parsing_risk
    findings = []
    evidence = []
    remediation = []
    score = max_score

    # Check if sections were detected
    if not resume.sections:
        score -= max_score * 0.4
        findings.append("Parser could not identify any sections — high parsing risk")

    # Check layout reading order confidence
    conf = getattr(resume.layout_metadata, 'reading_order_confidence', 1.0) if resume.layout_metadata else 1.0
    if conf < 0.8:
        score -= max_score * 0.3
        findings.append("Reading order uncertain — content may be scrambled by some ATS systems")

    # Check if critical data was extracted
    has_experience = len(resume.experience or []) > 0
    has_education = len(resume.education or []) > 0
    contact = resume.contact
    has_contact = bool(getattr(contact, 'name', None) or getattr(contact, 'email', None))

    if not has_contact:
        score -= max_score * 0.1
        findings.append("Contact information could not be confidently extracted")

    if not has_experience and not has_education:
        score -= max_score * 0.2
        findings.append("Neither experience nor education entries were extracted")

    if not findings:
        evidence.append("Parser extracted content with high confidence")

    return ATSRuleResult(
        dimension="Parsing Risk",
        score=max(0, round(score, 1)),
        max_score=max_score,
        severity=Severity.MEDIUM if findings else Severity.INFO,
        findings=findings, evidence=evidence, remediation=remediation,
    )


# ── Run all ATS rules ────────────────────────────────────────────

ALL_RULES = [
    _rule_text_extractability,
    _rule_section_structure,
    _rule_formatting_safety,
    _rule_contact_information,
    _rule_standard_headings,
    _rule_date_consistency,
    _rule_skill_visibility,
    _rule_links_contact_validity,
    _rule_parsing_risk,
]


def run_ats_analysis(resume: ResumeData) -> ATSResult:
    """
    Run all ATS rules and produce the final ATS result.
    Component scores sum exactly to the total — this is a hard invariant.
    """
    category_scores = [rule(resume) for rule in ALL_RULES]
    overall_score = sum(r.score for r in category_scores)
    max_possible = sum(r.max_score for r in category_scores)

    # Collect all warnings (findings with severity >= MEDIUM)
    warnings = []
    for result in category_scores:
        if result.severity in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM):
            for finding in result.findings:
                warnings.append({
                    "dimension": result.dimension,
                    "severity": result.severity.value,
                    "message": finding,
                    "remediation": result.remediation,
                })

    return ATSResult(
        overall_score=round(overall_score, 1),
        max_possible=max_possible,
        category_scores=category_scores,
        warnings=warnings,
    )

"""
Phase 1 — PDF Extraction with PyMuPDF.
Extracts text, sections, layout metadata, links, font info, and bounding boxes.
Retains reading order for the Readability Reviewer (Phase 10).
"""
import re
from typing import Optional

import pymupdf  # PyMuPDF

from backend.schemas.resume import (
    ResumeData, ContactInfo, Education, ExperienceEntry, Project,
    SkillCategory, Certification, Achievement, ResumeSection,
    DocumentMetadata, LayoutMetadata, TextBlock, SourceSpan,
)


# ── Standard section headings ────────────────────────────────────

SECTION_ALIASES: dict[str, str] = {
    "summary": "summary",
    "professional summary": "summary",
    "career summary": "summary",
    "profile": "summary",
    "about me": "summary",
    "objective": "summary",
    "career objective": "summary",
    "education": "education",
    "academic background": "education",
    "qualifications": "education",
    "experience": "experience",
    "work experience": "experience",
    "professional experience": "experience",
    "employment history": "experience",
    "work history": "experience",
    "projects": "projects",
    "personal projects": "projects",
    "academic projects": "projects",
    "key projects": "projects",
    "skills": "skills",
    "technical skills": "skills",
    "core competencies": "skills",
    "technologies": "skills",
    "tools & technologies": "skills",
    "tools and technologies": "skills",
    "programming languages": "skills",
    "certifications": "certifications",
    "certificates": "certifications",
    "licenses & certifications": "certifications",
    "licenses and certifications": "certifications",
    "achievements": "achievements",
    "awards": "achievements",
    "honors": "achievements",
    "honors & awards": "achievements",
    "publications": "publications",
    "research": "publications",
    "volunteer": "volunteer",
    "volunteer experience": "volunteer",
    "interests": "interests",
    "hobbies": "interests",
    "references": "references",
    "languages": "languages",
    "extracurricular": "extracurricular",
    "extracurricular activities": "extracurricular",
    "leadership": "leadership",
    "leadership experience": "leadership",
    "courses": "courses",
    "relevant coursework": "courses",
    "training": "training",
}


def _normalize_heading(text: str) -> str:
    """Normalize a heading to a standard section name."""
    cleaned = re.sub(r"[^a-z0-9\s&]", "", text.lower().strip())
    return SECTION_ALIASES.get(cleaned, cleaned)


def _is_heading(block: dict, avg_font_size: float) -> bool:
    """Heuristic: a text span is a heading if it's bold or notably larger."""
    if not block.get("lines"):
        return False
    for line in block["lines"]:
        for span in line.get("spans", []):
            text = span.get("text", "").strip()
            if not text or len(text) > 60:
                return False
            size = span.get("size", 0)
            flags = span.get("flags", 0)
            is_bold = bool(flags & 2**4)  # bit 4 = bold
            is_larger = size > avg_font_size * 1.15
            if (is_bold or is_larger) and len(text.split()) <= 6:
                return True
    return False


def _extract_contact(text: str) -> ContactInfo:
    """Extract contact information from resume text using regex patterns."""
    contact = ContactInfo()

    # Email
    emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    if emails:
        contact.email = emails[0]

    # Phone — various formats
    phones = re.findall(
        r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}",
        text
    )
    if phones:
        contact.phone = phones[0].strip()

    # LinkedIn
    linkedin = re.findall(
        r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+/?",
        text, re.IGNORECASE
    )
    if linkedin:
        contact.linkedin = linkedin[0]

    # GitHub
    github = re.findall(
        r"(?:https?://)?(?:www\.)?github\.com/[\w-]+/?",
        text, re.IGNORECASE
    )
    if github:
        contact.github = github[0]

    # Portfolio / other links
    urls = re.findall(r"https?://[\w./\-?=#%&+]+", text)
    contact.links = [u for u in urls if "linkedin" not in u.lower() and "github" not in u.lower()]

    # Name — heuristic: first non-empty line of the document (often the name)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if lines:
        first_line = lines[0]
        # If it's short and doesn't look like an email/url/phone, treat as name
        if (len(first_line) < 60
            and "@" not in first_line
            and "http" not in first_line.lower()
            and not re.match(r"^\+?\d", first_line)):
            contact.name = first_line

    # Location — look for common patterns
    location_patterns = [
        r"(?:Location|Address|City)\s*[:\-]?\s*(.+)",
        r"(\w[\w\s]+,\s*(?:[A-Z]{2}|[A-Za-z]+)\s*(?:\d{5,6})?)",
    ]
    for pat in location_patterns:
        match = re.search(pat, text[:2000])  # Search in first 2000 chars
        if match:
            loc = match.group(1).strip()
            if len(loc) < 80:
                contact.location = loc
                break

    return contact


def _extract_dates(text: str) -> tuple[Optional[str], Optional[str]]:
    """Extract start and end dates from a text line."""
    # Common date patterns
    date_patterns = [
        r"(\w+\s*\d{4})\s*[-–—to]+\s*(Present|\w+\s*\d{4})",
        r"(\d{1,2}/\d{4})\s*[-–—to]+\s*(Present|\d{1,2}/\d{4})",
        r"(\d{4})\s*[-–—to]+\s*(Present|\d{4})",
    ]
    for pat in date_patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            start = match.group(1).strip()
            end = match.group(2).strip()
            return start, end
    return None, None


def _parse_skills_section(text: str) -> list[SkillCategory]:
    """Parse a skills section into categorized skill lists."""
    categories = []
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    for line in lines:
        # Pattern: "Category: skill1, skill2, skill3" or "Category — skill1 | skill2"
        match = re.match(r"^([^:|\-–—]+?)\s*[:|—\-–]\s*(.+)$", line)
        if match:
            cat_name = match.group(1).strip()
            skills_text = match.group(2).strip()
            # Split by comma, pipe, semicolon
            skills = [s.strip() for s in re.split(r"[,|;•·]", skills_text) if s.strip()]
            if skills:
                categories.append(SkillCategory(category=cat_name, skills=skills))
        else:
            # Treat as uncategorized skills
            skills = [s.strip() for s in re.split(r"[,|;•·]", line) if s.strip()]
            if skills and len(skills) > 1:
                categories.append(SkillCategory(category="General", skills=skills))

    return categories


def extract_from_pdf_v1(file_path: str) -> ResumeData:
    """
    Extract resume data from a PDF file using PyMuPDF.
    Returns the canonical ResumeData schema with layout metadata and source spans.
    """
    doc = pymupdf.open(file_path)
    resume = ResumeData()
    all_text_blocks: list[TextBlock] = []
    sections: list[ResumeSection] = []
    full_text_parts: list[str] = []

    # ── First pass: collect all text blocks with layout info ─────
    all_font_sizes: list[float] = []
    page_blocks: list[list[dict]] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        blocks = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)["blocks"]
        page_blocks.append(blocks)

        for block in blocks:
            if block.get("type") != 0:  # Skip image blocks
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("size"):
                        all_font_sizes.append(span["size"])

    avg_font_size = sum(all_font_sizes) / len(all_font_sizes) if all_font_sizes else 12.0

    # ── Second pass: extract text blocks with metadata ───────────
    has_columns = False
    has_tables = False
    has_images = False

    for page_num, blocks in enumerate(page_blocks):
        page_text_parts = []

        # Detect columns: check if multiple text blocks share similar y-coordinates
        x_positions = []
        for b in blocks:
            if b.get("type") == 0:
                x_positions.append(b.get("bbox", [0])[0])
        if x_positions:
            unique_x = set(round(x / 50) for x in x_positions)
            if len(unique_x) > 1:
                has_columns = True

        for block in blocks:
            if block.get("type") == 1:  # Image block
                has_images = True
                continue
            if block.get("type") != 0:
                continue

            bbox = block.get("bbox", [0, 0, 0, 0])
            block_text_parts = []

            for line in block.get("lines", []):
                line_text_parts = []
                for span in line.get("spans", []):
                    text = span.get("text", "")
                    if text.strip():
                        line_text_parts.append(text)

                        font_size = span.get("size", avg_font_size)
                        font_name = span.get("font", "")
                        flags = span.get("flags", 0)
                        is_bold = bool(flags & 2**4)
                        is_italic = bool(flags & 2**1)

                        tb = TextBlock(
                            text=text.strip(),
                            page=page_num,
                            bbox=list(bbox),
                            font_size=font_size,
                            font_name=font_name,
                            is_bold=is_bold,
                            is_italic=is_italic,
                            block_type="heading" if _is_heading(block, avg_font_size) else "text",
                        )
                        all_text_blocks.append(tb)

                if line_text_parts:
                    block_text_parts.append(" ".join(line_text_parts))

            block_text = "\n".join(block_text_parts)
            if block_text.strip():
                page_text_parts.append(block_text)

                # Detect headings and create sections
                if _is_heading(block, avg_font_size):
                    heading_text = block_text.strip()
                    normalized = _normalize_heading(heading_text)
                    sections.append(ResumeSection(
                        name=heading_text,
                        normalized_name=normalized,
                        content="",
                        order=len(sections),
                        source_span=SourceSpan(
                            page=page_num,
                            text=heading_text,
                            bbox=list(bbox),
                        ),
                    ))
                elif sections:
                    # Append content to the current section
                    sections[-1].content += block_text + "\n"

        full_text_parts.append("\n".join(page_text_parts))

    full_text = "\n\n".join(full_text_parts)
    resume.raw_text = full_text

    # ── Detect tables ────────────────────────────────────────────
    for page_num in range(len(doc)):
        page = doc[page_num]
        tables = page.find_tables()
        if tables and len(tables.tables) > 0:
            has_tables = True
            break

    # ── Contact extraction ───────────────────────────────────────
    resume.contact = _extract_contact(full_text)

    # ── Section-based extraction ─────────────────────────────────
    for section in sections:
        norm = section.normalized_name
        content = section.content.strip()

        if norm == "summary":
            resume.summary = content
            resume.summary_span = section.source_span

        elif norm == "education":
            # Split by entries (look for institution names / degree patterns)
            edu_blocks = re.split(r"\n(?=[A-Z])", content)
            for block in edu_blocks:
                if not block.strip():
                    continue
                edu = Education()
                lines = [l.strip() for l in block.split("\n") if l.strip()]
                if lines:
                    edu.institution = lines[0]
                if len(lines) > 1:
                    edu.degree = lines[1]
                start, end = _extract_dates(block)
                edu.start_date = start
                edu.end_date = end
                # GPA
                gpa_match = re.search(r"(?:GPA|CGPA|Grade)[:\s]*(\d+\.?\d*(?:/\d+\.?\d*)?)", block, re.IGNORECASE)
                if gpa_match:
                    edu.gpa = gpa_match.group(1)
                edu.source_span = section.source_span
                resume.education.append(edu)

        elif norm == "experience":
            # Split experience entries by date patterns or company names
            entries = re.split(r"\n(?=\S.*(?:\d{4}|Present))", content)
            for entry_text in entries:
                if not entry_text.strip():
                    continue
                exp = ExperienceEntry()
                lines = [l.strip() for l in entry_text.split("\n") if l.strip()]
                if lines:
                    # First line is often title or company
                    exp.title = lines[0]
                if len(lines) > 1:
                    exp.company = lines[1]

                start, end = _extract_dates(entry_text)
                exp.start_date = start
                exp.end_date = end
                exp.is_current = bool(end and "present" in end.lower())

                # Bullets: lines starting with •, -, *, ▪, ►, or similar
                bullets = []
                for line in lines[1:]:
                    cleaned = re.sub(r"^[•\-*▪►→◦⁃]\s*", "", line).strip()
                    if cleaned and len(cleaned) > 15:
                        bullets.append(cleaned)
                exp.bullets = bullets
                exp.source_span = section.source_span
                resume.experience.append(exp)

        elif norm == "projects":
            entries = re.split(r"\n(?=[A-Z])", content)
            for entry_text in entries:
                if not entry_text.strip():
                    continue
                proj = Project()
                lines = [l.strip() for l in entry_text.split("\n") if l.strip()]
                if lines:
                    proj.name = lines[0]
                bullets = []
                for line in lines[1:]:
                    cleaned = re.sub(r"^[•\-*▪►→◦⁃]\s*", "", line).strip()
                    if cleaned:
                        bullets.append(cleaned)
                proj.bullets = bullets
                proj.description = " ".join(bullets[:2]) if bullets else ""

                # Extract technologies from bullets
                tech_keywords = re.findall(r"(?:using|built with|technologies?|stack|tools?)[:\s]+(.+?)(?:\.|$)", entry_text, re.IGNORECASE)
                if tech_keywords:
                    proj.technologies = [t.strip() for t in re.split(r"[,|;]", tech_keywords[0]) if t.strip()]

                proj.source_span = section.source_span
                resume.projects.append(proj)

        elif norm == "skills":
            resume.skills = _parse_skills_section(content)

        elif norm == "certifications":
            for line in content.split("\n"):
                line = line.strip()
                if line:
                    cert = Certification(name=line, source_span=section.source_span)
                    resume.certifications.append(cert)

        elif norm == "achievements":
            for line in content.split("\n"):
                line = re.sub(r"^[•\-*▪►→◦⁃]\s*", "", line).strip()
                if line:
                    resume.achievements.append(
                        Achievement(description=line, source_span=section.source_span)
                    )

    # ── Flatten all skills ───────────────────────────────────────
    all_skills = []
    for cat in resume.skills:
        all_skills.extend(cat.skills)
    # Also extract skills mentioned in experience/projects
    for exp in resume.experience:
        all_skills.extend(exp.technologies)
    for proj in resume.projects:
        all_skills.extend(proj.technologies)
    resume.all_skills_flat = list(set(s.strip() for s in all_skills if s.strip()))

    # ── Metadata ─────────────────────────────────────────────────
    word_count = len(full_text.split())
    resume.document_metadata = DocumentMetadata(
        filename="",  # Set by caller
        file_type="pdf",
        file_size_bytes=0,  # Set by caller
        page_count=len(doc),
        word_count=word_count,
        char_count=len(full_text),
    )

    resume.layout_metadata = LayoutMetadata(
        page_count=len(doc),
        has_columns=has_columns,
        has_tables=has_tables,
        has_images=has_images,
        has_text_boxes=False,  # Difficult to detect purely from PDF
        text_blocks=all_text_blocks[:500],  # Cap to avoid huge payloads
    )

    resume.sections = sections
    doc.close()
    return resume


def extract_from_pdf(file_path: str) -> ResumeData:
    """Default PDF path: layout-aware v2 parser (see layout_parser.py).
    Falls back to v1 only if v2 crashes on an unusual file."""
    from backend.ingestion.layout_parser import parse_pdf
    try:
        return parse_pdf(file_path)
    except Exception:  # pragma: no cover - defensive
        import logging
        logging.getLogger(__name__).exception("v2 parser failed, falling back to v1")
        return extract_from_pdf_v1(file_path)

"""
Phase 14 — LaTeX / Overleaf Source Analysis.
Parses raw .tex resume source files, normalizes macros into canonical ResumeData,
and detects LaTeX-specific ATS and layout risks (multicols, tabulars, fontawesome icons).
"""
import re
from typing import Optional

from backend.schemas.resume import (
    ResumeData,
    ContactInfo,
    ExperienceEntry,
    Project,
    Education,
    SkillCategory,
    ResumeSection,
    LayoutMetadata,
    DocumentMetadata,
)


def clean_latex(text: str) -> str:
    """Removes or normalizes LaTeX commands to plain text."""
    # Convert \href{url}{text} to text (url)
    text = re.sub(r"\\href\{([^}]+)\}\{([^}]+)\}", r"\2 (\1)", text)
    # Remove \textbf, \textit, \emph, \underline
    text = re.sub(r"\\(?:textbf|textit|emph|underline|textsc|large|Large|small)\{([^}]+)\}", r"\1", text)
    # Convert \item to bullet
    text = re.sub(r"\\item\s*", "• ", text)
    # Remove comments
    text = re.sub(r"%.*$", "", text, flags=re.MULTILINE)
    # Remove remaining generic \command{...} or \command
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{([^}]*)\})?", r"\1", text)
    # Clean up double braces and whitespace
    text = re.sub(r"[{}]", "", text)
    text = re.sub(r"\n\s*\n", "\n\n", text)
    return text.strip()


def parse_latex_resume(tex_content: str, filename: str = "resume.tex") -> tuple[ResumeData, list[str]]:
    """
    Parses a LaTeX resume source string into canonical ResumeData,
    returning structured data and LaTeX-specific ATS warning messages.
    """
    warnings = []

    # 1. Check for layout risks
    if re.search(r"\\begin\{(?:multicols|minipage)\}", tex_content, re.IGNORECASE):
        warnings.append(r"Multi-column layout detected (\multicols / \minipage) — ATS parsers may read across columns, scrambling timelines.")

    if re.search(r"\\begin\{tabular", tex_content, re.IGNORECASE):
        warnings.append(r"Tables detected (\begin{tabular}) — tabular formatting frequently drops content in standard ATS ingestion.")

    if re.search(r"\\fa[A-Z][a-zA-Z]+", tex_content):
        warnings.append("FontAwesome icon macros found without text fallback — contact icons may parse as unreadable unicode symbols.")

    # 2. Extract sections
    section_pattern = re.compile(r"\\(?:section|resumeSection)\{([^}]+)\}(.*?)(?=\\(?:section|resumeSection)|\Z)", re.DOTALL | re.IGNORECASE)
    sections_raw = section_pattern.findall(tex_content)

    experience_list = []
    education_list = []
    skills_list = []
    projects_list = []
    detected_sections = []
    all_skills_flat = []

    for idx, (sec_name, sec_body) in enumerate(sections_raw):
        clean_name = sec_name.strip()
        norm_name = clean_name.lower()
        cleaned_body = clean_latex(sec_body)

        detected_sections.append(
            ResumeSection(
                name=clean_name,
                normalized_name=norm_name,
                content=cleaned_body,
                order=idx,
            )
        )

        # Bullets inside section
        bullets = [b.replace("•", "").strip() for b in cleaned_body.split("\n") if "•" in b or b.strip().startswith("-")]

        if "experience" in norm_name or "employment" in norm_name or "work" in norm_name:
            if bullets:
                experience_list.append(
                    ExperienceEntry(
                        company="Extracted Experience",
                        title=clean_name,
                        bullets=bullets,
                    )
                )
        elif "education" in norm_name or "academic" in norm_name:
            education_list.append(
                Education(
                    institution=clean_name,
                    highlights=bullets,
                )
            )
        elif "project" in norm_name:
            if bullets:
                projects_list.append(
                    Project(
                        name=clean_name,
                        bullets=bullets,
                    )
                )
        elif "skill" in norm_name:
            skills_tokens = [s.strip() for s in re.split(r"[,:|•\n]", cleaned_body) if s.strip() and len(s.strip()) < 30]
            if skills_tokens:
                skills_list.append(SkillCategory(category=clean_name, skills=skills_tokens))
                all_skills_flat.extend(skills_tokens)

    # Clean full plain text
    plain_text = clean_latex(tex_content)

    # Contact extraction (email, phone)
    email_match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", plain_text)
    phone_match = re.search(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", plain_text)

    contact = ContactInfo(
        email=email_match.group(0) if email_match else None,
        phone=phone_match.group(0) if phone_match else None,
    )

    resume_data = ResumeData(
        contact=contact,
        experience=experience_list,
        education=education_list,
        projects=projects_list,
        skills=skills_list,
        all_skills_flat=list(dict.fromkeys(all_skills_flat)),
        sections=detected_sections,
        raw_text=plain_text,
        layout_metadata=LayoutMetadata(
            page_count=1,
            has_columns=bool(re.search(r"\\begin\{(?:multicols|minipage)\}", tex_content)),
            has_tables=bool(re.search(r"\\begin\{tabular", tex_content)),
        ),
        document_metadata=DocumentMetadata(
            filename=filename,
            file_type="tex",
            char_count=len(plain_text),
            word_count=len(plain_text.split()),
        ),
    )

    return resume_data, warnings

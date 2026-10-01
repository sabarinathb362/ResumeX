"""
Pydantic schemas for the canonical Resume structure.
Every field carries source_span for evidence tracing back to the original document.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import date
from enum import Enum


# ── Source span: every extracted field traces back to the doc ─────

class SourceSpan(BaseModel):
    """Locates a piece of text in the original document."""
    page: Optional[int] = None          # PDF page (0-indexed)
    paragraph_index: Optional[int] = None  # DOCX paragraph index
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    text: str = ""
    bbox: Optional[list[float]] = None  # [x0, y0, x1, y1] from PyMuPDF


# ── Contact ──────────────────────────────────────────────────────

class ContactInfo(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    location: Optional[str] = None
    links: list[str] = Field(default_factory=list)
    source_spans: list[SourceSpan] = Field(default_factory=list)


# ── Education ────────────────────────────────────────────────────

class Education(BaseModel):
    institution: Optional[str] = None
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    gpa: Optional[str] = None
    highlights: list[str] = Field(default_factory=list)
    source_span: Optional[SourceSpan] = None


# ── Experience ───────────────────────────────────────────────────

class ExperienceEntry(BaseModel):
    company: Optional[str] = None
    title: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    is_current: bool = False
    bullets: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    source_span: Optional[SourceSpan] = None
    bullet_spans: list[SourceSpan] = Field(default_factory=list)


# ── Projects ─────────────────────────────────────────────────────

class Project(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    technologies: list[str] = Field(default_factory=list)
    url: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)
    source_span: Optional[SourceSpan] = None


# ── Skills ───────────────────────────────────────────────────────

class SkillCategory(BaseModel):
    category: str = ""
    skills: list[str] = Field(default_factory=list)
    source_span: Optional[SourceSpan] = None


# ── Certifications ───────────────────────────────────────────────

class Certification(BaseModel):
    name: str
    issuer: Optional[str] = None
    date: Optional[str] = None
    credential_id: Optional[str] = None
    url: Optional[str] = None
    source_span: Optional[SourceSpan] = None


# ── Achievements ─────────────────────────────────────────────────

class Achievement(BaseModel):
    description: str
    source_span: Optional[SourceSpan] = None


# ── Layout metadata (for Readability Reviewer / Phase 10) ────────

class TextBlock(BaseModel):
    """A block of text with its layout properties from the PDF."""
    text: str
    page: int
    bbox: list[float] = Field(default_factory=list)  # [x0, y0, x1, y1]
    font_size: Optional[float] = None
    font_name: Optional[str] = None
    is_bold: bool = False
    is_italic: bool = False
    block_type: str = "text"  # "text" | "heading" | "bullet" | "table_cell"


class LayoutMetadata(BaseModel):
    """Document-level layout info for readability analysis."""
    page_count: int = 0
    has_columns: bool = False
    has_tables: bool = False
    has_images: bool = False
    has_text_boxes: bool = False
    has_headers_footers: bool = False
    text_blocks: list[TextBlock] = Field(default_factory=list)
    reading_order_confidence: float = 1.0


# ── Document metadata ────────────────────────────────────────────

class DocumentMetadata(BaseModel):
    filename: str = ""
    file_type: str = ""  # "pdf" | "docx" | "tex"
    file_size_bytes: int = 0
    page_count: int = 0
    word_count: int = 0
    char_count: int = 0
    created_at: Optional[str] = None
    modified_at: Optional[str] = None


# ── Section (generic) ────────────────────────────────────────────

class ResumeSection(BaseModel):
    """A detected section in the resume."""
    name: str
    normalized_name: str = ""  # Mapped to standard heading
    content: str = ""
    order: int = 0
    source_span: Optional[SourceSpan] = None


# ── Layout-anchored document model (v2 parser) ──────────────────
# These let every finding point at exact lines on the rendered page,
# which is what the in-app editor uses to draw highlights.

class LayoutLine(BaseModel):
    """One visual row of the document (fragments on the same baseline merged)."""
    id: str                       # "p0l12"
    page: int
    bbox: list[float]             # [x0, y0, x1, y1] in PDF points
    text: str
    size: float = 0.0
    bold_ratio: float = 0.0
    role: str = "text"            # contact|heading|title|meta|statement|item|text
    section_id: Optional[str] = None


class Statement(BaseModel):
    """A single claim/bullet a reviewer reads. May wrap across several lines."""
    id: str                       # "s7"
    text: str
    line_ids: list[str] = Field(default_factory=list)
    # Where this statement lives in the legacy structured fields, so an accepted
    # edit can be written back for export: ["experience", 0, "bullets", 1]
    path: list = Field(default_factory=list)


class DocEntry(BaseModel):
    id: str
    title: str = ""
    subtitle: str = ""            # org / degree / issuer line
    dates: str = ""
    tags: list[str] = Field(default_factory=list)   # e.g. tech after an em dash
    title_line_ids: list[str] = Field(default_factory=list)
    meta_line_ids: list[str] = Field(default_factory=list)
    statements: list[Statement] = Field(default_factory=list)


class DocSection(BaseModel):
    id: str
    heading: str
    kind: str                     # normalized: experience|education|projects|...
    kinds: list[str] = Field(default_factory=list)  # all categories a mixed heading matched
    heading_line_id: Optional[str] = None
    entries: list[DocEntry] = Field(default_factory=list)


class Publication(BaseModel):
    title: str
    venue: Optional[str] = None
    details: Optional[str] = None
    source_span: Optional[SourceSpan] = None


# ── The canonical Resume schema ──────────────────────────────────

class ResumeData(BaseModel):
    """
    The canonical resume JSON schema.
    Every extraction path (PDF, DOCX, LaTeX) normalizes into this structure.
    """
    contact: ContactInfo = Field(default_factory=ContactInfo)
    summary: Optional[str] = None
    summary_span: Optional[SourceSpan] = None
    education: list[Education] = Field(default_factory=list)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: list[SkillCategory] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    achievements: list[Achievement] = Field(default_factory=list)
    sections: list[ResumeSection] = Field(default_factory=list)
    document_metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    layout_metadata: LayoutMetadata = Field(default_factory=LayoutMetadata)
    raw_text: str = ""
    all_skills_flat: list[str] = Field(default_factory=list)
    # v2 parser additions (all optional so older stored rows still validate)
    publications: list[Publication] = Field(default_factory=list)
    activities: list[ExperienceEntry] = Field(default_factory=list)  # volunteer / outreach / extracurricular
    lines: list[LayoutLine] = Field(default_factory=list)
    doc_sections: list[DocSection] = Field(default_factory=list)
    page_sizes: list[list[float]] = Field(default_factory=list)
    parser_version: str = "1"


# ── API response models ─────────────────────────────────────────

class ResumeUploadResponse(BaseModel):
    id: str
    filename: str
    file_type: str
    status: str = "parsed"
    resume_data: ResumeData
    warnings: list[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    detail: str
    error_type: str = "parsing_error"

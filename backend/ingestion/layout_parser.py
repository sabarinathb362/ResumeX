"""
Phase 1 (v2) — Layout-aware resume parser.

Why this exists: the v1 parser marked ANY bold block of <=6 words as a section
heading. On a typical resume the candidate's name, every school and every job
title is bold, so real sections were shredded and Experience / Education /
Projects came back empty. Every downstream score was computed on that.

This parser works on visual *rows* instead of PyMuPDF blocks:
  1. Merge spans that share a baseline into one row (keeps right-aligned dates
     with their title, "— CGPA 8.03" with its school, etc.).
  2. Find the body font size (character-weighted mode). A heading must be
     larger than body text OR be an all-caps/known section label — bold alone
     is NOT enough.
  3. Inside a section, an entry starts on a row whose first word is bold
     (optionally behind a bullet glyph); regular-weight rows that follow are
     meta lines (company, degree) and then description statements.
  4. Every row gets a stable id ("p0l12") and its bbox, and every statement
     records which rows it spans, so findings can be drawn on the page.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import pymupdf

from backend.schemas.resume import (
    ResumeData, ContactInfo, Education, ExperienceEntry, Project, SkillCategory,
    Certification, Achievement, ResumeSection, DocumentMetadata, LayoutMetadata,
    TextBlock, SourceSpan, LayoutLine, Statement, DocEntry, DocSection, Publication,
)

PARSER_VERSION = "2.0"

BULLET_CHARS = "•●▪■◦‣⁃►▶➢➤→–-*·○"
BULLET_RE = re.compile(r"^\s*[•●▪■◦‣⁃►▶➢➤→*·○]\s*")
DASH_SPLIT_RE = re.compile(r"\s+[—–|]\s+|\s+-\s+")

MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
DATE_TOKEN = rf"(?:{MONTH}\.?\s+\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}})"
DATE_RANGE_RE = re.compile(
    rf"({DATE_TOKEN})\s*(?:[-–—]|to)\s*({DATE_TOKEN}|Present|Current|Now|Ongoing)", re.I
)
SINGLE_DATE_RE = re.compile(rf"\(?({MONTH}\.?\s+\d{{4}}|\b(?:19|20)\d{{2}}\b)\)?", re.I)

# ── Section vocabulary ───────────────────────────────────────────
# Order matters: first match wins for the primary kind; all matches are kept
# so "Certifications / Online Courses / Publications" is known to be mixed.
SECTION_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("skills", ("programming language", "technical skill", "skill", "competenc",
                "technolog", "tools", "tech stack", "toolkit")),
    ("experience", ("experience", "employment", "work history", "internship",
                    "professional background", "career history")),
    ("education", ("education", "academic", "qualification", "schooling")),
    ("projects", ("project",)),
    ("publications", ("publication", "research paper", "papers")),
    ("certifications", ("certif", "online course", "courses", "licen", "coursework", "moocs")),
    ("training", ("workshop", "training", "bootcamp", "seminar")),
    ("summary", ("summary", "profile", "objective", "about me", "about")),
    ("achievements", ("award", "honor", "honour", "achievement", "accomplishment", "scholarship")),
    ("volunteer", ("volunteer", "community", "outreach", "social service", "nss", "ncc")),
    ("leadership", ("leadership", "position of responsibility", "positions of responsibility")),
    ("extracurricular", ("extra-curricular", "extracurricular", "extra curricular", "activities", "sports")),
    ("languages", ("language",)),
    ("interests", ("interest", "hobb")),
    ("references", ("reference",)),
    ("declaration", ("declaration",)),
    ("personal", ("personal detail", "personal information", "personal profile")),
]

ENTRY_SECTIONS = {"experience", "education", "projects", "certifications", "training",
                  "publications", "volunteer", "leadership", "achievements", "extracurricular"}


def classify_heading(text: str) -> tuple[Optional[str], list[str]]:
    t = re.sub(r"[^a-z&/\- ]", " ", text.lower())
    t = re.sub(r"\s+", " ", t).strip()
    kinds = []
    for kind, keys in SECTION_KEYWORDS:
        if any(k in t for k in keys):
            kinds.append(kind)
    # "Areas of Interest" is interests, not a skills/profile thing
    if "interest" in t and kinds and kinds[0] != "interests":
        kinds = ["interests"] + [k for k in kinds if k != "interests"]
    if "programming language" in t:
        kinds = ["skills"]
    return (kinds[0] if kinds else None), kinds


@dataclass
class Row:
    id: str
    page: int
    bbox: list[float]
    text: str
    frags: list[str]
    size: float
    bold_ratio: float
    first_word_bold: bool
    italic_ratio: float
    is_bullet: bool
    role: str = "text"
    section_id: Optional[str] = None
    links: list[str] = field(default_factory=list)


# ── Row building ─────────────────────────────────────────────────

def _page_lines(page) -> list[tuple]:
    out = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []):
            spans = [s for s in ln.get("spans", []) if s.get("text", "").strip()]
            if spans:
                x0, y0, x1, y1 = ln["bbox"]
                out.append(((y0 + y1) / 2, x0, ln["bbox"], spans))
    return out


def _find_gutter(lines, width) -> Optional[float]:
    """x position no body line crosses, with real text on both sides."""
    if len(lines) < 16:
        return None
    best = None
    for g in range(int(width * 0.3), int(width * 0.7), 2):
        left = sum(1 for l in lines if l[2][2] <= g)
        right = sum(1 for l in lines if l[2][0] >= g)
        cross = sum(1 for l in lines if l[2][0] < g < l[2][2])
        if left >= 8 and right >= 8 and cross <= max(2, len(lines) * 0.06):
            score = cross * 10 - min(left, right)
            if best is None or score < best[0]:
                best = (score, g, cross)
    return float(best[1]) if best else None


def _group_rows(items, page_num, start_idx) -> list["Row"]:
    items = sorted(items, key=lambda r: (round(r[0], 0), r[1]))
    groups: list[list] = []
    for item in items:
        if groups and abs(groups[-1][0][0] - item[0]) <= 2.5:
            groups[-1].append(item)
        else:
            groups.append([item])
    rows = []
    for g in groups:
        g.sort(key=lambda r: r[1])
        frags, spans_all = [], []
        x0 = min(i[2][0] for i in g); y0 = min(i[2][1] for i in g)
        x1 = max(i[2][2] for i in g); y1 = max(i[2][3] for i in g)
        for _, _, _, spans in g:
            frags.append(" ".join(sp["text"].strip() for sp in spans).strip())
            spans_all.extend(spans)
        text = re.sub(r"\s+", " ", "  ".join(frags)).strip()
        text = re.sub(r"\s+([,.;:])", r"\1", text)
        total = sum(len(sp["text"].strip()) for sp in spans_all) or 1
        isb = lambda sp: bool(sp["flags"] & 16 or "bold" in sp.get("font", "").lower())
        bold = sum(len(sp["text"].strip()) for sp in spans_all if isb(sp))
        italic = sum(len(sp["text"].strip()) for sp in spans_all if sp["flags"] & 2)
        textual = [sp for sp in spans_all if len(sp["text"].strip()) > 1] or spans_all
        size = max(textual, key=lambda sp: len(sp["text"].strip()))["size"]
        fw_bold = False
        for sp in spans_all:
            st = sp["text"].strip()
            if not st or all(c in BULLET_CHARS for c in st):
                continue
            fw_bold = isb(sp)
            break
        rows.append(Row(
            id=f"p{page_num}l{start_idx + len(rows)}", page=page_num,
            bbox=[round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
            text=text, frags=frags, size=round(size, 2), bold_ratio=round(bold / total, 2),
            first_word_bold=fw_bold, italic_ratio=round(italic / total, 2),
            is_bullet=bool(BULLET_RE.match(text)),
        ))
    return rows


def _rows_for_page(page, page_num: int, start_idx: int) -> tuple[list["Row"], bool]:
    lines = _page_lines(page)
    gutter = _find_gutter(lines, page.rect.width)
    if gutter is None:
        return _group_rows(lines, page_num, start_idx), False
    # header band = everything above the first big bold line that sits in a column
    sizes = sorted(sp["size"] for l in lines for sp in l[3])
    median = sizes[len(sizes) // 2]
    col_heads = [l for l in lines
                 if not (l[2][0] < gutter < l[2][2])
                 and max(sp["size"] for sp in l[3]) >= median * 1.25
                 and any(sp["flags"] & 16 for sp in l[3])]
    crossing = [l for l in lines if l[2][0] < gutter < l[2][2]]
    band_end = max([l[2][3] for l in crossing], default=0)
    heads_below = [l[2][1] for l in col_heads if l[2][1] >= band_end - 1]
    region_start = min(heads_below) - 1 if heads_below else band_end
    header = [l for l in lines if l[2][1] < region_start]
    left = [l for l in lines if l[2][1] >= region_start and l[2][2] <= gutter + 1]
    right = [l for l in lines if l[2][1] >= region_start and l[2][2] > gutter + 1]
    rows = _group_rows(header, page_num, start_idx)
    rows += _group_rows(left, page_num, start_idx + len(rows))
    rows += _group_rows(right, page_num, start_idx + len(rows))
    return rows, True


def _body_size(rows: list[Row]) -> float:
    c = Counter()
    for r in rows:
        c[round(r.size * 2) / 2] += len(r.text)
    return c.most_common(1)[0][0] if c else 11.0


def _strip_bullet(t: str) -> str:
    return BULLET_RE.sub("", t).strip()


def _style(r: "Row") -> tuple:
    t = _strip_bullet(r.text)
    return (round(r.size * 2) / 2, r.bold_ratio >= 0.6, t.isupper())


def _heading_candidate(r: "Row") -> bool:
    t = _strip_bullet(r.text)
    words = t.split()
    if r.is_bullet or not words or len(words) > 7 or len(t) > 60:
        return False
    if DATE_RANGE_RE.search(t) or "@" in t or re.search(r"\d{3,}", t):
        return False
    return True


def _heading_styles(rows: list["Row"], body: float) -> set:
    """Learn what THIS document's section headings look like from rows that are
    unambiguously section labels ("Education", "PROJECTS", ...)."""
    c = Counter()
    for r in rows:
        if not _heading_candidate(r):
            continue
        kind, _ = classify_heading(_strip_bullet(r.text))
        st = _style(r)
        if kind and (st[1] or st[2] or r.size >= body * 1.06):
            c[st] += 1
    return {st for st, n in c.items() if n >= 2}


def _is_heading(r: Row, body: float, styles: set = frozenset()) -> bool:
    if not _heading_candidate(r):
        return False
    t = _strip_bullet(r.text)
    words = t.split()
    kind, _ = classify_heading(t)
    if styles:
        st = _style(r)
        if st in styles:
            return True
        # same size + weight as learned headings, different case
        return kind is not None and any(abs(st[0] - s[0]) <= 0.5 and st[1] == s[1] for s in styles)
    larger = r.size >= body * 1.06
    caps = t.isupper() and len(t) > 3
    if larger and r.bold_ratio >= 0.6:
        return True
    if (caps or larger) and kind:
        return True
    # exact standard label in regular weight, alone on its row, e.g. "EDUCATION"
    if kind and r.bold_ratio >= 0.6 and len(words) <= 4 and t.rstrip(":").lower() in {
        "education", "experience", "projects", "skills", "certifications", "publications",
        "summary", "profile", "achievements", "awards", "internships", "work experience",
        "technical skills", "languages", "interests", "hobbies", "volunteering"}:
        return True
    return False


# ── Small field helpers ──────────────────────────────────────────

def find_dates(text: str) -> str:
    m = DATE_RANGE_RE.search(text)
    if m:
        return f"{m.group(1)} – {m.group(2)}"
    m = SINGLE_DATE_RE.search(text)
    return m.group(1) if m else ""


def _remove_dates(text: str) -> str:
    t = DATE_RANGE_RE.sub("", text)
    t = re.sub(rf"\(\s*(?:{MONTH}\.?\s+)?\d{{4}}\s*\)", "", t, flags=re.I)
    t = re.sub(rf"[,\s]+{MONTH}\.?\s+\d{{4}}\s*$", "", t, flags=re.I)
    t = re.sub(r"\s+(?:19|20)\d{2}\s*$", "", t)
    return re.sub(r"\s{2,}", " ", t).strip(" ,–—-|")


def split_title(title: str) -> tuple[str, str]:
    """'Name (2026) — PyTorch, SimCLR' -> ('Name', 'PyTorch, SimCLR')."""
    clean = _remove_dates(title)
    parts = DASH_SPLIT_RE.split(clean, maxsplit=1)
    head = parts[0].strip(" ,–—-|")
    tail = parts[1].strip(" ,–—-|") if len(parts) > 1 else ""
    return head.strip(), tail.strip()


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Return (start, end) offsets of sentences; avoids splitting '3.7', 'e.g.', 'React.js'."""
    spans, start = [], 0
    for m in re.finditer(r"(?<=[.!?])\s+(?=[A-Z(])", text):
        prev = text[max(0, m.start() - 5):m.start()].lower()
        if re.search(r"\b(e\.g|i\.e|etc|vs|approx|no)\.$", prev):
            continue
        spans.append((start, m.start()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))
    return [(a, b) for a, b in spans if text[a:b].strip()]


PHONE_RE = re.compile(r"(?<![\w/=.])(\+?\d[\d\s().-]{8,16}\d)(?![\w/])")


def _extract_contact(header_rows: list[Row], full_text: str, page_links: list[str]) -> tuple[ContactInfo, list[str]]:
    c = ContactInfo()
    header_text = "\n".join(r.text for r in header_rows)
    blob = header_text + "\n" + full_text[:3000]

    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", blob)
    if m:
        c.email = m.group(0).rstrip(".")
    for m in PHONE_RE.finditer(header_text or blob):
        digits = re.sub(r"\D", "", m.group(1))
        if 10 <= len(digits) <= 13:
            c.phone = m.group(1).strip()
            break
    all_links = set(page_links)
    for m in re.finditer(r"(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)+/[\w\-./?=#%&+~]*", blob):
        all_links.add(m.group(0).rstrip(".,)"))
    def _norm(u):
        return re.sub(r"^(?:https?://)?(?:www\.)?", "", u.lower()).rstrip("/")
    dedup = {}
    for link in sorted(all_links, key=lambda u: (not u.startswith("http"), u)):
        dedup.setdefault(_norm(link), link)
    for link in dedup.values():
        low = link.lower()
        if "linkedin.com" in low and not c.linkedin:
            c.linkedin = link
        elif "github.com" in low and not c.github:
            c.github = link
        elif not low.startswith("mailto:") and "@" not in low:
            c.links.append(link)

    name_ids = []
    if header_rows:
        biggest = max(header_rows, key=lambda r: r.size)
        cand = _strip_bullet(biggest.text)
        if "@" not in cand and not re.search(r"\d{3}", cand) and len(cand.split()) <= 6:
            c.name = cand.title() if cand.isupper() else cand
            name_ids.append(biggest.id)
        loc_m = re.search(r"\b([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?,\s*[A-Z][a-zA-Z]+(?:,\s*[A-Z][a-zA-Z]+)?)\b", header_text)
        if loc_m and "@" not in loc_m.group(1):
            c.location = loc_m.group(1)
    c.source_spans = [SourceSpan(page=r.page, text=r.text, bbox=r.bbox) for r in header_rows]
    return c, name_ids


# ── Main entry point ─────────────────────────────────────────────

def parse_pdf(file_path: str) -> ResumeData:
    doc = pymupdf.open(file_path)
    rows: list[Row] = []
    page_sizes, page_links, has_images, has_tables = [], [], False, False
    has_columns = False
    for pno, page in enumerate(doc):
        page_sizes.append([round(page.rect.width, 1), round(page.rect.height, 1)])
        prow, cols = _rows_for_page(page, pno, len(rows))
        rows.extend(prow)
        has_columns = has_columns or cols
        for ln in page.get_links():
            if ln.get("uri"):
                page_links.append(ln["uri"])
        if page.get_images(full=False):
            # ignore tiny icons (< 2% of page area)
            for img in page.get_image_info():
                x0, y0, x1, y1 = img["bbox"]
                if (x1 - x0) * (y1 - y0) > 0.02 * page.rect.width * page.rect.height:
                    has_images = True
        try:
            tabs = page.find_tables()
            if tabs and any(t.row_count >= 2 and t.col_count >= 2 for t in tabs.tables):
                has_tables = True
        except Exception:
            pass

    body = _body_size(rows)
    heading_styles = _heading_styles(rows, body)

    # ── sections ────────────────────────────────────────────────
    header_rows: list[Row] = []
    sections: list[tuple[Row, list[Row]]] = []
    for r in rows:
        if _is_heading(r, body, heading_styles) and not (not sections and r is rows[0]):
            r.role = "heading"
            sections.append((r, []))
        elif sections:
            sections[-1][1].append(r)
        else:
            header_rows.append(r)
    # A largest-font first row that also looks like a heading is the name, not a section
    for r in header_rows:
        r.role = "contact"

    resume = ResumeData()
    full_text = "\n".join(r.text for r in rows)
    resume.raw_text = full_text
    resume.contact, name_ids = _extract_contact(header_rows, full_text, page_links)

    doc_sections: list[DocSection] = []
    legacy_sections: list[ResumeSection] = []
    stmt_counter = [0]

    for si, (h, body_rows) in enumerate(sections):
        sid = f"sec{si}"
        kind, kinds = classify_heading(h.text)
        kind = kind or "other"
        h.section_id = sid
        for r in body_rows:
            r.section_id = sid
        ds = DocSection(id=sid, heading=h.text, kind=kind, kinds=kinds, heading_line_id=h.id)
        ds.entries = _segment_entries(sid, kind, body_rows, stmt_counter)
        doc_sections.append(ds)
        legacy_sections.append(ResumeSection(
            name=h.text, normalized_name=kind if kind != "other" else h.text.lower(),
            content="\n".join(r.text for r in body_rows), order=si,
            source_span=SourceSpan(page=h.page, text=h.text, bbox=h.bbox),
        ))

    _fill_legacy_fields(resume, doc_sections, {r.id: r for r in rows})

    resume.sections = legacy_sections
    resume.doc_sections = doc_sections
    resume.page_sizes = page_sizes
    resume.lines = [LayoutLine(id=r.id, page=r.page, bbox=r.bbox, text=r.text, size=r.size,
                               bold_ratio=r.bold_ratio, role=r.role, section_id=r.section_id)
                    for r in rows]
    resume.parser_version = PARSER_VERSION

    words = len(full_text.split())
    resume.document_metadata = DocumentMetadata(
        file_type="pdf", page_count=len(doc), word_count=words, char_count=len(full_text))
    heading_sizes = {round(r.size, 1) for r in rows if r.role == "heading"}
    resume.layout_metadata = LayoutMetadata(
        page_count=len(doc), has_columns=has_columns, has_tables=has_tables,
        has_images=has_images, has_text_boxes=False,
        text_blocks=[TextBlock(text=r.text, page=r.page, bbox=r.bbox, font_size=r.size,
                               is_bold=r.bold_ratio > 0.6,
                               block_type="heading" if r.role == "heading" else
                               ("bullet" if r.is_bullet else "text")) for r in rows[:500]],
        reading_order_confidence=0.75 if has_columns else 1.0,
    )
    doc.close()
    return resume


def _segment_entries(sid: str, kind: str, body_rows: list[Row], counter: list[int]) -> list[DocEntry]:
    entries: list[DocEntry] = []
    cur: Optional[dict] = None
    bulleted_titles = sum(1 for r in body_rows if r.is_bullet and r.first_word_bold) >= 2
    title_x = min((r.bbox[0] for r in body_rows if r.first_word_bold), default=0)
    any_bold_lead = any(r.first_word_bold for r in body_rows)
    sizes = [r.size for r in body_rows]
    size_titles = (not any_bold_lead and sizes and max(sizes) - min(sizes) >= 0.8
                   and sum(1 for x in sizes if x >= max(sizes) - 0.3) < len(sizes))

    def flush():
        if cur:
            entries.append(_build_entry(sid, len(entries), kind, cur, counter))

    prev_title = False
    for r in body_rows:
        t = _strip_bullet(r.text)
        title_like = r.first_word_bold and r.bold_ratio >= 0.25
        if size_titles:
            title_like = r.size >= max(sizes) - 0.3
        has_date = bool(DATE_RANGE_RE.search(t))
        if kind in ("summary",):
            title_like = False
        if bulleted_titles and title_like and not r.is_bullet and not has_date:
            # e.g. "**100% recall** for failure detection." wrapped inside a description
            if cur is not None and cur["rest"]:
                title_like = False
            elif r.bbox[0] > title_x + 6 and not prev_title:
                title_like = False
        new_entry = title_like and (r.is_bullet or not prev_title or has_date)
        # list-like sections: every bullet row is its own item
        if kind in ("skills", "languages", "interests", "extracurricular", "achievements") and r.is_bullet:
            new_entry = True
        if kind in ("training",) and r.is_bullet:
            new_entry = True
        # classic layout: title rows not bulleted, descriptions bulleted
        if cur is None:
            new_entry = True
        if new_entry:
            flush()
            cur = {"title": [r] if (title_like or kind in ("skills", "languages", "interests")) else [],
                   "rest": [] if (title_like or kind in ("skills", "languages", "interests")) else [r]}
        elif title_like and prev_title and not cur["rest"]:
            cur["title"].append(r)          # wrapped title line
        else:
            cur["rest"].append(r)
        prev_title = title_like and (not cur["rest"] or cur["rest"][-1] is not r)
    flush()
    return entries


def _build_entry(sid: str, idx: int, kind: str, cur: dict, counter: list[int]) -> DocEntry:
    title_rows: list[Row] = cur["title"]
    rest: list[Row] = cur["rest"]
    title_text = " ".join(_strip_bullet(r.text) for r in title_rows)
    dates = find_dates(title_text) or find_dates(" ".join(r.text for r in rest[:2]))
    name, tail = split_title(title_text)
    e = DocEntry(id=f"{sid}e{idx}", title=name or title_text, dates=dates,
                 title_line_ids=[r.id for r in title_rows])
    if tail:
        e.tags = [t.strip() for t in re.split(r",\s*", tail) if t.strip()] if "," in tail else [tail]
    for r in title_rows:
        r.role = "title" if kind not in ("skills", "languages", "interests") else "item"

    # meta lines: up to 2 short rows right after the title, no sentence punctuation
    meta, desc = [], []
    for r in rest:
        t = _strip_bullet(r.text)
        if (not desc and len(meta) < 2 and title_rows and not r.is_bullet
                and len(t.split()) <= 10 and not t.endswith(".")):
            meta.append(r)
        else:
            desc.append(r)
    if meta:
        e.subtitle = " · ".join(_strip_bullet(r.text) for r in meta)
        e.meta_line_ids = [r.id for r in meta]
        for r in meta:
            r.role = "meta"
        if not e.dates:
            e.dates = find_dates(e.subtitle)

    # statements: bullets start new statements; otherwise sentence split
    if any(r.is_bullet for r in desc):
        groups: list[list[Row]] = []
        for r in desc:
            if r.is_bullet or not groups:
                groups.append([r])
            else:
                groups[-1].append(r)
        chunks = [(" ".join(_strip_bullet(x.text) for x in g), g) for g in groups]
        for text, g in chunks:
            e.statements.append(_mk_stmt(counter, text, [x.id for x in g]))
    elif desc:
        joined, offsets = "", []
        for r in desc:
            t = _strip_bullet(r.text)
            if joined:
                joined += " "
            offsets.append((len(joined), len(joined) + len(t), r.id))
            joined += t
        for a, b in split_sentences(joined):
            ids = [rid for (s, en, rid) in offsets if s < b and en > a]
            e.statements.append(_mk_stmt(counter, joined[a:b].strip(), ids))
    for r in desc:
        r.role = "statement" if kind not in ("skills", "languages", "interests") else "item"
    return e


def _mk_stmt(counter, text, ids) -> Statement:
    counter[0] += 1
    return Statement(id=f"s{counter[0]}", text=text.strip(), line_ids=ids)


# ── Legacy structured fields (ATS, matching, export rely on these) ─

def _span(rows_by_id, ids) -> Optional[SourceSpan]:
    rs = [rows_by_id[i] for i in ids if i in rows_by_id]
    if not rs:
        return None
    return SourceSpan(page=rs[0].page, text=" ".join(r.text for r in rs),
                      bbox=[min(r.bbox[0] for r in rs), min(r.bbox[1] for r in rs),
                            max(r.bbox[2] for r in rs), max(r.bbox[3] for r in rs)])


PUB_HINT = re.compile(r"\b(IEEE|ACM|Springer|Elsevier|journal|conference|proceedings|DOI|arXiv|Xplore|published)\b", re.I)


def _fill_legacy_fields(resume: ResumeData, secs: list[DocSection], rows_by_id: dict):
    for s in secs:
        for e in s.entries:
            all_ids = e.title_line_ids + e.meta_line_ids + [i for st in e.statements for i in st.line_ids]
            span = _span(rows_by_id, all_ids)
            stmts = [st.text for st in e.statements]
            if s.kind == "summary":
                resume.summary = ((resume.summary + " ") if resume.summary else "") + " ".join(stmts or [e.title])
                resume.summary_span = span
                for j, st in enumerate(e.statements):
                    st.path = ["summary"]
            elif s.kind == "education":
                gpa = re.search(r"(?:C?GPA|CPI|Score|Percentage)\s*[:\-]?\s*([\d.]+\s*%?(?:\s*/\s*[\d.]+)?)", e.title + " " + " ".join(e.tags) + " " + e.subtitle, re.I)
                resume.education.append(Education(
                    institution=e.title, degree=e.subtitle or None,
                    start_date=e.dates.split("–")[0].strip() if "–" in e.dates else None,
                    end_date=e.dates.split("–")[-1].strip() if e.dates else None,
                    gpa=gpa.group(1).strip() if gpa else None,
                    highlights=stmts, source_span=span))
                for j, st in enumerate(e.statements):
                    st.path = ["education", len(resume.education) - 1, "highlights", j]
            elif s.kind in ("experience", "volunteer", "leadership", "extracurricular") and (e.statements or e.dates or e.subtitle):
                title, org = e.title, (e.tags[0] if len(e.tags) == 1 else ", ".join(e.tags))
                ex = ExperienceEntry(
                    title=title, company=org or (e.subtitle.split(" · ")[0] if e.subtitle else None),
                    location=e.subtitle if org else None,
                    start_date=e.dates.split("–")[0].strip() if "–" in e.dates else (e.dates or None),
                    end_date=e.dates.split("–")[-1].strip() if "–" in e.dates else None,
                    is_current=bool(re.search(r"present|current|now|ongoing", e.dates, re.I)),
                    bullets=stmts, source_span=span,
                    bullet_spans=[_span(rows_by_id, st.line_ids) or SourceSpan() for st in e.statements])
                target = resume.experience if s.kind == "experience" else resume.activities
                target.append(ex)
                name = "experience" if s.kind == "experience" else "activities"
                for j, st in enumerate(e.statements):
                    st.path = [name, len(target) - 1, "bullets", j]
            elif s.kind == "projects":
                resume.projects.append(Project(
                    name=e.title, technologies=e.tags, bullets=stmts,
                    description=" ".join(stmts[:2]), source_span=span))
                for j, st in enumerate(e.statements):
                    st.path = ["projects", len(resume.projects) - 1, "bullets", j]
            elif s.kind == "skills":
                txt = _strip_bullet(" ".join(rows_by_id[i].text for i in e.title_line_ids + [x for st in e.statements for x in st.line_ids] if i in rows_by_id))
                m = re.match(r"^([^:]{2,40}):\s*(.+)$", txt)
                cat, items = (m.group(1).strip(), m.group(2)) if m else ("General", txt)
                skills = [x.strip(" .") for x in re.split(r"[,|;•·]", items) if x.strip(" .")]
                if not m and len(skills) <= 1:
                    # chip/grid layout: each visual fragment is one skill
                    ids = e.title_line_ids + e.meta_line_ids + [x for st in e.statements for x in st.line_ids]
                    skills = [_strip_bullet(f) for i in ids if i in rows_by_id for f in rows_by_id[i].frags if f.strip()]
                if skills:
                    resume.skills.append(SkillCategory(category=cat, skills=skills, source_span=span))
            elif s.kind in ("certifications", "publications", "training"):
                text_all = " ".join([e.title, e.subtitle] + stmts)
                if len(s.kinds) > 1:
                    is_pub = "publications" in s.kinds and bool(PUB_HINT.search(text_all))
                else:
                    is_pub = s.kind == "publications"
                if is_pub:
                    resume.publications.append(Publication(title=e.title, venue=e.subtitle or None,
                                                           details=" ".join(stmts) or None, source_span=span))
                else:
                    cid = re.search(r"(?:Certificate|Credential)\s*ID\s*[:\-]?\s*(\S+)", text_all, re.I)
                    resume.certifications.append(Certification(
                        name=e.title, issuer=(e.subtitle or (e.tags[0] if e.tags else None)),
                        date=e.dates or find_dates(text_all) or None,
                        credential_id=cid.group(1) if cid else None, source_span=span))
            elif s.kind == "achievements":
                resume.achievements.append(Achievement(description=" ".join([e.title] + stmts).strip(), source_span=span))

    flat = []
    for cat in resume.skills:
        flat.extend(cat.skills)
    for p in resume.projects:
        flat.extend(p.technologies)
    seen, out = set(), []
    for sk in flat:
        k = sk.lower()
        if k not in seen and len(sk) < 40:
            seen.add(k)
            out.append(sk)
    resume.all_skills_flat = out

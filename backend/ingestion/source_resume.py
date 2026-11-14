"""
LaTeX / Typst source inspector (Phase 5).

Two jobs for .tex and .typ uploads:
  1. Structure: build doc_sections (sections -> entries -> statements) and line records from the
     source, so the editor, RRI, interview and timeline checks work on these files as they do on PDFs.
     Line ids are "t<source line>", so every finding points at a line of the user's file.
  2. Inspection: report constructs that hide text or confuse parsers, with the source line:
     hidden text (white text, \\phantom, 1 pt fonts, Typst #hide), images, multi-column and table
     layouts, icon fonts, and a pdflatex file without glyphtounicode (ligatures like "fi" then extract
     as junk, so "efficient" can be read as "e cient").
LaTeX is parsed with pylatexenc's tolerant walker, which handles any template's custom macros:
an unknown macro followed by brace groups is read as macro + arguments, and which argument is the
date, title or organisation is decided by content, not by position.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Optional

from backend.ingestion.layout_parser import classify_heading
from backend.schemas.resume import DocEntry, DocSection, LayoutLine, Statement

DATE_HINT = re.compile(r"\b((jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*'?\d{2,4}|(19|20)\d{2}|present|current)\b", re.I)
LOCATION_HINT = re.compile(r"^\s*([A-Z][A-Za-z .'-]+,\s*(?:[A-Z]{2}|India|USA|United States|UK|United Kingdom|Canada|Germany|"
                           r"Singapore|Australia|Netherlands|France|Ireland|UAE)|Remote|Hybrid|On-?site)\s*$")
HIDDEN_COLORS = {"white", "#ffffff", "#fff", "ffffff", "fff"}


@dataclass
class Event:
    kind: str                      # heading | entry | item
    line: int
    texts: list[str]


@dataclass
class SourceFinding:
    kind: str                      # hidden_text | layout | image | icons | unicode_map
    severity: str                  # high | medium | low
    line: int
    message: str
    text: str = ""


@dataclass
class SourceReport:
    format: str
    findings: list[SourceFinding] = field(default_factory=list)


def _clean(t: str) -> str:
    t = t.replace("$|$", "|")
    return re.sub(r"\s+", " ", t).strip(" \t\n{}:")


# ── LaTeX ────────────────────────────────────────────────────────────

SECTION_MACROS = {"section", "section*", "cvsection", "resumesection", "sectiontitle", "sectionheading", "chapter"}
ITEM_MACROS_RE = re.compile(r"item", re.I)
ENTRY_MACROS_RE = re.compile(r"(heading|entry|event|subsection|position|role|job)", re.I)
# Argument counts for common resume macros; \newcommand definitions in the file take precedence.
BUILTIN_ARITY = {"phantom": 1, "hphantom": 1, "vphantom": 1, "resumeItem": 1, "resumeSubItem": 2, "resumeSubheading": 4,
                 "resumeSubSubheading": 2, "resumeProjectHeading": 2, "cventry": 6, "cvitem": 2, "cvlistitem": 1,
                 "cvevent": 4, "datedsubsection": 2, "small": 1, "textbf": 1, "textit": 1, "emph": 1, "underline": 1}
NEWCOMMAND = re.compile(r"\\(?:re)?newcommand\*?\s*\{?\\([A-Za-z@]+)\}?\s*(?:\[(\d)\])?")
LAYOUT_ENVS = {"multicols": "two-column layout", "multicols*": "two-column layout", "paracol": "two-column layout",
               "minipage": "side-by-side boxes", "tabularx": "a table", "longtable": "a table", "tabular": "a table"}


def latex_events(src: str) -> tuple[list[Event], list[SourceFinding]]:
    from pylatexenc.latexwalker import (LatexCharsNode, LatexEnvironmentNode, LatexGroupNode, LatexMacroNode,
                                        LatexWalker)
    from pylatexenc.latex2text import LatexNodes2Text

    arity = {**BUILTIN_ARITY, **{m.group(1): int(m.group(2) or 0) for m in NEWCOMMAND.finditer(src)}}
    w = LatexWalker(src, tolerant_parsing=True)
    l2t = LatexNodes2Text(math_mode="text", strict_latex_spaces=False)
    nodes, _, _ = w.get_latex_nodes()
    events: list[Event] = []
    findings: list[SourceFinding] = []

    def line(n) -> int:
        return w.pos_to_lineno_colno(n.pos)[0]

    def text(n) -> str:
        try:
            return _clean(l2t.nodelist_to_text([n]))
        except Exception:
            return _clean(src[n.pos:n.pos + n.len])

    def group_args(seq, i, limit=6):
        """Brace groups that follow position i (an unknown macro's arguments), up to `limit`,
        never across a blank line."""
        out, j = [], i + 1
        while j < len(seq) and len(out) < limit:
            n = seq[j]
            if isinstance(n, LatexCharsNode) and not n.chars.strip():
                if "\n\n" in n.chars.replace(" ", "").replace("\t", ""):
                    break
                j += 1
                continue
            if isinstance(n, LatexGroupNode) and n.delimiters == ("{", "}"):
                out.append(n)
                j += 1
                continue
            break
        return out, j

    def macro_args(n):
        return [a for a in (n.nodeargd.argnlist if n.nodeargd else []) if a is not None]

    def hidden(kind_text: str, n, payload: str):
        if payload.strip():
            findings.append(SourceFinding("hidden_text", "high", line(n),
                                          f"{kind_text}: a parser reads this text but a person cannot see it.", payload[:200]))

    def walk(seq):
        i = 0
        while i < len(seq):
            n = seq[i]
            if isinstance(n, LatexMacroNode):
                name = n.macroname
                low = name.lower()
                args = macro_args(n)
                extra, nxt = group_args(seq, i, arity.get(name, 6)) if not args else ([], i + 1)
                allargs = args + extra
                if low in SECTION_MACROS or (low.startswith("section") and allargs):
                    head = text(allargs[-1]) if allargs else ""
                    if head:
                        events.append(Event("heading", line(n), [head]))
                    i = nxt
                    continue
                if low in ("textcolor", "colorbox") and len(allargs) >= 2 and text(allargs[-2]).lower() in HIDDEN_COLORS:
                    hidden("White text (\\textcolor{white})", n, text(allargs[-1]))
                    i = nxt
                    continue
                if low in ("phantom", "hphantom", "vphantom") and allargs:
                    hidden("\\phantom", n, text(allargs[0]))
                    i = nxt
                    continue
                if low == "includegraphics":
                    findings.append(SourceFinding("image", "low", line(n),
                                                  "Image: any words inside it are invisible to parsers."))
                if low.startswith("fa") and len(low) > 2 and low[2:3].isalpha() and name[2:3].isupper():
                    findings.append(SourceFinding("icons", "low", line(n), f"Icon font (\\{name}): parsers read it as "
                                                  f"a private-use symbol. Keep a text label next to it."))
                if low == "item":
                    # an \item's content runs until the next \item at this level
                    j, buf = i + 1, []
                    while j < len(seq) and not (isinstance(seq[j], LatexMacroNode) and seq[j].macroname == "item"):
                        buf.append(seq[j])
                        j += 1
                    inner_events = len(events)
                    walk(buf)
                    if len(events) == inner_events and buf:     # plain item, not a wrapper around entries
                        seg = src[buf[0].pos:buf[-1].pos + buf[-1].len]
                        for part in re.split(r"\\\\(?:\[[^\]]*\])?", seg):     # one statement per \\ line
                            t = _clean(l2t.latex_to_text(part)) if part.strip() else ""
                            if t:
                                events.append(Event("item", line(n) + seg[:seg.find(part)].count("\n"), [t]))
                    i = j
                    continue
                if allargs and ITEM_MACROS_RE.search(low) and not low.endswith(("start", "end")):
                    t = _clean(": ".join(text(a) for a in allargs if text(a)))
                    if t:
                        events.append(Event("item", line(n), [t]))
                    i = nxt
                    continue
                if len(allargs) >= 2 and (ENTRY_MACROS_RE.search(low) or any(DATE_HINT.search(text(a)) for a in allargs)) \
                        and low not in ("href", "newcommand", "renewcommand", "setlength", "fontsize", "textcolor"):
                    events.append(Event("entry", line(n), [text(a) for a in allargs]))
                    i = nxt
                    continue
                for a in allargs:                           # \small{...}, \textbf{...}: look inside
                    if isinstance(a, LatexGroupNode) and low not in ("newcommand", "renewcommand", "def", "href"):
                        walk(a.nodelist)
                i = nxt
                continue
            if isinstance(n, LatexEnvironmentNode):
                env = n.environmentname
                if env in LAYOUT_ENVS:
                    findings.append(SourceFinding("layout", "medium", line(n),
                                                  f"\\begin{{{env}}} makes {LAYOUT_ENVS[env]}. Many parsers read it row "
                                                  f"by row across columns, so dates and titles can end up in the wrong entry."))
                walk(n.nodelist)
                i += 1
                continue
            if isinstance(n, LatexGroupNode):
                inner = n.nodelist
                first = next((x for x in inner if not (isinstance(x, LatexCharsNode) and not x.chars.strip())), None)
                if isinstance(first, LatexMacroNode) and first.macroname == "color":
                    col = text(macro_args(first)[-1]) if macro_args(first) else ""
                    if not col:
                        g, _ = group_args(inner, inner.index(first), 1)
                        col = text(g[0]) if g else ""
                    if col.lower() in HIDDEN_COLORS:
                        rest = _clean(" ".join(text(x) for x in inner[inner.index(first) + 1:]
                                               if not (isinstance(x, LatexGroupNode) and text(x).lower() == col.lower())))
                        hidden("White text (\\color{white})", n, rest)
                        i += 1
                        continue
                if isinstance(first, LatexMacroNode) and first.macroname == "fontsize":
                    fa = macro_args(first) or group_args(inner, inner.index(first), 2)[0]
                    size = re.match(r"\s*([\d.]+)", text(fa[0])) if fa else None
                    if size and float(size.group(1)) < 4:
                        hidden(f"{size.group(1)} pt font", n, _clean(" ".join(text(x) for x in inner if isinstance(x, LatexCharsNode))))
                        i += 1
                        continue
                walk(inner)
                i += 1
                continue
            i += 1

    doc = next((n for n in nodes if isinstance(n, LatexEnvironmentNode) and n.environmentname == "document"), None)
    walk(doc.nodelist if doc else nodes)

    uses_unicode_engine = re.search(r"\\usepackage(\[[^\]]*\])?\{(fontspec|unicode-math)\}", src) is not None
    if not uses_unicode_engine and not (re.search(r"\\pdfgentounicode\s*=\s*1", src) and "glyphtounicode" in src):
        findings.append(SourceFinding("unicode_map", "medium", 1,
                                      "Add \\input{glyphtounicode} and \\pdfgentounicode=1 to the preamble. Without "
                                      "them pdflatex output can extract ligatures as junk (\"efficient\" read as \"e cient\")."))
    return events, findings


# ── Typst ────────────────────────────────────────────────────────────

TYP_HEADING = re.compile(r"^\s*(=+)\s+(.+)$")
TYP_ITEM = re.compile(r"^\s*[-+]\s+(.+)$")
TYP_HIDE = re.compile(r"#hide\[([^\]]*)\]")
TYP_WHITE = re.compile(r"#text\([^)]*fill:\s*(?:white|rgb\(\s*\"#?f{3,6}\"\s*\))[^)]*\)\[([^\]]*)\]", re.I)
TYP_TINY = re.compile(r"#text\([^)]*size:\s*([\d.]+)pt[^)]*\)\[([^\]]*)\]")
TYP_LAYOUT = re.compile(r"#(columns|grid|table)\(")


def _typ_text(t: str) -> str:
    t = t.replace("--", "–")
    t = re.sub(r"#link\(\"[^\"]*\"\)\[([^\]]*)\]", r"\1", t)
    t = re.sub(r"#h\([^)]*\)", " | ", t)
    t = re.sub(r"#[a-z]+\([^)]*\)", "", t)
    t = re.sub(r"[*_`\\]", "", t)
    return _clean(t.replace("[", " ").replace("]", " ")).strip(" |")


def typst_events(src: str) -> tuple[list[Event], list[SourceFinding]]:
    events, findings = [], []
    levels = [len(m.group(1)) for m in (TYP_HEADING.match(l) for l in src.splitlines()) if m]
    name_level = 1 if levels.count(1) == 1 and 2 in levels else None     # "= Asha Rao" is the name, not a section
    for no, raw in enumerate(src.splitlines(), 1):
        for m in TYP_HIDE.finditer(raw):
            if m.group(1).strip():
                findings.append(SourceFinding("hidden_text", "high", no, "#hide: a parser reads this text but a person cannot see it.", m.group(1)[:200]))
        for m in TYP_WHITE.finditer(raw):
            findings.append(SourceFinding("hidden_text", "high", no, "White text: a parser reads it but a person cannot see it.", m.group(1)[:200]))
        for m in TYP_TINY.finditer(raw):
            if float(m.group(1)) < 4:
                findings.append(SourceFinding("hidden_text", "high", no, f"{m.group(1)} pt text is unreadable.", m.group(2)[:200]))
        if TYP_LAYOUT.search(raw):
            findings.append(SourceFinding("layout", "medium", no, "Columns, grids and tables can be read across columns by parsers."))
        if "#image(" in raw:
            findings.append(SourceFinding("image", "low", no, "Image: any words inside it are invisible to parsers."))
        clean = TYP_TINY.sub("", TYP_WHITE.sub("", TYP_HIDE.sub("", raw)))
        if raw.lstrip().startswith(("#set", "#show", "#let", "#import", "//")):
            continue
        if m := TYP_HEADING.match(clean):
            if len(m.group(1)) != name_level:
                events.append(Event("heading", no, [_typ_text(m.group(2))]))
        elif m := TYP_ITEM.match(clean):
            events.append(Event("item", no, [_typ_text(m.group(1))]))
        elif DATE_HINT.search(clean) and _typ_text(clean):
            events.append(Event("entry", no, [p for p in (_typ_text(x) for x in re.split(r"#h\([^)]*\)|\|", clean)) if p]))
    return events, findings


# ── Shared: events -> doc_sections + lines ───────────────────────

def _entry_fields(texts: list[str]) -> tuple[str, str, str, list[str], list[str]]:
    """(title, subtitle, dates, tags, sentences). Which argument is which is decided by content."""
    dates = next((t for t in texts if DATE_HINT.search(t) and len(t) < 40), "")
    rest = [t for t in texts if t and t != dates and not LOCATION_HINT.match(t)]
    sentences = [t for t in rest[2:] if len(t.split()) >= 4]          # \cventry's description argument
    title = rest[0] if rest else ""
    subtitle = rest[1] if len(rest) > 1 else ""
    tags: list[str] = []
    if "|" in title:
        title, tail = (p.strip() for p in title.split("|", 1))
        tags = [t.strip() for t in tail.split(",") if t.strip()]
    return title, subtitle, dates, tags, sentences


def build_structure(events: list[Event]) -> tuple[list[DocSection], list[LayoutLine]]:
    sections: list[DocSection] = []
    lines: list[LayoutLine] = []
    used: dict[int, int] = {}
    n_stmt = 0

    def line_id(no: int, txt: str, role: str, sid: Optional[str]) -> str:
        k = used.get(no, 0)
        used[no] = k + 1
        lid = f"t{no}" + ("" if k == 0 else chr(ord("a") + k))
        lines.append(LayoutLine(id=lid, page=0, bbox=[0.0, 0.0, 0.0, 0.0], text=txt, role=role, section_id=sid))
        return lid

    for ev in events:
        if ev.kind == "heading":
            kind, kinds = classify_heading(ev.texts[0])
            sid = f"S{len(sections) + 1}"
            sections.append(DocSection(id=sid, heading=ev.texts[0], kind=kind or "other", kinds=kinds,
                                       heading_line_id=line_id(ev.line, ev.texts[0], "heading", sid)))
            continue
        if not sections:
            sections.append(DocSection(id="S0", heading="", kind="header"))
        sec = sections[-1]
        if ev.kind == "entry":
            title, sub, dates, tags, sentences = _entry_fields(ev.texts)
            sec.entries.append(DocEntry(id=f"{sec.id}E{len(sec.entries) + 1}", title=title, subtitle=sub, dates=dates,
                                        tags=tags, title_line_ids=[line_id(ev.line, " | ".join(ev.texts), "title", sec.id)]))
            texts = sentences
        else:
            texts = ev.texts[:1]
        if not sec.entries:
            sec.entries.append(DocEntry(id=f"{sec.id}E1"))
        for txt in texts:
            n_stmt += 1
            sec.entries[-1].statements.append(Statement(id=f"s{n_stmt}", text=txt,
                                                        line_ids=[line_id(ev.line, txt, "statement", sec.id)]))
    return sections, lines


def inspect_source(src: str, fmt: str) -> tuple[list[DocSection], list[LayoutLine], SourceReport]:
    events, findings = (latex_events if fmt == "tex" else typst_events)(src)
    sections, lines = build_structure(events)
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order[f.severity], f.line))
    return sections, lines, SourceReport(fmt, findings)


def report_dict(r: SourceReport) -> dict:
    return asdict(r)


# ── Upload helpers (.tex / .typ) ─────────────────────────────────

def fill_legacy(rd, sections: list[DocSection]) -> None:
    """Rebuild the legacy fields that ATS rules and matching read, and set Statement.path so an edit
    accepted in the editor is written back for export (same convention as the PDF parser)."""
    from backend.schemas.resume import Education, ExperienceEntry, Project, SkillCategory
    exp, proj, edu, skills = [], [], [], []
    for sec in sections:
        for e in sec.entries:
            bullets = [st.text for st in e.statements]
            start, _, end = (p.strip() or None for p in (e.dates.partition("–") if "–" in e.dates else (e.dates, "", "")))
            if sec.kind == "experience":
                for k, st in enumerate(e.statements):
                    st.path = ["experience", len(exp), "bullets", k]
                exp.append(ExperienceEntry(title=e.title or None, company=e.subtitle or None, start_date=start,
                                           end_date=end, is_current=bool(re.search(r"present|current", e.dates, re.I)),
                                           bullets=bullets, technologies=e.tags))
            elif sec.kind == "projects":
                for k, st in enumerate(e.statements):
                    st.path = ["projects", len(proj), "bullets", k]
                proj.append(Project(name=e.title or None, technologies=e.tags, bullets=bullets))
            elif sec.kind == "education":
                edu.append(Education(institution=e.title or None, degree=e.subtitle or None, start_date=start,
                                     end_date=end, highlights=bullets))
            elif sec.kind == "skills":
                for st in e.statements:
                    cat, sep, vals = st.text.partition(":")
                    if not sep:
                        cat, vals = "Skills", st.text
                    skills.append(SkillCategory(category=cat.strip(),
                                                skills=[v.strip() for v in re.split(r"[,;|•]", vals) if v.strip()]))
    if exp:
        rd.experience = exp
    if proj:
        rd.projects = proj
    if edu:
        rd.education = edu
    if skills:
        rd.skills = skills
        rd.all_skills_flat = list(dict.fromkeys(s for c in skills for s in c.skills))


def enrich_from_source(rd, src: str, fmt: str) -> SourceReport:
    sections, lines, report = inspect_source(src, fmt)
    rd.doc_sections, rd.lines, rd.parser_version = sections, lines, f"{fmt}-source-1"
    fill_legacy(rd, sections)
    return report


def resume_from_typst(src: str, filename: str):
    from backend.schemas.resume import ContactInfo, DocumentMetadata, ResumeData
    plain = "\n".join(_typ_text(l) for l in src.splitlines()
                      if l.strip() and not l.lstrip().startswith(("#set", "#show", "#let", "#import", "//")))
    email = re.search(r"[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}", src.replace("\\@", "@"))
    phone = re.search(r"(?<![\w/])(\+?\d[\d\s().-]{8,16}\d)(?![\w/])", plain)
    gh = re.search(r"https?://(?:www\.)?github\.com/[A-Za-z0-9-]+", src)
    li = re.search(r"https?://(?:www\.)?linkedin\.com/in/[\w-]+", src)
    name = next((m.group(2).strip() for m in (TYP_HEADING.match(l) for l in src.splitlines()) if m and len(m.group(1)) == 1), None)
    rd = ResumeData(contact=ContactInfo(name=name, email=email.group(0) if email else None,
                                        phone=phone.group(1) if phone else None,
                                        github=gh.group(0) if gh else None, linkedin=li.group(0) if li else None),
                    raw_text=plain,
                    document_metadata=DocumentMetadata(filename=filename, file_type="typ", char_count=len(plain),
                                                       word_count=len(plain.split())))
    return rd, enrich_from_source(rd, src, "typ")


def source_warnings(report: SourceReport) -> list[str]:
    return [f"Line {f.line}: {f.message}" for f in report.findings if f.severity != "low"]

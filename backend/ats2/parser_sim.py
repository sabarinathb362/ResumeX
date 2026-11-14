"""
ATS 2.0 — "What a naive parser sees".

We do not have Workday's, Taleo's or Greenhouse's parsers, so we do not claim to emulate them.
Instead we run three deliberately naive extraction strategies that many older or simpler
pipelines resemble, and compare each with ResumeX's layout-aware v2 reading order:

  stream   text in PDF content-stream order (no layout analysis)
  rows     every row read straight across the full page width (no column detection)
  tables   table cells concatenated with no separators

For each view we report reading-order integrity, which contact fields and dates still come out,
and glyphs that commonly turn into garbage (ligatures, private-use icon fonts, unmapped glyphs).
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field

import pymupdf

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
DATE = re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b|\b\d{1,2}/\d{4}\b", re.I)
LIGATURES = {chr(c) for c in range(0xFB00, 0xFB07)}


@dataclass
class View:
    name: str
    text: str
    integrity: float                     # 0..1 token-order similarity to the v2 reading order
    issues: list[str] = field(default_factory=list)


@dataclass
class ParserReport:
    views: list[View] = field(default_factory=list)
    field_checks: list[dict] = field(default_factory=list)
    glyph_issues: list[dict] = field(default_factory=list)
    worst_view: str = ""
    verdict: str = ""
    reference: str = ""                  # the layout-aware reading order, for a side-by-side comparison
    advice: list[str] = field(default_factory=list)
    disclosure: str = ("Naive extraction strategies run on your PDF. Real ATS products differ; this shows "
                       "failure modes, not how any specific vendor will parse your file.")


def _tokens(t: str) -> list[str]:
    return re.findall(r"\w+", t.lower())


def _integrity(reference: str, candidate: str) -> float:
    a, b = _tokens(reference), _tokens(candidate)
    if not a or not b:
        return 0.0
    return round(difflib.SequenceMatcher(None, a, b, autojunk=False).ratio(), 3)


def _rows_view(page) -> str:
    """Group spans into rows by baseline across the WHOLE page width, ignoring columns."""
    spans = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln.get("spans", []):
                if sp["text"].strip():
                    spans.append((round(sp["bbox"][3] / 3), sp["bbox"][0], sp["text"].strip()))
    spans.sort()
    rows, cur, key = [], [], None
    for k, _, t in spans:
        if key is not None and k != key:
            rows.append(" ".join(cur))
            cur = []
        cur.append(t)
        key = k
    if cur:
        rows.append(" ".join(cur))
    return "\n".join(rows)


def _tables_view(page) -> tuple[str, int]:
    out, n = [], 0
    try:
        for t in page.find_tables().tables:
            n += 1
            for row in t.extract():
                out.append("".join(c or "" for c in row))
    except Exception:
        pass
    return "\n".join(out), n


def _glyphs(text: str) -> list[dict]:
    found: dict[str, dict] = {}
    for i, ch in enumerate(text):
        cp = ord(ch)
        kind = None
        if ch in LIGATURES:
            kind = "ligature (may not match keyword search)"
        elif 0xF020 <= cp <= 0xF0FF:
            # Word maps Symbol / Wingdings characters into this range; U+F0A7 and U+F0B7 are its bullets.
            kind = "bullet or symbol from a Symbol / Wingdings font"
        elif 0xE000 <= cp <= 0xF8FF:
            kind = "private-use icon glyph"
        elif ch == "�":
            kind = "unmapped glyph (font has no text mapping)"
        elif unicodedata.category(ch) == "Co":
            kind = "private-use character"
        if kind:
            d = found.setdefault(ch, {"char": ch, "codepoint": f"U+{cp:04X}", "kind": kind, "count": 0,
                                      "example": text[max(0, i - 20):i + 20].replace("\n", " ")})
            d["count"] += 1
    return list(found.values())


def simulate_parsers(pdf_path: str, reference_text: str, contact: dict) -> ParserReport:
    stream, rows, tables, n_tables = [], [], [], 0
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            # keep ligatures and raw glyphs exactly as a naive extractor would get them
            stream.append(page.get_text("text", sort=False,
                                        flags=pymupdf.TEXT_PRESERVE_LIGATURES | pymupdf.TEXT_PRESERVE_WHITESPACE))
            rows.append(_rows_view(page))
            t, n = _tables_view(page)
            tables.append(t)
            n_tables += n
    views = [View("stream", "\n".join(stream), _integrity(reference_text, "\n".join(stream))),
             View("rows", "\n".join(rows), _integrity(reference_text, "\n".join(rows)))]
    if n_tables:
        views.append(View("tables", "\n".join(tables), 0.0, [f"{n_tables} table(s): cells run together"]))

    text_views = [v for v in views if v.name != "tables"]          # tables hold only cell text
    expected = {"email": contact.get("email"), "phone": contact.get("phone")}
    ref_dates = set(DATE.findall(reference_text))
    checks = []
    for name, val in expected.items():
        if not val:
            continue
        digits = re.sub(r"\D", "", val) if name == "phone" else val.lower()
        found = {}
        for v in text_views:
            hay = re.sub(r"\D", "", v.text) if name == "phone" else v.text.lower()
            found[v.name] = digits in hay
        checks.append({"field": name, "expected": val, "found_in": found})
    for v in views:
        lost = [d for d in ref_dates if d not in v.text]
        if lost and v.name != "tables":
            v.issues.append(f"{len(lost)} of {len(ref_dates)} dates not found as written: " + ", ".join(sorted(lost)[:3]))
        if v.integrity and v.integrity < 0.85 and v.name != "tables":
            v.issues.append(f"Reading order differs from the page ({v.integrity:.0%} match): columns or side boxes interleave")
        for c in checks:
            if not c["found_in"].get(v.name, True):
                v.issues.append(f"{c['field']} not recoverable")

    glyphs = _glyphs("\n".join(stream))
    scored = [v for v in views if v.name != "tables"]
    worst = min(scored, key=lambda v: v.integrity) if scored else None
    rep = ParserReport(views=views, field_checks=checks, glyph_issues=glyphs, worst_view=worst.name if worst else "")
    if worst and worst.integrity >= 0.95 and not glyphs and not n_tables:
        rep.verdict = "Naive parsers read this file in the same order you do. Low parsing risk."
    else:
        parts = []
        if worst and worst.integrity < 0.95:
            parts.append(f"a naive '{worst.name}' parser keeps only {worst.integrity:.0%} of your reading order")
        if n_tables:
            parts.append(f"{n_tables} table(s) would have their cells run together")
        if glyphs:
            parts.append(f"{sum(g['count'] for g in glyphs)} glyph(s) may come out as garbage")
        rep.verdict = "Risk: " + "; ".join(parts) + "."
    if any("Symbol" in g["kind"] for g in glyphs):
        rep.advice.append("Your bullet points use a Symbol / Wingdings character. A parser cannot read it as a bullet and "
                          "stores an unknown character at the start of each line. In Word: select the list, then "
                          "Home > Bullets and choose the plain round bullet.")
    if any(g["kind"].startswith("private-use icon") for g in glyphs):
        rep.advice.append("Icon-font symbols (phone, email, link icons) have no text meaning. Keep a text label next to "
                          "each one, or replace them with words.")
    if any(g["kind"].startswith("ligature") for g in glyphs):
        rep.advice.append("Ligatures such as 'fi' and 'ffi' are stored as single characters, so a keyword like "
                          "'efficient' may not match a search. Export the PDF with ligatures off, or use a standard font.")
    if any(g["kind"].startswith("unmapped") for g in glyphs):
        rep.advice.append("Some characters have no text mapping at all and extract as empty boxes. Re-export the PDF "
                          "from the original document with fonts embedded.")
    if n_tables:
        rep.advice.append("Tables are read cell by cell with nothing between the cells. Use plain lines with tabs or "
                          "a single column instead.")
    if worst and worst.integrity < 0.95:
        rep.advice.append("Columns or side boxes are being interleaved. A single-column layout is read in the order "
                          "you intend by every parser.")
    for c in checks:
        if not all(c["found_in"].values()):
            rep.advice.append(f"Your {c['field']} is not recovered by every extraction. Keep it as plain text on its "
                              "own in the header, not inside an icon, image or text box.")
    rep.reference = reference_text[:4000]
    for v in views:
        v.text = v.text[:4000]
    return rep

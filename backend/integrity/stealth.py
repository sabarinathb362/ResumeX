"""
Hidden-text detector for PDF resumes (Phase 5).

Finds text that a parser extracts but a human reader cannot see:
  invisible   PDF text render mode 3 (no fill, no stroke)
  transparent fill opacity below 10 %
  tiny        font size under 4 pt
  off_page    glyph box outside the visible page
  low_contrast text colour almost equal to what is rendered under it (white on white)
  covered     no pixel of the text's colour survives rendering (an image or box drawn on top)
Each finding lists the hidden words and which of them are JD keywords, because pasting the
JD in white text is the usual reason this text exists. It shows up verbatim in the ATS's
plain-text view, which is what recruiters read.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pymupdf

ZOOM = 2.0
HIDDEN_RATIO = 1.25        # WCAG contrast ratio; white on white is 1.0, black on white is 21
FAINT_RATIO = 1.6


@dataclass
class HiddenSpan:
    page: int
    bbox: list[float]
    text: str
    reasons: list[str]
    severity: str                       # high | low
    jd_terms: list[str] = field(default_factory=list)


@dataclass
class StealthReport:
    spans: list[HiddenSpan]
    hidden_words: int
    hidden_jd_terms: list[str]
    verdict: str


def _lum(rgb) -> float:
    """Relative luminance of an 0-255 RGB triple."""
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(float(x)) for x in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _pixels(pix: pymupdf.Pixmap):
    rows = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)
    return rows[:, :pix.width * pix.n].reshape(pix.height, pix.width, pix.n)[:, :, :3]


def _text(trace) -> str:
    return "".join(chr(c[0]) for c in trace["chars"])


def _visibility(img, trace) -> list[str]:
    x0, y0, x1, y1 = (int(round(v * ZOOM)) for v in trace["bbox"])
    region = img[max(0, y0):max(0, y1), max(0, x0):max(0, x1)].reshape(-1, 3)
    if len(region) < 4:
        return []
    colors, counts = np.unique(region, axis=0, return_counts=True)
    bg = tuple(int(c) for c in colors[counts.argmax()])
    col = tuple(int(c * 255) for c in (trace.get("color") or (0, 0, 0))[:3])
    ratio = contrast(col, bg)
    if ratio < HIDDEN_RATIO:
        return ["low_contrast"]
    if ratio < FAINT_RATIO:
        return ["faint"]
    near = (np.abs(region.astype(int) - np.array(col)).sum(axis=1) < 120).mean()
    return ["covered"] if near < 0.01 else []


def scan_pdf(path: str, jd_skills: list[str] | None = None) -> StealthReport:
    from backend.feedback.taxonomy import canonical, grounded_canonicals
    jd_set = {(canonical(s) or s).lower() for s in (jd_skills or [])}
    doc = pymupdf.open(path)
    spans: list[HiddenSpan] = []
    try:
        for pno, page in enumerate(doc):
            img = None
            for t in page.get_texttrace():
                text = _text(t).strip()
                # Icon-font and unmapped glyphs (U+FFFD, private use) carry no words, and their thin
                # glyph boxes read as "covered". They are reported by the ATS 2.0 glyph check instead.
                if not any(ch.isalnum() for ch in text):
                    continue
                reasons = []
                if t.get("type") == 3:
                    reasons.append("invisible")
                if (t.get("opacity") if t.get("opacity") is not None else 1.0) < 0.1:
                    reasons.append("transparent")
                if t["size"] < 4:
                    reasons.append("tiny")
                if not pymupdf.Rect(t["bbox"]).intersects(page.rect):
                    reasons.append("off_page")
                if not reasons:
                    if img is None:
                        img = _pixels(page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), alpha=False))
                    reasons = _visibility(img, t)
                if not reasons:
                    continue
                sev = "low" if reasons == ["faint"] else "high"
                terms = sorted(c for c in grounded_canonicals(text) if c.lower() in jd_set) if jd_set else []
                prev = spans[-1] if spans else None
                if prev and prev.page == pno and prev.reasons == reasons and abs(prev.bbox[1] - t["bbox"][1]) < 2:
                    prev.text += " " + text                      # same line, same reason: merge
                    prev.bbox[2] = max(prev.bbox[2], t["bbox"][2])
                    prev.jd_terms = sorted(set(prev.jd_terms) | set(terms))
                    continue
                spans.append(HiddenSpan(pno, [round(v, 1) for v in t["bbox"]], text, reasons, sev, terms))
    finally:
        doc.close()
    high = [s for s in spans if s.severity == "high"]
    words = sum(len(s.text.split()) for s in high)
    jd_terms = sorted({t for s in high for t in s.jd_terms})
    if not high:
        verdict = "No hidden text found."
    elif jd_terms:
        verdict = (f"{words} hidden words, including JD keywords ({', '.join(jd_terms[:6])}). Recruiters see this text "
                   f"in the ATS's plain-text view; remove it.")
    else:
        verdict = f"{words} words a parser reads but a person cannot see. Remove them or make them visible."
    return StealthReport(spans, words, jd_terms, verdict)


def to_dict(r: StealthReport) -> dict:
    return asdict(r)

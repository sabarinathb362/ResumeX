"""
Edit a PDF resume in place, keeping the user's own layout.

The page is cut into "units": one run of text on one line (a heading, the left part of a title row,
the date at its right, one line of a bullet ...), without any leading bullet glyph. An edit replaces
the text of one unit, or of several consecutive units that form one paragraph (a wrapped bullet),
and is typeset back into the same place:

  * only the old text is removed (redaction limited to text; lines, boxes and images stay),
  * the new text uses the same font size and colour, and the same font when possible: the font
    embedded in the PDF if it has every glyph needed, else the matching system font file, else the
    closest standard PDF font,
  * a single unit keeps its alignment (left, right-aligned dates, centred headers) and may shrink
    to 88 % to fit; a paragraph is re-wrapped across its lines and may grow downward only into
    empty space,
  * anything that still does not fit is NOT applied, and is reported, rather than overflowing
    onto other text.

Nothing here invents content: it only places the text it is given.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

import pymupdf

from backend.ingestion.layout_parser import BULLET_CHARS

MIN_SCALE = 0.88
_SUBSET = re.compile(r"^[A-Z]{6}\+")

# family keyword -> (regular, bold, italic, bold-italic) file names in the system font folder
_SYSTEM_FONTS = {
    "timesnewroman": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "times": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "arial": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "calibri": ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
    "georgia": ("georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf"),
    "verdana": ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
    "tahoma": ("tahoma.ttf", "tahomabd.ttf", "tahoma.ttf", "tahomabd.ttf"),
    "trebuchet": ("trebuc.ttf", "trebucbd.ttf", "trebucit.ttf", "trebucbi.ttf"),
    "garamond": ("GARA.TTF", "GARABD.TTF", "GARAIT.TTF", "GARABD.TTF"),
    "bookantiqua": ("BKANT.TTF", "ANTQUAB.TTF", "ANTQUAI.TTF", "ANTQUABI.TTF"),
    "centurygothic": ("GOTHIC.TTF", "GOTHICB.TTF", "GOTHICI.TTF", "GOTHICBI.TTF"),
    "couriernew": ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
    "consolas": ("consola.ttf", "consolab.ttf", "consolai.ttf", "consolaz.ttf"),
    "segoeui": ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    "helvetica": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
}
_FONT_DIRS = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
              "/usr/share/fonts/truetype/msttcorefonts", "/Library/Fonts", "/System/Library/Fonts/Supplemental"]


@dataclass
class Unit:
    id: str
    page: int
    bbox: list[float]              # the text only (bullet glyph excluded)
    text: str
    size: float
    font: str
    flags: int
    color: tuple
    baseline: float
    line_id: Optional[str] = None  # parser line this unit sits on, when known


@dataclass
class EditResult:
    key: str
    ok: bool
    reason: str = ""
    scale: float = 1.0
    font: str = ""                 # embedded | system | standard
    pages: list[int] = field(default_factory=list)


def _is_bullet_char(c: str) -> bool:
    return c in BULLET_CHARS or "\ue000" <= c <= "\uf8ff"


def page_units(page, pno: int) -> list[Unit]:
    """Every run of text on the page, in content order. Ids are stable for a given file."""
    units: list[Unit] = []
    k = 0
    for b in page.get_text("rawdict", flags=pymupdf.TEXT_PRESERVE_LIGATURES | pymupdf.TEXT_PRESERVE_WHITESPACE)["blocks"]:
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []):
            chars = [(c, sp) for sp in ln.get("spans", []) for c in sp.get("chars", [])]
            if not any(c["c"].strip() for c, _ in chars):
                continue
            uid = f"p{pno}u{k}"
            k += 1
            # skip a leading bullet glyph (and the space after it); "- " only when a letter follows
            i = 0
            while i < len(chars) and chars[i][0]["c"].isspace():
                i += 1
            if i < len(chars) and (_is_bullet_char(chars[i][0]["c"]) and not (chars[i][0]["c"] in "-–" and not (
                    i + 2 < len(chars) and chars[i + 1][0]["c"].isspace() and chars[i + 2][0]["c"].isalpha()))):
                i += 1
                while i < len(chars) and chars[i][0]["c"].isspace():
                    i += 1
            else:
                i = 0
            rest = chars[i:]
            # A wide gap inside one line (a tab between a title and its right-aligned date) separates
            # two pieces that are edited and aligned independently.
            pieces, cur, prev = [], [], None
            for c, sp in rest:
                if not c["c"].isspace():
                    if prev is not None and c["bbox"][0] - prev["bbox"][2] > max(14.0, 1.6 * sp["size"]):
                        pieces.append(cur)
                        cur = []
                    prev = c
                cur.append((c, sp))
            pieces.append(cur)
            for n, body in enumerate(pieces):
                while body and body[0][0]["c"].isspace():
                    body.pop(0)
                while body and body[-1][0]["c"].isspace():
                    body.pop()
                if not body:
                    continue
                if n:
                    uid = f"p{pno}u{k}"
                    k += 1
                units.append(_unit(uid, pno, ln, body))
    return units


def _unit(uid: str, pno: int, ln: dict, body: list) -> Unit:
    text = "".join(c["c"] for c, _ in body)
    # the style of the unit is the style most of its characters use
    weight: dict[int, int] = {}
    for c, sp in body:
        weight[id(sp)] = weight.get(id(sp), 0) + (0 if c["c"].isspace() else 1)
    main = max((sp for _, sp in body), key=lambda sp: weight[id(sp)])
    x0 = min(c["bbox"][0] for c, _ in body)
    x1 = max(c["bbox"][2] for c, _ in body)
    col = main.get("color", 0)
    return Unit(
        id=uid, page=pno, bbox=[round(x0, 2), round(ln["bbox"][1], 2), round(x1, 2), round(ln["bbox"][3], 2)],
        text=re.sub(r"\s+", " ", text), size=round(main["size"], 2), font=main.get("font", ""),
        flags=int(main.get("flags", 0)),
        color=((col >> 16 & 255) / 255, (col >> 8 & 255) / 255, (col & 255) / 255),
        baseline=round(main["origin"][1], 2))


def document_units(doc, lines=None) -> list[Unit]:
    """Units for every page; `lines` (parser LayoutLine list) links each unit to its line id."""
    units: list[Unit] = []
    for pno, page in enumerate(doc):
        units.extend(page_units(page, pno))
    if lines:
        by_page: dict[int, list] = {}
        for l in lines:
            by_page.setdefault(l.page, []).append(l)
        for u in units:
            cx, cy = (u.bbox[0] + u.bbox[2]) / 2, (u.bbox[1] + u.bbox[3]) / 2
            best = None
            for l in by_page.get(u.page, []):
                x0, y0, x1, y1 = l.bbox
                if y0 - 2 <= cy <= y1 + 2 and x0 - 3 <= cx <= x1 + 3:
                    best = l
                    break
            u.line_id = best.id if best else None
    return units


# ── fonts ────────────────────────────────────────────────────────

def _style(name: str, flags: int) -> tuple[bool, bool]:
    low = name.lower()
    return bool(flags & 16 or "bold" in low or "black" in low or "heavy" in low), \
        bool(flags & 2 or "italic" in low or "oblique" in low)


@lru_cache(maxsize=64)
def _system_font(family_key: str, bold: bool, italic: bool) -> Optional[str]:
    files = _SYSTEM_FONTS.get(family_key)
    if not files:
        return None
    fname = files[(1 if bold else 0) + (2 if italic else 0)]
    for d in _FONT_DIRS:
        p = os.path.join(d, fname)
        if os.path.exists(p):
            return p
    return None


def _norm_font(name: str) -> str:
    n = _SUBSET.sub("", name).lower()
    n = re.sub(r"(regular|roman|mt|ps|psmt)", "", n)
    return re.sub(r"[^a-z0-9]", "", n)


@lru_cache(maxsize=1)
def _installed_fonts() -> dict[str, str]:
    """Normalised font name -> file, for every TrueType / OpenType file in the system font folders."""
    index: dict[str, str] = {}
    for d in _FONT_DIRS:
        if not os.path.isdir(d):
            continue
        for fname in os.listdir(d):
            if not fname.lower().endswith((".ttf", ".otf")):
                continue
            path = os.path.join(d, fname)
            try:
                index.setdefault(_norm_font(pymupdf.Font(fontfile=path).name), path)
            except Exception:
                continue
    return index


def _installed_font(name: str, bold: bool, italic: bool) -> Optional[str]:
    base = _norm_font(name)
    plain = re.sub(r"(bold|italic|oblique)", "", base)
    style = ("bold" if bold else "") + ("italic" if italic else "")
    idx = _installed_fonts()
    for want in ((plain + style, base, plain) if style else (base, plain)):
        for key, path in idx.items():
            # font names are stored as e.g. "Times New Roman Regular", sometimes cut short ("...Regula")
            if key == want or (key.startswith(want) and "regular".startswith(key[len(want):])):
                return path
    return None


def _family_key(name: str) -> str:
    n = _SUBSET.sub("", name)
    n = re.split(r"[,-]", n)[0]
    n = re.sub(r"(?i)(mt|ps|psmt|regular|bold|italic|oblique)$", "", n)
    return re.sub(r"[^a-z]", "", n.lower())


def _has_all(font: pymupdf.Font, text: str) -> bool:
    return all(font.has_glyph(ord(c)) for c in text if not c.isspace())


def resolve_font(doc, page, unit: Unit, text: str) -> tuple[pymupdf.Font, str]:
    """(font, where it came from). Tries embedded, then the system font file, then a standard font."""
    bold, italic = _style(unit.font, unit.flags)
    want = _SUBSET.sub("", unit.font).lower().replace(" ", "")
    for xref, ext, _typ, basefont, *_ in page.get_fonts(full=True):
        base = _SUBSET.sub("", basefont).lower().replace(" ", "").replace(",", "-")
        if ext == "n/a" or base.replace("-", "") != want.replace("-", "").replace(",", ""):
            continue
        try:
            buf = doc.extract_font(xref)[3]
            f = pymupdf.Font(fontbuffer=buf)
            if buf and _has_all(f, text):
                return f, "embedded"
        except Exception:
            pass
    path = _installed_font(unit.font, bold, italic) or _system_font(_family_key(unit.font), bold, italic)
    if path:
        try:
            f = pymupdf.Font(fontfile=path)
            if _has_all(f, text):
                return f, "system"
        except Exception:
            pass
    low = unit.font.lower()
    serif = bool(unit.flags & 4) or any(k in low for k in ("times", "serif", "georgia", "garamond", "cambria", "roman", "book", "minion", "palatino"))
    mono = bool(unit.flags & 8) or any(k in low for k in ("courier", "mono", "consolas"))
    base = "co" if mono else "ti" if serif else "he"
    code = {"he": ("helv", "hebo", "heit", "hebi"), "ti": ("tiro", "tibo", "tiit", "tibi"),
            "co": ("cour", "cobo", "coit", "cobi")}[base][(1 if bold else 0) + (2 if italic else 0)]
    return pymupdf.Font(code), "standard"


# ── applying edits ───────────────────────────────────────────────

def _wrap(words: list[str], font: pymupdf.Font, size: float, width: float) -> list[str]:
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if cur and font.text_length(trial, fontsize=size) > width:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def apply_edits(doc, units: list[Unit], edits: list[dict]) -> list[EditResult]:
    """Apply [{key, unit_ids, text}] to `doc` in place. Returns one result per edit."""
    by_id = {u.id: u for u in units}
    by_page: dict[int, list[Unit]] = {}
    for u in units:
        by_page.setdefault(u.page, []).append(u)

    plans, results = [], []
    for e in edits:
        key = str(e.get("key") or (e.get("unit_ids") or ["?"])[0])
        us = sorted((by_id[i] for i in e.get("unit_ids", []) if i in by_id), key=lambda u: (u.page, u.baseline, u.bbox[0]))
        text = re.sub(r"\s+", " ", (e.get("text") or "")).strip()
        if not us:
            results.append(EditResult(key, False, "This text could not be located on the page."))
            continue
        if len({u.page for u in us}) > 1:
            results.append(EditResult(key, False, "This paragraph continues on another page and cannot be re-wrapped in place."))
            continue
        page = doc[us[0].page]
        first = us[0]
        others = [u for u in by_page[first.page] if u not in us]
        pw = page.rect.width
        left_margin = min(u.bbox[0] for u in by_page[first.page])
        right_margin = max(u.bbox[2] for u in by_page[first.page])
        font, source = resolve_font(doc, page, first, text) if text else (pymupdf.Font("helv"), "standard")
        size = first.size
        draw: list[tuple[float, float, str, float]] = []      # (x, baseline, text, size)
        ok, reason, scale = True, "", 1.0

        if len(us) == 1:
            u = first
            same_row = [o for o in others if abs(o.baseline - u.baseline) < 3]
            lim_left = max([o.bbox[2] + 4 for o in same_row if o.bbox[2] <= u.bbox[0]], default=left_margin)
            lim_right = min([o.bbox[0] - 4 for o in same_row if o.bbox[0] >= u.bbox[2]], default=right_margin)
            centre = (u.bbox[0] + u.bbox[2]) / 2
            if abs(centre - pw / 2) < 4 and u.bbox[0] > left_margin + 12 and not same_row:
                align = "centre"
            elif abs(u.bbox[2] - right_margin) < 3 and u.bbox[0] > left_margin + 0.3 * (right_margin - left_margin):
                align = "right"
            else:
                align = "left"
            avail = (2 * min(centre - lim_left, lim_right - centre) if align == "centre"
                     else u.bbox[2] - lim_left if align == "right" else lim_right - u.bbox[0])
            width = font.text_length(text, fontsize=size) if text else 0
            if width > avail:
                scale = max(MIN_SCALE, avail / width)
                width = font.text_length(text, fontsize=size * scale)
                if width > avail + 0.5:
                    ok = False
                    reason = (f"Too long for this line in your layout by about {round((width / avail - 1) * 100)}%. "
                              "Shorten it, or it would run into the text beside it.")
            if ok and text:
                x = centre - width / 2 if align == "centre" else u.bbox[2] - width if align == "right" else u.bbox[0]
                draw.append((x, u.baseline, text, size * scale))
        else:
            x0 = min(u.bbox[0] for u in us)
            peers = [o.bbox[2] for o in others if abs(o.bbox[0] - x0) < 3]        # other lines at this indent
            x1 = max([u.bbox[2] for u in us] + peers)
            gap = (us[-1].baseline - us[0].baseline) / (len(us) - 1)
            below = min([o.bbox[1] for o in others if o.bbox[1] >= us[-1].bbox[3] - 1], default=page.rect.height - 18)
            for s in (1.0, 0.96, 0.92, MIN_SCALE):
                lines = _wrap(text.split(), font, size * s, x1 - x0)
                extra = len(lines) - len(us)
                last_bottom = us[-1].bbox[3] + max(0, extra) * gap * s
                if extra <= 0 or last_bottom <= below - 1:
                    scale = s
                    draw = [(x0, us[0].baseline + i * gap * (s if extra > 0 else 1.0), t, size * s) for i, t in enumerate(lines)]
                    break
            else:
                ok = False
                reason = (f"Needs {len(lines)} lines but your layout has room for {len(us)} here. "
                          "Shorten it, or there would be no space above the next line.")
        plans.append((key, us, draw, font, first.color, ok, reason, scale, source))

    # Remove the old text of every edit that fits, page by page, then write the new text.
    for pno in {us[0].page for _, us, _, _, _, ok, *_ in plans if ok}:
        page = doc[pno]
        for _, us, _, _, _, ok, *_ in plans:
            if ok and us[0].page == pno:
                for u in us:
                    x0, y0, x1, y1 = u.bbox
                    page.add_redact_annot(pymupdf.Rect(x0 - 0.3, y0 + 0.8, x1 + 0.3, y1 - 0.8), fill=False, cross_out=False)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
    for key, us, draw, font, color, ok, reason, scale, source in plans:
        if ok and draw:
            page = doc[us[0].page]
            tw = pymupdf.TextWriter(page.rect, color=color)
            for x, base, t, sz in draw:
                tw.append((x, base), t, font=font, fontsize=sz)
            tw.write_text(page)
        results.append(EditResult(key, ok, reason, round(scale, 3), source if ok else "", [us[0].page]))
    return results

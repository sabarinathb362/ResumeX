"""Phase 3: naive-parser view, simulated skim and VIQ on synthetic inputs."""
from types import SimpleNamespace as N

import pymupdf

from backend.ats2.attention import simulate_attention
from backend.ats2.impact import impact_quotient
from backend.ats2.parser_sim import simulate_parsers, _glyphs


def _two_column_pdf(path):
    doc = pymupdf.open()
    p = doc.new_page(width=612, height=792)
    p.insert_text((50, 50), "Asha Rao", fontsize=20)
    p.insert_text((50, 70), "asha.rao@example.com | +91 98765 43210", fontsize=9)
    for k, t in enumerate(["EXPERIENCE", "Backend Intern, Acme  Jun 2025 - Aug 2025", "Built a FastAPI invoice service.",
                           "Cut report time from 40 to 5 minutes.", "PROJECTS", "Raft KV store"]):
        p.insert_text((50, 110 + 16 * k), t, fontsize=10)
    for k, t in enumerate(["SKILLS", "Python, Go, Docker", "AWS, PostgreSQL", "EDUCATION", "B.Tech CSE 2026"]):
        p.insert_text((360, 110 + 16 * k), t, fontsize=10)
    doc.save(path)


def test_rows_view_exposes_column_interleaving(tmp_path):
    pdf = tmp_path / "r.pdf"
    _two_column_pdf(str(pdf))
    ref = "\n".join(["Asha Rao", "asha.rao@example.com | +91 98765 43210", "EXPERIENCE",
                     "Backend Intern, Acme Jun 2025 - Aug 2025", "Built a FastAPI invoice service.",
                     "Cut report time from 40 to 5 minutes.", "PROJECTS", "Raft KV store", "SKILLS",
                     "Python, Go, Docker", "AWS, PostgreSQL", "EDUCATION", "B.Tech CSE 2026"])
    rep = simulate_parsers(str(pdf), ref, {"email": "asha.rao@example.com", "phone": "+91 98765 43210"})
    rows = next(v for v in rep.views if v.name == "rows")
    assert rows.integrity < 0.95 and "Built a FastAPI invoice service. AWS, PostgreSQL" in rows.text
    assert all(c["found_in"]["stream"] for c in rep.field_checks)


def test_glyph_detector():
    kinds = {g["codepoint"] for g in _glyphs("Eﬃcient  icon �")}
    assert kinds == {"U+FB03", "U+E001", "U+FFFD"}


def test_skim_misses_strong_bullet_on_page_two_and_viq():
    lines = [N(id="a", page=0, bbox=[50, 35, 150, 52], text="Asha Rao", size=20, bold_ratio=1, role="contact"),
             N(id="b", page=0, bbox=[50, 100, 140, 112], text="EXPERIENCE", size=11, bold_ratio=1, role="heading"),
             N(id="c", page=0, bbox=[50, 116, 300, 128], text="Backend Intern, Acme", size=10, bold_ratio=1, role="title"),
             N(id="d", page=1, bbox=[50, 700, 330, 712], text="Cut report time from 40 to 5 minutes.", size=10, bold_ratio=0, role="statement")]
    # a realistic page holds ~50 lines competing for the same ~30 fixations
    lines += [N(id=f"f{i}", page=0, bbox=[50, 140 + 12 * i, 400, 150 + 12 * i], text="Maintained internal tooling for the team",
                size=10, bold_ratio=0, role="statement") for i in range(50)]
    st = N(id="s2", line_ids=["d"])
    resume = N(lines=lines, page_sizes=[[612, 792], [612, 792]], doc_sections=[N(entries=[N(statements=[st])])])
    g = N(id="s2", grade="A", line_ids=["d"], entry="Backend Intern", text="Cut report time from 40 to 5 minutes.",
          has_action=True, has_specific=True, has_metric=True, has_outcome=True, section="experience")
    att = simulate_attention(resume, [g])
    assert att.missed_strong and att.missed_strong[0]["statement_id"] == "s2"
    assert impact_quotient([g]).viq == 100.0

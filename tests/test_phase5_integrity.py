"""Phase 5: hidden text, timeline, GitHub check (mocked) and LaTeX/Typst source inspector."""
import base64
from datetime import date
from types import SimpleNamespace as N

import httpx
import pymupdf

from backend.integrity.github import API, check_github
from backend.integrity.stealth import scan_pdf
from backend.integrity.timeline import check_timeline, parse_range
from backend.ingestion.source_resume import inspect_source, resume_from_typst

TODAY = date(2026, 11, 12)


def _e(i, title, dates="", sub="", tags=(), stmts=()):
    return N(id=i, title=title, subtitle=sub, dates=dates, tags=list(tags), statements=[N(text=t) for t in stmts])


# ── hidden text ──────────────────────────────────────────────────

def test_hidden_text_found_and_visible_text_left_alone(tmp_path):
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_text((50, 50), "Asha Rao - Backend Engineer", fontsize=14)
    p.insert_text((50, 110), "python kubernetes terraform aws", fontsize=10, color=(1, 1, 1))
    p.insert_text((50, 140), "invisible keywords docker", fontsize=10, render_mode=3)
    p.insert_text((50, 170), "tiny react", fontsize=1)
    p.insert_text((50, 200), "Page 1 of 1", fontsize=9, color=(0.6, 0.6, 0.6))
    p.draw_rect(pymupdf.Rect(45, 215, 300, 235), color=None, fill=(0.1, 0.1, 0.1))
    p.insert_text((50, 230), "SKILLS (white on dark band)", fontsize=10, color=(1, 1, 1))
    p.insert_text((50, 260), "covered golang", fontsize=10)
    p.draw_rect(pymupdf.Rect(45, 248, 200, 265), color=None, fill=(1, 1, 1))
    path = tmp_path / "s.pdf"
    doc.save(str(path))

    rep = scan_pdf(str(path), jd_skills=["Python", "Kubernetes", "Docker", "Go"])
    reasons = {s.text: s.reasons for s in rep.spans}
    assert reasons["python kubernetes terraform aws"] == ["low_contrast"]
    assert reasons["invisible keywords docker"] == ["invisible"]
    assert reasons["tiny react"] == ["tiny"]
    assert reasons["covered golang"] == ["covered"]
    assert "Page 1 of 1" not in reasons and "SKILLS (white on dark band)" not in reasons
    assert {"Docker", "Kubernetes", "Python", "Go"} <= set(rep.hidden_jd_terms)


# ── timeline ─────────────────────────────────────────────────────

def test_timeline_findings():
    r = N(summary="", doc_sections=[
        N(kind="summary", entries=[_e("sum", "", stmts=["Backend engineer with 5+ years of experience building APIs."])]),
        N(kind="experience", entries=[
            _e("e1", "Software Engineer, Acme", "Jan 2025 – Present"),
            _e("e2", "Backend Engineer, Beta", "Jun 2024 – Mar 2025"),
            _e("e3", "Software Engineering Intern, Gamma", "May 2023 – Aug 2023"),
            _e("e4", "Developer, Delta", "Aug 2022 – Jun 2022"),
            _e("e5", "Consultant, Epsilon", "")]),
        N(kind="projects", entries=[_e("p1", "Raft KV store", "Dec 2026 – Feb 2027")]),
        N(kind="education", entries=[_e("ed", "B.Tech CSE", "2020 – Expected May 2026")]),
    ])
    out = check_timeline(r, today=TODAY)
    kinds = [(f["kind"], f["entry_ids"]) for f in out["findings"]]
    assert out["findings"][0]["severity"] == "error" and ("end_before_start", ["e4"]) in kinds
    assert ("overlap", ["e1", "e2"]) in kinds
    assert not any(k == "overlap" and "e3" in ids for k, ids in kinds)          # internship
    assert ("future", ["p1"]) in kinds and ("undated", ["e5"]) in kinds
    assert any(k == "years_claim" for k, _ in kinds)


def test_year_only_neighbours_are_not_flagged():
    r = N(summary="", doc_sections=[N(kind="experience", entries=[_e("a", "Engineer, A", "2020 - 2022"),
                                                                  _e("b", "Engineer, B", "2022 - 2024")])])
    assert check_timeline(r, today=TODAY)["findings"] == []
    assert parse_range("Summer 2024", TODAY)[:2] == (2024 * 12 + 5, 2024 * 12 + 7)
    assert parse_range("06/2022 - 03/2023", TODAY)[:2] == (2022 * 12 + 5, 2023 * 12 + 2)


# ── GitHub (mocked, no network) ──────────────────────────────────

def test_github_claims_checked_against_repo_evidence():
    resume = N(raw_text="", contact=N(github="https://github.com/asharao", links=[]), doc_sections=[
        N(kind="projects", entries=[
            _e("p1", "Invoice API | FastAPI, PostgreSQL, Redis", "Jan 2024 – Mar 2024",
               stmts=["Built a FastAPI service on PostgreSQL with Redis caching."]),
            _e("p2", "raft-kv", "Jun 2023", stmts=["Implemented leader election in Go; see github.com/asharao/raft-kv"]),
            _e("p3", "Secret ML project", stmts=["Trained models in PyTorch."])])])
    repos = [{"name": "invoice-api", "full_name": "asharao/invoice-api", "fork": False, "created_at": "2024-09-01T00:00:00Z",
              "description": "", "topics": ["fastapi"], "owner": {"login": "asharao"}},
             {"name": "raft-kv", "full_name": "asharao/raft-kv", "fork": True, "created_at": "2023-05-01T00:00:00Z",
              "description": "", "topics": [], "owner": {"login": "asharao"}}]
    req_txt = base64.b64encode(b"fastapi==0.115\npsycopg2-binary\n").decode()
    routes = {"/users/asharao/repos": repos,
              "/repos/asharao/invoice-api/languages": {"Python": 9000},
              "/repos/asharao/invoice-api/contents/": [{"name": "requirements.txt", "type": "file"}],
              "/repos/asharao/invoice-api/contents/requirements.txt": {"encoding": "base64", "content": req_txt},
              "/repos/asharao/raft-kv/languages": {"Go": 5000},
              "/repos/asharao/raft-kv/contents/": []}

    def handler(req):
        assert "resume" not in str(req.url).lower()
        return httpx.Response(200, json=routes[req.url.path]) if req.url.path in routes else httpx.Response(404, json={})

    rep = check_github(resume, client=httpx.Client(base_url=API, transport=httpx.MockTransport(handler)), today=TODAY)
    by = {p.entry_id: p for p in rep.projects}
    assert by["p1"].found == ["FastAPI", "PostgreSQL"] and by["p1"].not_found == ["Redis"]
    assert any("created 2024-09" in n for n in by["p1"].notes)
    assert by["p2"].match == "url" and any("fork" in n for n in by["p2"].notes)
    assert by["p3"].repo is None
    assert rep.cvi == 75.0


# ── LaTeX / Typst source ─────────────────────────────────────────

JAKE = r"""\documentclass[letterpaper,11pt]{article}
\input{glyphtounicode}
\pdfgentounicode=1
\newcommand{\resumeItem}[1]{\item\small{{#1 \vspace{-2pt}}}}
\newcommand{\resumeSubheading}[4]{\item \textbf{#1} & #2 \\ \textit{\small#3} & \textit{\small #4}}
\begin{document}
\section{Experience}
  \resumeSubHeadingListStart
    \resumeSubheading
      {Undergraduate Research Assistant}{June 2020 -- Present}
      {Texas A\&M University}{College Station, TX}
      \resumeItemListStart
        \resumeItem{Developed a REST API using FastAPI and PostgreSQL}
        \resumeItem{Cut query time by 40\% by adding indexes}
      \resumeItemListEnd
  \resumeSubHeadingListEnd
\section{Projects}
      \resumeProjectHeading
          {\textbf{Gitlytics} $|$ \emph{Python, Flask, React}}{June 2020 -- Present}
{\color{white} kubernetes terraform aws}
\phantom{hidden words}
{\fontsize{1pt}{1pt}\selectfont tiny stuffing}
\end{document}
"""


def test_latex_structure_and_hidden_text_with_line_numbers():
    secs, lines, rep = inspect_source(JAKE, "tex")
    exp = next(s for s in secs if s.kind == "experience")
    e = exp.entries[0]
    assert (e.title, e.subtitle, e.dates) == ("Undergraduate Research Assistant", "Texas A&M University", "June 2020 – Present")
    assert [st.line_ids for st in e.statements] == [["t13"], ["t14"]]
    assert e.statements[1].text == "Cut query time by 40% by adding indexes"
    proj = next(s for s in secs if s.kind == "projects").entries[0]
    assert proj.title == "Gitlytics" and proj.tags == ["Python", "Flask", "React"]
    hidden = {f.line: f.text for f in rep.findings if f.kind == "hidden_text"}
    assert hidden == {20: "kubernetes terraform aws", 21: "hidden words", 22: "tiny stuffing"}
    assert not any(f.kind == "unicode_map" for f in rep.findings)


def test_latex_without_glyphtounicode_and_typst():
    _, _, rep = inspect_source(r"\begin{document}\begin{multicols}{2}x\end{multicols}\end{document}", "tex")
    assert {f.kind for f in rep.findings} == {"unicode_map", "layout"}
    typ = "= Asha Rao\n== Experience\n*Backend Engineer*, Acme #h(1fr) Jun 2024 -- Present\n" \
          "- Cut p95 latency from 800ms to 120ms.\n#hide[kubernetes terraform]\n== Skills\n- Python, Go\n"
    rd, rep2 = resume_from_typst(typ, "r.typ")
    assert rd.contact.name == "Asha Rao"
    assert rd.experience[0].title == "Backend Engineer, Acme" and rd.experience[0].is_current
    assert rd.all_skills_flat == ["Python", "Go"]
    assert [(f.kind, f.line) for f in rep2.findings] == [("hidden_text", 5)]

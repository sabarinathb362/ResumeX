"""
Experiments for the ResumeX paper. Runs the real system code on the local resume corpus and writes
paper/experiments/results.json (aggregate numbers only, no resume text or contact details).

Run from the repo root:  python -m paper.experiments.run_experiments
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import statistics as st
import tempfile
import time
from collections import Counter
from pathlib import Path

import pymupdf

from backend.ingestion.pdf import extract_from_pdf
from backend.ats.rules import run_ats_analysis
from backend.readability.rri import run_rri
from backend.insights.engine import build_insights
from backend.ats2.attention import simulate_attention
from backend.ats2.impact import impact_quotient
from backend.ats2.parser_sim import simulate_parsers
from backend.integrity.stealth import scan_pdf
from backend.integrity.timeline import check_timeline
from backend.feedback.validator import validate_rewrite
from backend.editor.inplace import document_units, apply_edits

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "results.json"
random.seed(7)


def unique_pdfs() -> list[Path]:
    seen, out = set(), []
    for p in sorted((ROOT / "uploads").glob("*.pdf")):
        h = hashlib.md5(p.read_bytes()).hexdigest()
        if h not in seen:
            seen.add(h)
            out.append(p)
    return out


def timed(fn, *a, **k):
    t = time.perf_counter()
    r = fn(*a, **k)
    return r, (time.perf_counter() - t) * 1000


# ── E1: deterministic pipeline on the corpus ─────────────────────────────────────
def corpus_analysis(pdfs):
    rows, bullets = [], []
    for p in pdfs:
        data, t_parse = timed(extract_from_pdf, str(p))
        ats, t_ats = timed(run_ats_analysis, data)
        rri, t_rri = timed(run_rri, data, use_llm=False)
        ins, t_ins = timed(build_insights, data, ats, rri)
        att, t_att = timed(simulate_attention, data, rri.statements)
        viq, t_viq = timed(impact_quotient, rri.statements)
        ref = "\n".join(l.text for l in data.lines) or data.raw_text
        par, t_par = timed(simulate_parsers, str(p), ref, data.contact.model_dump())
        stealth, t_st = timed(scan_pdf, str(p))
        tl, t_tl = timed(check_timeline, data)
        grades = Counter(g.grade for g in rri.statements)
        rows.append({
            "pages": len(data.page_sizes), "lines": len(data.lines),
            "sections": len(data.doc_sections), "bullets": len(rri.statements),
            "ats": ats.overall_score, "ats_dims": {d.dimension: round(d.score / d.max_score, 3) for d in ats.category_scores},
            "rri": rri.overall_score,
            "rri_dims": {d.dimension: round(d.score / d.max_score, 3) for d in rri.dimensions},
            "viq": viq.viq, "viq_weighted": viq.viq_weighted,
            "grades": dict(grades), "findings": len(ins),
            "severity": dict(Counter(str(getattr(f.severity, "value", f.severity)) for f in ins)),
            "seen_share": att.seen_share, "seen_by_role": att.seen_by_role,
            "parser_integrity": {v.name: round(v.integrity, 3) for v in par.views},
            "glyph_issues": len(par.glyph_issues),
            "hidden_words": stealth.hidden_words,
            "timeline_issues": len(tl["findings"]),
            "latency_ms": {"parse": t_parse, "ats": t_ats, "rri": t_rri, "insights": t_ins,
                           "skim": t_att, "viq": t_viq, "parser_sim": t_par, "stealth": t_st, "timeline": t_tl},
        })
        for g in rri.statements:
            bullets.append({"text": g.text, "section": g.section, "grade": g.grade,
                            "action": g.has_action, "specific": g.has_specific,
                            "outcome": g.has_outcome, "metric": g.has_metric})
    return rows, bullets


# ── E2: fact-checker against controlled perturbations of real bullets ────────────
FAKE_TOOLS = ["Kubernetes", "Snowflake", "Terraform", "Kafka", "TensorFlow", "Salesforce", "Tableau", "Redis"]
LEADS = {"Developed": "Built", "Built": "Developed", "Designed": "Created", "Created": "Designed",
         "Implemented": "Delivered", "Led": "Directed", "Managed": "Oversaw"}


def perturbations(text: str):
    """Yield (kind, rewrite, should_pass)."""
    t = text.strip().rstrip(".")
    words = t.split()
    if len(words) < 5:
        return
    # faithful edits: verb swap, trimming, clause reorder, no new facts
    first = words[0].capitalize()
    yield "verb_swap", " ".join([LEADS.get(first, "Delivered")] + words[1:]), True
    yield "trim", " ".join(words[: max(5, int(len(words) * 0.75))]), True
    if "," in t:
        a, b = t.split(",", 1)
        yield "reorder", f"{b.strip().capitalize()}, {a[0].lower() + a[1:]}", True
    # unfaithful edits
    n = random.choice([12, 25, 40, 3, 150, 500])
    yield "add_percent", f"{t}, improving efficiency by {n}%", False
    yield "add_count", f"{t} for {n * 7} users", False
    nums = re.findall(r"\d+(?:\.\d+)?", t)
    if nums:
        x = nums[0]
        y = str(int(float(x) * 3 + 7))
        yield "inflate_number", t.replace(x, y, 1), False
    tool = next(x for x in random.sample(FAKE_TOOLS, len(FAKE_TOOLS)) if x.lower() not in t.lower())
    yield "add_tool", f"{t} using {tool}", False


def factcheck(bullets):
    res = Counter()
    per = {}
    for b in bullets:
        for kind, rw, ok in perturbations(b["text"]):
            v = validate_rewrite(b["text"], rw).is_valid
            per.setdefault(kind, Counter())["correct" if v == ok else "wrong"] += 1
            res[("pass" if ok else "fail", v)] += 1
    tp = res[("fail", False)]; fn = res[("fail", True)]
    tn = res[("pass", True)]; fp = res[("pass", False)]
    return {"tp": tp, "fn": fn, "tn": tn, "fp": fp,
            "recall_unfaithful": tp / max(1, tp + fn),
            "precision_reject": tp / max(1, tp + fp),
            "faithful_acceptance": tn / max(1, tn + fp),
            "per_kind": {k: {"correct": v["correct"], "total": v["correct"] + v["wrong"]} for k, v in per.items()}}


# ── E3: hidden-text detector against injected text ───────────────────────────────
INJECT = {
    "render_mode_3": dict(render_mode=3, fontsize=9, color=(0, 0, 0)),
    "white_on_white": dict(render_mode=0, fontsize=9, color=(1, 1, 1)),
    "tiny_font": dict(render_mode=0, fontsize=1.5, color=(0, 0, 0)),
    "near_white": dict(render_mode=0, fontsize=9, color=(0.97, 0.97, 0.97)),
    "off_page": dict(render_mode=0, fontsize=9, color=(0, 0, 0), off=True),
}


def stealth(pdfs):
    out = {}
    with tempfile.TemporaryDirectory() as td:
        base_fp = sum(1 for p in pdfs if scan_pdf(str(p)).hidden_words > 0)
        for name, kw in INJECT.items():
            hit = 0
            for i, p in enumerate(pdfs):
                doc = pymupdf.open(str(p))
                page = doc[0]
                pos = (page.rect.width + 40, 60) if kw.get("off") else (60, page.rect.height - 30)
                page.insert_text(pos, "Python Kubernetes TensorFlow AWS leadership", fontsize=kw["fontsize"],
                                 color=kw["color"], render_mode=kw["render_mode"])
                f = Path(td) / f"{name}_{i}.pdf"
                doc.save(str(f)); doc.close()
                r = scan_pdf(str(f))
                hit += int(any("kubernetes" in s.text.lower() and s.severity == "high" for s in r.spans))
            out[name] = {"detected": hit, "total": len(pdfs)}
        out["clean_false_positive_files"] = {"flagged": base_fp, "total": len(pdfs)}
    return out


# ── E4: in-place edit fit vs. length change ──────────────────────────────────────
def inplace(pdfs):
    ratios = [0.6, 0.8, 1.0, 1.1, 1.2, 1.3, 1.5, 1.8]
    out = {str(r): Counter() for r in ratios}
    lat = []
    for p in pdfs:
        doc = pymupdf.open(str(p))
        units = [u for u in document_units(doc) if len(u.text) >= 25]
        doc.close()
        sample = random.sample(units, min(12, len(units)))
        for r in ratios:
            for u in sample:
                words = u.text.split()
                target = max(3, round(len(words) * r))
                filler = (words * 3)[:target]
                doc = pymupdf.open(str(p))
                us = document_units(doc)
                t0 = time.perf_counter()
                res = apply_edits(doc, us, [{"key": "k", "unit_ids": [u.id], "text": " ".join(filler)}])[0]
                lat.append((time.perf_counter() - t0) * 1000)
                doc.close()
                out[str(r)]["ok" if res.ok else "fail"] += 1
                if res.ok and res.scale < 0.999:
                    out[str(r)]["scaled"] += 1
    return {"by_ratio": {k: dict(v) for k, v in out.items()}, "latency_ms_median": st.median(lat),
            "latency_ms_p95": sorted(lat)[int(0.95 * len(lat))]}


def main():
    pdfs = unique_pdfs()
    print(f"{len(pdfs)} unique resumes")
    rows, bullets = corpus_analysis(pdfs)
    print("E1 done")
    fc = factcheck(bullets)
    print("E2 done", fc["recall_unfaithful"], fc["faithful_acceptance"])
    sh = stealth(pdfs)
    print("E3 done", sh)
    ip = inplace(pdfs)
    print("E4 done")
    bullet_stats = {
        "n": len(bullets),
        "grades": dict(Counter(b["grade"] for b in bullets)),
        "flags": {k: sum(b[k] for b in bullets) for k in ("action", "specific", "outcome", "metric")},
        "by_section": {s: dict(Counter(b["grade"] for b in bullets if b["section"] == s))
                       for s in {b["section"] for b in bullets}},
    }
    OUT.write_text(json.dumps({"n_resumes": len(pdfs), "resumes": rows, "bullets": bullet_stats,
                               "factcheck": fc, "stealth": sh, "inplace": ip}, indent=2, default=str))
    print("wrote", OUT)


if __name__ == "__main__":
    main()

"""
Evaluate ResumeX job matching (and ATS / readability) on the public
cnamuangtoun/resume-job-description-fit test split.

Each row has resume_text, job_description_text and a label (No Fit / Potential Fit / Good Fit).
The resume text is flattened, so it is re-laid out into a simple one-column PDF and run through the
real ResumeX pipeline: PDF parser -> ATS rules -> readability -> JD parser -> hybrid matcher.

Run from the repo root:
    python -m paper.experiments.eval_hf_fit --n 300            # quick run (about 5-10 min)
    python -m paper.experiments.eval_hf_fit --n 0              # the whole test split (1,760 rows)
    python -m paper.experiments.eval_hf_fit --n 300 --ablate   # also: no embeddings, embedding-only

Writes paper/experiments/hf_fit_results.json and hf_fit_rows.csv (scores only, no resume text).
Note: if the fine-tuned encoder saw these resumes during training, its numbers are optimistic;
report the base-model ablation alongside it.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import statistics as st
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pymupdf

OUT = Path(__file__).resolve().parent
LABEL = {"No Fit": 0.0, "Potential Fit": 0.5, "Good Fit": 1.0}
HEADINGS = ["Professional Summary", "Summary", "Objective", "Experience", "Work History", "Work Experience",
            "Skills", "Education", "Highlights", "Accomplishments", "Certifications", "Projects",
            "Qualifications", "Additional Information", "Languages", "Interests"]
HEAD_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(sorted(map(re.escape, HEADINGS), key=len, reverse=True)) + r")(?=[A-Z0-9 :,-]|$)")


def to_lines(text: str) -> list[tuple[str, bool]]:
    """Flattened resume text -> [(line, is_heading)]: break before known headings and at sentence ends."""
    t = re.sub(r"[•●▪■◦‣►▶➢➤]", "\n", text or "")
    t = HEAD_RE.sub(lambda m: "\n\u0000" + m.group(1) + "\n", t)
    out = []
    for block in t.split("\n"):
        block = block.strip()
        if not block:
            continue
        if block.startswith("\u0000"):
            out.append((block[1:].strip().upper(), True))
            continue
        for s in re.split(r"(?<=[.!?;])\s+(?=[A-Z])", block):
            s = s.strip()
            if s:
                out.append(("- " + s if len(s.split()) >= 5 else s, False))
    return out


def make_pdf(lines: list[tuple[str, bool]], path: str) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 50
    for text, head in lines:
        size = 12 if head else 10
        font = "hebo" if head else "helv"
        width = 495
        # wrap manually so the parser sees real lines
        words, cur, rows = text.split(), "", []
        for w in words:
            cand = (cur + " " + w).strip()
            if pymupdf.get_text_length(cand, fontname=font, fontsize=size) > width and cur:
                rows.append(cur); cur = w
            else:
                cur = cand
        if cur:
            rows.append(cur)
        if head:
            y += 6
        for r in rows:
            if y > 800:
                page = doc.new_page(width=595, height=842); y = 50
            page.insert_text((50, y), r, fontname=font, fontsize=size)
            y += size * 1.35
    doc.save(path)
    doc.close()


def jd_lines(text: str) -> str:
    """The dataset's JDs are one paragraph; put each sentence on its own line, as a pasted JD would be."""
    t = re.sub(r"[•●▪■◦]", "\n", text or "")
    t = re.sub(r"(?<=[.!?;:])\s+(?=[A-Z0-9])", "\n", t)
    t = re.sub(r"(?<=[a-z0-9)])(?=[A-Z][a-z]+ )", "\n", t)       # glued items: "...SQLStrong exp..."
    return t


def auc(pos: list[float], neg: list[float]) -> float:
    """ROC-AUC via the Mann-Whitney statistic."""
    if not pos or not neg:
        return float("nan")
    allv = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    ranks, i = {}, 0
    while i < len(allv):
        j = i
        while j < len(allv) and allv[j][0] == allv[i][0]:
            j += 1
        for k in range(i, j):
            ranks[k] = (i + j + 1) / 2
        i = j
    rpos = sum(ranks[k] for k, (_, y) in enumerate(allv) if y == 1)
    return (rpos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def summarise(name: str, scores: list[float], labels: list[float]) -> dict:
    from scipy.stats import spearmanr, pearsonr
    scores = [float(s) for s in scores]
    if len(set(scores)) < 2:
        return {"variant": name, "n": len(scores), "note": "constant score, correlation undefined",
                "mean": round(scores[0], 2) if scores else None}
    by = defaultdict(list)
    for s, l in zip(scores, labels):
        by[l].append(s)
    return {
        "variant": name, "n": len(scores),
        "spearman": round(float(spearmanr(scores, labels).correlation), 4),
        "pearson": round(float(pearsonr(scores, labels)[0]), 4),
        "auc_good_vs_no": round(auc(by[1.0], by[0.0]), 4),
        "auc_fit_vs_no": round(auc(by[1.0] + by[0.5], by[0.0]), 4),
        "mean_by_label": {k: round(st.mean(v), 2) for k, v in sorted(by.items())},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300, help="rows to sample from the test split (0 = all)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ablate", action="store_true", help="also run without embeddings and embedding-only")
    args = ap.parse_args()

    from datasets import load_dataset
    from backend.ingestion.pdf import extract_from_pdf
    from backend.ats.rules import run_ats_analysis
    from backend.readability.rri import run_rri
    from backend.parsing.jd_parser import parse_jd
    from backend.matching.hybrid import run_hybrid_matching
    from backend.nlp import embeddings

    ds = load_dataset("cnamuangtoun/resume-job-description-fit", split="test")
    idx = list(range(len(ds)))
    if args.n:
        # stratified sample so every label is represented
        by = defaultdict(list)
        for i, l in enumerate(ds["label"]):
            by[l].append(i)
        rng = random.Random(args.seed)
        idx = []
        for l, ids in by.items():
            idx += rng.sample(ids, min(len(ids), round(args.n * len(ids) / len(ds))))
        idx.sort()
    print(f"{len(idx)} rows; embedding model available: {embeddings.is_available()}")

    rows, t0 = [], time.time()
    cache_resume: dict[int, tuple] = {}
    with tempfile.TemporaryDirectory() as td:
        for k, i in enumerate(idx):
            r = ds[i]
            key = hash(r["resume_text"])
            if key not in cache_resume:
                pdf = f"{td}/r{k}.pdf"
                make_pdf(to_lines(r["resume_text"]), pdf)
                data = extract_from_pdf(pdf)
                ats = run_ats_analysis(data)
                rri = run_rri(data, use_llm=False)
                cache_resume[key] = (data, ats.overall_score, rri.overall_score, len(data.doc_sections), len(rri.statements))
            data, ats_s, rri_s, n_sec, n_bul = cache_resume[key]
            jd = parse_jd(jd_lines(r["job_description_text"]))
            m = run_hybrid_matching(data, jd)
            dims = {d.dimension: d.score for d in m.dimension_scores}
            rows.append({"row": i, "label": r["label"], "y": LABEL[r["label"]], "match": m.overall_score,
                         "ats": ats_s, "rri": rri_s, "sections": n_sec, "bullets": n_bul,
                         "jd_requirements": len(jd.requirements), **{f"dim:{k}": v for k, v in dims.items()}})
            if (k + 1) % 25 == 0:
                print(f"  {k + 1}/{len(idx)}  {time.time() - t0:.0f}s")

        results = {"dataset": "cnamuangtoun/resume-job-description-fit (test)", "rows": len(rows),
                   "unique_resumes": len(cache_resume), "seconds": round(time.time() - t0, 1)}
        y = [r["y"] for r in rows]
        variants = [summarise("ResumeX full match score", [r["match"] for r in rows], y)]
        for dim in [k for k in rows[0] if k.startswith("dim:")]:
            variants.append(summarise(f"  dimension only: {dim[4:]}", [r[dim] for r in rows], y))

        if args.ablate:
            # (a) whole pipeline with the embedding model switched off (alias + taxonomy + rules only)
            orig = embeddings._get_model
            embeddings._get_model = lambda: None
            try:
                no_emb = []
                for r in rows:
                    ds_r = ds[r["row"]]
                    data = cache_resume[hash(ds_r["resume_text"])][0]
                    no_emb.append(run_hybrid_matching(data, parse_jd(jd_lines(ds_r["job_description_text"]))).overall_score)
                variants.append(summarise("Ablation: no embeddings (rules + aliases only)", no_emb, y))
            finally:
                embeddings._get_model = orig
            # (b) embedding cosine only, whole resume vs whole JD
            texts_r = [ds[r["row"]]["resume_text"][:4000] for r in rows]
            texts_j = [ds[r["row"]]["job_description_text"][:4000] for r in rows]
            a, b = embeddings.encode(texts_r), embeddings.encode(texts_j)
            if a is not None:
                a = a / np.linalg.norm(a, axis=1, keepdims=True); b = b / np.linalg.norm(b, axis=1, keepdims=True)
                variants.append(summarise("Ablation: embedding cosine only", list((a * b).sum(1)), y))

        results["variants"] = variants
        results["ats_mean"] = round(st.mean(r["ats"] for r in rows), 2)
        results["rri_mean"] = round(st.mean(r["rri"] for r in rows), 2)
        results["parse_failures_no_sections"] = sum(1 for r in rows if r["sections"] == 0)

    (OUT / "hf_fit_results.json").write_text(json.dumps(results, indent=2))
    with open(OUT / "hf_fit_rows.csv", "w", newline="", encoding="utf8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

"""
Step 3 — Task T2: requirement-by-requirement judge (feeds recommendations/jd.py).

Input format = exactly what _llm_judge() sends at runtime: {"requirements":[...], "evidence":[...]}.
Labels come from the teacher run TWICE (temperature 0.0 and 0.5). A requirement is kept only
when both runs agree on the verdict and every cited id was in the evidence pool. Requirements
the runs disagree on are dropped from BOTH the input and the target, so they stay consistent.

    python -m training.03_make_judge_data --limit 1500
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict

from training.common import DATA, Teacher, read_jsonl, rng, write_jsonl
from backend.llm.prompts import JD_REQUIREMENT_JUDGE_SYSTEM
from backend.feedback.taxonomy import grounded_canonicals
from backend.recommendations.jd import _content_words, _retrieve

VERDICTS = {"met", "partial", "transferable", "missing"}


def judge(teacher: Teacher, payload: dict, temperature: float) -> dict:
    out = teacher.chat_json(JD_REQUIREMENT_JUDGE_SYSTEM, json.dumps(payload, ensure_ascii=False),
                            temperature=temperature, max_tokens=900) or {}
    return {v.get("id"): v for v in out.get("verdicts", []) if isinstance(v, dict) and v.get("verdict") in VERDICTS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1500)
    ap.add_argument("--reqs", type=int, default=5, help="requirements per example")
    args = ap.parse_args()
    r = rng()
    teacher = Teacher()

    bullets = defaultdict(list)
    for b in read_jsonl(DATA / "bullets.jsonl"):
        bullets[b["group"]].append(b)
    reqs = defaultdict(list)
    for q in read_jsonl(DATA / "requirements.jsonl"):
        reqs[q["jd_id"]].append(q)
    pairs = {(p["resume_id"], p["jd_id"]): p for p in read_jsonl(DATA / "pairs.jsonl")}
    keys = list(pairs)
    r.shuffle(keys)

    out_rows, agree, total = [], 0, 0
    for resume_id, jd_id in keys[:args.limit]:
        bs, qs = bullets.get(resume_id, []), reqs.get(jd_id, [])
        if len(bs) < 3 or not qs:
            continue
        qs = r.sample(qs, min(args.reqs, len(qs)))
        stmts = [{"id": f"e{i}", "text": b["text"], "where": "Experience", "skills": grounded_canonicals(b["text"]),
                  "words": _content_words(b["text"])} for i, b in enumerate(bs[:40])]
        pool_ids = []
        req_items = []
        for j, q in enumerate(qs):
            hits = _retrieve(q["text"], grounded_canonicals(q["text"]), stmts, k=3)
            pool_ids += [h[1]["id"] for h in hits]
            req_items.append({"id": f"r{j}", "text": q["text"], "type": "required"})
        pool_ids = list(dict.fromkeys(pool_ids))
        for s in r.sample(stmts, min(3, len(stmts))):           # distractors: not every bullet is relevant
            if s["id"] not in pool_ids:
                pool_ids.append(s["id"])
        pool = [next(s for s in stmts if s["id"] == i) for i in pool_ids][:12]
        payload = {"requirements": req_items,
                   "evidence": [{"id": e["id"], "where": e["where"], "text": e["text"]} for e in pool]}
        a, b = judge(teacher, payload, 0.0), judge(teacher, payload, 0.5)
        valid = {e["id"] for e in pool}
        keep = []
        for q in req_items:
            va, vb = a.get(q["id"]), b.get(q["id"])
            total += 1
            if not va or not vb or va["verdict"] != vb["verdict"]:
                continue
            cited = [i for i in va.get("evidence_ids", []) if i in valid]
            if va["verdict"] in ("met", "partial", "transferable") and not cited:
                continue
            agree += 1
            keep.append((q, {"id": q["id"], "verdict": va["verdict"], "confidence": va.get("confidence", "med"),
                             "evidence_ids": cited, "rationale": (va.get("rationale") or "")[:200]}))
        if len(keep) < max(2, len(req_items) // 2):
            continue
        payload_kept = {"requirements": [q for q, _ in keep], "evidence": payload["evidence"]}
        out_rows.append({"task": "judge", "group": resume_id, "split": pairs[(resume_id, jd_id)]["split"],
                         "system": JD_REQUIREMENT_JUDGE_SYSTEM, "user": json.dumps(payload_kept, ensure_ascii=False),
                         "assistant": json.dumps({"verdicts": [v for _, v in keep]}, ensure_ascii=False),
                         "meta": {"label": pairs[(resume_id, jd_id)]["label"]}})
    print(f"teacher self-agreement {agree}/{total} = {agree / max(1, total):.0%}")
    print("kept", write_jsonl(DATA / "t2_judge.jsonl", out_rows))


if __name__ == "__main__":
    main()

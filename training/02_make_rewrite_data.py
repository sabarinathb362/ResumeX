"""
Step 2 — Task T1: grounded bullet rewrites (the editor co-pilot).

Every example uses the SAME system prompt and the SAME input keys the editor sends at
runtime (backend/feedback/grounded.py). A teacher rewrite is kept only if:
  1. validate_rewrite() passes — no new number, tool, company or claim (the runtime gate);
  2. the RRI rubric grades it at least as high as the original;
  3. it is one sentence of 8-40 words and actually differs from the input.
Rejected teacher outputs are saved too: they are ready-made "rejected" sides for DPO later.

Variants per bullet:
  plain       ORIGINAL only                          -> teaches "improve without inventing"
  user-facts  + a realistic USER_FACTS string        -> teaches "use the fact the user typed"
  jd-aligned  + a requirement from the matched JD    -> teaches "reuse JD wording only where true"

    set TEACHER_BASE_URL / TEACHER_MODEL, then:
    python -m training.02_make_rewrite_data --limit 4000
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict

from training.common import DATA, Teacher, read_jsonl, rng, write_jsonl
from backend.feedback.grounded import STREAM_REWRITE_SYSTEM, ANGLES, clean_line
from backend.feedback.validator import validate_rewrite
from backend.readability.rri import grade_statement
from backend.schemas.resume import Statement, DocEntry, DocSection

FACT_SYSTEM = """You invent ONE realistic, specific fact a candidate could truthfully add to the bullet below:
a number with a unit, a scale (users, records, requests), or a before/after. 5-14 words, no new tools.
Return JSON {"fact": "..."}."""


def grade(text: str) -> str:
    st = Statement(id="s", text=text)
    entry = DocEntry(id="e", title="", statements=[st])
    return grade_statement(st, DocSection(id="x", heading="Experience", kind="experience", entries=[entry]), entry, False).grade


def prompt(original: str, siblings: list[str], user_facts: str, jd_req: str, weaknesses: list[str], angle: str) -> str:
    # Keys and order mirror grounded._llm_prompt() exactly.
    return json.dumps({
        "ORIGINAL": original,
        "ENTRY_CONTEXT": {"title": "", "org_or_degree": "", "dates": "", "tools": [], "section": "Experience"},
        "SAME_ENTRY_BULLETS": siblings[:6],
        "USER_FACTS": user_facts,
        "TARGET_REQUIREMENT": jd_req,
        "WEAKNESSES": weaknesses,
        "STYLE": ANGLES[angle],
    }, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=4000, help="source bullets to process")
    ap.add_argument("--tries", type=int, default=2, help="teacher samples per variant")
    args = ap.parse_args()
    r = rng()
    teacher = Teacher()

    bullets = list(read_jsonl(DATA / "bullets.jsonl"))
    r.shuffle(bullets)
    by_group = defaultdict(list)
    for b in bullets:
        by_group[b["group"]].append(b["text"])
    reqs_by_jd = defaultdict(list)
    for q in read_jsonl(DATA / "requirements.jsonl"):
        reqs_by_jd[q["jd_id"]].append(q["text"])
    reqs_by_group = defaultdict(list)          # requirements of every JD this resume was paired with
    for pr in read_jsonl(DATA / "pairs.jsonl"):
        reqs_by_group[pr["resume_id"]].extend(reqs_by_jd.get(pr["jd_id"], []))

    kept, rejected, stats = [], [], defaultdict(int)
    for i, b in enumerate(bullets[:args.limit]):
        original = b["text"]
        g0 = grade(original)
        st = Statement(id="s", text=original)
        entry = DocEntry(id="e", statements=[st])
        weak = grade_statement(st, DocSection(id="x", heading="Experience", kind="experience", entries=[entry]),
                               entry, False).reasons
        siblings = [t for t in by_group[b["group"]] if t != original]
        r.shuffle(siblings)
        variants = [("plain", "", "", r.choice(["result-first", "tighter"]))]
        if r.random() < 0.35:
            f = teacher.chat_json(FACT_SYSTEM, original, temperature=0.9) or {}
            if f.get("fact"):
                variants.append(("user-facts", f["fact"].strip(), "", "result-first"))
        if reqs_by_group[b["group"]] and r.random() < 0.35:
            variants.append(("jd-aligned", "", r.choice(reqs_by_group[b["group"]]), "jd-aligned"))

        for kind, facts, jd_req, angle in variants:
            user = prompt(original, siblings[:3], facts, jd_req, weak, angle)
            ground = " ".join([original, *siblings[:3], facts])
            for _ in range(args.tries):
                out = clean_line(teacher.chat(STREAM_REWRITE_SYSTEM, user, temperature=0.7, max_tokens=120))
                words = len(out.split())
                v = validate_rewrite(original, out, ground, {facts} if facts else set())
                ok_len = 8 <= words <= 40 and out.lower() != original.lower()
                g1 = grade(out) if out else "D"
                if v.is_valid and ok_len and g1 <= g0:             # "A" < "B": better or equal grade
                    kept.append({"task": "rewrite", "variant": kind, "group": b["group"], "split": b["split"],
                                 "system": STREAM_REWRITE_SYSTEM, "user": user, "assistant": out,
                                 "meta": {"grade_before": g0, "grade_after": g1, "warnings": v.warnings,
                                          "original": original, "ground": ground, "facts": facts}})
                    stats[f"kept_{kind}"] += 1
                    break
                rejected.append({"user": user, "rejected": out, "problems": v.unsupported_facts,
                                 "reason": "validator" if not v.is_valid else "length" if not ok_len else "grade"})
                stats["rejected"] += 1
        if i % 100 == 0:
            print(i, dict(stats), flush=True)

    print("kept", write_jsonl(DATA / "t1_rewrite.jsonl", kept))
    print("rejected (DPO negatives)", write_jsonl(DATA / "t1_rewrite_rejected.jsonl", rejected))


if __name__ == "__main__":
    main()

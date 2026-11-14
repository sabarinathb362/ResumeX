"""
Step 4 — Task T3: STAR answer grading (mock interview).

Labels are reliable because they are set BEFORE the answer is written ("controlled
generation"): we sample a recipe such as {situation: specific, task: vague, action: specific,
result: absent}, ask the teacher to write an answer that follows it and to copy each part's
quote, then build the target from the recipe. A sample is kept only if every quote is a
verbatim substring of the answer, absent parts have no quote, and quantified parts contain a number.

    python -m training.04_make_star_data --limit 2500
"""
from __future__ import annotations

import argparse
import json
import re

from training.common import DATA, Teacher, read_jsonl, rng, write_jsonl, norm_space
from backend.llm.prompts import STAR_GRADER_SYSTEM
from backend.feedback.validator import validate_rewrite

LEVELS = ["absent", "vague", "generic", "specific", "quantified"]
LEVEL_SCORE = {"absent": 0, "vague": 3, "generic": 6, "specific": 8, "quantified": 10}
PARTS = ["situation", "task", "action", "result"]
WEIGHTS = {"situation": 0.15, "task": 0.15, "action": 0.35, "result": 0.35}
BEHAVIORAL = [
    "Tell me about a time you had to deliver under a tight deadline.",
    "Describe a technical decision you made that you later had to defend.",
    "Tell me about a time something you built broke. What did you do?",
    "Give an example of when you disagreed with a teammate on an approach.",
    "Tell me about a time you had to learn a new tool quickly to finish a task.",
    "Describe a time you improved something nobody asked you to improve.",
    "Tell me about a project where the requirements changed halfway through.",
    "Describe a time you had to explain a technical problem to a non-technical person.",
]
WRITER_SYSTEM = """You role-play a job candidate answering an interview question in the first person.
Follow RECIPE exactly. Levels: absent = do not mention this part at all; vague = one generic phrase;
generic = clear but no names or numbers; specific = names the system, constraint or people;
quantified = specific plus a number or a before/after. Base the story on RESUME_BULLET. You may add
plausible situational detail, but no numbers except in parts marked quantified. 60-160 words.
Return JSON {"answer": "...", "quotes": {"situation": "...", "task": "...", "action": "...", "result": "..."}}
where each quote is copied character-for-character from your answer ("" for absent parts)."""
STRONGER_SYSTEM = """Rewrite the interview answer as a clear STAR story in at most 120 words, first person.
Use ONLY facts from ANSWER and RESUME_EVIDENCE. Where a fact is missing write a [bracketed placeholder].
Return JSON {"stronger_answer": "..."}."""


def tip_for(levels: dict[str, str]) -> str:
    gap = max(PARTS, key=lambda p: WEIGHTS[p] * (10 - LEVEL_SCORE[levels[p]]))
    return {
        "result": "Finish with the result: what changed, by how much, and for whom.",
        "action": "Say what you personally did, step by step, instead of what the team did.",
        "task": "State your specific responsibility before describing the work.",
        "situation": "Open with one sentence of context: the system, the problem and the stakes.",
    }[gap]


def sample_recipe(r) -> dict[str, str]:
    while True:
        rec = {p: r.choices(LEVELS, weights=[2, 2, 3, 3, 2])[0] for p in PARTS}
        if rec["action"] != "absent" or r.random() < 0.2:
            return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2500)
    args = ap.parse_args()
    r = rng()
    teacher = Teacher()
    bullets = list(read_jsonl(DATA / "bullets.jsonl"))
    r.shuffle(bullets)

    rows, dropped = [], 0
    for b in bullets[:args.limit]:
        question = r.choice(BEHAVIORAL) if r.random() < 0.4 else \
            f'Walk me through this from your resume: "{b["text"]}" What was the situation and what did you do?'
        recipe = sample_recipe(r)
        gen = teacher.chat_json(WRITER_SYSTEM, json.dumps({"QUESTION": question, "RESUME_BULLET": b["text"],
                                                           "RECIPE": recipe}), temperature=0.8, max_tokens=500) or {}
        answer, quotes = norm_space(gen.get("answer", "")), gen.get("quotes") or {}
        ok = bool(answer)
        labels = {}
        for p in PARTS:
            q = norm_space(quotes.get(p, ""))
            if recipe[p] == "absent":
                ok &= q == ""
            else:
                ok &= bool(q) and q.lower() in answer.lower()
                if recipe[p] == "quantified":
                    ok &= bool(re.search(r"\d", q))
            labels[p] = {"present": recipe[p] != "absent", "quote": q, "score": LEVEL_SCORE[recipe[p]]}
        if not ok:
            dropped += 1
            continue
        stronger = (teacher.chat_json(STRONGER_SYSTEM, json.dumps({"ANSWER": answer, "RESUME_EVIDENCE": [b["text"]]}),
                                      temperature=0.3) or {}).get("stronger_answer", "")
        if stronger and not validate_rewrite(answer, stronger, b["text"]).is_valid:
            stronger = ""                                    # never teach the grader to invent facts
        target = {**labels, "tip": tip_for(recipe), "stronger_answer": norm_space(stronger)}
        user = json.dumps({"QUESTION": question, "ANSWER": answer, "RESUME_EVIDENCE": [b["text"]]}, ensure_ascii=False)
        rows.append({"task": "star", "group": b["group"], "split": b["split"], "system": STAR_GRADER_SYSTEM,
                     "user": user, "assistant": json.dumps(target, ensure_ascii=False), "meta": {"recipe": recipe}})
    print(f"kept {len(rows)}, dropped {dropped} (quote or recipe mismatch)")
    write_jsonl(DATA / "t3_star.jsonl", rows)


if __name__ == "__main__":
    main()

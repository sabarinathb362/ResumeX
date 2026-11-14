"""
Step 5 — merge the three tasks into chat-format SFT files.

  * user turns get the SAME untrusted-data wrapper the runtime adds (backend/llm/router.py)
  * splits come from the source resume hash, so no resume is in both train and test
  * task mix is capped so the rewrite task does not drown the other two

Outputs training/data/sft_{train,val,test}.jsonl with {"messages": [...], "task": ...}
"""
from __future__ import annotations

import argparse
from collections import Counter

from training.common import DATA, read_jsonl, rng, write_jsonl
from backend.llm.router import wrap_untrusted

FILES = {"rewrite": "t1_rewrite.jsonl", "judge": "t2_judge.jsonl", "star": "t3_star.jsonl"}


def to_chat(row: dict) -> dict:
    return {"task": row["task"], "group": row["group"], "meta": row.get("meta", {}),
            "messages": [{"role": "system", "content": row["system"]},
                         {"role": "user", "content": wrap_untrusted(row["user"])},
                         {"role": "assistant", "content": row["assistant"]}]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-rewrite", type=int, default=6000)
    ap.add_argument("--max-judge", type=int, default=1500)
    ap.add_argument("--max-star", type=int, default=2000)
    args = ap.parse_args()
    caps = {"rewrite": args.max_rewrite, "judge": args.max_judge, "star": args.max_star}
    r = rng()
    out = {"train": [], "val": [], "test": []}
    for task, fname in FILES.items():
        path = DATA / fname
        if not path.exists():
            print(f"skip {task}: {fname} not found")
            continue
        rows = list(read_jsonl(path))
        r.shuffle(rows)
        train = [x for x in rows if x["split"] == "train"][:caps[task]]
        for x in train:
            out["train"].append(to_chat(x))
        for x in rows:
            if x["split"] in ("val", "test"):
                out[x["split"]].append(to_chat(x))
    for split, rows in out.items():
        r.shuffle(rows)
        n = write_jsonl(DATA / f"sft_{split}.jsonl", rows)
        print(split, n, dict(Counter(x["task"] for x in rows)))


if __name__ == "__main__":
    main()

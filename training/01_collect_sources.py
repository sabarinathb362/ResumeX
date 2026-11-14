"""
Step 1 — collect raw material from public datasets (no user data).

Outputs (training/data/):
  bullets.jsonl       {id, group, text, split}                  achievement-like sentences from real resumes
  requirements.jsonl  {id, group, jd_id, text, split}           requirement sentences from real JDs
  pairs.jsonl         {group, resume_id, jd_id, label, split}   which resume was paired with which JD
  knowledge_base/skill_hypernyms.json  {"PostgreSQL": ["database management system software"], ...}  (if --onet)

Sources
  * cnamuangtoun/resume-job-description-fit  (8k pairs; 642 unique resumes, 280 unique JDs; no licence stated —
    use locally for research, do not redistribute the text)
  * O*NET "Technology Skills.txt" (CC BY 4.0), optional: --onet path/to/Technology\\ Skills.txt
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict

from training.common import DATA, group_split, norm_space, write_jsonl

VERB_START = re.compile(
    r"^(achieved|analy[sz]ed|architected|automated|built|collaborated|conducted|coordinated|created|cut|"
    r"delivered|deployed|designed|developed|drove|enhanced|established|evaluated|executed|expanded|"
    r"facilitated|generated|grew|handled|implemented|improved|increased|integrated|launched|led|maintained|"
    r"managed|mentored|migrated|monitored|negotiated|optimi[sz]ed|organi[sz]ed|oversaw|performed|planned|"
    r"prepared|processed|produced|reduced|refactored|resolved|reviewed|saved|scaled|served|set up|"
    r"streamlined|supervised|supported|tested|trained|wrote|worked on|responsible for|assisted|helped|"
    r"participated in|involved in)\b", re.I)
REQ_HINT = re.compile(
    r"\b(experience|knowledge|proficien|familiar|ability|skill|degree|bachelor|master|years?|"
    r"understanding|expertise|must|required|preferred|plus)\b", re.I)
SECTION_GLUE = re.compile(r"(Professional Summary|Summary|Experience|Skills|Education|Highlights|Accomplishments|"
                          r"Work History|Certifications|Projects)(?=[A-Z])")


def sentences(text: str) -> list[str]:
    """The dataset's resume text is flattened ("SummaryHighly motivated..."): re-insert breaks
    before glued section names, then split on sentence ends and bullet glyphs."""
    t = SECTION_GLUE.sub(". ", text or "")
    t = re.sub(r"[•●▪■◦‣►▶➢➤]", ". ", t)
    parts = re.split(r"(?<=[.!?;])\s+(?=[A-Z])|\s{2,}", t)
    return [norm_space(p).strip(" .;") for p in parts if p and p.strip()]


def bullet_like(s: str) -> bool:
    n = len(s.split())
    return 6 <= n <= 45 and bool(VERB_START.match(s)) and not re.search(r"@|https?://|\bphone\b", s, re.I)


def requirement_like(s: str) -> bool:
    n = len(s.split())
    return 4 <= n <= 40 and bool(REQ_HINT.search(s))


def hid(t: str) -> str:
    return hashlib.md5(t.encode("utf-8")).hexdigest()[:12]


def load_onet(path: str) -> dict[str, list[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    with open(path, encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            ex, title = row.get("Example", "").strip(), row.get("Commodity Title", "").strip().lower()
            if ex and title:
                out[ex].add(title)
    return {k: sorted(v) for k, v in out.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--onet", help="path to O*NET 'Technology Skills.txt' (tab-delimited)")
    ap.add_argument("--max-bullets-per-resume", type=int, default=25)
    args = ap.parse_args()

    from datasets import load_dataset
    ds = load_dataset("cnamuangtoun/resume-job-description-fit")
    rows = [r for split in ds.values() for r in split]

    bullets, reqs, pairs, seen_b, seen_r = [], [], [], set(), set()
    for r in rows:
        rid, jid = hid(r["resume_text"]), hid(r["job_description_text"])
        split = group_split(rid)
        pairs.append({"group": rid, "resume_id": rid, "jd_id": jid, "label": str(r["label"]).strip().lower(), "split": split})
        if rid not in seen_r:
            seen_r.add(rid)
            kept = 0
            for s in sentences(r["resume_text"]):
                if bullet_like(s) and kept < args.max_bullets_per_resume and hid(s) not in seen_b:
                    seen_b.add(hid(s))
                    bullets.append({"id": f"b{hid(s)}", "group": rid, "text": s, "split": split})
                    kept += 1
        for s in sentences(r["job_description_text"]):
            key = f"{jid}:{hid(s)}"
            if requirement_like(s) and key not in seen_b:
                seen_b.add(key)
                reqs.append({"id": f"q{hid(key)}", "group": rid, "jd_id": jid, "text": s, "split": split})

    print("bullets", write_jsonl(DATA / "bullets.jsonl", bullets))
    print("requirements", write_jsonl(DATA / "requirements.jsonl", reqs))
    print("pairs", write_jsonl(DATA / "pairs.jsonl", pairs))
    if args.onet:
        hyp = load_onet(args.onet)
        from training.common import ROOT
        # The validator's taxonomy loads this file at startup (feedback/taxonomy.py::_onet_hypernyms).
        (ROOT / "knowledge_base" / "skill_hypernyms.json").write_text(json.dumps(hyp, indent=1), encoding="utf-8")
        print("onet tools", len(hyp), "-> knowledge_base/skill_hypernyms.json")


if __name__ == "__main__":
    main()

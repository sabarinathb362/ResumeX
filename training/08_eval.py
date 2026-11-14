"""
Step 8 — compare the base model and your fine-tune ON THE DEPLOYED GGUF (through Ollama),
on the held-out test split. Ship only if every gate passes.

    python -m training.08_eval --base qwen3:4b-instruct-2507-q4_K_M --tuned resumex-copilot
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import time

import httpx

from training.common import DATA, read_jsonl
from backend.feedback.validator import validate_rewrite

GATES = {"rewrite_fabrication_rate": ("<=", 0.02), "json_valid_rate": (">=", 0.99),
         "judge_accuracy": (">=", 0.70), "star_presence_accuracy": (">=", 0.85)}
PARTS = ["situation", "task", "action", "result"]


def chat(client: httpx.Client, model: str, messages: list[dict], temperature: float) -> tuple[str, float]:
    t = time.time()
    r = client.post("/api/chat", json={"model": model, "messages": messages, "stream": False,
                                       "options": {"temperature": temperature, "num_ctx": 4096, "num_predict": 700}})
    r.raise_for_status()
    return r.json()["message"]["content"], time.time() - t


def parse_json(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0) if m else text)
    except json.JSONDecodeError:
        return None


def _unwrap(content: str) -> dict:
    return json.loads(content.split("<UNTRUSTED_DATA>\n", 1)[1].rsplit("\n</UNTRUSTED_DATA>", 1)[0])


def evaluate(model: str, rows: list[dict], client: httpx.Client) -> dict:
    m = {"rewrite_n": 0, "rewrite_fabricated": 0, "rewrite_one_line": 0, "json_n": 0, "json_ok": 0,
         "judge_n": 0, "judge_correct": 0, "judge_bad_cite": 0, "star_n": 0, "star_presence_ok": 0,
         "star_abs_err": [], "star_bad_quote": 0, "latency": []}
    for row in rows:
        prompt, gold = row["messages"][:2], row["messages"][2]["content"]
        task = row["task"]
        out, dt = chat(client, model, prompt, 0.3 if task == "rewrite" else 0.0)
        m["latency"].append(dt)
        if task == "rewrite":
            m["rewrite_n"] += 1
            line = out.strip().splitlines()[0] if out.strip() else ""
            m["rewrite_one_line"] += int(len(out.strip().splitlines()) == 1)
            meta = row["meta"]
            v = validate_rewrite(meta["original"], line, meta["ground"], {meta["facts"]} if meta.get("facts") else set())
            m["rewrite_fabricated"] += int(not v.is_valid)
            continue
        m["json_n"] += 1
        pred, ref = parse_json(out), json.loads(gold)
        if pred is None:
            continue
        m["json_ok"] += 1
        if task == "judge":
            valid = {e["id"] for e in _unwrap(prompt[1]["content"])["evidence"]}
            pv = {v.get("id"): v for v in pred.get("verdicts", []) if isinstance(v, dict)}
            for v in ref["verdicts"]:
                m["judge_n"] += 1
                p = pv.get(v["id"], {})
                m["judge_correct"] += int(p.get("verdict") == v["verdict"])
                m["judge_bad_cite"] += int(any(i not in valid for i in p.get("evidence_ids", [])))
        elif task == "star":
            answer = _unwrap(prompt[1]["content"])["ANSWER"]
            for part in PARTS:
                m["star_n"] += 1
                p, g = pred.get(part) or {}, ref[part]
                m["star_presence_ok"] += int(bool(p.get("present")) == g["present"])
                m["star_abs_err"].append(abs(float(p.get("score", 0) or 0) - g["score"]))
                q = (p.get("quote") or "").strip()
                m["star_bad_quote"] += int(bool(q) and q.lower() not in answer.lower())
    lat = sorted(m["latency"]) or [0]
    return {
        "rewrite_fabrication_rate": m["rewrite_fabricated"] / max(1, m["rewrite_n"]),
        "rewrite_one_line_rate": m["rewrite_one_line"] / max(1, m["rewrite_n"]),
        "json_valid_rate": m["json_ok"] / max(1, m["json_n"]),
        "judge_accuracy": m["judge_correct"] / max(1, m["judge_n"]),
        "judge_invalid_citation_rate": m["judge_bad_cite"] / max(1, m["judge_n"]),
        "star_presence_accuracy": m["star_presence_ok"] / max(1, m["star_n"]),
        "star_score_mae": statistics.fmean(m["star_abs_err"]) if m["star_abs_err"] else None,
        "star_invented_quote_rate": m["star_bad_quote"] / max(1, m["star_n"]),
        "latency_p50_s": lat[len(lat) // 2], "latency_p95_s": lat[min(len(lat) - 1, round(0.95 * (len(lat) - 1)))],
        "n": len(rows),
    }


QUALITY = {"poor": 1, "average": 2, "good": 3, "high": 3, "excellent": 4}


def spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    var = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return cov / var if var else 0.0


def eddcv_correlation(model: str, client: httpx.Client, limit: int = 200) -> dict:
    """Human-labelled answer quality (akshatshaw/eddcv, no licence stated: evaluation only)."""
    from datasets import load_dataset
    from backend.llm.prompts import STAR_GRADER_SYSTEM
    from backend.llm.router import wrap_untrusted
    WEIGHTS = {"situation": 0.15, "task": 0.15, "action": 0.35, "result": 0.35}
    rows = [r for split in load_dataset("akshatshaw/eddcv").values() for r in split]
    rows = [r for r in rows if str(r.get("Interview Phase", "")).lower() == "behavioral"
            and str(r.get("Answer Quality", "")).lower() in QUALITY][:limit]
    human, ours = [], []
    for r in rows:
        user = json.dumps({"QUESTION": r["Question"], "ANSWER": r["Answer"], "RESUME_EVIDENCE": []})
        out, _ = chat(client, model, [{"role": "system", "content": STAR_GRADER_SYSTEM},
                                      {"role": "user", "content": wrap_untrusted(user)}], 0.0)
        pred = parse_json(out) or {}
        score = sum(WEIGHTS[p] * float((pred.get(p) or {}).get("score", 0) or 0) for p in WEIGHTS)
        human.append(QUALITY[str(r["Answer Quality"]).lower()])
        ours.append(score)
    return {"eddcv_n": len(rows), "eddcv_spearman": round(spearman(ours, human), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eddcv", action="store_true", help="also correlate STAR scores with human quality labels")
    ap.add_argument("--base", required=True)
    ap.add_argument("--tuned", required=True)
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--ollama", default="http://localhost:11434")
    args = ap.parse_args()
    rows = list(read_jsonl(DATA / "sft_test.jsonl"))[:args.limit]
    client = httpx.Client(base_url=args.ollama, timeout=300)
    report = {name: evaluate(model, rows, client) for name, model in (("base", args.base), ("tuned", args.tuned))}
    if args.eddcv:
        for name, model in (("base", args.base), ("tuned", args.tuned)):
            report[name].update(eddcv_correlation(model, client))
    gates = {}
    for k, (op, thr) in GATES.items():
        val = report["tuned"][k]
        gates[k] = (val <= thr) if op == "<=" else (val >= thr)
    gates["no_worse_fabrication_than_base"] = report["tuned"]["rewrite_fabrication_rate"] <= report["base"]["rewrite_fabrication_rate"]
    report["gates"], report["ship"] = gates, all(gates.values())
    (DATA / "eval_report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()

"""
Re-train the ResumeX encoder on a LEAK-FREE split of cnamuangtoun/resume-job-description-fit.

Why: the dataset reuses each resume and job description across many rows, and its own train/test
splits share resumes. A model trained on "train" has already seen every "test" resume, so test scores
are inflated. Here the 8,000 pairs are grouped so that a resume or JD lives in exactly ONE split
(connected components of the resume-JD graph), then split ~80/10/10 into train / val / test.

Outputs
  backend/models/bge-small-resumex-v2/          the new model (the old one is left untouched)
  training/data/clean_split/{train,val,test}.jsonl   the split, for re-use by the evaluation
  training/data/clean_split/report.json         base vs old vs new encoder on the clean test set

Run (GPU strongly recommended: ~6 min on a Colab T4, hours on CPU):
  python -m training.train_encoder_clean
  python -m training.train_encoder_clean --epochs 2 --batch 16 --lr 2e-5
In Colab: upload the repo folder (or just this file), `pip install sentence-transformers datasets`,
then `python train_encoder_clean.py --out bge-small-resumex-v2` and download the output folder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LABEL = {"No Fit": 0.0, "Potential Fit": 0.5, "Good Fit": 1.0}
BASE = "BAAI/bge-small-en-v1.5"


def clip(t: str, n: int = 350) -> str:
    return " ".join((t or "").split()[:n])


def h(t: str) -> str:
    return hashlib.md5(" ".join((t or "").split()).encode("utf-8")).hexdigest()


def group_split(rows: list[dict], seed: int, frac=(0.8, 0.1, 0.1)) -> dict[str, list[dict]]:
    """Resume-disjoint split: all pairs of one resume go to the same split, so test resumes are never
    seen in training. (A split that is disjoint in BOTH resumes and JDs is impossible here: the
    resume-JD graph of this dataset is one connected component. JD overlap is reported instead.)"""
    groups = defaultdict(list)
    for r in rows:
        groups[r["rid"]].append(r)
    gs = list(groups.values())
    random.Random(seed).shuffle(gs)
    gs.sort(key=len, reverse=True)                    # place big components first, then fill greedily
    target = [f * len(rows) for f in frac]
    out = {"train": [], "val": [], "test": []}
    names = list(out)
    for g in gs:
        # put the group in the split that is furthest below its target share
        k = max(range(3), key=lambda i: (target[i] - len(out[names[i]])) / target[i])
        out[names[k]].extend(g)
    return out


def spearman(x, y):
    from scipy.stats import spearmanr
    return float(spearmanr(x, y).correlation)


def auc(pos, neg):
    from sklearn.metrics import roc_auc_score
    if not pos or not neg:
        return float("nan")
    return float(roc_auc_score([1] * len(pos) + [0] * len(neg), list(pos) + list(neg)))


def evaluate(model_name_or_path: str, rows: list[dict]) -> dict:
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(model_name_or_path)
    a = m.encode([clip(r["resume_text"]) for r in rows], normalize_embeddings=True, batch_size=32, show_progress_bar=False)
    b = m.encode([clip(r["job_description_text"]) for r in rows], normalize_embeddings=True, batch_size=32, show_progress_bar=False)
    c = (a * b).sum(1)
    y = [r["y"] for r in rows]
    pos = [v for v, t in zip(c, y) if t == 1.0]
    neg = [v for v, t in zip(c, y) if t == 0.0]
    fit = [v for v, t in zip(c, y) if t > 0]
    return {"model": model_name_or_path, "n": len(rows), "spearman": round(spearman(c, y), 4),
            "auc_good_vs_no": round(auc(pos, neg), 4), "auc_fit_vs_no": round(auc(fit, neg), 4),
            "cos_p5_p95_train_calibration": None}


def percentiles(model_path: str, rows: list[dict], k: int = 400, seed: int = 0) -> list[float]:
    from sentence_transformers import SentenceTransformer
    s = random.Random(seed).sample(rows, min(k, len(rows)))
    m = SentenceTransformer(model_path)
    a = m.encode([clip(r["resume_text"]) for r in s], normalize_embeddings=True, batch_size=32, show_progress_bar=False)
    b = m.encode([clip(r["job_description_text"]) for r in s], normalize_embeddings=True, batch_size=32, show_progress_bar=False)
    c = (a * b).sum(1)
    return [round(float(np.percentile(c, 5)), 3), round(float(np.percentile(c, 95)), 3)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "backend" / "models" / "bge-small-resumex-v2"))
    ap.add_argument("--split-dir", default=str(ROOT / "training" / "data" / "clean_split"))
    ap.add_argument("--old-model", default=str(ROOT / "backend" / "models" / "bge-small-resumex"))
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-train", type=int, default=0, help="limit training pairs (0 = all); for a quick smoke test")
    ap.add_argument("--split-only", action="store_true", help="write the split and stop")
    args = ap.parse_args()

    from datasets import load_dataset, concatenate_datasets
    ds = load_dataset("cnamuangtoun/resume-job-description-fit")
    full = concatenate_datasets([ds["train"], ds["test"]])
    rows = [{"resume_text": r["resume_text"], "job_description_text": r["job_description_text"],
             "label": r["label"], "y": LABEL[r["label"]], "rid": h(r["resume_text"]), "jid": h(r["job_description_text"])}
            for r in full]
    split = group_split(rows, args.seed)

    # sanity: no resume crosses splits
    for a in split:
        for b in split:
            if a < b:
                assert not ({r["rid"] for r in split[a]} & {r["rid"] for r in split[b]}), (a, b, "resume overlap")
    train_jds = {r["jid"] for r in split["train"]}
    unseen_jd_test = [r for r in split["test"] if r["jid"] not in train_jds]
    sd = Path(args.split_dir)
    sd.mkdir(parents=True, exist_ok=True)
    for name, part in split.items():
        with open(sd / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for r in part:
                f.write(json.dumps({k: r[k] for k in ("resume_text", "job_description_text", "label")}) + "\n")
        labels = defaultdict(int)
        for r in part:
            labels[r["label"]] += 1
        print(f"{name:5s} {len(part):5d} pairs  {len({r['rid'] for r in part}):4d} resumes  "
              f"{len({r['jid'] for r in part}):4d} JDs  {dict(labels)}")
    print("No resume appears in more than one split. "
          f"Test pairs whose JD is also unseen in training: {len(unseen_jd_test)}")
    with open(sd / "test_unseen_jd.jsonl", "w", encoding="utf-8") as f:
        for r in unseen_jd_test:
            f.write(json.dumps({k: r[k] for k in ("resume_text", "job_description_text", "label")}) + "\n")
    if args.split_only:
        return

    from datasets import Dataset
    from sentence_transformers import SentenceTransformer, SentenceTransformerTrainer, SentenceTransformerTrainingArguments
    from sentence_transformers.losses import CoSENTLoss
    from sentence_transformers.evaluation import EmbeddingSimilarityEvaluator

    def to_ds(part):
        return Dataset.from_dict({"sentence1": [clip(r["job_description_text"]) for r in part],
                                  "sentence2": [clip(r["resume_text"]) for r in part],
                                  "score": [r["y"] for r in part]})

    train = split["train"] if not args.max_train else random.Random(args.seed).sample(split["train"], args.max_train)
    model = SentenceTransformer(BASE)
    model.max_seq_length = 512
    val_eval = EmbeddingSimilarityEvaluator([clip(r["job_description_text"]) for r in split["val"]],
                                            [clip(r["resume_text"]) for r in split["val"]],
                                            [r["y"] for r in split["val"]], name="val")
    targs = SentenceTransformerTrainingArguments(
        output_dir=str(sd / "checkpoints"), num_train_epochs=args.epochs, per_device_train_batch_size=args.batch,
        learning_rate=args.lr, warmup_ratio=0.1, eval_strategy="epoch", save_strategy="no", logging_steps=50,
        seed=args.seed, report_to="none", fp16=_has_cuda())
    trainer = SentenceTransformerTrainer(model=model, args=targs, train_dataset=to_ds(train),
                                         eval_dataset=to_ds(split["val"]), loss=CoSENTLoss(model), evaluator=val_eval)
    trainer.train()
    model.save(args.out)
    print("saved", args.out)

    # ── report on the clean test split ──
    report = {"split": {k: len(v) for k, v in split.items()}, "test": []}
    for name in [BASE, args.old_model, args.out]:
        if name != BASE and not Path(name).exists():
            continue
        r = evaluate(name, split["test"])
        r["note"] = {BASE: "never saw this dataset",
                     args.old_model: "old fine-tune: may have seen these resumes during training (leaky)",
                     args.out: "new fine-tune: test resumes and JDs never seen"}[name]
        report["test"].append(r)
        print(json.dumps(r))
        if len(unseen_jd_test) >= 30:
            u = evaluate(name, unseen_jd_test)
            u["note"] = "subset: resume AND job description unseen in training"
            report["test"].append(u)
            print(json.dumps(u))
    report["calibration_for_config"] = {
        "match_semantic_cos_low/high (p5, p95 on clean train, new model)": percentiles(args.out, split["train"])}
    (sd / "report.json").write_text(json.dumps(report, indent=2))
    print("report:", sd / "report.json")


def _has_cuda() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


if __name__ == "__main__":
    main()

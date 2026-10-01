# pip install -U sentence-transformers datasets accelerate
import hashlib, json, torch
from datasets import load_dataset, Dataset
from sentence_transformers import (SentenceTransformer, SentenceTransformerTrainer,
                                   SentenceTransformerTrainingArguments, losses)
from sentence_transformers.evaluation import EmbeddingSimilarityEvaluator

BASE, OUT = "BAAI/bge-small-en-v1.5", "models/bge-small-resumex"
LABEL = {"good fit": 1.0, "potential fit": 0.5, "no fit": 0.0}

raw = load_dataset("cnamuangtoun/resume-job-description-fit")
rows = [r for split in raw.values() for r in split]
cols = list(rows[0].keys())
rc = next(c for c in cols if "resume" in c.lower())
jc = next(c for c in cols if "job" in c.lower())
print("Using columns:", rc, jc, "label")

def clip(t, n=350):
    return " ".join(str(t).split()[:n])

splits = {"train": [], "val": [], "test": []}
for r in rows:
    lab = r["label"]
    if not isinstance(lab, str):
        raise ValueError("Label is not a string; check dataset label names and edit LABEL")
    bucket = int(hashlib.md5(r[rc].encode()).hexdigest(), 16) % 10   # group split by resume
    key = "test" if bucket == 0 else "val" if bucket == 1 else "train"
    splits[key].append({"sentence1": clip(r[jc]), "sentence2": clip(r[rc]),
                        "score": LABEL[lab.strip().lower()]})

# Add your KB skill pairs so skill-level similarity also improves
kb = json.load(open("knowledge_base/skill_relationships.json"))
for item in kb.get("skill_relationships", []):
    for rel in item.get("related", []):
        splits["train"].append({"sentence1": item["source_skill"], "sentence2": rel["skill"],
                                "score": float(rel.get("transferability", 0.7))})

train, val, test = (Dataset.from_list(splits[k]) for k in ("train", "val", "test"))
model = SentenceTransformer(BASE)
model.max_seq_length = 512

def evaluator(ds, name):
    return EmbeddingSimilarityEvaluator(ds["sentence1"], ds["sentence2"], ds["score"], name=name)

print("Before:", evaluator(test, "test")(model))

args = SentenceTransformerTrainingArguments(
    output_dir="outputs/embedder", num_train_epochs=2, per_device_train_batch_size=16,
    learning_rate=2e-5, warmup_ratio=0.1, fp16=torch.cuda.is_available(),
    eval_strategy="epoch", save_strategy="no", logging_steps=50, seed=42,
)
trainer = SentenceTransformerTrainer(model=model, args=args, train_dataset=train,
                                     eval_dataset=val, loss=losses.CoSENTLoss(model),
                                     evaluator=evaluator(val, "val"))
trainer.train()
print("After:", evaluator(test, "test")(model))
model.save(OUT)
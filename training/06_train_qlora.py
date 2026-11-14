"""
Step 6 — QLoRA fine-tune on an 8 GB RTX 4060 (run in WSL2 Ubuntu; see requirements-train.txt).

    python -m training.06_train_qlora                                   # Qwen3-4B-Instruct-2507 (default)
    python -m training.06_train_qlora --base unsloth/Qwen2.5-7B-Instruct --max-len 1536 --batch 1 --accum 16

4-bit base + LoRA + gradient checkpointing keeps a 4B model inside 8 GB at 2k context.
If you hit OOM, lower --max-len first, then --batch.
"""
from __future__ import annotations

import argparse
import inspect
import json
import os

# Unsloth must be imported before transformers/trl so its patches apply.
from unsloth import FastLanguageModel, is_bfloat16_supported
from unsloth.chat_templates import train_on_responses_only
from datasets import load_dataset
from trl import SFTConfig, SFTTrainer
from transformers import EarlyStoppingCallback

DATA = os.path.join(os.path.dirname(__file__), "data")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="unsloth/Qwen3-4B-Instruct-2507")
    ap.add_argument("--out", default="outputs/resumex-copilot")
    ap.add_argument("--max-len", type=int, default=2048)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--accum", type=int, default=8)          # effective batch 16
    args = ap.parse_args()

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base, max_seq_length=args.max_len, dtype=None, load_in_4bit=True)
    model = FastLanguageModel.get_peft_model(
        model, r=args.rank, lora_alpha=args.rank, lora_dropout=0, bias="none",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth", random_state=3407)

    def render(batch):
        return {"text": [tokenizer.apply_chat_template(m, tokenize=False, add_generation_prompt=False)
                         for m in batch["messages"]]}

    ds = load_dataset("json", data_files={"train": f"{DATA}/sft_train.jsonl", "val": f"{DATA}/sft_val.jsonl"})
    ds = ds.map(render, batched=True, remove_columns=[c for c in ds["train"].column_names if c != "text"])

    # Arg names moved between TRL releases (max_seq_length -> max_length); pick what this install has.
    params = inspect.signature(SFTConfig.__init__).parameters
    seq_key = "max_length" if "max_length" in params else "max_seq_length"
    cfg = SFTConfig(**{
        seq_key: args.max_len,
        "dataset_text_field": "text", "packing": False,
        "per_device_train_batch_size": args.batch, "gradient_accumulation_steps": args.accum,
        "num_train_epochs": args.epochs, "learning_rate": args.lr, "warmup_ratio": 0.03,
        "lr_scheduler_type": "cosine", "optim": "adamw_8bit", "weight_decay": 0.01,
        "bf16": is_bfloat16_supported(), "fp16": not is_bfloat16_supported(),
        "logging_steps": 10, "eval_strategy": "steps", "eval_steps": 100, "save_strategy": "steps",
        "save_steps": 100, "save_total_limit": 2, "load_best_model_at_end": True,
        "metric_for_best_model": "eval_loss", "greater_is_better": False,
        "output_dir": args.out, "seed": 3407, "report_to": "none",
    })
    trainer = SFTTrainer(model=model, processing_class=tokenizer, train_dataset=ds["train"],
                         eval_dataset=ds["val"], args=cfg,
                         callbacks=[EarlyStoppingCallback(early_stopping_patience=3)])
    # Loss only on assistant tokens: the model learns to answer, not to echo prompts.
    trainer = train_on_responses_only(trainer, instruction_part="<|im_start|>user\n",
                                      response_part="<|im_start|>assistant\n")
    stats = trainer.train()
    print(json.dumps(stats.metrics, indent=1))

    model.save_pretrained(f"{args.out}/lora")
    tokenizer.save_pretrained(f"{args.out}/lora")
    # Merged GGUF for Ollama (Unsloth builds llama.cpp on first use; needs build-essential + cmake).
    model.save_pretrained_gguf(f"{args.out}/gguf", tokenizer, quantization_method="q4_k_m")
    print("GGUF written to", f"{args.out}/gguf")


if __name__ == "__main__":
    main()

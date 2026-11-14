"""
Step 7 — register the fine-tuned GGUF with Ollama, reusing the base model's chat TEMPLATE
(a hand-written template that drifts from training is the most common cause of garbage output).

    python -m training.07_export_ollama --gguf-dir outputs/resumex-copilot/gguf \
        --base qwen3:4b-instruct-2507-q4_K_M --name resumex-copilot
"""
from __future__ import annotations

import argparse
import glob
import os
import subprocess


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gguf-dir", required=True)
    ap.add_argument("--base", default="qwen3:4b-instruct-2507-q4_K_M")
    ap.add_argument("--name", default="resumex-copilot")
    ap.add_argument("--create", action="store_true", help="run `ollama create` after writing the Modelfile")
    args = ap.parse_args()

    ggufs = sorted(glob.glob(os.path.join(args.gguf_dir, "**", "*.gguf"), recursive=True), key=os.path.getsize)
    ggufs = [g for g in ggufs if "q4_k_m" in os.path.basename(g).lower()] or ggufs
    if not ggufs:
        raise SystemExit(f"no .gguf under {args.gguf_dir}")
    gguf = os.path.abspath(ggufs[-1])

    base = subprocess.run(["ollama", "show", args.base, "--modelfile"], capture_output=True, text=True, check=True).stdout
    drop = ("FROM ", "#", "PARAMETER temperature", "PARAMETER num_ctx")
    lines = [l for l in base.splitlines() if not l.startswith(drop)]
    modelfile = "\n".join([f"FROM {gguf}", *lines,
                           "PARAMETER temperature 0.2", "PARAMETER num_ctx 2048"]) + "\n"
    path = os.path.join(args.gguf_dir, "Modelfile")
    with open(path, "w", encoding="utf-8") as f:
        f.write(modelfile)
    print("wrote", path)
    cmd = ["ollama", "create", args.name, "-f", path]
    if args.create:
        subprocess.run(cmd, check=True)
    else:
        print("next:", " ".join(cmd))
    print(f'then set RESUMEIQ_LLM_FAST_MODEL={args.name} in backend/.env and restart the API')


if __name__ == "__main__":
    main()

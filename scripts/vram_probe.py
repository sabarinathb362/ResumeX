"""
Measure what each LLM tier really costs on YOUR GPU (run with Ollama running).

    python scripts/vram_probe.py
    python scripts/vram_probe.py qwen3:4b-instruct-2507-q4_K_M qwen2.5:7b-instruct-q4_K_M

Prints VRAM, total size (VRAM + CPU spill), generation speed and time to first token.
If "CPU spill" is above 0 GB the model did not fit and inference will be several times slower.
"""
import json
import sys
import time
import urllib.request

BASE = "http://localhost:11434"
PROMPT = "Rewrite this resume bullet in one sentence without adding facts: Worked on the invoice API using FastAPI."


def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"}, method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


def probe(model: str, ctx: int):
    t0 = time.time()
    out = call("/api/generate", {"model": model, "prompt": PROMPT, "stream": False, "keep_alive": "10m",
                                 "options": {"num_ctx": ctx, "num_predict": 80, "temperature": 0}})
    wall = time.time() - t0
    ps = call("/api/ps")
    m = next((x for x in ps.get("models", []) if x.get("name") == model or x.get("model") == model), None)
    vram = (m or {}).get("size_vram", 0) / 1e9
    total = (m or {}).get("size", 0) / 1e9
    tps = out["eval_count"] / max(1e-9, out["eval_duration"] / 1e9)
    ttft = (out.get("load_duration", 0) + out.get("prompt_eval_duration", 0)) / 1e9
    print(f"{model:40s} ctx={ctx:5d}  VRAM {vram:4.1f} GB  CPU spill {max(0, total - vram):4.1f} GB  "
          f"{tps:5.1f} tok/s  first token {ttft:4.2f} s  wall {wall:4.1f} s")


if __name__ == "__main__":
    fast = sys.argv[1] if len(sys.argv) > 1 else "qwen3:4b-instruct-2507-q4_K_M"
    deep = sys.argv[2] if len(sys.argv) > 2 else "qwen2.5:7b-instruct-q4_K_M"
    probe(fast, 2048)
    probe(deep, 4096)
    print("\nLoaded now:", [(m["name"], round(m["size_vram"] / 1e9, 1)) for m in call("/api/ps").get("models", [])])

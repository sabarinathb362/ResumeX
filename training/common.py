"""
Shared helpers for the ResumeX fine-tuning pipeline (run from the repo root):

    python -m training.01_collect_sources
    python -m training.02_make_rewrite_data   ...

Train and serve with IDENTICAL prompts: every system prompt here is imported from the
backend, so a change to a runtime prompt automatically changes the training data.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from pathlib import Path
from typing import Iterable, Iterator, Optional

import httpx

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "training" / "data"
DATA.mkdir(parents=True, exist_ok=True)
SEED = 3407


def read_jsonl(path: Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def group_split(key: str, val_pct: int = 5, test_pct: int = 5) -> str:
    """Deterministic split by a GROUP key (e.g. the source resume), so near-duplicate
    bullets from one resume never land in both train and test."""
    b = int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16) % 100
    return "test" if b < test_pct else "val" if b < test_pct + val_pct else "train"


def norm_space(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


class Teacher:
    """Any OpenAI-compatible chat endpoint: Ollama (http://localhost:11434/v1), vLLM,
    LM Studio, or a hosted open-weight model. Configure with env vars:
        TEACHER_BASE_URL, TEACHER_MODEL, TEACHER_API_KEY (optional)
    Only public dataset text is sent to the teacher — never a user's resume."""

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None,
                 api_key: Optional[str] = None, transport: Optional[httpx.BaseTransport] = None):
        self.base_url = (base_url or os.environ.get("TEACHER_BASE_URL", "http://localhost:11434/v1")).rstrip("/")
        self.model = model or os.environ.get("TEACHER_MODEL", "qwen2.5:7b-instruct-q4_K_M")
        key = api_key or os.environ.get("TEACHER_API_KEY", "")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        self.client = httpx.Client(base_url=self.base_url, headers=headers, timeout=180, transport=transport)

    def chat(self, system: str, user: str, *, temperature: float = 0.4, json_mode: bool = False,
             max_tokens: int = 700, retries: int = 3) -> str:
        body = {"model": self.model, "temperature": temperature, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        for attempt in range(retries):
            try:
                r = self.client.post("/chat/completions", json=body)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            except (httpx.HTTPError, KeyError, IndexError):
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)
        return ""

    def chat_json(self, system: str, user: str, **kw) -> Optional[dict]:
        text = self.chat(system, user, json_mode=True, **kw)
        m = re.search(r"\{.*\}", text, re.S)
        try:
            return json.loads(m.group(0) if m else text)
        except json.JSONDecodeError:
            return None


def rng() -> random.Random:
    return random.Random(SEED)

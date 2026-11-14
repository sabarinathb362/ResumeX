"""
Phase 7 — Local LLM Integration Client.
Connects to local Ollama / LLaMA.cpp with structured JSON output,
temperature 0 determinism, prompt injection delimiters, and graceful fallback.
"""
import json
import logging
import re
import time
import urllib.request
import urllib.error
from typing import Any, Optional, Type
from pydantic import BaseModel

from backend.config import settings

logger = logging.getLogger(__name__)


class LLMResponse:
    def __init__(self, content: str, model: str, raw_json: Optional[dict] = None, fallback_used: bool = False):
        self.content = content
        self.model = model
        self.raw_json = raw_json
        self.fallback_used = fallback_used

    def to_dict(self):
        return {
            "content": self.content,
            "model": self.model,
            "raw_json": self.raw_json,
            "fallback_used": self.fallback_used,
        }


class LocalLLMClient:
    """Client for local LLM inference via Ollama with schema constraints & graceful fallback."""

    def __init__(self):
        self.base_url = settings.ollama_base_url
        self.model = settings.llm_model
        self.fallback_model = settings.llm_fallback_model
        self.timeout = 30  # seconds (gracefully fall back if inference is too slow)
        self._online_cache: tuple[float, bool] = (0.0, False)

    def is_online(self) -> bool:
        """Check if local Ollama daemon is reachable (cached for 30 s so a batch of
        calls doesn't pay a 1.5 s probe each time)."""
        ts, val = self._online_cache
        if time.time() - ts < 30:
            return val
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                val = resp.status == 200
        except Exception:
            val = False
        self._online_cache = (time.time(), val)
        return val

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Optional[Type[BaseModel]] = None,
        temperature: float = 0.0,
        seed: int = 42,
        json_schema: Optional[dict] = None,
        tier: str = "deep",
    ) -> LLMResponse:
        """
        Invoke the local LLM. If Ollama is running, query it with format='json'.
        If Ollama is not running, return deterministic fallback response adhering to the schema.
        `tier` picks the model: "deep" (llm_model) or "fast" (llm_fast_model).
        """
        # Same wrapper as the async router, so fine-tuned models see one prompt format.
        from backend.llm.router import wrap_untrusted
        safe_user_prompt = wrap_untrusted(user_prompt)

        fast = tier == "fast"
        model = settings.llm_fast_model if fast else self.model
        timeout = settings.llm_fast_timeout_s if fast else settings.llm_deep_timeout_s
        payload = {
            "model": model,
            "keep_alive": settings.llm_fast_keep_alive if fast else settings.llm_deep_keep_alive,
            "system": system_prompt,
            "prompt": safe_user_prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "seed": seed,
            },
        }

        # Constrained decoding: Ollama >= 0.5 accepts a JSON schema in `format`,
        # so the model physically cannot emit off-schema output.
        schema = json_schema or (response_schema.model_json_schema() if response_schema else None)
        if schema:
            payload["format"] = schema
        payload["options"]["num_ctx"] = settings.llm_fast_ctx if fast else settings.llm_deep_ctx

        if self.is_online():
            try:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    f"{self.base_url}/api/generate",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    res_json = json.loads(resp.read().decode("utf-8"))
                    raw_text = res_json.get("response", "").strip()

                    parsed_json = None
                    if schema:
                        try:
                            clean_text = self._extract_json(raw_text)
                            parsed_json = json.loads(clean_text)
                        except Exception as parse_err:
                            logger.warning("Failed to parse JSON from LLM: %s. Raw: %s", parse_err, raw_text)

                    return LLMResponse(
                        content=raw_text,
                        model=model,
                        raw_json=parsed_json,
                        fallback_used=False,
                    )
            except Exception as e:
                logger.warning("Ollama query failed: %s. Using deterministic fallback.", e)

        # Graceful fallback when local daemon is not running
        return self._generate_fallback(system_prompt, user_prompt, response_schema)

    def _extract_json(self, text: str) -> str:
        """Strip markdown fences if model returned ```json ... ```."""
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            return match.group(1)
        match_arr = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if match_arr:
            return match_arr.group(1)
        return text

    def _generate_fallback(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Optional[Type[BaseModel]],
    ) -> LLMResponse:
        """LLM offline. Return NO content.

        The previous version returned a canned rewrite ("...improving operational
        throughput by 30%...") and a canned "met" verdict for every requirement.
        That is fabrication by construction and violated the plan's hard
        constraint, so callers must now handle raw_json=None and fall back to
        their own deterministic path.
        """
        return LLMResponse(content="", model="offline", raw_json=None, fallback_used=True)


_llm_client_instance = None

def get_llm_client() -> LocalLLMClient:
    global _llm_client_instance
    if _llm_client_instance is None:
        _llm_client_instance = LocalLLMClient()
    return _llm_client_instance

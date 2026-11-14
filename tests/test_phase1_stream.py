"""Phase 1: streaming suggestions validate each finished candidate and never leak fabricated ones."""
import asyncio
import json

import httpx

from backend.schemas.resume import ResumeData, DocSection, DocEntry, Statement
from backend.feedback.grounded import build_context, stream_llm_candidates, clean_line
from backend.llm.router import LLMRouter

RESUME = ResumeData(doc_sections=[DocSection(id="sec0", heading="Experience", kind="experience", entries=[
    DocEntry(id="e0", title="Backend Intern", subtitle="Acme", dates="Jun 2025 – Aug 2025", tags=["FastAPI"], statements=[
        Statement(id="s1", text="Worked on the invoice service using k8s."),
        Statement(id="s2", text="Cut report generation from 40 minutes to 5 minutes with PostgreSQL views.")])])])


def _ollama(outputs):
    it = iter(outputs)

    def handler(req: httpx.Request):
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:4b-instruct-2507-q4_K_M"},
                                                        {"name": "qwen2.5:7b-instruct-q4_K_M"}]})
        text = next(it)
        lines = [json.dumps({"message": {"content": w + " "}, "done": False}) for w in text.split()]
        return httpx.Response(200, content="\n".join(lines + [json.dumps({"done": True})]).encode())
    return httpx.MockTransport(handler)


def test_stream_validates_candidates():
    async def run():
        router = LLMRouter(base_url="http://ollama.test", transport=_ollama([
            "Deployed the FastAPI invoice service on Kubernetes during the Acme internship.",
            "Scaled the invoice service to 10k users on AWS."]))
        ctx = build_context(RESUME, "s1")
        events = [e async for e in stream_llm_candidates(ctx, router)]
        await router.aclose()
        return events
    events = asyncio.run(run())
    kinds = [e["event"] for e in events]
    assert kinds[0] == "status" and "token" in kinds
    cands = [e["data"] for e in events if e["event"] == "candidate"]
    rejected = [e["data"] for e in events if e["event"] == "rejected"]
    assert cands and "Kubernetes" in cands[0]["text"]
    assert rejected and any("AWS" in p for p in rejected[0]["problems"])


def test_current_text_is_used_and_original_stays_ground():
    ctx = build_context(RESUME, "s1", current_text="Deployed the invoice service on Kubernetes.")
    assert ctx.current.startswith("Deployed") and "Worked on" in ctx.ground
    assert "PostgreSQL" in ctx.ground          # same-entry sibling is ground truth
    assert clean_line('1. "Hello world"\nextra') == "Hello world"

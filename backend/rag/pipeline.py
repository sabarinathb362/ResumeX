"""
Retrieval-Augmented Generation for ResumeX.
retrieve -> format with chunk ids -> inject into LLM -> verify citations.
"""
import re
from typing import Optional
from backend.rag.retriever import get_retriever, RetrievedResult


def retrieve_context(bullet: str, jd_requirement: Optional[str] = None,
                     target_role: Optional[str] = None) -> list[RetrievedResult]:
    r = get_retriever()
    query = " ".join(x for x in [bullet, jd_requirement, target_role] if x)
    hits = r.search(query, collection="writing_guidance", top_k=2, rerank=True)
    if target_role:
        hits += r.search(f"{target_role} expected metrics tools anti-patterns",
                         collection="role_norms", top_k=1)
    if jd_requirement:
        hits += r.search(jd_requirement, collection="skill_relationships", top_k=1)
    seen, out = set(), []
    for h in hits:
        if h.chunk.chunk_id not in seen:
            seen.add(h.chunk.chunk_id)
            out.append(h)
    return out


def format_context(hits: list[RetrievedResult]) -> str:
    if not hits:
        return "(no reference guidance retrieved)"
    return "\n".join(f"[{h.chunk.chunk_id}] {h.chunk.text}" for h in hits)


def verify_citations(cited, hits: list[RetrievedResult]) -> list[str]:
    """Keep only ids that were actually retrieved (drops hallucinated citations)."""
    valid = {h.chunk.chunk_id for h in hits}
    if isinstance(cited, str):
        cited = re.findall(r"[\w.\-]+", cited)
    return [c for c in (cited or []) if c in valid]
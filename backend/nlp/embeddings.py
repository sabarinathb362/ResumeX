"""
Phase 5 — Embedding Service.

Provides semantic similarity via sentence-transformers (BGE-small-en-v1.5).
Lazy-loads the model on first use and caches it as a module-level singleton.
Falls back to word-overlap if the model cannot be loaded.
"""
import logging
import threading
from functools import lru_cache
from typing import Optional

import numpy as np

from backend.config import settings

logger = logging.getLogger(__name__)

# ── Module-level singleton ───────────────────────────────────────

_model = None
_model_lock = threading.Lock()
_model_failed = False


def _get_model():
    """Lazy-load the sentence-transformer model (thread-safe singleton)."""
    global _model, _model_failed
    if _model is not None:
        return _model
    if _model_failed:
        return None

    with _model_lock:
        # Double-check after acquiring lock
        if _model is not None:
            return _model
        if _model_failed:
            return None

        try:
            from sentence_transformers import SentenceTransformer
            import torch

            device = settings.embedding_device
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            model_name = settings.embedding_model

            logger.info(
                "Loading embedding model '%s' on device '%s'...",
                model_name, device,
            )
            from pathlib import Path
            name = model_name if ("/" in model_name or Path(model_name).exists()) else f"BAAI/{model_name}"
            _model = SentenceTransformer(name, device=device, trust_remote_code=False)
            logger.info("Embedding model loaded successfully.")
            return _model

        except Exception as e:
            logger.warning(
                "Failed to load embedding model: %s. "
                "Semantic matching will fall back to word overlap.",
                e,
            )
            _model_failed = True
            return None


def is_available() -> bool:
    """Check whether the embedding model is loaded and usable."""
    return _get_model() is not None


# ── Core primitives ─────────────────────────────────────────────


def encode(texts: list[str], batch_size: int = 64) -> Optional[np.ndarray]:
    """
    Encode a list of texts into dense vectors.

    Returns:
        np.ndarray of shape (len(texts), embed_dim) or None if unavailable.
    """
    model = _get_model()
    if model is None:
        return None
    if not texts:
        return np.empty((0, model.get_sentence_embedding_dimension()))

    return model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,  # BGE works best with normalized embeddings
    )


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    Compute cosine similarity between two L2-normalised vectors.
    Since we normalize on encode, this is just a dot product.
    """
    return float(np.dot(a, b))


def cosine_similarity_matrix(
    a: np.ndarray, b: np.ndarray,
) -> np.ndarray:
    """
    Compute pairwise cosine similarities between two sets of embeddings.

    Args:
        a: shape (m, d)
        b: shape (n, d)

    Returns:
        np.ndarray of shape (m, n)
    """
    return np.dot(a, b.T)


# ── Higher-level helpers ─────────────────────────────────────────


def _chunk_words(text, size=180, overlap=40):
    w = text.split()
    if len(w) <= size:
        return [" ".join(w)] if w else []
    return [" ".join(w[i:i + size]) for i in range(0, len(w) - overlap, size - overlap)]

def document_similarity(text_a: str, text_b: str) -> Optional[float]:
    """Chunk both docs; score = mean over B-chunks of best match in A (covers the full resume)."""
    a, b = _chunk_words(text_a), _chunk_words(text_b)
    if not a or not b:
        return 0.0
    ea, eb = encode(a), encode(b)
    if ea is None or eb is None:
        return None
    return float(cosine_similarity_matrix(eb, ea).max(axis=1).mean())


def chunk_similarities(
    query_chunks: list[str],
    corpus_chunks: list[str],
    top_k: int = 3,
) -> Optional[list[dict]]:
    """
    For each query chunk, find the top-k most similar corpus chunks.

    Returns:
        List of dicts with keys:
            query_idx, corpus_idx, similarity, query_text, corpus_text
        Sorted by similarity descending.
        Returns None if embeddings unavailable.
    """
    if not query_chunks or not corpus_chunks:
        return []

    q_embs = encode(query_chunks)
    c_embs = encode(corpus_chunks)
    if q_embs is None or c_embs is None:
        return None

    sim_matrix = cosine_similarity_matrix(q_embs, c_embs)

    results = []
    for qi in range(len(query_chunks)):
        top_indices = np.argsort(sim_matrix[qi])[::-1][:top_k]
        for ci in top_indices:
            results.append({
                "query_idx": qi,
                "corpus_idx": int(ci),
                "similarity": float(sim_matrix[qi, ci]),
                "query_text": query_chunks[qi][:120],
                "corpus_text": corpus_chunks[int(ci)][:120],
            })

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results


@lru_cache(maxsize=512)
def _skill_embedding_key(skill: str) -> str:
    """Cache key helper — just returns the lowered skill for caching."""
    return skill.strip().lower()


def skill_similarity(skill_a: str, skill_b: str) -> Optional[float]:
    """
    Compute semantic similarity between two skill names/phrases.

    Returns:
        Similarity in [0, 1] or None if embeddings unavailable.
    """
    embeddings = encode([skill_a, skill_b])
    if embeddings is None:
        return None
    return cosine_similarity(embeddings[0], embeddings[1])


def batch_skill_similarities(
    jd_skills: list[str],
    resume_skills: list[str],
    threshold: float = 0.65,
) -> Optional[list[dict]]:
    """
    For each JD skill, find the best-matching resume skill by embedding similarity.
    Only returns matches above the threshold.

    Returns:
        List of dicts with keys:
            jd_skill, resume_skill, similarity
        Returns None if embeddings unavailable.
    """
    if not jd_skills or not resume_skills:
        return []

    jd_embs = encode(jd_skills)
    res_embs = encode(resume_skills)
    if jd_embs is None or res_embs is None:
        return None

    sim_matrix = cosine_similarity_matrix(jd_embs, res_embs)

    results = []
    for ji in range(len(jd_skills)):
        best_idx = int(np.argmax(sim_matrix[ji]))
        best_sim = float(sim_matrix[ji, best_idx])
        if best_sim >= threshold:
            results.append({
                "jd_skill": jd_skills[ji],
                "resume_skill": resume_skills[best_idx],
                "similarity": round(best_sim, 4),
            })

    return results

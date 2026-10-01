"""
Phase 6 — RAG Knowledge Base & Retrieval System.
Provides hybrid semantic and lexical retrieval over role norms, skill taxonomies,
writing guidance, and project archetypes.
All retrieval carries traceable chunk IDs and collection metadata.
"""
import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Optional
import hashlib
from collections import Counter
import numpy as np

from backend.config import settings
from backend.nlp.embeddings import (
    is_available as is_embedding_available,
    encode,
    cosine_similarity,
)

logger = logging.getLogger(__name__)

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
_TOKEN_RE = re.compile(r"[a-z0-9_+#.-]+")
_STOP = {"the","a","an","and","or","of","to","in","for","with","on","is","are","by","as","at","be"}

def _tok(text):
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP]

def _ranks(scores):
    return {i: r for r, i in enumerate(sorted(scores, key=scores.get, reverse=True), 1)}

_reranker = None
def _get_reranker():
    global _reranker
    if _reranker is None:
        try:
            from sentence_transformers import CrossEncoder
            _reranker = CrossEncoder("BAAI/bge-reranker-base")
        except Exception as e:
            logger.warning("Reranker unavailable: %s", e)
            _reranker = False
    return _reranker or None

class KnowledgeChunk:
    def __init__(
        self,
        chunk_id: str,
        collection: str,
        title: str,
        text: str,
        metadata: Optional[dict] = None,
    ):
        self.chunk_id = chunk_id
        self.collection = collection
        self.title = title
        self.text = text
        self.metadata = metadata or {}
        self.embedding: Optional[list[float]] = None

    def to_dict(self):
        return {
            "chunk_id": self.chunk_id,
            "collection": self.collection,
            "title": self.title,
            "text": self.text,
            "metadata": self.metadata,
        }


class RetrievedResult:
    def __init__(self, chunk: KnowledgeChunk, score: float, match_type: str = "hybrid"):
        self.chunk = chunk
        self.score = round(score, 4)
        self.match_type = match_type

    def to_dict(self):
        return {
            "chunk_id": self.chunk.chunk_id,
            "collection": self.chunk.collection,
            "title": self.chunk.title,
            "text": self.chunk.text,
            "metadata": self.chunk.metadata,
            "score": self.score,
            "match_type": self.match_type,
        }


class KnowledgeRetriever:
    """Singleton hybrid retriever over the local knowledge base corpus."""

    _instance = None

    def __init__(self, kb_dir: Optional[Path] = None):
        self.kb_dir = kb_dir or settings.knowledge_base_dir
        self.chunks: list[KnowledgeChunk] = []
        self._load_corpus()

    @classmethod
    def get_instance(cls) -> "KnowledgeRetriever":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_corpus(self):
        """Loads and chunks all JSON files from the knowledge base directory."""
        self.chunks = []
        if not self.kb_dir.exists():
            logger.warning("Knowledge base directory %s does not exist", self.kb_dir)
            return

        # 1. Role norms
        role_norms_dir = self.kb_dir / "role_norms"
        if role_norms_dir.exists():
            for f in role_norms_dir.glob("*.json"):
                self._load_role_norms_file(f)

        # 2. Skill relationships
        skills_file = self.kb_dir / "skill_relationships.json"
        if skills_file.exists():
            self._load_skill_relationships(skills_file)

        # 3. Writing guidance
        writing_file = self.kb_dir / "writing_guidance.json"
        if writing_file.exists():
            self._load_writing_guidance(writing_file)

        # 4. Project archetypes
        projects_file = self.kb_dir / "project_archetypes.json"
        if projects_file.exists():
            self._load_project_archetypes(projects_file)

        logger.info("Loaded %d knowledge chunks into retriever corpus", len(self.chunks))
        self._build_index()

    def _load_role_norms_file(self, path: Path):
        try:
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            family = data.get("role_family", "General")
            for role in data.get("roles", []):
                role_id = role.get("id")
                canonical = role.get("canonical_title")
                aliases = role.get("aliases", [])
                levels = role.get("seniority_levels", {})

                for level_name, details in levels.items():
                    chunk_text = (
                        f"Role: {canonical} ({level_name.capitalize()} Level). "
                        f"Expected sections: {', '.join(details.get('expected_sections', []))}. "
                        f"Typical tools: {', '.join(details.get('typical_tools', []))}. "
                        f"Expected metrics: {', '.join(details.get('expected_metrics', []))}. "
                        f"Anti-patterns: {'; '.join(details.get('anti_patterns', []))}."
                    )
                    self.chunks.append(
                        KnowledgeChunk(
                            chunk_id=f"norm_{role_id}_{level_name}",
                            collection="role_norms",
                            title=f"{canonical} ({level_name.capitalize()} Norms)",
                            text=chunk_text,
                            metadata={
                                "role_family": family,
                                "role_id": role_id,
                                "role_title": canonical,
                                "aliases": aliases,
                                "seniority": level_name,
                            },
                        )
                    )
        except Exception as e:
            logger.error("Failed to load role norms from %s: %s", path, e)

    def _load_skill_relationships(self, path: Path):
        try:
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            for item in data.get("skill_relationships", []):
                source = item.get("source_skill")
                for rel in item.get("related", []):
                    target = rel.get("skill")
                    transfer = rel.get("transferability", 0.7)
                    rationale = rel.get("rationale", "")
                    chunk_text = (
                        f"Skill relationship: {source} relates to {target} "
                        f"({rel.get('relation')}, transferability {transfer:.0%}). "
                        f"Rationale: {rationale}"
                    )
                    self.chunks.append(
                        KnowledgeChunk(
                            chunk_id=f"skill_rel_{source.lower()}_{target.lower()}",
                            collection="skill_relationships",
                            title=f"Skill Link: {source} -> {target}",
                            text=chunk_text,
                            metadata={
                                "source_skill": source,
                                "target_skill": target,
                                "transferability": transfer,
                            },
                        )
                    )
        except Exception as e:
            logger.error("Failed to load skill relationships: %s", e)

    def _load_writing_guidance(self, path: Path):
        try:
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            for g in data.get("guidelines", []):
                chunk_text = f"{g.get('title')}: {g.get('summary')} {g.get('explanation')}"
                if g.get("good_example"):
                    chunk_text += f" Good example: {g.get('good_example')}"
                self.chunks.append(
                    KnowledgeChunk(
                        chunk_id=g.get("id"),
                        collection="writing_guidance",
                        title=g.get("title"),
                        text=chunk_text,
                        metadata={"category": g.get("category")},
                    )
                )
        except Exception as e:
            logger.error("Failed to load writing guidance: %s", e)

    def _load_project_archetypes(self, path: Path):
        try:
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            for proj in data.get("project_archetypes", []):
                chunk_text = (
                    f"Project: {proj.get('title')} (Difficulty: {proj.get('difficulty')}). "
                    f"Gap skills addressed: {', '.join(proj.get('gap_skills', []))}. "
                    f"Suggested stack: {', '.join(proj.get('suggested_stack', []))}. "
                    f"Deliverables: {'; '.join(proj.get('deliverables', []))}. "
                    f"Resume bullet template: {proj.get('resume_bullet_template')}"
                )
                self.chunks.append(
                    KnowledgeChunk(
                        chunk_id=proj.get("id"),
                        collection="project_archetypes",
                        title=proj.get("title"),
                        text=chunk_text,
                        metadata={
                            "difficulty": proj.get("difficulty"),
                            "gap_skills": proj.get("gap_skills", []),
                            "suggested_stack": proj.get("suggested_stack", []),
                        },
                    )
                )
        except Exception as e:
            logger.error("Failed to load project archetypes: %s", e)

    def _build_index(self):
        self._toks = [_tok(c.title + " " + c.text) for c in self.chunks]
        self._tf = [Counter(t) for t in self._toks]
        n = len(self.chunks)
        df = Counter(t for toks in self._toks for t in set(toks))
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        self._avgdl = sum(map(len, self._toks)) / max(n, 1)
        self._emb = None
        if not n or not is_embedding_available():
            return
        sig = hashlib.md5((settings.embedding_model + "".join(
            c.chunk_id + c.text for c in self.chunks)).encode()).hexdigest()
        cache = self.kb_dir / ".kb_embeddings.npz"
        try:
            if cache.exists():
                data = np.load(cache)
                if str(data["sig"]) == sig:
                    self._emb = data["emb"]
        except Exception:
            pass
        if self._emb is None:
            self._emb = encode([c.text for c in self.chunks])   # one batched call
            try:
                np.savez(cache, emb=self._emb, sig=np.array(sig))
            except Exception as e:
                logger.debug("Could not cache KB embeddings: %s", e)

    def _bm25(self, q_tokens, i, k1=1.5, b=0.75):
        tf, dl, s = self._tf[i], len(self._toks[i]), 0.0
        for t in q_tokens:
            f = tf.get(t, 0)
            if f:
                s += self._idf.get(t, 0) * f * (k1 + 1) / (f + k1 * (1 - b + b * dl / self._avgdl))
        return s

    def search(self, query, collection=None, top_k=5, min_score=0.1, rerank=False):
        if not query or not query.strip():
            return []
        idx = [i for i, c in enumerate(self.chunks) if not collection or c.collection == collection]
        if not idx:
            return []
        q_tokens = _tok(query)
        bm = {i: self._bm25(q_tokens, i) for i in idx}
        bm_max = max(bm.values()) or 1.0

        sem = {}
        if self._emb is not None:
            qv = encode([BGE_QUERY_PREFIX + query.strip()])[0]
            sem = {i: float(s) for i, s in zip(idx, self._emb[idx] @ qv)}

        # Reciprocal Rank Fusion: robust to the two scores being on different scales
        K, fused = 60, Counter()
        for i, r in _ranks(bm).items():
            fused[i] += 1 / (K + r)
        for i, r in _ranks(sem).items():
            fused[i] += 1 / (K + r)

        cand = [i for i in sorted(fused, key=fused.get, reverse=True)
                if bm[i] > 0 or sem.get(i, 0) >= 0.45][:max(top_k * 4, 20)]

        if rerank and cand and (ce := _get_reranker()):
            scores = ce.predict([(query, self.chunks[i].text) for i in cand])
            cand = [i for _, i in sorted(zip(scores, cand), key=lambda x: -x[0])]

        out = []
        for i in cand:
            score = (0.65 * sem[i] + 0.35 * bm[i] / bm_max) if sem else bm[i] / bm_max
            if score >= min_score:
                out.append(RetrievedResult(self.chunks[i], score, "hybrid" if sem else "lexical"))
            if len(out) == top_k:
                break
        return out

def get_retriever() -> KnowledgeRetriever:
    return KnowledgeRetriever.get_instance()

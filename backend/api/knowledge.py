"""
API routes — Knowledge base & RAG search (Phase 6).
GET /api/knowledge/search
"""
from typing import Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from backend.rag.retriever import get_retriever

router = APIRouter(prefix="/api/knowledge", tags=["Knowledge Base"])


class SearchResultItem(BaseModel):
    chunk_id: str
    collection: str
    title: str
    text: str
    metadata: dict = Field(default_factory=dict)
    score: float
    match_type: str


class SearchResponse(BaseModel):
    query: str
    collection_filter: Optional[str] = None
    count: int
    results: list[SearchResultItem]


@router.get("/search", response_model=SearchResponse, summary="Hybrid RAG Search")
def search_knowledge(
    q: str = Query(..., description="Query string for search"),
    collection: Optional[str] = Query(None, description="Optional collection filter: role_norms, skill_relationships, writing_guidance, project_archetypes"),
    limit: int = Query(5, ge=1, le=20, description="Max results to return"),
):
    retriever = get_retriever()
    results = retriever.search(query=q, collection=collection, top_k=limit)
    return SearchResponse(
        query=q,
        collection_filter=collection,
        count=len(results),
        results=[r.to_dict() for r in results],
    )

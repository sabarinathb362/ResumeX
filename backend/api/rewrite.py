"""
API routes — Grounded Rewriting (Phase 8).
POST /api/rewrite
"""
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.feedback.rewriter import generate_bullet_rewrites, RewriteResponse

router = APIRouter(prefix="/api/rewrite", tags=["Rewrite"])


class RewriteRequest(BaseModel):
    original_bullet: str
    resume_context: Optional[str] = ""
    jd_requirement: Optional[str] = None
    user_supplied_metric: Optional[str] = None


@router.post("", response_model=RewriteResponse, summary="Generate factually validated bullet rewrites")
def rewrite_bullet(req: RewriteRequest):
    if not req.original_bullet.strip():
        raise HTTPException(400, "original_bullet cannot be empty")

    return generate_bullet_rewrites(
        original_bullet=req.original_bullet,
        resume_context=req.resume_context or "",
        jd_requirement=req.jd_requirement,
        user_supplied_metric=req.user_supplied_metric,
    )

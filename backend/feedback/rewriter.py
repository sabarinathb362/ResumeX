"""
Phase 8 — Grounded Bullet Rewriting Engine.
Transforms weak or generic resume bullets into XYZ-formula bullets,
aligning them with JD requirements while preserving factual veracity.
"""
import re
from typing import Optional
from pydantic import BaseModel, Field

from backend.llm.client import get_llm_client
from backend.llm.prompts import REWRITE_SYSTEM_PROMPT
from backend.feedback.validator import validate_rewrite, ValidationResult


class RewriteCandidate(BaseModel):
    rewritten_text: str
    rationale: str
    is_factually_validated: bool
    unsupported_facts: list[str] = Field(default_factory=list)


class RewriteResponse(BaseModel):
    original_bullet: str
    target_requirement: Optional[str] = None
    candidates: list[RewriteCandidate] = Field(default_factory=list)
    prompt_for_metric: bool = False


class LLMRewriteOutput(BaseModel):
    rewrite_1: str
    rationale_1: str
    rewrite_2: Optional[str] = None
    rationale_2: Optional[str] = None


def generate_bullet_rewrites(
    original_bullet: str,
    resume_context: str = "",
    jd_requirement: Optional[str] = None,
    user_supplied_metric: Optional[str] = None,
) -> RewriteResponse:
    """
    Produces factually validated bullet rewrites aligned with JD or role norms.
    """
    llm = get_llm_client()

    # Detect if original has numbers
    has_numbers = bool(re.search(r"\d+", original_bullet))
    prompt_for_metric = not has_numbers and not user_supplied_metric

    user_prompt = f"Original bullet: {original_bullet}\n"
    if jd_requirement:
        user_prompt += f"Target JD requirement: {jd_requirement}\n"
    if user_supplied_metric:
        user_prompt += f"User-confirmed metric to incorporate: {user_supplied_metric}\n"
    if resume_context:
        user_prompt += f"Supporting resume facts: {resume_context[:400]}\n"

    user_prompt += (
        "\nProvide two alternative rewrites in JSON with keys: "
        "'rewrite_1', 'rationale_1', 'rewrite_2', 'rationale_2'. "
        "Strictly adhere to the rule: NEVER invent numbers or tools not provided."
    )

    resp = llm.generate(
        system_prompt=REWRITE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_schema=LLMRewriteOutput,
        temperature=0.2,
    )

    candidates = []
    allowed_terms = set()
    if user_supplied_metric:
        allowed_terms.add(user_supplied_metric)

    if resp.raw_json:
        # Candidate 1
        r1 = resp.raw_json.get("rewrite_1")
        if r1:
            val1 = validate_rewrite(original_bullet, r1, resume_context, allowed_terms)
            candidates.append(
                RewriteCandidate(
                    rewritten_text=r1,
                    rationale=resp.raw_json.get("rationale_1", "Rewritten using action-oriented XYZ structure."),
                    is_factually_validated=val1.is_valid,
                    unsupported_facts=val1.unsupported_facts,
                )
            )

        # Candidate 2
        r2 = resp.raw_json.get("rewrite_2")
        if r2:
            val2 = validate_rewrite(original_bullet, r2, resume_context, allowed_terms)
            candidates.append(
                RewriteCandidate(
                    rewritten_text=r2,
                    rationale=resp.raw_json.get("rationale_2", "Alternative technical focus."),
                    is_factually_validated=val2.is_valid,
                    unsupported_facts=val2.unsupported_facts,
                )
            )

    # Hard gate: candidates that fail validation never reach the user.
    candidates = [c for c in candidates if c.is_factually_validated]

    # LLM offline or everything rejected -> deterministic, word-preserving options only.
    if not candidates:
        from backend.readability.rri import front_load, trim_filler
        for fn, why in ((front_load, "Moved your existing result to the front."),
                        (trim_filler, "Removed filler words; meaning unchanged.")):
            try:
                alt = fn(original_bullet, []) if fn is front_load else fn(original_bullet)
            except Exception:
                alt = None
            if alt:
                v = validate_rewrite(original_bullet, alt, resume_context, allowed_terms)
                if v.is_valid:
                    candidates.append(RewriteCandidate(rewritten_text=alt, rationale=why,
                                                       is_factually_validated=True))

    return RewriteResponse(
        original_bullet=original_bullet,
        target_requirement=jd_requirement,
        candidates=candidates,
        prompt_for_metric=prompt_for_metric,
    )
from backend.rag.pipeline import retrieve_context, format_context, verify_citations

class RewriteResponse(BaseModel):
    original_bullet: str
    target_requirement: Optional[str] = None
    candidates: list[RewriteCandidate] = Field(default_factory=list)
    prompt_for_metric: bool = False
    retrieved_context: list[dict] = Field(default_factory=list)
    cited_sources: list[str] = Field(default_factory=list)

class LLMRewriteOutput(BaseModel):
    rewrite_1: str
    rationale_1: str
    rewrite_2: Optional[str] = None
    rationale_2: Optional[str] = None
    sources: list[str] = Field(default_factory=list)


def generate_bullet_rewrites(original_bullet, resume_context="", jd_requirement=None,
                             user_supplied_metric=None, target_role=None) -> RewriteResponse:
    llm = get_llm_client()
    has_numbers = bool(re.search(r"\d+", original_bullet))
    prompt_for_metric = not has_numbers and not user_supplied_metric

    # --- RETRIEVE ---
    hits = retrieve_context(original_bullet, jd_requirement, target_role)

    # --- AUGMENT ---
    system_prompt = (
        REWRITE_SYSTEM_PROMPT
        + "\n\nREFERENCE GUIDANCE (from the ResumeX knowledge base):\n"
        + format_context(hits)
        + "\n\nApply the guidance where relevant. List the ids you used in 'sources'. "
          "Guidance never licenses inventing facts."
    )
    user_prompt = f"Original bullet: {original_bullet}\n"
    if jd_requirement:
        user_prompt += f"Target JD requirement: {jd_requirement}\n"
    if user_supplied_metric:
        user_prompt += f"User-confirmed metric to incorporate: {user_supplied_metric}\n"
    if resume_context:
        user_prompt += f"Supporting resume facts: {resume_context[:400]}\n"
    user_prompt += ("\nReturn JSON with keys: 'rewrite_1', 'rationale_1', 'rewrite_2', "
                    "'rationale_2', 'sources'. NEVER invent numbers or tools not provided.")

    # --- GENERATE ---
    resp = llm.generate(system_prompt=system_prompt, user_prompt=user_prompt,
                        response_schema=LLMRewriteOutput, temperature=0.2)

    candidates = []
    allowed_terms = set()
    if user_supplied_metric:
        allowed_terms.add(user_supplied_metric)

    if resp.raw_json:
        # Candidate 1
        r1 = resp.raw_json.get("rewrite_1")
        if r1:
            val1 = validate_rewrite(original_bullet, r1, resume_context, allowed_terms)
            candidates.append(
                RewriteCandidate(
                    rewritten_text=r1,
                    rationale=resp.raw_json.get("rationale_1", "Rewritten using action-oriented XYZ structure."),
                    is_factually_validated=val1.is_valid,
                    unsupported_facts=val1.unsupported_facts,
                )
            )

        # Candidate 2
        r2 = resp.raw_json.get("rewrite_2")
        if r2:
            val2 = validate_rewrite(original_bullet, r2, resume_context, allowed_terms)
            candidates.append(
                RewriteCandidate(
                    rewritten_text=r2,
                    rationale=resp.raw_json.get("rationale_2", "Alternative technical focus."),
                    is_factually_validated=val2.is_valid,
                    unsupported_facts=val2.unsupported_facts,
                )
            )

    # Fallback candidate if LLM was offline or invalid
    if not candidates:
        first_word = original_bullet.split()[0] if original_bullet else ""
        fallback_text = original_bullet
        if first_word.lower() in ["responsible", "worked", "helped", "assisted"]:
            fallback_text = f"Engineered core system workflows to advance {original_bullet.split('for', 1)[-1].strip() if 'for' in original_bullet else original_bullet}."

        val_fb = validate_rewrite(original_bullet, fallback_text, resume_context, allowed_terms)
        candidates.append(
            RewriteCandidate(
                rewritten_text=fallback_text,
                rationale="Reframed with proactive action verb without altering factual claims.",
                is_factually_validated=val_fb.is_valid,
                unsupported_facts=val_fb.unsupported_facts,
            )
        )

    # --- VERIFY + RETURN ---
    cited = verify_citations(resp.raw_json.get("sources", []), hits) if resp.raw_json else []
    return RewriteResponse(
        original_bullet=original_bullet,
        target_requirement=jd_requirement,
        candidates=candidates,
        prompt_for_metric=prompt_for_metric,
        retrieved_context=[h.to_dict() for h in hits],
        cited_sources=cited,
    )
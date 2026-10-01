"""
Phase 8 — Rewrite Fact-Checking Validator.
Strict validation gate that prevents the LLM from inventing metrics,
unverified technologies, companies, or accomplishments.
"""
import re
from typing import Optional
from pydantic import BaseModel, Field


class ValidationResult(BaseModel):
    is_valid: bool
    unsupported_facts: list[str] = Field(default_factory=list)
    rejection_reason: Optional[str] = None


def extract_metrics(text: str) -> set[str]:
    """Extract every number-like token (percentages, money, multipliers, counts).

    The previous pattern wrapped '%' and '$' in \\b...\\b. Because '%' and '$' are
    not word characters, '30%' and '$5M' NEVER matched, so fabricated percentages
    passed validation. We now compare bare numeric values instead."""
    nums = re.findall(r"\d+(?:[.,]\d+)*", text)
    return {n.replace(",", "") for n in nums}


def extract_key_terms(text: str) -> set[str]:
    """Things that look like named entities a rewrite could fabricate:
    mixed-case/acronym tokens (PyTorch, AWS, LLMs), tokens with digits
    (ResNet-50, YOLOv11s), known skill names, and capitalised words that are
    not at the start of a sentence. Plain sentence-initial verbs are ignored."""
    try:
        from backend.nlp.skills import SKILL_ALIASES
        known = {k.lower() for k in SKILL_ALIASES} | {v.lower() for v in SKILL_ALIASES.values()}
    except Exception:
        known = set()
    out = set()
    for m in re.finditer(r"[A-Za-z][\w+#.-]*[\w+#]|[A-Za-z]", text):
        w = m.group(0)
        start = m.start()
        prev = text[:start].rstrip()
        sentence_start = (not prev) or prev[-1] in ".!?;:—–-(["
        if re.search(r"[A-Z].*[A-Z]|\d", w) or (len(w) > 1 and w[1:].lower() != w[1:]):
            out.add(w)
        elif w.lower() in known and len(w) > 2:
            out.add(w)
        elif w[0].isupper() and not sentence_start:
            out.add(w)
    return out


def validate_rewrite(
    original_bullet: str,
    rewritten_bullet: str,
    resume_context: str = "",
    allowed_new_terms: Optional[set[str]] = None,
) -> ValidationResult:
    """
    Hard-gate validator:
    Ensures that any new metric or unverified technical entity in the rewrite
    was already present in the original bullet, resume context, or explicitly allowed.
    """
    allowed_terms = allowed_new_terms or set()
    combined_ground_truth = f"{original_bullet} {resume_context}".lower()

    # 1. Metric check: no fabricated numbers or percentages
    orig_metrics = extract_metrics(f"{original_bullet} {resume_context}")
    new_metrics = extract_metrics(rewritten_bullet)

    allowed_nums = set()
    for t in allowed_terms:
        allowed_nums |= extract_metrics(t)
    unsupported_metrics = [m for m in new_metrics if m not in orig_metrics and m not in allowed_nums]

    # 2. Check for newly introduced tool/framework entities
    orig_tools = extract_key_terms(f"{original_bullet} {resume_context}")
    new_tools = extract_key_terms(rewritten_bullet)
    allowed_low = " ".join(allowed_terms).lower()
    unsupported_tools = [t for t in new_tools
                         if t.lower() not in combined_ground_truth and t.lower() not in allowed_low
                         and not t.startswith("[")]

    unsupported = []
    if unsupported_metrics:
        unsupported.extend([f"Fabricated metric: '{m}'" for m in unsupported_metrics])
    if unsupported_tools:
        unsupported.extend([f"Unverified entity: '{t}'" for t in unsupported_tools])

    if unsupported:
        return ValidationResult(
            is_valid=False,
            unsupported_facts=unsupported,
            rejection_reason="Rewrite introduced metrics or technologies not grounded in the candidate's resume.",
        )

    return ValidationResult(is_valid=True)

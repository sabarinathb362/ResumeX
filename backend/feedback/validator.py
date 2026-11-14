"""
Phase 8 → ResumeX 2.0 — Rewrite Fact-Checking Validator (v2).

Still a hard gate: a rewrite may not add a number, tool, company or claim that is
not in the evidence. v2 removes the false positives that emptied the editor sidebar:

  * aliases are equal          (k8s == Kubernetes, Postgres == PostgreSQL)
  * generalising is allowed     (PostgreSQL -> "relational database"; never the reverse)
  * ambiguous aliases only count when written as a tool ("Spring Boot", not "spring semester")
  * whole-word matching         ("Java" is no longer grounded by "JavaScript")
  * numbers compare by value    ("three" == 3, "1.2k" == 1,200, "$5M" == 5,000,000)
  * derived metrics are allowed but flagged (850ms -> 120ms  =>  "86% lower")
"""
from __future__ import annotations

import itertools
import re
from typing import Optional

from pydantic import BaseModel, Field

from backend.feedback.taxonomy import (
    AMBIGUOUS_ALIASES, allowed_generalisations, canonical, grounded_canonicals, is_supported_term,
)


class ValidationResult(BaseModel):
    is_valid: bool
    unsupported_facts: list[str] = Field(default_factory=list)
    rejection_reason: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)       # e.g. derived metrics the user should check


# ── numbers ─────────────────────────────────────────────────────────

_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "hundred": 100, "dozen": 12, "double": 2, "doubled": 2,
    "triple": 3, "tripled": 3, "twice": 2,
}
_SUFFIX = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "mn": 1e6, "b": 1e9, "billion": 1e9, "bn": 1e9}
_NUM_RE = re.compile(r"(?<![\w.])(\d+(?:,\d{3})*(?:\.\d+)?)(?:\s?(k|thousand|mn|m|million|bn|b|billion)(?![A-Za-z]))?", re.I)


def extract_numbers(text: str) -> set[float]:
    vals: set[float] = set()
    for m in _NUM_RE.finditer(text):
        v = float(m.group(1).replace(",", ""))
        if m.group(2):
            v *= _SUFFIX[m.group(2).lower()]
        vals.add(round(v, 6))
    for w in re.findall(r"[A-Za-z]+", text):
        if w.lower() in _NUM_WORDS:
            vals.add(float(_NUM_WORDS[w.lower()]))
    return vals


def extract_metrics(text: str) -> set[str]:
    """Back-compat helper (older callers/tests import it)."""
    return {str(v).rstrip("0").rstrip(".") for v in extract_numbers(text)}


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= max(1e-9, 1e-6 * max(abs(a), abs(b)))


def _derived(v: float, ground: set[float]) -> bool:
    """v is a % change or an x-fold ratio between two grounded numbers (rounded)."""
    nums = [g for g in ground if g > 0][:24]
    for a, b in itertools.permutations(nums, 2):
        if a > b:
            pct = (a - b) / a * 100
            if abs(round(pct) - v) <= 1 or abs(pct - v) <= 0.5:
                return True
            ratio = a / b
            if abs(ratio - v) <= 0.15 or abs(round(ratio) - v) < 1e-9:
                return True
    return False


# ── named things ─────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[A-Za-z][\w+#./-]*[\w+#]|[A-Za-z]")
_SENTENCE_BREAK = ".!?;:—–(["


def extract_key_terms(text: str) -> set[str]:
    """Tokens a rewrite could fabricate: acronyms / mixed case (PyTorch, AWS), tokens with
    digits (ResNet-50), known skills, and capitalised words that don't start a sentence.
    Multi-word canonical skills ("Spring Boot", "Power BI") are returned whole."""
    out: set[str] = set()
    for canon in grounded_canonicals(text):
        if " " in canon:
            out.add(canon)
    for m in _TOKEN_RE.finditer(text):
        w = m.group(0).rstrip("./-")
        if not w:
            continue
        prev = text[:m.start()].rstrip()
        sentence_start = (not prev) or prev[-1] in _SENTENCE_BREAK
        low = w.lower()
        if re.search(r"[A-Z].*[A-Z]|\d", w) or (len(w) > 1 and w[1:].lower() != w[1:]):
            out.add(w)                                   # AWS, PyTorch, ResNet-50, p99
        elif low in AMBIGUOUS_ALIASES:
            if w[0].isupper() and not sentence_start:
                out.add(w)                               # "Spring", "Express" mid-sentence
        elif canonical(w) and len(w) > 2:
            out.add(w)                                   # docker, kubernetes, pandas
        elif w[0].isupper() and not sentence_start:
            out.add(w)                                   # Google, Stripe, Payments
    return out


def validate_rewrite(
    original_bullet: str,
    rewritten_bullet: str,
    resume_context: str = "",
    allowed_new_terms: Optional[set[str]] = None,
) -> ValidationResult:
    """Hard gate. Every number and named thing in the rewrite must be grounded in the
    original bullet, the supplied context, or user-supplied facts (allowed_new_terms)."""
    allowed_terms = {t for t in (allowed_new_terms or set()) if t}
    ground_text = " ".join([original_bullet, resume_context, *allowed_terms])

    problems: list[str] = []
    warnings: list[str] = []

    # 1. numbers
    ground_nums = extract_numbers(ground_text)
    for v in sorted(extract_numbers(rewritten_bullet)):
        if any(_same(v, g) for g in ground_nums):
            continue
        if _derived(v, ground_nums):
            warnings.append(f"Derived figure '{v:g}' — calculated from your numbers; double-check it.")
            continue
        problems.append(f"Fabricated metric: '{v:g}'")

    # 2. named things
    grounded = grounded_canonicals(ground_text)
    general = allowed_generalisations(grounded)
    for term in sorted(extract_key_terms(rewritten_bullet)):
        if term.startswith("["):
            continue
        ok, _how = is_supported_term(term, ground_text, grounded, general)
        if not ok and any(ch.isdigit() for ch in term):
            # "p99" / "ResNet-50": fine when every number inside it is grounded
            nums = extract_numbers(re.sub(r"[A-Za-z]", " ", term))
            ok = bool(nums) and all(any(_same(n, g) for g in ground_nums) for n in nums) \
                and is_supported_term(re.sub(r"[\d.-]+", "", term) or term, ground_text, grounded, general)[0]
        if not ok:
            problems.append(f"Unverified entity: '{term}'")

    if problems:
        return ValidationResult(
            is_valid=False, unsupported_facts=problems, warnings=warnings,
            rejection_reason="Rewrite introduced metrics or technologies not grounded in the candidate's resume.",
        )
    return ValidationResult(is_valid=True, warnings=warnings)

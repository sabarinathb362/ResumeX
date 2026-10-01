"""
Phase 9A — AI-Likeness & Generic-Writing Signal Detector.
Evaluates sentences for generic buzzword density, template phrasing,
and low information density.

MANDATORY CONSTRAINT:
Never claims certainty of AI authorship. Always frames findings as
'AI-likeness / generic-writing signals' with confidence bands.
"""
import re
from pydantic import BaseModel, Field

# High-frequency AI and corporate buzzwords / formulaic fillers
GENERIC_AI_PHRASES = [
    r"\bspearheaded\s+(?:pivotal|strategic|critical)\s+initiatives\b",
    r"\bpassionate\s+and\s+results-driven\s+professional\b",
    r"\bproven\s+track\s+record\s+of\s+delivering\s+impact\b",
    r"\bleveraged\s+cutting-edge\s+(?:technologies|paradigms|frameworks)\b",
    r"\bdynamic\s+self-starter\b",
    r"\bthrives\s+in\s+fast-paced\s+environments\b",
    r"\bdemonstrated\s+ability\s+to\s+think\s+outside\s+the\s+box\b",
    r"\bseamlessly\s+integrated\b",
    r"\borchestrated\s+cross-functional\s+synergies\b",
    r"\bplayed\s+a\s+pivotal\s+role\b",
    r"\brobust\s+and\s+scalable\s+solutions\b",
    r"\btestament\s+to\b",
    r"\bdrive\s+success\s+and\s+growth\b",
    r"\bharnessing\s+the\s+power\s+of\b",
    r"\binnovative\s+solutions\s+to\s+complex\s+problems\b",
]


class AILikenessSignal(BaseModel):
    sentence: str
    signal_type: str
    confidence: str  # "low" | "medium" | "high"
    explanation: str
    suggestion: str


class AILikenessReport(BaseModel):
    overall_likeness_signal: str  # "minimal" | "moderate" | "elevated"
    generic_phrase_count: int = 0
    signals: list[AILikenessSignal] = Field(default_factory=list)
    disclosure: str = (
        "AI-likeness signals detect generic, formulaic phrasing commonly associated with AI text generators. "
        "This is an indicator of writing style and information density, NOT definitive proof of AI authorship."
    )


def detect_ai_likeness(bullets: list[str]) -> AILikenessReport:
    """
    Analyzes bullets for generic filler phrases, buzzword clustering,
    and lack of concrete technical specificity.
    """
    if not bullets:
        return AILikenessReport(overall_likeness_signal="minimal")

    signals: list[AILikenessSignal] = []

    for b in bullets:
        clean = b.strip()
        if not clean:
            continue

        matched_phrases = []
        for pat in GENERIC_AI_PHRASES:
            m = re.search(pat, clean, re.IGNORECASE)
            if m:
                matched_phrases.append(m.group(0))

        if matched_phrases:
            confidence = "high" if len(matched_phrases) >= 2 else "medium"
            signals.append(
                AILikenessSignal(
                    sentence=clean,
                    signal_type="generic_buzzwords",
                    confidence=confidence,
                    explanation=f"Contains formulaic phrasing: {', '.join(repr(p) for p in matched_phrases)}.",
                    suggestion="Replace grandiose buzzwords with specific tools, architectural decisions, and measured outcomes.",
                )
            )

    count = len(signals)
    ratio = count / max(len(bullets), 1)

    if ratio >= 0.35:
        overall = "elevated"
    elif ratio >= 0.15:
        overall = "moderate"
    else:
        overall = "minimal"

    return AILikenessReport(
        overall_likeness_signal=overall,
        generic_phrase_count=count,
        signals=signals,
    )

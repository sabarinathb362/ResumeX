"""
Phase 9B — Placeholder & Lorem Ipsum Detector.
Detects leftover template text, pseudo-Latin filler, unpopulated brackets,
and stock placeholders in resumes.
Runs deterministically on every resume.
"""
import re
from typing import Optional
from pydantic import BaseModel, Field

LOREM_IPSUM_TOKENS = {
    "lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing",
    "elit", "sed", "do", "eiusmod", "tempor", "incididunt", "ut", "labore",
    "et", "dolore", "magna", "aliqua", "enim", "ad", "minim", "veniam",
    "quis", "nostrud", "exercitation", "ullamco", "laboris", "nisi", "aliquip",
    "commodo", "consequat", "duis", "aute", "irure", "in", "reprehenderit",
    "voluptate", "velit", "esse", "cillum", "fugiat", "nulla", "pariatur",
}

PLACEHOLDER_PATTERNS = [
    # Bracketed / Tagged tokens
    (r"\[(?:Company\s*Name|Your\s*Name|Job\s*Title|Insert\s*.*?|City|State|Degree|University|Date)\]", "bracketed_placeholder", "critical"),
    (r"\{(?:Company|Role|Name|Phone|Email|Insert|Title)\}", "bracketed_placeholder", "critical"),
    (r"<(?:Insert|Company|Role|Name|Title).*?>", "bracketed_placeholder", "critical"),
    # Obvious stock fillers
    (r"\b(?:Your Name|First Last|John Doe|Jane Doe)\b", "stock_name", "critical"),
    (r"\b(?:Company Name|Employer Name|Client Name)\b", "stock_company", "critical"),
    (r"\b(?:City,\s*State|City,\s*ST|Address Line|Zip Code)\b", "stock_location", "high"),
    (r"\b(?:123-456-7890|000-000-0000|555-555-5555)\b", "stock_phone", "critical"),
    (r"\b(?:email@example\.com|username@email\.com|your\.email@domain\.com|john\.doe@example\.com)\b", "stock_email", "critical"),
    # Masked numbers & Dates
    (r"\b(?:XX%|\$XX|XX\+?|\d+X)\b", "masked_metric", "high"),
    (r"\b(?:MM/YYYY|YYYY\s*-\s*YYYY|Month\s*Year)\b", "masked_date", "high"),
    # Workflow markers
    (r"\b(?:TODO|TBD|FIXME|INSERT HERE|REPLACE THIS)\b", "todo_marker", "critical"),
]


class PlaceholderFinding(BaseModel):
    span: str
    finding_type: str
    severity: str  # "critical" | "high" | "medium"
    context: str
    message: str
    remediation: str


class PlaceholderReport(BaseModel):
    has_critical_placeholders: bool = False
    total_findings: int = 0
    findings: list[PlaceholderFinding] = Field(default_factory=list)


def detect_placeholders(raw_text: str) -> PlaceholderReport:
    """
    Scans text for lorem ipsum, unfilled template tokens, masked values,
    and placeholder contact information.
    """
    if not raw_text:
        return PlaceholderReport()

    findings: list[PlaceholderFinding] = []

    # 1. Lorem Ipsum Detection
    words = re.findall(r"\b[a-zA-Z]+\b", raw_text.lower())
    if words:
        lorem_matches = [w for w in words if w in LOREM_IPSUM_TOKENS]
        lorem_ratio = len(lorem_matches) / len(words)

        if lorem_matches and (lorem_ratio >= 0.05 or "lorem ipsum" in raw_text.lower()):
            findings.append(
                PlaceholderFinding(
                    span="lorem ipsum",
                    finding_type="lorem_ipsum",
                    severity="critical",
                    context=raw_text[:120].strip() + "...",
                    message="Lorem ipsum placeholder text detected in resume.",
                    remediation="Replace all Latin placeholder text with your actual work experience and accomplishments.",
                )
            )

    # 2. Regex Patterns
    for pattern, p_type, severity in PLACEHOLDER_PATTERNS:
        matches = re.finditer(pattern, raw_text, re.IGNORECASE)
        for m in matches:
            span_text = m.group(0)
            start = max(0, m.start() - 30)
            end = min(len(raw_text), m.end() + 30)
            snippet = raw_text[start:end].replace("\n", " ").strip()

            findings.append(
                PlaceholderFinding(
                    span=span_text,
                    finding_type=p_type,
                    severity=severity,
                    context=f"...{snippet}...",
                    message=f"Unfilled placeholder detected: '{span_text}'.",
                    remediation=f"Replace '{span_text}' with your specific information before sending.",
                )
            )

    has_crit = any(f.severity == "critical" for f in findings)
    return PlaceholderReport(
        has_critical_placeholders=has_crit,
        total_findings=len(findings),
        findings=findings,
    )

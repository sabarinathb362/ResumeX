"""
Phase 3 — JD Parser.
Accepts text (paste) or file, extracts and classifies requirements as
required/preferred/responsibility/education/certification.
"""
import re
import uuid
from typing import Optional

from backend.schemas.jd import JDData, JDRequirement, RequirementType
from backend.schemas.resume import SourceSpan
from backend.nlp.skills import normalize_skill, normalize_skill_list, SKILL_ALIASES


# ── Seniority detection ──────────────────────────────────────────

SENIORITY_KEYWORDS = {
    "intern": "intern",
    "internship": "intern",
    "entry level": "entry",
    "entry-level": "entry",
    "junior": "entry",
    "associate": "entry",
    "mid level": "mid",
    "mid-level": "mid",
    "intermediate": "mid",
    "senior": "senior",
    "sr.": "senior",
    "sr ": "senior",
    "lead": "lead",
    "tech lead": "lead",
    "team lead": "lead",
    "staff": "staff",
    "staff engineer": "staff",
    "principal": "principal",
    "architect": "principal",
    "director": "principal",
    "manager": "lead",
    "vp": "principal",
    "head of": "principal",
}


# ── Requirement classification patterns ──────────────────────────

REQUIRED_INDICATORS = [
    r"\brequired?\b", r"\bmust\s+have\b", r"\bessential\b",
    r"\bmandatory\b", r"\bneed(?:ed)?\b", r"\bshould\s+have\b",
    r"\bminimum\b", r"\bat\s+least\b",
]

PREFERRED_INDICATORS = [
    r"\bpreferred?\b", r"\bnice\s+to\s+have\b", r"\bbonus\b",
    r"\bplus\b", r"\bdesirable\b", r"\badvantage\b",
    r"\bideally\b", r"\ba\s+plus\b", r"\bfamiliarity\b",
]

EDUCATION_INDICATORS = [
    r"\bbachelor'?s?\b", r"\bmaster'?s?\b", r"\bphd\b", r"\bdoctorate\b",
    r"\bdegree\b", r"\bb\.?s\.?\b", r"\bm\.?s\.?\b", r"\bmba\b",
    r"\bcomputer\s+science\b", r"\bengineering\b", r"\buniversity\b",
]

CERTIFICATION_INDICATORS = [
    r"\bcertif(?:ied|ication)\b", r"\baws\s+certified\b",
    r"\bazure\s+certified\b", r"\bgoogle\s+certified\b",
    r"\bpmp\b", r"\bscrum\s+master\b", r"\bcka\b", r"\bckad\b",
]

RESPONSIBILITY_INDICATORS = [
    r"\byou\s+will\b", r"\bresponsible\s+for\b", r"\byou['']?ll\b",
    r"\bin\s+this\s+role\b", r"\bduties\b", r"\bresponsibilities\b",
    r"\bday-to-day\b", r"\byour\s+role\b",
]


def _detect_seniority(text: str) -> Optional[str]:
    """Detect seniority level from JD text."""
    lower = text.lower()
    for keyword, level in SENIORITY_KEYWORDS.items():
        if keyword in lower:
            return level
    return None


def _classify_requirement(text: str) -> RequirementType:
    """Classify a single requirement line by type."""
    lower = text.lower()

    # Check education first (specific)
    for pat in EDUCATION_INDICATORS:
        if re.search(pat, lower):
            return RequirementType.EDUCATION

    # Then certifications
    for pat in CERTIFICATION_INDICATORS:
        if re.search(pat, lower):
            return RequirementType.CERTIFICATION

    # Then preferred
    for pat in PREFERRED_INDICATORS:
        if re.search(pat, lower):
            return RequirementType.PREFERRED

    # Then responsibility
    for pat in RESPONSIBILITY_INDICATORS:
        if re.search(pat, lower):
            return RequirementType.RESPONSIBILITY

    # Default to required
    return RequirementType.REQUIRED


def _extract_skills_from_text(text: str) -> list[str]:
    """Extract skill mentions from a text chunk."""
    found = []
    lower = text.lower()

    # Check against known skills
    for alias in SKILL_ALIASES:
        # Word-boundary match to avoid false positives
        pattern = r'\b' + re.escape(alias) + r'\b'
        if re.search(pattern, lower):
            canonical = SKILL_ALIASES[alias]
            if canonical not in found:
                found.append(canonical)

    return found


def _extract_title(text: str) -> Optional[str]:
    """Extract job title from the beginning of JD text."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return None

    # Common title patterns
    for line in lines[:5]:
        # Explicit "Job Title:" pattern
        match = re.match(r"(?:job\s+)?title\s*[:]\s*(.+)", line, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # Short title-like line at the top
        if len(line) < 80 and not re.search(r"[.!?]$", line):
            if any(kw in line.lower() for kw in ["engineer", "developer", "analyst", "designer",
                                                   "manager", "scientist", "architect", "specialist",
                                                   "consultant", "coordinator", "lead", "director",
                                                   "intern"]):
                return line

    return lines[0] if lines and len(lines[0]) < 80 else None


def _extract_company(text: str) -> Optional[str]:
    """Extract company name from JD text."""
    patterns = [
        r"(?:company|organization|employer)\s*[:]\s*(.+)",
        r"(?:at|@)\s+([A-Z][A-Za-z\s&.]+?)(?:\s*[,\-–—]|\s+is\b|\s+we\b)",
        r"(?:about|join)\s+([A-Z][A-Za-z\s&.]+?)(?:\s*[,\-–—]|\s+is\b)",
    ]
    for pat in patterns:
        match = re.search(pat, text[:2000], re.IGNORECASE)
        if match:
            company = match.group(1).strip()
            if len(company) < 60:
                return company
    return None


def parse_jd(text: str) -> JDData:
    """
    Parse a job description text into the canonical JDData schema.
    Classifies requirements as required/preferred/responsibility/education/certification.
    """
    jd = JDData(raw_text=text)

    # ── Extract metadata ─────────────────────────────────────────
    jd.title = _extract_title(text)
    jd.company = _extract_company(text)
    jd.seniority = _detect_seniority(text)

    # ── Location ─────────────────────────────────────────────────
    location_match = re.search(
        r"(?:location|based\s+in|office)\s*[:]\s*(.+?)(?:\n|$)",
        text, re.IGNORECASE
    )
    if location_match:
        jd.location = location_match.group(1).strip()

    # ── Parse into requirements ──────────────────────────────────
    # Split by bullet points, numbered lists, or newlines
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Split on bullet-style markers
        cleaned = re.sub(r"^[\d.)+\-•*▪►→◦⁃]+\s*", "", line).strip()
        if cleaned and len(cleaned) > 10:
            lines.append(cleaned)

    # Detect sections within the JD
    current_section = "general"
    section_map = {
        "requirements": ["requirement", "qualifications", "what you need",
                         "what we're looking for", "what you'll need",
                         "must have", "minimum qualifications"],
        "preferred": ["preferred", "nice to have", "bonus", "plus",
                      "additional qualifications", "desired"],
        "responsibilities": ["responsibilities", "what you'll do", "your role",
                             "key responsibilities", "duties", "role description"],
        "education": ["education", "academic"],
    }

    requirements = []
    for line in lines:
        lower = line.lower()

        # Check if this is a section header
        for section_name, keywords in section_map.items():
            if any(kw in lower for kw in keywords) and len(line) < 60:
                current_section = section_name
                break
        else:
            # Classify based on content + current section context
            req_type = _classify_requirement(line)

            # Override based on current section
            if current_section == "preferred" and req_type == RequirementType.REQUIRED:
                req_type = RequirementType.PREFERRED
            elif current_section == "responsibilities" and req_type == RequirementType.REQUIRED:
                req_type = RequirementType.RESPONSIBILITY

            skills = _extract_skills_from_text(line)

            req = JDRequirement(
                id=str(uuid.uuid4())[:8],
                text=line,
                type=req_type,
                skills=skills,
                normalized_skills=normalize_skill_list(skills),
                source_span=SourceSpan(text=line),
            )
            requirements.append(req)

    jd.requirements = requirements

    # ── Aggregate skills ─────────────────────────────────────────
    required_skills = set()
    preferred_skills = set()
    responsibilities = []

    for req in requirements:
        if req.type == RequirementType.REQUIRED:
            required_skills.update(req.normalized_skills)
        elif req.type == RequirementType.PREFERRED:
            preferred_skills.update(req.normalized_skills)
        elif req.type == RequirementType.RESPONSIBILITY:
            responsibilities.append(req.text)
        elif req.type == RequirementType.EDUCATION:
            jd.education_requirements.append(req.text)
        elif req.type == RequirementType.CERTIFICATION:
            jd.certifications.append(req.text)

    jd.required_skills = list(required_skills)
    jd.preferred_skills = list(preferred_skills)
    jd.responsibilities = responsibilities
    jd.all_skills_flat = list(required_skills | preferred_skills)

    # ── Domain terms (words that appear often but aren't in skill dictionary) ──
    words = re.findall(r"\b[A-Za-z][\w.+-]+\b", text)
    from collections import Counter
    word_counts = Counter(w.lower() for w in words if len(w) > 3)
    common_words = {"with", "that", "this", "will", "have", "your", "from", "they",
                    "been", "more", "work", "about", "also", "team", "role", "year",
                    "years", "experience", "including", "such", "using", "ability",
                    "strong", "knowledge", "understanding", "working", "must", "should"}
    domain_terms = [
        w for w, c in word_counts.most_common(20)
        if c >= 2 and w not in common_words and w not in {s.lower() for s in jd.all_skills_flat}
    ]
    jd.domain_terms = domain_terms[:10]

    return jd

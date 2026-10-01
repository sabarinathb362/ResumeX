"""
Phase 10 — Resume Readability Index (RRI).

Deterministic, multi-dimensional readability scoring for resumes.
Evaluates bullet quality, sentence complexity, section balance,
whitespace utilisation, action-verb usage, and quantification depth.
All rules are evidence-grounded and fully transparent.
"""
import re
import math
from typing import Optional

from backend.schemas.resume import ResumeData
from backend.config import settings


# ── Action verbs (strong resume language) ────────────────────────

ACTION_VERBS = {
    # Achievement / Impact
    "achieved", "accelerated", "delivered", "drove", "exceeded",
    "generated", "improved", "increased", "reduced", "saved",
    "transformed", "launched", "pioneered", "boosted", "maximized",
    # Leadership
    "led", "managed", "mentored", "directed", "coordinated",
    "supervised", "oversaw", "guided", "spearheaded", "established",
    # Technical
    "built", "designed", "developed", "implemented", "engineered",
    "architected", "optimized", "automated", "configured", "deployed",
    "integrated", "migrated", "refactored", "scaled", "streamlined",
    # Analysis / Research
    "analyzed", "assessed", "evaluated", "investigated", "researched",
    "identified", "diagnosed", "audited", "benchmarked", "tested",
    # Communication
    "authored", "communicated", "documented", "presented", "published",
    "reported", "trained", "collaborated", "facilitated", "negotiated",
    # Creation
    "created", "constructed", "formulated", "initiated", "introduced",
    "produced", "proposed", "prototyped", "conceptualized", "crafted",
}

# ── Weak / filler words ─────────────────────────────────────────

WEAK_PHRASES = [
    r"\bresponsible for\b",
    r"\bhelped\b",
    r"\bassisted\b",
    r"\bworked on\b",
    r"\binvolved in\b",
    r"\bparticipated in\b",
    r"\bwas part of\b",
    r"\btasked with\b",
    r"\bfamiliar with\b",
    r"\bexposure to\b",
    r"\bvarious\b",
    r"\betc\.?\b",
    r"\bseveral\b",
    r"\bsome\b",
    r"\bmany\b",
    r"\ba lot of\b",
    r"\bstuff\b",
    r"\bthings\b",
]

# ── Quantification patterns ──────────────────────────────────────

QUANTIFICATION_PATTERNS = [
    r"\d+%",                          # 25%
    r"\$[\d,.]+[KkMmBb]?",           # $1.2M, $500K
    r"\d+[KkMmBb]\b",                # 10K users
    r"\d+\+?\s*(?:users?|customers?|clients?|teams?|members?|engineers?|developers?)",
    r"\d+x\b",                        # 3x improvement
    r"\d+\s*(?:ms|seconds?|minutes?|hours?|days?|weeks?|months?)",
    r"top\s*\d+",                     # top 5
    r"#\d+",                          # #1
    r"\d+\s*(?:projects?|applications?|services?|endpoints?|APIs?|features?)",
]


class ReadabilityDimension:
    """Result from a single readability dimension."""
    def __init__(self, dimension: str, score: float, max_score: float,
                 details: list[str] = None, tips: list[str] = None):
        self.dimension = dimension
        self.score = round(max(0, min(score, max_score)), 1)
        self.max_score = max_score
        self.details = details or []
        self.tips = tips or []

    def to_dict(self):
        return {
            "dimension": self.dimension,
            "score": self.score,
            "max_score": self.max_score,
            "details": self.details,
            "tips": self.tips,
        }


class ReadabilityResult:
    """Complete readability analysis result."""
    def __init__(self, dimensions: list[ReadabilityDimension]):
        self.dimensions = dimensions
        self.overall_score = round(sum(d.score for d in dimensions), 1)
        self.max_possible = round(sum(d.max_score for d in dimensions), 1)
        self.rri_percentage = round(
            (self.overall_score / self.max_possible * 100) if self.max_possible > 0 else 0, 1
        )

    def to_dict(self):
        return {
            "overall_score": self.overall_score,
            "max_possible": self.max_possible,
            "rri_percentage": self.rri_percentage,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "rubric_version": "1.0",
            "disclosure": (
                "The Resume Readability Index (RRI) is ResumeIQ's own transparent, "
                "versioned rubric — not an industry standard. It measures how easily "
                "a human reviewer can scan and understand your resume."
            ),
        }


# ── Helper: extract all bullets ──────────────────────────────────

def _all_bullets(resume: ResumeData) -> list[str]:
    """Gather all bullet points from experience and projects."""
    bullets = []
    for exp in (resume.experience or []):
        bullets.extend(exp.bullets or [])
    for proj in (resume.projects or []):
        bullets.extend(proj.bullets or [])
    return [b.strip() for b in bullets if b and isinstance(b, str) and b.strip()]


def _syllable_count(word: str) -> int:
    """Estimate syllable count for English words."""
    word = word.lower().strip()
    if len(word) <= 3:
        return 1
    # Remove trailing 'e'
    if word.endswith('e'):
        if word.endswith('le') and len(word) > 2 and word[-3] not in 'aeiouy':
            pass  # Syllabic 'l' after consonant (e.g. sim-ple, ta-ble)
        else:
            word = word[:-1]
    # Count vowel groups
    count = len(re.findall(r'[aeiouy]+', word))
    return max(count, 1)


def _flesch_kincaid_grade(text: str) -> float:
    """Compute Flesch-Kincaid Grade Level for a text."""
    sentences = re.split(r'[.!?;]+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 5]
    if not sentences:
        return 0.0

    words = re.findall(r'\b[a-zA-Z]+\b', text)
    if not words:
        return 0.0

    total_syllables = sum(_syllable_count(w) for w in words)
    avg_words_per_sent = len(words) / len(sentences)
    avg_syllables_per_word = total_syllables / len(words)

    grade = 0.39 * avg_words_per_sent + 11.8 * avg_syllables_per_word - 15.59
    return max(0, grade)


# ── Dimension scorers ────────────────────────────────────────────

def _score_bullet_quality(resume: ResumeData) -> ReadabilityDimension:
    """
    Score 1: Bullet Quality (25 pts)
    - Starts with action verb
    - Proper length (40-150 chars ideal)
    - No filler/weak language
    """
    max_score = 25.0
    bullets = _all_bullets(resume)
    details = []
    tips = []

    if not bullets:
        return ReadabilityDimension(
            "Bullet Quality", 0, max_score,
            details=["No bullet points found in resume"],
            tips=["Add bullet points to your experience and project sections"],
        )

    # Action verb score
    action_count = 0
    for b in bullets:
        first_word = re.match(r'^([a-zA-Z]+)', b)
        if first_word and first_word.group(1).lower() in ACTION_VERBS:
            action_count += 1

    action_ratio = action_count / len(bullets)
    details.append(f"{action_count}/{len(bullets)} bullets start with action verbs ({action_ratio:.0%})")

    # Length score
    too_short = sum(1 for b in bullets if len(b) < 40)
    too_long = sum(1 for b in bullets if len(b) > 200)
    ideal = len(bullets) - too_short - too_long
    length_ratio = ideal / len(bullets)
    if too_short:
        details.append(f"{too_short} bullets are too short (<40 chars)")
        tips.append("Expand short bullets with specific outcomes and metrics")
    if too_long:
        details.append(f"{too_long} bullets are too long (>200 chars)")
        tips.append("Break long bullets into concise, focused statements")

    # Weak phrase detection
    weak_count = 0
    weak_examples = []
    for b in bullets:
        for pattern in WEAK_PHRASES:
            match = re.search(pattern, b, re.IGNORECASE)
            if match:
                weak_count += 1
                if len(weak_examples) < 3:
                    weak_examples.append(f'"{match.group()}" in: {b[:60]}...')
                break

    if weak_count:
        details.append(f"{weak_count} bullets contain weak/filler language")
        tips.append(f"Replace passive phrases like {weak_examples[0] if weak_examples else '\"responsible for\"'} with action verbs")

    weak_ratio = weak_count / len(bullets)

    # Composite score
    score = max_score * (
        0.4 * action_ratio +
        0.3 * length_ratio +
        0.3 * (1 - weak_ratio)
    )

    if action_ratio < 0.5:
        tips.append("Start each bullet with a strong action verb (Built, Designed, Led, Optimized...)")

    return ReadabilityDimension("Bullet Quality", score, max_score, details, tips)


def _score_quantification(resume: ResumeData) -> ReadabilityDimension:
    """
    Score 2: Quantification Depth (20 pts)
    - % of bullets with numbers/metrics
    - Quality of quantification (%, $, multipliers)
    """
    max_score = 20.0
    bullets = _all_bullets(resume)
    details = []
    tips = []

    if not bullets:
        return ReadabilityDimension(
            "Quantification", 0, max_score,
            details=["No bullet points to analyze"],
            tips=["Add metrics and numbers to demonstrate impact"],
        )

    quantified_count = 0
    quant_examples = []

    for b in bullets:
        matched = False
        for pattern in QUANTIFICATION_PATTERNS:
            match = re.search(pattern, b, re.IGNORECASE)
            if match:
                matched = True
                if len(quant_examples) < 3:
                    quant_examples.append(f'{match.group()} in: "{b[:50]}..."')
                break
        if matched:
            quantified_count += 1

    quant_ratio = quantified_count / len(bullets)
    details.append(f"{quantified_count}/{len(bullets)} bullets contain quantified results ({quant_ratio:.0%})")

    if quant_examples:
        details.append(f"Examples: {quant_examples[0]}")

    # Score: 0-30% = poor, 30-50% = ok, 50%+ = excellent
    if quant_ratio >= 0.5:
        score = max_score
    elif quant_ratio >= 0.3:
        score = max_score * 0.7 + (max_score * 0.3 * (quant_ratio - 0.3) / 0.2)
    else:
        score = max_score * 0.7 * (quant_ratio / 0.3)

    if quant_ratio < 0.3:
        tips.append("Add numbers to at least 30-50% of bullets: revenue, users, time saved, error reduction")
    if quant_ratio < 0.5:
        tips.append("Use specific metrics: '25% faster' is better than 'significantly faster'")

    return ReadabilityDimension("Quantification", score, max_score, details, tips)


def _score_sentence_complexity(resume: ResumeData) -> ReadabilityDimension:
    """
    Score 3: Sentence Complexity (15 pts)
    - Flesch-Kincaid grade level (target: 8-12)
    - Average words per bullet
    """
    max_score = 15.0
    bullets = _all_bullets(resume)
    details = []
    tips = []

    if not bullets:
        return ReadabilityDimension(
            "Sentence Complexity", max_score * 0.5, max_score,
            details=["No bullets to analyze"],
        )

    all_text = " ".join(bullets)
    fk_grade = _flesch_kincaid_grade(all_text)

    avg_words = sum(len(b.split()) for b in bullets) / len(bullets)
    details.append(f"Flesch-Kincaid grade level: {fk_grade:.1f}")
    details.append(f"Average words per bullet: {avg_words:.1f}")

    # Ideal FK grade for resumes: 8-12
    if 8 <= fk_grade <= 12:
        grade_score = 1.0
    elif 6 <= fk_grade < 8 or 12 < fk_grade <= 14:
        grade_score = 0.7
    else:
        grade_score = 0.4
        if fk_grade > 14:
            tips.append("Simplify language — use shorter sentences and common words")
        elif fk_grade < 6:
            tips.append("Add more technical depth — your language may be too simple")

    # Ideal avg words: 10-25
    if 10 <= avg_words <= 25:
        words_score = 1.0
    elif 7 <= avg_words < 10 or 25 < avg_words <= 35:
        words_score = 0.7
    else:
        words_score = 0.4
        if avg_words > 35:
            tips.append("Shorten bullets — aim for 10-25 words per bullet point")
        elif avg_words < 7:
            tips.append("Bullets are too terse — add context about what you did and the impact")

    score = max_score * (0.5 * grade_score + 0.5 * words_score)

    return ReadabilityDimension("Sentence Complexity", score, max_score, details, tips)


def _score_section_balance(resume: ResumeData) -> ReadabilityDimension:
    """
    Score 4: Section Balance (15 pts)
    - Has all key sections
    - Reasonable content distribution
    - Page count appropriateness
    """
    max_score = 15.0
    details = []
    tips = []

    # Check for key sections
    sections_found = {s.normalized_name.lower() for s in (resume.sections or []) if getattr(s, 'normalized_name', None)}
    if not sections_found:
        # Fall back to checking data presence
        sections_found = set()
        if resume.experience:
            sections_found.add("experience")
        if resume.education:
            sections_found.add("education")
        if resume.skills:
            sections_found.add("skills")
        if resume.projects:
            sections_found.add("projects")
        if resume.summary:
            sections_found.add("summary")
        if resume.certifications:
            sections_found.add("certifications")

    essential = {"experience", "education", "skills"}
    recommended = {"summary", "projects"}

    essential_present = essential & sections_found
    recommended_present = recommended & sections_found
    essential_missing = essential - sections_found
    recommended_missing = recommended - sections_found

    details.append(f"Essential sections: {len(essential_present)}/{len(essential)} present")
    if essential_missing:
        details.append(f"Missing essential: {', '.join(essential_missing)}")
        tips.append(f"Add missing sections: {', '.join(essential_missing)}")

    if recommended_missing:
        details.append(f"Missing recommended: {', '.join(recommended_missing)}")
        tips.append(f"Consider adding: {', '.join(recommended_missing)}")

    section_score = (len(essential_present) / len(essential)) * 0.7 + \
                    (len(recommended_present) / len(recommended)) * 0.3

    # Check page count
    page_count = (
        getattr(resume.layout_metadata, 'page_count', 0)
        or getattr(resume.document_metadata, 'page_count', 0)
        or 0
    )
    if page_count > 0:
        if page_count == 1:
            page_score = 1.0
        elif page_count == 2:
            page_score = 0.9
            details.append("2 pages — acceptable for experienced candidates")
        elif page_count == 3:
            page_score = 0.6
            details.append("3 pages — consider condensing")
            tips.append("Aim for 1-2 pages unless you have 10+ years of experience")
        else:
            page_score = 0.3
            details.append(f"{page_count} pages — too long for most roles")
            tips.append("Trim to 1-2 pages — focus on recent, relevant experience")
    else:
        page_score = 0.8  # Can't check, neutral

    score = max_score * (0.6 * section_score + 0.4 * page_score)

    return ReadabilityDimension("Section Balance", score, max_score, details, tips)


def _score_consistency(resume: ResumeData) -> ReadabilityDimension:
    """
    Score 5: Formatting Consistency (15 pts)
    - Bullet punctuation consistency
    - Date format consistency
    - Tense consistency in experience
    """
    max_score = 15.0
    bullets = _all_bullets(resume)
    details = []
    tips = []

    if not bullets:
        return ReadabilityDimension(
            "Formatting Consistency", max_score * 0.5, max_score,
            details=["No bullets to check for consistency"],
        )

    # Punctuation consistency
    ends_with_period = sum(1 for b in bullets if b.rstrip().endswith('.'))
    ends_without = len(bullets) - ends_with_period
    if ends_with_period > 0 and ends_without > 0:
        dominant = max(ends_with_period, ends_without)
        punct_ratio = dominant / len(bullets)
        if punct_ratio < 0.8:
            details.append(f"Inconsistent punctuation: {ends_with_period} end with period, {ends_without} don't")
            tips.append("Be consistent — either end ALL bullets with periods or none")
        else:
            details.append("Mostly consistent punctuation")
    else:
        punct_ratio = 1.0
        details.append("Consistent bullet punctuation")

    # Tense consistency in experience
    past_tense_count = 0
    present_tense_count = 0
    for exp in (resume.experience or []):
        for b in (exp.bullets or []):
            first_word = re.match(r'^([a-zA-Z]+)', b)
            if first_word:
                word = first_word.group(1).lower()
                if word.endswith('ed') or word.endswith('ew') or word in {'led', 'built', 'wrote', 'ran', 'set', 'cut'}:
                    past_tense_count += 1
                elif word.endswith('ing') or word.endswith('s') and not word.endswith('ss'):
                    present_tense_count += 1

    total_tense = past_tense_count + present_tense_count
    if total_tense > 0:
        dominant_tense = max(past_tense_count, present_tense_count)
        tense_ratio = dominant_tense / total_tense
        if tense_ratio < 0.7:
            details.append(f"Mixed tenses: {past_tense_count} past, {present_tense_count} present")
            tips.append("Use past tense for previous roles, present tense only for current role")
        else:
            details.append("Consistent tense usage")
    else:
        tense_ratio = 0.8  # Neutral

    # Date format consistency
    dates = []
    for exp in (resume.experience or []):
        if exp.start_date:
            dates.append(exp.start_date)
        if exp.end_date:
            dates.append(exp.end_date)
    for edu in (resume.education or []):
        if edu.start_date:
            dates.append(edu.start_date)
        if edu.end_date:
            dates.append(edu.end_date)

    if len(dates) >= 2:
        # Check if dates follow similar formats
        has_month_year = sum(1 for d in dates if re.search(r'[A-Za-z]+\s*\d{4}', d))
        has_num_date = sum(1 for d in dates if re.search(r'\d{1,2}/\d{1,2}/\d{2,4}', d))
        has_year_only = sum(1 for d in dates if re.match(r'^\d{4}$', d.strip()))

        formats_used = sum(1 for x in [has_month_year, has_num_date, has_year_only] if x > 0)
        if formats_used > 1:
            date_ratio = 0.5
            details.append("Inconsistent date formats detected")
            tips.append("Use the same date format throughout (e.g., 'Jan 2023' everywhere)")
        else:
            date_ratio = 1.0
            details.append("Consistent date formatting")
    else:
        date_ratio = 0.8

    score = max_score * (0.35 * punct_ratio + 0.35 * tense_ratio + 0.3 * date_ratio)

    return ReadabilityDimension("Formatting Consistency", score, max_score, details, tips)


def _score_scannability(resume: ResumeData) -> ReadabilityDimension:
    """
    Score 6: Scannability (10 pts)
    - Bullet count per job (3-6 ideal)
    - Skills presented in categorised lists
    - Summary/objective present and concise
    """
    max_score = 10.0
    details = []
    tips = []

    # Bullets per experience entry
    exp_bullet_counts = [len(exp.bullets or []) for exp in (resume.experience or [])]
    if exp_bullet_counts:
        avg_bullets = sum(exp_bullet_counts) / len(exp_bullet_counts)
        ideal_count = sum(1 for c in exp_bullet_counts if 3 <= c <= 6)
        details.append(f"Average {avg_bullets:.1f} bullets per role")

        if avg_bullets < 2:
            bullet_score = 0.3
            tips.append("Add 3-6 bullets per experience entry")
        elif avg_bullets > 8:
            bullet_score = 0.5
            tips.append("Trim to 3-6 bullets per role — focus on the most impactful ones")
        elif 3 <= avg_bullets <= 6:
            bullet_score = 1.0
        else:
            bullet_score = 0.7
    else:
        bullet_score = 0.3
        details.append("No experience entries with bullets")

    # Categorised skills
    if resume.skills:
        cat_count = len(resume.skills)
        total_skills = sum(len(cat.skills or []) for cat in resume.skills)
        if cat_count >= 2 and total_skills > 5:
            skills_score = 1.0
            details.append(f"Skills well-organized in {cat_count} categories")
        elif cat_count >= 1:
            skills_score = 0.7
            details.append(f"Skills in {cat_count} category — consider more grouping")
            tips.append("Group skills into categories (Languages, Frameworks, Tools, etc.)")
        else:
            skills_score = 0.4
    else:
        skills_score = 0.3
        tips.append("Add a dedicated Skills section with categorised technical skills")

    # Summary
    if resume.summary and len(resume.summary) > 20:
        if len(resume.summary) <= 300:
            summary_score = 1.0
            details.append("Summary present and concise")
        else:
            summary_score = 0.6
            details.append(f"Summary is {len(resume.summary)} chars — consider shortening")
            tips.append("Keep your summary to 2-3 sentences (under 300 characters)")
    else:
        summary_score = 0.4
        tips.append("Add a 2-3 sentence professional summary at the top")

    score = max_score * (0.4 * bullet_score + 0.3 * skills_score + 0.3 * summary_score)

    return ReadabilityDimension("Scannability", score, max_score, details, tips)


# ── Main entry point ─────────────────────────────────────────────

def run_readability_analysis(resume: ResumeData) -> ReadabilityResult:
    """
    Run the full Resume Readability Index (RRI) analysis.
    Returns scores across 6 dimensions with actionable tips.
    """
    dimensions = [
        _score_bullet_quality(resume),
        _score_quantification(resume),
        _score_sentence_complexity(resume),
        _score_section_balance(resume),
        _score_consistency(resume),
        _score_scannability(resume),
    ]

    return ReadabilityResult(dimensions)

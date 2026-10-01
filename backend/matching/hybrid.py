"""
Phase 4+5 — Hybrid Semantic Matching & Evidence Tracing.
Combines exact/normalized skill matching + taxonomy matching +
real embedding-based semantic similarity (BGE-small) +
rule-based experience/project scoring.
"""
import re
from typing import Optional

from backend.schemas.resume import ResumeData
from backend.schemas.jd import JDData, JDRequirement, RequirementType
from backend.schemas.analysis import (
    HybridMatchResult, MatchDimensionScore, SkillMatch, SkillMatchType,
)
from backend.nlp.skills import (
    normalize_skill, normalize_skill_list, find_skill_match_type,
    get_related_skills,
)
from backend.config import settings
from backend.nlp import embeddings


def _find_evidence(skill: str, resume: ResumeData) -> list[str]:
    """Search for a skill mention in resume bullets and project technologies."""
    evidence = []
    skill_lower = skill.lower()
    for exp in resume.experience:
        for bullet in exp.bullets:
            if skill_lower in bullet.lower():
                evidence.append(f"Experience ({exp.company}): {bullet[:100]}")
    for proj in resume.projects:
        for bullet in proj.bullets:
            if skill_lower in bullet.lower():
                evidence.append(f"Project ({proj.name}): {bullet[:100]}")
        if skill in (proj.technologies or []):
            evidence.append(f"Project ({proj.name}): listed in technologies")
    return evidence[:3]


def _match_skills(jd: JDData, resume: ResumeData) -> list[SkillMatch]:
    """
    Match every JD skill against resume skills.
    Phase 5 upgrade: after alias/taxonomy/substring matching, uses
    embedding similarity as a fallback for unmatched skills.
    Classifies as: direct, related, partial, semantic, or missing.
    """
    resume_skills = resume.all_skills_flat
    matches = []
    seen = set()
    unmatched_jd_skills = []  # Skills that failed alias/taxonomy matching

    all_jd_skills = list(set(jd.required_skills + jd.preferred_skills))

    for jd_skill in all_jd_skills:
        if jd_skill.lower() in seen:
            continue
        seen.add(jd_skill.lower())

        match_type_str, matched_skill = find_skill_match_type(jd_skill, resume_skills)

        if match_type_str == "missing":
            # Defer — will try embedding fallback below
            unmatched_jd_skills.append(jd_skill)
            continue

        evidence = _find_evidence(matched_skill, resume) if matched_skill else []

        match_type_enum = {
            "direct": SkillMatchType.DIRECT,
            "related": SkillMatchType.RELATED,
            "partial": SkillMatchType.PARTIAL,
        }.get(match_type_str, SkillMatchType.MISSING)

        confidence = {
            "direct": 1.0,
            "related": 0.6,
            "partial": 0.4,
        }.get(match_type_str, 0.0)

        matches.append(SkillMatch(
            jd_skill=jd_skill,
            resume_skill=matched_skill,
            match_type=match_type_enum,
            confidence=confidence,
            evidence=evidence,
        ))

    # ── Phase 5: Embedding-based fallback for unmatched skills ────
    if unmatched_jd_skills and resume_skills:
        embedding_matches = embeddings.batch_skill_similarities(
            unmatched_jd_skills,
            resume_skills,
            threshold=0.65,
        )

        # Build a lookup: jd_skill → best embedding match
        emb_lookup = {}
        if embedding_matches:  # None means embeddings unavailable
            for em in embedding_matches:
                jd_s = em["jd_skill"]
                if jd_s not in emb_lookup or em["similarity"] > emb_lookup[jd_s]["similarity"]:
                    emb_lookup[jd_s] = em

        for jd_skill in unmatched_jd_skills:
            if jd_skill in emb_lookup:
                em = emb_lookup[jd_skill]
                evidence = _find_evidence(em["resume_skill"], resume)
                matches.append(SkillMatch(
                    jd_skill=jd_skill,
                    resume_skill=em["resume_skill"],
                    match_type=SkillMatchType.RELATED,
                    confidence=round(em["similarity"] * 0.8, 2),  # Scaled down vs direct
                    evidence=evidence + [
                        f"Semantic similarity: {em['similarity']:.0%}"
                    ],
                ))
            else:
                matches.append(SkillMatch(
                    jd_skill=jd_skill,
                    resume_skill=None,
                    match_type=SkillMatchType.MISSING,
                    confidence=0.0,
                    evidence=[],
                ))

    return matches


def _score_required_skills(matches: list[SkillMatch], jd: JDData) -> MatchDimensionScore:
    """Score based on required skill coverage."""
    max_score = settings.match_weight_required_skills
    required = set(s.lower() for s in jd.required_skills)
    if not required:
        return MatchDimensionScore(
            dimension="Required Skills", score=max_score, max_score=max_score,
            details=["No required skills specified in JD"],
        )

    total_value = 0.0
    details = []
    for m in matches:
        if m.jd_skill.lower() in required:
            total_value += m.confidence
            status = f"✓ {m.jd_skill}" if m.confidence > 0 else f"✗ {m.jd_skill}"
            if m.resume_skill and m.match_type != SkillMatchType.DIRECT:
                status += f" (via {m.resume_skill}, {m.match_type.value})"
            details.append(status)

    coverage = total_value / len(required) if required else 0
    score = max_score * coverage

    return MatchDimensionScore(
        dimension="Required Skills",
        score=round(score, 1),
        max_score=max_score,
        details=details,
    )


def _score_preferred_skills(matches: list[SkillMatch], jd: JDData) -> MatchDimensionScore:
    """Score based on preferred skill coverage."""
    max_score = settings.match_weight_preferred_skills
    preferred = set(s.lower() for s in jd.preferred_skills)
    if not preferred:
        return MatchDimensionScore(
            dimension="Preferred Skills", score=max_score, max_score=max_score,
            details=["No preferred skills specified"],
        )

    total_value = 0.0
    details = []
    for m in matches:
        if m.jd_skill.lower() in preferred:
            total_value += m.confidence
            status = f"✓ {m.jd_skill}" if m.confidence > 0 else f"○ {m.jd_skill}"
            details.append(status)

    coverage = total_value / len(preferred) if preferred else 0
    score = max_score * coverage

    return MatchDimensionScore(
        dimension="Preferred Skills",
        score=round(score, 1),
        max_score=max_score,
        details=details,
    )


def _score_relevant_experience(resume: ResumeData, jd: JDData) -> MatchDimensionScore:
    """Score based on experience relevance to the JD."""
    max_score = settings.match_weight_relevant_experience
    details = []

    if not resume.experience:
        return MatchDimensionScore(
            dimension="Relevant Experience", score=0, max_score=max_score,
            details=["No experience entries found"],
        )

    jd_keywords = set()
    for req in jd.requirements:
        jd_keywords.update(w.lower() for w in re.findall(r"\b\w{3,}\b", req.text))
    jd_keywords.update(s.lower() for s in jd.all_skills_flat)

    total_relevance = 0.0
    for exp in resume.experience:
        all_text = " ".join(exp.bullets) + " " + (exp.title or "")
        exp_words = set(w.lower() for w in re.findall(r"\b\w{3,}\b", all_text))

        overlap = exp_words & jd_keywords
        relevance = len(overlap) / max(len(jd_keywords), 1)
        total_relevance += min(relevance, 1.0)

        if overlap:
            details.append(f"{exp.title} @ {exp.company}: {len(overlap)} keyword matches")

    avg_relevance = total_relevance / len(resume.experience)
    score = max_score * min(avg_relevance * 2, 1.0)  # Scale up, cap at max

    return MatchDimensionScore(
        dimension="Relevant Experience",
        score=round(score, 1),
        max_score=max_score,
        details=details[:5],
    )


def _score_relevant_projects(resume: ResumeData, jd: JDData) -> MatchDimensionScore:
    """Score based on project relevance."""
    max_score = settings.match_weight_relevant_projects
    details = []

    if not resume.projects:
        return MatchDimensionScore(
            dimension="Relevant Projects", score=0, max_score=max_score,
            details=["No projects found"],
        )

    jd_skills_lower = set(s.lower() for s in jd.all_skills_flat)

    relevant_count = 0
    for proj in resume.projects:
        proj_techs = set(t.lower() for t in proj.technologies)
        proj_text = " ".join(proj.bullets + [proj.description or ""])
        proj_words = set(w.lower() for w in re.findall(r"\b\w{3,}\b", proj_text))

        overlap = (proj_techs | proj_words) & jd_skills_lower
        if overlap:
            relevant_count += 1
            details.append(f"{proj.name}: matches {', '.join(list(overlap)[:5])}")

    coverage = relevant_count / len(resume.projects) if resume.projects else 0
    score = max_score * min(coverage * 1.5, 1.0)

    return MatchDimensionScore(
        dimension="Relevant Projects",
        score=round(score, 1),
        max_score=max_score,
        details=details[:5],
    )


def _score_responsibilities(resume: ResumeData, jd: JDData) -> MatchDimensionScore:
    """Score alignment between JD responsibilities and resume experience."""
    max_score = settings.match_weight_responsibilities

    if not jd.responsibilities:
        return MatchDimensionScore(
            dimension="Responsibilities Alignment", score=max_score, max_score=max_score,
            details=["No responsibilities specified in JD"],
        )

    resume_text = " ".join(
        b for exp in resume.experience for b in exp.bullets
    ).lower()

    matched = 0
    details = []
    for resp in jd.responsibilities:
        resp_keywords = set(w.lower() for w in re.findall(r"\b\w{4,}\b", resp))
        matches_found = sum(1 for kw in resp_keywords if kw in resume_text)
        if matches_found >= len(resp_keywords) * 0.3:
            matched += 1
            details.append(f"✓ {resp[:80]}...")
        else:
            details.append(f"○ {resp[:80]}...")

    coverage = matched / len(jd.responsibilities) if jd.responsibilities else 0
    score = max_score * coverage

    return MatchDimensionScore(
        dimension="Responsibilities Alignment",
        score=round(score, 1),
        max_score=max_score,
        details=details[:5],
    )


def _score_education(resume: ResumeData, jd: JDData) -> MatchDimensionScore:
    """Score education alignment."""
    max_score = settings.match_weight_education

    if not jd.education_requirements:
        return MatchDimensionScore(
            dimension="Education Alignment", score=max_score, max_score=max_score,
            details=["No education requirements specified"],
        )

    if not resume.education:
        return MatchDimensionScore(
            dimension="Education Alignment", score=0, max_score=max_score,
            details=["No education found in resume"],
        )

    # Simple check: does resume education match JD requirements?
    resume_edu_text = " ".join(
        f"{e.degree or ''} {e.field_of_study or ''} {e.institution or ''}"
        for e in resume.education
    ).lower()

    matched = 0
    details = []
    for req in jd.education_requirements:
        req_lower = req.lower()
        if any(kw in resume_edu_text for kw in re.findall(r"\b\w{4,}\b", req_lower)):
            matched += 1
            details.append(f"✓ {req[:80]}")
        else:
            details.append(f"○ {req[:80]}")

    coverage = matched / len(jd.education_requirements) if jd.education_requirements else 0
    score = max_score * coverage

    return MatchDimensionScore(
        dimension="Education Alignment",
        score=round(score, 1),
        max_score=max_score,
        details=details,
    )


def _score_semantic_relevance(resume: ResumeData, jd: JDData) -> MatchDimensionScore:
    """
    Phase 5 — Semantic/domain relevance via real embeddings.
    Uses document-level cosine similarity from BGE-small-en-v1.5.
    Falls back to word overlap if the embedding model is unavailable.
    """
    max_score = settings.match_weight_semantic_relevance

    if not jd.raw_text.strip():
        return MatchDimensionScore(
            dimension="Semantic/Domain Relevance", score=max_score, max_score=max_score,
            details=["No JD text to compare"],
        )

    # ── Try embedding-based similarity first ─────────────────────
    doc_sim = embeddings.document_similarity(resume.raw_text, jd.raw_text)

    if doc_sim is not None:
        # doc_sim is in [-1, 1] for normalised vectors; for BGE it's
        # typically in [0, 1] since texts are always positive-ish.
        # Map the useful range [0.3, 0.85] → [0, 1] for scoring.
        normalized = max(0.0, min((doc_sim - 0.3) / 0.55, 1.0))
        score = max_score * normalized

        details = [
            f"Embedding similarity: {doc_sim:.1%} (BGE-small-en-v1.5)",
        ]

        # Add chunk-level highlights for richer feedback
        resume_chunks = _extract_chunks(resume)
        jd_chunks = _extract_jd_chunks(jd)

        if resume_chunks and jd_chunks:
            chunk_matches = embeddings.chunk_similarities(
                jd_chunks[:10],   # Top 10 JD requirements
                resume_chunks[:30],  # Top 30 resume bullets
                top_k=1,
            )
            if chunk_matches:
                top_pairs = chunk_matches[:3]
                for pair in top_pairs:
                    details.append(
                        f"JD→Resume match ({pair['similarity']:.0%}): "
                        f'"{pair["query_text"]}..." ↔ "{pair["corpus_text"]}..."'
                    )

        return MatchDimensionScore(
            dimension="Semantic/Domain Relevance",
            score=round(score, 1),
            max_score=max_score,
            details=details,
        )

    # ── Fallback: word overlap (same as Phase 4 placeholder) ─────
    resume_words = set(w.lower() for w in re.findall(r"\b\w{4,}\b", resume.raw_text))
    jd_words = set(w.lower() for w in re.findall(r"\b\w{4,}\b", jd.raw_text))

    overlap = resume_words & jd_words
    jaccard = len(overlap) / len(resume_words | jd_words) if (resume_words | jd_words) else 0
    score = max_score * min(jaccard * 5, 1.0)

    return MatchDimensionScore(
        dimension="Semantic/Domain Relevance",
        score=round(score, 1),
        max_score=max_score,
        details=[f"Word overlap: {len(overlap)} shared terms (embedding model unavailable)"],
    )


def _extract_chunks(resume: ResumeData) -> list[str]:
    """Extract meaningful text chunks from the resume for chunk-level matching."""
    chunks = []
    if resume.summary:
        chunks.append(resume.summary)
    for exp in resume.experience:
        for bullet in exp.bullets:
            if len(bullet.strip()) > 15:
                chunks.append(bullet.strip())
    for proj in resume.projects:
        if proj.description:
            chunks.append(proj.description)
        for bullet in proj.bullets:
            if len(bullet.strip()) > 15:
                chunks.append(bullet.strip())
    return chunks


def _extract_jd_chunks(jd: JDData) -> list[str]:
    """Extract meaningful text chunks from the JD for chunk-level matching."""
    chunks = []
    for req in jd.requirements:
        if len(req.text.strip()) > 15:
            chunks.append(req.text.strip())
    for resp in jd.responsibilities:
        if len(resp.strip()) > 15:
            chunks.append(resp.strip())
    return chunks


def run_hybrid_matching(resume: ResumeData, jd: JDData) -> HybridMatchResult:
    """
    Run the full hybrid matching pipeline.
    Returns scores per dimension + per-skill match details with evidence.
    """
    # Step 1: Match all skills
    skill_matches = _match_skills(jd, resume)

    # Step 2: Score each dimension
    dimension_scores = [
        _score_required_skills(skill_matches, jd),
        _score_preferred_skills(skill_matches, jd),
        _score_relevant_experience(resume, jd),
        _score_relevant_projects(resume, jd),
        _score_responsibilities(resume, jd),
        _score_education(resume, jd),
        _score_semantic_relevance(resume, jd),
    ]

    overall = sum(d.score for d in dimension_scores)
    max_possible = sum(d.max_score for d in dimension_scores)

    # Classify skills
    matched = [m.jd_skill for m in skill_matches if m.match_type == SkillMatchType.DIRECT]
    missing = [m.jd_skill for m in skill_matches if m.match_type == SkillMatchType.MISSING]
    partial = [m.jd_skill for m in skill_matches
               if m.match_type in (SkillMatchType.RELATED, SkillMatchType.PARTIAL)]

    return HybridMatchResult(
        overall_score=round(overall, 1),
        max_possible=max_possible,
        dimension_scores=dimension_scores,
        skill_matches=skill_matches,
        matched_skills=matched,
        missing_skills=missing,
        partial_skills=partial,
    )

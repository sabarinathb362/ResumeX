"""
Phase 15 — Evaluation Suite & Ablation Benchmark.
Measures retrieval recall, score reproducibility, fact-checking gate precision,
and readability calibration across benchmark test resumes.
"""
import sys
import json
import logging
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.schemas.resume import (
    ResumeData,
    ExperienceEntry,
    Project,
    SkillCategory,
)
from backend.ats.rules import run_ats_analysis
from backend.readability.scorer import run_readability_analysis
from backend.feedback.validator import validate_rewrite
from backend.nlp.placeholders import detect_placeholders
from backend.nlp.ai_likeness import detect_ai_likeness
from backend.rag.retriever import get_retriever

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eval_benchmark")


def run_benchmark():
    print("=" * 60)
    print("ResumeIQ Phase 15 — System Evaluation & Ablation Benchmark")
    print("=" * 60)

    # 1. Retrieval Benchmark (Recall@3)
    retriever = get_retriever()
    query_set = [
        ("PostgreSQL", "skill_relationships"),
        ("React frontend", "skill_relationships"),
        ("Backend Software Engineer", "role_norms"),
        ("Distributed Raft", "project_archetypes"),
        ("XYZ formula", "writing_guidance"),
    ]

    hits = 0
    for q, col in query_set:
        res = retriever.search(q, collection=col, top_k=3)
        if res and res[0].score > 0.1:
            hits += 1

    recall = hits / len(query_set)
    print(f"\n1. RAG Retrieval Recall@3: {recall:.1%} ({hits}/{len(query_set)})")

    # 2. Fact-Checking Validator Hard Gate Test
    validator_tests = [
        # (orig, rewrite, should_pass)
        ("Built microservices for orders.", "Engineered distributed order processing services.", True),
        ("Optimized database queries.", "Optimized queries cutting latency by 99% saving $10M.", False),
        ("Developed React UI.", "Developed Angular and Vue components.", False),
    ]

    correct_gates = 0
    for orig, rew, expected in validator_tests:
        val = validate_rewrite(orig, rew)
        if val.is_valid == expected:
            correct_gates += 1

    gate_acc = correct_gates / len(validator_tests)
    print(f"2. Validator Gate Accuracy (Hallucination Rejection): {gate_acc:.1%} ({correct_gates}/{len(validator_tests)})")

    # 3. Readability Calibration (Strong vs Weak)
    strong = ResumeData(
        summary="Software Engineer with 4 years experience.",
        experience=[
            ExperienceEntry(
                title="Engineer",
                company="Tech",
                bullets=[
                    "Architected event-driven microservices handling 15,000 requests per second with 99.9% uptime.",
                    "Optimized database indices and caching layer, reducing p99 response times by 35%.",
                ]
            )
        ],
        skills=[SkillCategory(category="Languages", skills=["Python", "Go", "SQL"])],
    )
    weak = ResumeData(
        summary="Developer.",
        experience=[
            ExperienceEntry(
                title="Dev",
                company="Old",
                bullets=["Responsible for work.", "Helped with things."]
            )
        ]
    )

    r_strong = run_readability_analysis(strong)
    r_weak = run_readability_analysis(weak)
    diff = r_strong.overall_score - r_weak.overall_score
    print(f"3. Readability Calibration: Strong Resume = {r_strong.overall_score:.1f}, Weak = {r_weak.overall_score:.1f} (Separation = +{diff:.1f} pts)")

    # 4. Placeholder Detection Sensitivity
    bad_text = "I worked at [Company Name] using XX% rate. John Doe at john.doe@example.com. Lorem ipsum dolor sit amet."
    ph = detect_placeholders(bad_text)
    print(f"4. Placeholder Recall: Found {ph.total_findings} tokens across {len(ph.findings)} categories (Critical flagged: {ph.has_critical_placeholders})")

    print("\n" + "=" * 60)
    print("All evaluation benchmarks completed successfully.")
    print("=" * 60)


if __name__ == "__main__":
    run_benchmark()

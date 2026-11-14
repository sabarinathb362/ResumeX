"""Phase 1: the fact-checker keeps blocking fabrication but stops rejecting honest rewrites."""
import pytest

from backend.feedback.validator import validate_rewrite, extract_numbers

OK = [
    ("Deployed services on k8s with Docker.", "Deployed containerized services on Kubernetes.", "", None),
    ("Hosted the API on Amazon Web Services.", "Hosted the API on AWS.", "", None),
    ("Tuned PostgreSQL indexes for the reporting service.", "Tuned relational database indexes for the reporting service.", "", None),
    ("Built a FastAPI service for invoices.", "Built an invoice API with FastAPI.", "", None),
    ("Shipped the feature before the spring release.", "Shipped the feature ahead of the spring release.", "", None),
    ("Prepared the next sprint plan.", "Planned the next sprint.", "", None),
    ("Mentored three interns.", "Mentored 3 interns.", "", None),
    ("Processed 1,200 records daily.", "Processed 1.2k records daily.", "", None),
    ("Built a dashboard.", "Built a dashboard in 2024.", "Intern 2024 – Present", None),
    ("Automated the weekly report.", "Automated the weekly report, saving 6 hours a week.", "", {"saves 6 hours a week"}),
    ("Optimized database query performance, reducing p99 latency by 45%.",
     "Refactored PostgreSQL queries and indexing, cutting p99 latency by 45%.", "PostgreSQL database engineer", None),
]

BLOCKED = [
    ("Tuned relational database indexes for the reporting service.", "Tuned PostgreSQL indexes for the reporting service."),
    ("Built a FastAPI service for invoices.", "Built a REST-style API for invoices."),
    ("Built a Java service.", "Built a Spring Boot service."),
    ("Wrote JavaScript widgets.", "Wrote Java widgets."),
    ("Cut query latency from 850ms to 120ms.", "Cut query latency 60% (850ms to 120ms)."),
    ("Built microservices for customer payments.", "Built microservices with 99.9% uptime processing $5M in payments."),
    ("Worked on backend services for the team.", "Served 10k users at Google."),
]


@pytest.mark.parametrize("orig,rewrite,ctx,allowed", OK)
def test_honest_rewrites_pass(orig, rewrite, ctx, allowed):
    r = validate_rewrite(orig, rewrite, ctx, allowed)
    assert r.is_valid, r.unsupported_facts


@pytest.mark.parametrize("orig,rewrite", BLOCKED)
def test_fabrication_is_blocked(orig, rewrite):
    assert not validate_rewrite(orig, rewrite, orig).is_valid


def test_derived_metric_passes_with_warning():
    r = validate_rewrite("Cut query latency from 850ms to 120ms.", "Cut query latency 86% (850ms to 120ms).")
    assert r.is_valid and r.warnings


def test_number_parsing():
    assert extract_numbers("$5M, 10k users, three teams, 2.5x faster, ResNet-50") == {5e6, 1e4, 3.0, 2.5, 50.0}

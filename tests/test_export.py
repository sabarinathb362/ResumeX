"""
Tests for Export Engine (DOCX, LaTeX, PDF, TXT).
"""
import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

SAMPLE_RESUME = {
    "contact": {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "phone": "+1-555-0199",
        "location": "San Francisco, CA",
        "linkedin": "https://linkedin.com/in/janedoe",
        "github": "https://github.com/janedoe",
    },
    "summary": "Full-stack engineer with 6+ years experience architecting cloud applications.",
    "experience": [
        {
            "company": "Tech Corp",
            "title": "Senior Software Engineer",
            "start_date": "2021",
            "end_date": "Present",
            "location": "San Francisco, CA",
            "bullets": [
                "Architected distributed microservices handling 10M+ daily events.",
                "Reduced p99 API latency from 450ms to 85ms across 12 services.",
            ],
        }
    ],
    "education": [
        {
            "institution": "University of California, Berkeley",
            "degree": "B.S.",
            "field_of_study": "Computer Science",
            "start_date": "2015",
            "end_date": "2019",
            "gpa": "3.85",
            "highlights": ["Dean's Honors List", "Teaching Assistant for CS61B"],
        }
    ],
    "skills": [
        {
            "category": "Languages",
            "skills": ["Python", "TypeScript", "Go", "SQL"],
        },
        {
            "category": "Frameworks",
            "skills": ["FastAPI", "React", "Docker", "Kubernetes"],
        }
    ],
    "projects": [
        {
            "name": "ResumeIQ",
            "technologies": ["Python", "FastAPI", "React"],
            "url": "https://github.com/example/resumeiq",
            "bullets": ["Engineered local-first resume optimization platform."],
        }
    ],
    "certifications": [
        {
            "name": "AWS Certified Solutions Architect",
            "issuer": "Amazon Web Services",
            "date": "2023",
        }
    ],
}


def test_export_docx():
    resp = client.post("/api/export/docx", json={"resume_data": SAMPLE_RESUME, "filename": "test_resume"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert len(resp.content) > 1000
    assert "attachment; filename=\"test_resume.docx\"" in resp.headers["content-disposition"]


def test_export_latex():
    resp = client.post("/api/export/latex", json={"resume_data": SAMPLE_RESUME, "filename": "test_resume"})
    assert resp.status_code == 200
    assert "application/x-tex" in resp.headers["content-type"]
    tex_text = resp.text
    assert "\\begin{document}" in tex_text
    assert "Jane Doe" in tex_text
    assert "Tech Corp" in tex_text
    assert "\\end{document}" in tex_text


def test_export_pdf():
    resp = client.post("/api/export/pdf", json={"resume_data": SAMPLE_RESUME, "filename": "test_resume"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")
    assert len(resp.content) > 1000


def test_export_txt():
    resp = client.post("/api/export/txt", json={"resume_data": SAMPLE_RESUME, "filename": "test_resume"})
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "Jane Doe" in resp.text
    assert "EXPERIENCE" in resp.text
    assert "Architected distributed microservices" in resp.text

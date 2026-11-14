"""Phase 4: mock interview plan + STAR grading. No Ollama needed: the LLM client is faked."""
from types import SimpleNamespace as N

import pytest

import backend.llm.client as llm_client
from backend.interview import engine
from backend.interview.star import finalize


def _st(i, t):
    return N(id=i, text=t)


RESUME = N(doc_sections=[
    N(kind="experience", heading="Experience", entries=[N(title="Backend Intern, Acme", statements=[
        _st("s1", "Built a FastAPI invoice service used by 3 finance teams."),
        _st("s2", "Cut report generation time from 40 to 5 minutes by caching PostgreSQL queries."),
        _st("s3", "Helped with testing.")])]),
    N(kind="projects", heading="Projects", entries=[N(title="Raft KV store", statements=[
        _st("s4", "Implemented leader election in Go.")])]),
    N(kind="skills", heading="Skills", entries=[N(title="", statements=[_st("s5", "Python, Go")])]),
])
GRADES = [N(id="s1", grade="B", has_metric=True), N(id="s2", grade="A", has_metric=True),
          N(id="s3", grade="D", has_metric=False), N(id="s4", grade="C", has_metric=False)]
JD = N(requirements=[N(text="Experience with Kubernetes"), N(text="Design REST APIs")])
EVIDENCE = [s.text for s in RESUME.doc_sections[0].entries[0].statements]
ANSWER = ("At Acme our finance reports took 40 minutes. I was responsible for making them faster. "
          "I profiled the slow PostgreSQL queries and added a cache. Report time fell to 5 minutes for 3 teams, "
          "and we saved 20 hours a month.")


class FakeClient:
    def __init__(self, online, replies):
        self.online, self.replies, self.calls = online, replies, []

    def is_online(self):
        return self.online

    def generate(self, system, user, json_schema=None, temperature=0.0, tier="deep", **_):
        self.calls.append((system, tier))
        return N(raw_json=self.replies.get(system), fallback_used=False)


@pytest.fixture
def fake(monkeypatch):
    def install(online=False, replies=None):
        c = FakeClient(online, replies or {})
        monkeypatch.setattr(llm_client, "get_llm_client", lambda: c)
        return c
    return install


def test_offline_plan_is_grounded(fake):
    fake(online=False)
    plan = engine.build_plan(RESUME, GRADES, jd=JD, company="Amazon", signals=["Data-Driven"])
    r1, r2, r3 = plan["rounds"]
    assert [q["probes"] for q in r1["questions"]] == ["s2", "s1", "s4"]        # strongest first, skills skipped
    assert [q["probes"] for q in r2["questions"]] == ["Experience with Kubernetes", "Design REST APIs"]
    assert r3["questions"][0]["probes"] == "Customer Obsession"
    assert plan["values_source"].startswith("https://www.amazon.jobs/")
    assert "not questions this company is known to ask" in plan["disclosure"]


def test_llm_question_without_valid_citation_is_dropped(fake):
    from backend.llm.prompts import INTERVIEW_QUESTION_SYSTEM
    fake(online=True, replies={INTERVIEW_QUESTION_SYSTEM: {"questions": [
        {"text": "How did caching change the query plan?", "probes": "s2"},
        {"text": "Tell me about your time at Google.", "probes": "s99"}]}})
    plan = engine.build_plan(RESUME, GRADES, jd=JD)
    assert [q["text"] for q in plan["rounds"][0]["questions"]] == ["How did caching change the query plan?"]
    assert plan["rounds"][1]["questions"][0]["probes"] == "Experience with Kubernetes"   # template kept


def test_fabricated_quote_is_capped_and_score_computed_in_code():
    labels = {"situation": {"present": True, "quote": "At Acme our finance reports took 40 minutes.", "score": 8},
              "task": {"present": True, "quote": "I was responsible for making them faster.", "score": 6},
              "action": {"present": True, "quote": "I rewrote the whole system in Rust.", "score": 10},
              "result": {"present": True, "quote": "Report time fell to 5 minutes for 3 teams", "score": 10},
              "tip": "Say how you chose what to cache.",
              "stronger_answer": "I cut report time from 40 to 5 minutes for 3 teams, saving $50,000 a year."}
    out = finalize(labels, ANSWER, EVIDENCE, "llm")
    assert out["parts"]["action"]["score"] == 3 and out["parts"]["action"]["quote_verified"] is False
    assert out["overall"] == 66.5
    assert out["numbers_not_on_resume"] == ["20"]
    assert out["stronger_answer"] is None                       # $50,000 appears nowhere


def test_heuristic_fallback_and_tier(fake):
    fake(online=False)
    good = engine.grade_answer("q", ANSWER, EVIDENCE)
    weak = engine.grade_answer("q", "We worked on a project as a team and it went well.", EVIDENCE)
    assert good["method"] == "heuristic" and good["overall"] > weak["overall"]
    assert "personally" in weak["tip"]
    from backend.llm.prompts import STAR_GRADER_SYSTEM
    from backend.config import settings
    c = fake(online=True, replies={STAR_GRADER_SYSTEM: {p: {"present": True, "quote": "", "score": 6}
                                                        for p in ("situation", "task", "action", "result")}})
    assert engine.grade_answer("q", ANSWER, EVIDENCE)["method"] == "llm"
    assert c.calls[-1] == (STAR_GRADER_SYSTEM, settings.llm_interview_tier)

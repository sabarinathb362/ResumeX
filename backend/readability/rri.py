"""
Phase 10 — Readability Reviewer (ATS 2.0): Recruiter Readability Index (RRI).

ATS asks "can a parser read this?". RRI asks "in the first skim, does a human
understand who this person is, what they did, and why it matters?".

Design rules (from the implementation plan):
  * The LLM never produces a score. It produces labels (bullet grade, inferred
    role, strengths) that are aggregated by fixed, versioned formulas here.
  * Everything works without the LLM. When Ollama is online the LLM adds a
    skim-test vote and a grading vote; disagreement lowers confidence.
  * Every finding cites line ids (for the editor overlay) and, when it is
    role-specific, the role-norm chunk it came from.
  * Suggestions only rearrange or trim words that are already in the resume.
    Where a fact is missing (a metric, a tool) we ASK — we never invent it.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from backend.config import settings
from backend.schemas.resume import ResumeData, DocSection, DocEntry, Statement
from backend.schemas.analysis import (
    ReadabilityResult, ReadabilityDimensionScore, Finding, StatementGrade,
    SkimSnapshot, Severity,
)

RRI_VERSION = "2.0"

WEIGHTS = {  # plan section 10, kept in one place so they can be tuned + versioned
    "First-impression clarity": 20,
    "Impact & evidence density": 20,
    "Specificity & concreteness": 15,
    "Clarity & concision": 15,
    "Visual hierarchy & scan flow": 10,
    "Narrative coherence": 10,
    "Role-norm alignment": 10,
}

GRADED_KINDS = {"experience", "projects", "volunteer", "leadership", "extracurricular"}
# How much a weak bullet costs, by section. Reviewers weigh your only internship
# far more than a volunteering line.
SECTION_WEIGHT = {"experience": 1.6, "projects": 1.0, "leadership": 0.6, "volunteer": 0.4, "extracurricular": 0.3}
LOW_VALUE_KINDS = {"interests", "languages", "extracurricular", "declaration", "personal", "references"}
SKIM_WORDS = 8

# ── Lexicons ─────────────────────────────────────────────────────

ACTION_VERBS = {
    "achieved", "accelerated", "delivered", "drove", "exceeded", "generated", "improved",
    "increased", "reduced", "saved", "transformed", "launched", "pioneered", "boosted",
    "led", "managed", "mentored", "directed", "coordinated", "supervised", "oversaw",
    "spearheaded", "established", "organized", "organised", "founded", "built", "designed",
    "developed", "implemented", "engineered", "architected", "optimized", "optimised",
    "automated", "configured", "deployed", "integrated", "migrated", "refactored", "scaled",
    "streamlined", "analyzed", "analysed", "assessed", "evaluated", "investigated",
    "researched", "identified", "diagnosed", "audited", "benchmarked", "tested", "authored",
    "documented", "presented", "published", "trained", "fine-tuned", "finetuned", "created",
    "prototyped", "modeled", "modelled", "simulated", "conducted", "collected", "labeled",
    "annotated", "cleaned", "curated", "visualized", "won", "ranked", "represented",
    "shipped", "wrote", "programmed", "coded", "debugged", "fixed", "resolved", "cut",
    "lowered", "raised", "doubled", "tripled", "secured", "negotiated", "taught", "tutored",
}
PRESENT_FORMS = {"build", "design", "develop", "implement", "lead", "manage", "own", "train",
                 "evaluate", "test", "analyze", "analyse", "maintain", "deploy", "automate",
                 "research", "write", "create", "optimize", "optimise", "benchmark", "fine-tune"}
WEAK_OPENERS = re.compile(
    r"^(working on|worked on|responsible for|helped|helping|assisted|assisting|involved in|"
    r"participated in|part of|was part of|exposure to|familiar with|learning|learned|"
    r"interested in|tasked with|duties included|handled)\b", re.I)
VAGUE = re.compile(
    r"\b(various|several|multiple|many|a lot of|etc\.?|real-world applications?|intelligent "
    r"systems?|ai-driven|cutting[- ]edge|state[- ]of[- ]the[- ]art|passionate|hands-on|"
    r"dynamic|synergy|leverag\w+|robust|seamless(ly)?|innovative|with a focus on|"
    r"focused on|in order to|successfully|effectively)\b", re.I)
METRIC = re.compile(
    r"(\d+(?:\.\d+)?\s?%|\d+(?:\.\d+)?\s?[×x]\b|[$₹€£]\s?\d[\d,.]*\s?[kKmMbB]?|"
    r"\b\d[\d,.]*\s?(?:k|K|M|B)?\+?\s(?:users?|customers?|requests?|images?|samples?|records?|"
    r"rows?|students?|people|families|participants?|teams?|members?|hours?|days?|weeks?|"
    r"ms|seconds?|minutes?|fps|qps|endpoints?|apis?|models?|classes|nodes?|devices?|"
    r"villages?|downloads?|stars?|commits?)\b|\btop\s?\d+|\b#\d+\b|\b\d+\s?(?:st|nd|rd|th)\s+place)",
    re.I)
OUTCOME = re.compile(
    r"\b(achiev\w*|reduc\w*|improv\w*|increas\w*|decreas\w*|cut(ting)?|sav(ed|ing)|enabl\w*|"
    r"resulting|leading to|so that|boost\w*|accelerat\w*|published|won|ranked|adopted|"
    r"used by|serving|lower(ed|ing)|rais(ed|ing)|eliminat\w*|prevent\w*|recall|precision|"
    r"accuracy|f1|latency|throughput|uptime|faster|slower|fewer|more than)\b", re.I)
PASSIVE = re.compile(r"\b(was|were|been|being|is|are)\s+\w+ed\b(\s+by\b)?", re.I)
FIRST_PERSON = re.compile(r"\b(I|me|my|mine)\b")

ROLE_FAMILIES = {
    "ml_ai": ("AI / Machine Learning", "role_ml_engineer",
              ["ai", "machine learning", "deep learning", "computer vision", "nlp", "llm", "llms",
               "large language model", "pytorch", "tensorflow", "keras", "neural", "yolo",
               "yolov\\w*", "resnet", "transformer", "self-supervised", "simclr", "gru", "lstm",
               "cnn", "artificial intelligence", "data science", "shap", "scikit-learn",
               "hugging face", "accuracy", "recall", "f1", "classification", "detection"]),
    "data": ("Data Analyst", None,
             ["sql", "tableau", "power bi", "dashboard", "excel", "analytics", "pandas", "etl",
              "visualization", "bi", "reporting", "a/b test"]),
    "backend": ("Backend Engineer", "role_swe_backend",
                ["rest", "api", "apis", "microservice\\w*", "django", "flask", "fastapi", "spring",
                 "node\\.js", "postgres\\w*", "mysql", "mongodb", "redis", "docker", "kubernetes",
                 "backend", "server", "grpc", "kafka"]),
    "frontend": ("Frontend / Web Developer", "role_swe_frontend",
                 ["react(\\.js)?", "html", "css", "javascript", "typescript", "frontend",
                  "responsive", "web platform", "next\\.js", "tailwind", "ui", "ux"]),
    "embedded": ("Embedded / IoT Engineer", None,
                 ["iot", "embedded", "arduino", "nodemcu", "esp32", "microcontroller", "sensor\\w*",
                  "firmware", "raspberry pi", "infrared", "low-power"]),
    "creative": ("3D / Creative Designer", None,
                 ["blender", "photoshop", "premiere", "3d modelling", "3d modeling", "unreal",
                  "godot", "animation", "poster", "logo", "gimp", "davinci", "character design"]),
}
GENERIC_DEV = {"python", "java", "c", "c++", "git", "github", "linux", "sql", "javascript", "r"}

GERUND = {"developed": "developing", "built": "building", "designed": "designing",
          "created": "creating", "implemented": "implementing", "engineered": "engineering",
          "trained": "training", "deployed": "deploying", "optimized": "optimizing",
          "automated": "automating", "integrated": "integrating", "led": "leading",
          "organized": "organizing", "conducted": "conducting", "analyzed": "analyzing",
          "evaluated": "evaluating", "researched": "researching", "wrote": "writing",
          "architected": "architecting", "prototyped": "prototyping", "modeled": "modeling"}


# ── Helpers ──────────────────────────────────────────────────────

def _words(t: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][\w.+#×%-]*", t)


@lru_cache(maxsize=1)
def _known_skills() -> set[str]:
    try:
        from backend.nlp.skills import SKILL_ALIASES
        return {k.lower() for k in SKILL_ALIASES} | {v.lower() for v in SKILL_ALIASES.values()}
    except Exception:
        return set()


def _named_things(text: str, context_tags: list[str]) -> list[str]:
    """Concrete nouns a reviewer can check: tools, acronyms, model names, proper nouns."""
    found = []
    low = text.lower()
    for sk in _known_skills():
        if len(sk) > 2 and re.search(rf"(?<![\w]){re.escape(sk)}(?![\w])", low):
            found.append(sk)
    toks = _words(text)
    for i, w in enumerate(toks):
        if i == 0:
            continue
        if re.match(r"^[A-Z]{2,}[\w-]*$", w) or re.match(r"^[A-Z][a-z]+[A-Z]\w*$", w) \
                or re.match(r"^[A-Za-z]+-?\d+\w*$", w):
            found.append(w)
    for t in context_tags:
        if t and t.lower() in low:
            found.append(t)
    return sorted(set(found))


def _metric_phrase(text: str) -> Optional[str]:
    m = re.search(METRIC.pattern + r"(\s(?:accuracy|recall|precision|f1(?:-score)?|faster|reduction|"
                  r"fewer|less|more|improvement|speed-?up|uptime|latency))?", text, re.I)
    return re.sub(r"\s+×", "×", m.group(0).strip()) if m else None


def _first_metric_pos(text: str) -> Optional[int]:
    m = METRIC.search(text)
    if not m:
        return None
    return len(_words(text[:m.start()]))


def _role_scores(text: str) -> dict[str, float]:
    low = text.lower()
    out = {}
    for fam, (_, _, keys) in ROLE_FAMILIES.items():
        out[fam] = sum(len(re.findall(rf"(?<![\w]){k}(?![\w])", low)) for k in keys)
    return out


def infer_resume_role(resume: ResumeData) -> Optional[str]:
    """What the evidence says, not what the skills list says: profile and titles
    count x3, bullets x2, the skills list x1."""
    summ = resume.summary or ""
    titles = " ".join(e.title + " " + " ".join(e.tags) for s in resume.doc_sections
                      if s.kind not in ("skills", "interests", "languages") for e in s.entries)
    stmts = " ".join(st.text for s in resume.doc_sections if s.kind in GRADED_KINDS
                     for e in s.entries for st in e.statements)
    skills = " ".join(sk for c in resume.skills for sk in c.skills)
    total: dict[str, float] = {}
    for txt, w in ((summ, 3), (titles, 3), (stmts, 2), (skills, 1)):
        for fam, v in _role_scores(txt).items():
            total[fam] = total.get(fam, 0) + w * v
    if not total:
        return None
    fam, val = max(total.items(), key=lambda kv: kv[1])
    if val == 0:
        return _infer_role(resume.raw_text or "")
    return fam


def _infer_role(text: str) -> Optional[str]:
    sc = _role_scores(text)
    fam, val = max(sc.items(), key=lambda kv: kv[1])
    return fam if val > 0 else None


@lru_cache(maxsize=8)
def _load_norm(norm_id: str) -> Optional[dict]:
    d = settings.knowledge_base_dir / "role_norms"
    if not d.exists():
        return None
    for f in d.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for role in data.get("roles", []):
            if role.get("id") == norm_id:
                return role
    return None


def _iter_statements(resume: ResumeData, kinds: set[str]):
    for sec in resume.doc_sections:
        if sec.kind in kinds:
            for e in sec.entries:
                for st in e.statements:
                    yield sec, e, st


def _sev(points: float) -> Severity:
    if points >= 5:
        return Severity.HIGH
    if points >= 2:
        return Severity.MEDIUM
    return Severity.LOW


# ── Statement grading (anchored rubric, deterministic) ───────────
# A: action + concrete object + quantified outcome
# B: action + concrete object + qualitative outcome, or action + metric
# C: action + object, outcome missing
# D: no clear action (duty/interest phrasing) or mostly vague words

GRADE_VALUE = {"A": 1.0, "B": 0.75, "C": 0.45, "D": 0.15}


def grade_statement(st: Statement, sec: DocSection, entry: DocEntry, current: bool) -> StatementGrade:
    text = st.text.strip()
    m = re.match(r"^([^–—:]{2,40})\s[–—:]\s(.+)$", text)
    if m and _words(m.group(2)) and _words(m.group(2))[0].lower() in ACTION_VERBS:
        text = m.group(2)  # "Table Tennis – Represented Kollam District…" -> grade the clause
    words = _words(text)
    first = words[0].lower() if words else ""
    weak = bool(WEAK_OPENERS.search(text))
    action = (not weak) and (first in ACTION_VERBS or (current and first in PRESENT_FORMS)
                             or (first.endswith("ed") and len(first) > 4 and first not in {"based", "need", "used"}))
    named = _named_things(text, entry.tags)
    metric_pos = _first_metric_pos(text)
    metric = metric_pos is not None
    outcome = metric or bool(OUTCOME.search(text))
    vague_hits = [m.group(0) for m in VAGUE.finditer(text)]
    # Project/role titles that already name the stack count as context a reviewer sees.
    specific = len(named) >= 1 or metric or (sec.kind == "projects" and len(entry.tags) >= 2)

    reasons, missing = [], []
    if weak:
        reasons.append(f'Opens with "{" ".join(words[:2])}" — describes involvement, not what you did')
    elif not action:
        reasons.append("Doesn't start with an action verb")
    if not specific:
        missing.append("specifics")
        reasons.append("No named tool, system, dataset or number")
    if not outcome:
        missing.append("outcome")
        reasons.append("No result — what changed because of this work?")
    elif not metric:
        missing.append("metric")
    if len(vague_hits) >= 2:
        reasons.append("Vague filler: " + ", ".join(f'"{v}"' for v in vague_hits[:3]))
    if not action:
        missing.insert(0, "action")

    if action and specific and metric:
        grade = "A"
    elif action and (metric or (outcome and specific)):
        grade = "B"
    elif action and (specific or outcome):
        grade = "C"
    else:
        grade = "D"
    if grade in ("A", "B") and len(vague_hits) >= 3:
        grade = chr(ord(grade) + 1)

    return StatementGrade(
        id=st.id, text=st.text.strip(), section=sec.kind, entry=entry.title, grade=grade,
        has_action=action, has_specific=specific, has_outcome=outcome, has_metric=metric,
        metric_position=metric_pos, reasons=reasons, missing=missing, line_ids=st.line_ids)


def front_load(text: str, tags: list[str]) -> Optional[str]:
    """Move an existing result to the front: 'Developed X achieving Y' ->
    'Achieved Y by developing X'. Uses only words already in the statement."""
    m = re.match(r"^(\w+)\s+(.+?),?\s+(achieving|reducing|improving|increasing|cutting|resulting in)\s+(.+?)\.?$",
                 text.strip(), re.I)
    if not m:
        return None
    verb, obj, link, result = m.groups()
    ger = GERUND.get(verb.lower())
    if not ger:
        return None
    lead = {"achieving": "Achieved", "reducing": "Reduced", "improving": "Improved",
            "increasing": "Increased", "cutting": "Cut", "resulting in": "Delivered"}[link.lower()]
    obj = obj.rstrip(",")
    result = re.sub(r"\s+×", "×", result)
    return f"{lead} {result} by {ger} {obj}."


def trim_filler(text: str) -> Optional[str]:
    t = re.sub(r",?\s*(with a focus on|focused on)\s+[^.]*", "", text, flags=re.I)
    if t != text and not t.rstrip().endswith("."):
        t = t.rstrip(" ,") + "."
    t = re.sub(r"\b(successfully|effectively|various)\s+", "", t, flags=re.I)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t if t != text.strip() and len(t) > 20 else None


# ── Main ─────────────────────────────────────────────────────────

def run_rri(resume: ResumeData, jd_requirements: Optional[list[str]] = None,
            use_llm: bool = True) -> ReadabilityResult:
    findings: list[Finding] = []
    fid = [0]

    def add(dim, title, detail, fix, points, line_ids=(), stmt_ids=(), action="edit",
            suggestion=None, norm_ref=None, severity=None):
        fid[0] += 1
        findings.append(Finding(
            id=f"rri{fid[0]}", source="rri", dimension=dim, title=title, detail=detail, fix=fix,
            points=round(points, 1), line_ids=list(line_ids), statement_ids=list(stmt_ids),
            action=action, suggestion=suggestion, norm_ref=norm_ref,
            severity=severity or _sev(points)))

    lines = {l.id: l for l in resume.lines}
    has_layout = bool(resume.lines)

    # ── role + seniority ─────────────────────────────────────────
    full_text = resume.raw_text or ""
    full_role = infer_resume_role(resume)
    exp_titles = [e.title or "" for e in resume.experience]
    non_intern = [t for t in exp_titles if not re.search(r"intern|trainee|apprentice", t, re.I)]
    studying = any((ed.end_date or "").lower() in ("present", "current", "ongoing") for ed in resume.education)
    seniority = "entry" if (studying or not non_intern) else "mid_senior"
    current_entries = {id(e) for s in resume.doc_sections for e in s.entries if re.search(r"present|current", e.dates, re.I)}

    # ── statements ───────────────────────────────────────────────
    grades: list[StatementGrade] = []
    entry_of: dict[str, tuple[DocSection, DocEntry]] = {}
    for sec, e, st in _iter_statements(resume, GRADED_KINDS):
        if st.text.lower().startswith("published") and len(st.text.split()) < 8:
            continue  # a publication note, not an achievement bullet
        g = grade_statement(st, sec, e, id(e) in current_entries)
        grades.append(g)
        entry_of[st.id] = (sec, e)

    llm_used = False
    if use_llm and grades:
        llm_used = _llm_grade_vote(grades, entry_of)

    # ── skim view ────────────────────────────────────────────────
    skim_ids, skim_parts = [], []
    if has_layout and resume.page_sizes:
        h0 = resume.page_sizes[0][1]
        for l in resume.lines:
            if l.page == 0 and l.bbox[3] <= h0 / 3:
                skim_ids.append(l.id); skim_parts.append(l.text)
    for sec in resume.doc_sections:
        if sec.heading_line_id and sec.heading_line_id not in skim_ids:
            skim_ids.append(sec.heading_line_id); skim_parts.append(sec.heading)
        for e in sec.entries:
            for lid in e.title_line_ids:
                if lid not in skim_ids:
                    skim_ids.append(lid); skim_parts.append(lines[lid].text if lid in lines else e.title)
            for st in e.statements:
                skim_parts.append(" ".join(st.text.split()[:SKIM_WORDS]))
    skim_text = "\n".join(skim_parts)
    skim_role = _infer_role(skim_text)

    # strengths a reviewer should come away with
    strengths: list[tuple[str, str, list[str]]] = []  # (label, needle, line_ids)
    for g in grades:
        mp = _metric_phrase(g.text)
        if mp:
            needle = METRIC.search(g.text).group(0).strip()
            strengths.append((f"{mp} — {_short(g.entry, 40)}", needle, g.line_ids))
    for p in resume.publications:
        venue = (p.venue or p.title).split(",")[0].split("·")[0].strip()
        strengths.append((f"Publication: {venue}", venue[:30], []))
    for ex in resume.experience[:2]:
        if ex.title:
            strengths.append((f"{ex.title} @ {ex.company or ''}".strip(" @"), ex.title, []))
    seen_labels = set()
    strengths = [s for s in strengths if not (s[0] in seen_labels or seen_labels.add(s[0]))][:6]
    skim_low = skim_text.lower()
    visible = [s for s in strengths if s[1].lower() in skim_low]
    missed = [s for s in strengths if s not in visible]

    llm_skim = _llm_skim_vote(skim_text) if (use_llm and llm_used is not None) else None
    if llm_skim and llm_skim.get("role_family") in ROLE_FAMILIES:
        skim_role = llm_skim["role_family"]

    # ═════════ 1. First-impression clarity (20) ═════════════════
    dim = "First-impression clarity"
    s1 = 0.0
    summary_stmts = [st for sec in resume.doc_sections if sec.kind == "summary" for e in sec.entries for st in e.statements]
    summary_text = " ".join(st.text for st in summary_stmts) or (resume.summary or "")
    first_sentence = summary_stmts[0] if summary_stmts else None
    identity = re.search(r"\b(engineer|developer|scientist|analyst|student|undergraduate|graduate|"
                         r"researcher|designer|intern|architect|manager|consultant|specialist)\b",
                         " ".join(summary_text.split()[:14]), re.I)
    if identity:
        s1 += 6
    else:
        sugg = _identity_line(resume, full_role)
        add(dim, "Your opening line says what you're interested in, not who you are",
            (f'A reviewer reads the top of page 1 first. "{" ".join(summary_text.split()[:10])}…" '
             "doesn't state a role or level, so they have to work it out from the rest of the page."
             if summary_text else "There is no summary/profile line under your name, so the top of the page "
             "doesn't say what role you're targeting."),
            "Open with identity + focus + your single strongest proof, all taken from your resume.",
            6, line_ids=first_sentence.line_ids if first_sentence else [],
            stmt_ids=[first_sentence.id] if first_sentence else [],
            action="rewrite" if first_sentence else "add", suggestion=sugg)
    if skim_role and full_role and skim_role == full_role:
        s1 += 6
    elif full_role:
        s1 += 2
        add(dim, f"The skim reads as {ROLE_FAMILIES.get(skim_role, ('unclear',))[0]}, the full resume as {ROLE_FAMILIES[full_role][0]}",
            "Headings, titles and the first words of each bullet point a skimmer toward a different role "
            "than your detailed content supports.",
            f"Put {ROLE_FAMILIES[full_role][0]} terms in your entry titles and the first words of bullets.", 4)
    if strengths:
        frac = len(visible) / len(strengths)
        s1 += 8 * frac
        if missed:
            buried = [s for s in missed if s[2]]
            ids = [i for s in buried for i in s[2]]
            add(dim, (f"{len(missed)} of your strongest facts is" if len(missed) == 1 else
                      f"{len(missed)} of your strongest facts are") + " invisible in a 6-second skim",
                "Reviewers skim headings, titles and roughly the first " + str(SKIM_WORDS) +
                " words of each bullet. These never appear there: " + "; ".join(s[0] for s in missed[:4]) + ".",
                "Lead bullets with the result, and surface your publication/role in the profile line.",
                8 * (1 - frac), line_ids=ids, action="rewrite",
                stmt_ids=[g.id for g in grades if any(i in g.line_ids for i in ids)])
    else:
        add(dim, "Nothing measurable for a skimmer to latch onto",
            "No bullet contains a number, and there's no publication or role title that stands out.",
            "Add one concrete result per entry (accuracy, users, time saved, size of data).", 8, action="add")
    d1 = min(20, s1)

    # ═════════ 2. Impact & evidence density (20) ═════════════════
    dim = "Impact & evidence density"
    if grades:
        wsum = sum(SECTION_WEIGHT.get(g.section, 1.0) for g in grades)
        avg = sum(GRADE_VALUE[g.grade] * SECTION_WEIGHT.get(g.section, 1.0) for g in grades) / wsum
        d2 = 20 * avg
        weak = [g for g in grades if g.grade in ("C", "D")]
        for g in sorted(weak, key=lambda x: -SECTION_WEIGHT.get(x.section, 1.0) * (GRADE_VALUE["B"] - GRADE_VALUE[x.grade]))[:6]:
            sec, e = entry_of[g.id]
            w = SECTION_WEIGHT.get(g.section, 1.0)
            pts = 20 * w * (GRADE_VALUE["B"] - GRADE_VALUE[g.grade]) / wsum
            where = {"experience": "role", "projects": "project"}.get(g.section, "entry")
            add(dim, f'Weak bullet ({g.grade}) in {where} "{_short(e.title or sec.heading, 40)}"',
                f'"{_short(g.text, 90)}" — ' + "; ".join(g.reasons) + ".",
                _question_for(g), pts, line_ids=g.line_ids, stmt_ids=[g.id], action="rewrite",
                suggestion=_template_for(g, e),
                severity=Severity.HIGH if (g.section == "experience" and g.grade == "D") else None)
        buried = [g for g in grades if g.has_metric and (g.metric_position or 0) >= SKIM_WORDS]
        for g in buried[:4]:
            sec, e = entry_of[g.id]
            fl = front_load(g.text, e.tags)
            add(dim, f"Result buried at word {g.metric_position + 1}: \"{_short(g.text, 60)}\"",
                f"The number is the most persuasive part of this bullet, but it appears after the first "
                f"{SKIM_WORDS} words where skimmers stop.",
                "Start the bullet with the result, then say how you got it.",
                1.5, line_ids=g.line_ids, stmt_ids=[g.id], action="rewrite", suggestion=fl,
                severity=Severity.MEDIUM)
    else:
        d2 = 0
        add(dim, "No experience or project bullets were found",
            "Without bullets there is nothing for a reviewer to evaluate.",
            "Add 1–3 bullets under each project and role: action → what → result.", 20, action="add",
            severity=Severity.CRITICAL)

    # ═════════ 3. Specificity & concreteness (15) ════════════════
    dim = "Specificity & concreteness"
    if grades:
        spec_frac = sum(1 for g in grades if g.has_specific) / len(grades)
        vague_stmts = [(g, [m.group(0) for m in VAGUE.finditer(g.text)]) for g in grades]
        vague_stmts = [(g, v) for g, v in vague_stmts if v]
        sum_vague = [m.group(0) for m in VAGUE.finditer(summary_text)]
        penalty = min(4, 0.6 * len(vague_stmts) + 0.3 * len(sum_vague))
        d3 = max(0, 15 * spec_frac - penalty)
        for g, v in vague_stmts[:4]:
            trimmed = trim_filler(g.text)
            add(dim, f"Vague wording in \"{_short(g.text, 55)}\"",
                "Phrases like " + ", ".join(f'"{x}"' for x in v[:3]) +
                " could describe anyone's project; they take space without adding evidence.",
                "Replace with the concrete thing: which model, dataset, device, or user group.",
                1.2, line_ids=g.line_ids, stmt_ids=[g.id], action="rewrite", suggestion=trimmed,
                severity=Severity.LOW)
        if sum_vague and first_sentence:
            add(dim, "Profile relies on generic phrases",
                "Your profile uses " + ", ".join(f'"{x}"' for x in sorted(set(s.lower() for s in sum_vague))[:4]) +
                ". Reviewers read these as filler.",
                "Swap each for a fact from your resume (a project result, the IEEE paper, your internship).",
                min(3, len(sum_vague)), line_ids=[i for st in summary_stmts for i in st.line_ids],
                stmt_ids=[st.id for st in summary_stmts], action="rewrite", severity=Severity.LOW)
    else:
        d3 = 0

    # ═════════ 4. Clarity & concision (15) ═══════════════════════
    dim = "Clarity & concision"
    d4 = 15.0
    for g in grades:
        n = len(g.text.split())
        if n > 34:
            d4 -= 1.5
            add(dim, f"{n}-word bullet is hard to scan", f"\"{_short(g.text, 70)}\" runs over two lines.",
                "Keep bullets to 1–2 lines (≈15–30 words). Split at the 'and' or cut the least important clause.",
                1.5, line_ids=g.line_ids, stmt_ids=[g.id], action="rewrite", severity=Severity.LOW)
        elif n < 6:
            d4 -= 0.5
        if PASSIVE.search(g.text):
            d4 -= 0.75
        if FIRST_PERSON.search(g.text):
            d4 -= 0.5
    try:
        from backend.nlp.placeholders import detect_placeholders
        ph = detect_placeholders(resume.raw_text or "")
        for f in ph.findings[:5]:
            d4 -= 5 if f.severity == "critical" else 2
            ids = [l.id for l in resume.lines if f.span and f.span.lower() in l.text.lower()][:3]
            add(dim, f"Template text left in: \"{f.span}\"", f.message, f.remediation,
                5 if f.severity == "critical" else 2, line_ids=ids, action="edit",
                severity=Severity.CRITICAL if f.severity == "critical" else Severity.HIGH)
    except Exception:
        pass
    # tense: past roles should be past tense
    for sec, e, st in _iter_statements(resume, {"experience"}):
        w = (st.text.split() or [""])[0].lower()
        if id(e) not in current_entries and w in PRESENT_FORMS:
            d4 -= 0.5
    d4 = max(0, d4)

    # ═════════ 5. Visual hierarchy & scan flow (10) ══════════════
    dim = "Visual hierarchy & scan flow"
    d5 = 10.0
    heading_lines = [lines[s.heading_line_id] for s in resume.doc_sections if s.heading_line_id in lines]
    if heading_lines:
        sizes = {round(l.size, 1) for l in heading_lines}
        if len(sizes) > 1:
            d5 -= 2
            add(dim, "Section headings use different font sizes",
                f"Headings appear in {len(sizes)} sizes ({', '.join(str(s) for s in sorted(sizes))} pt), "
                "so sections don't read as one consistent level.",
                "Use one size/weight for every section heading.", 2,
                line_ids=[l.id for l in heading_lines], action="format", severity=Severity.LOW)
    pages = resume.document_metadata.page_count or (len(resume.page_sizes) or 1)
    low_secs = [s for s in resume.doc_sections if s.kind in LOW_VALUE_KINDS]
    low_lines = [l.id for l in resume.lines if l.section_id in {s.id for s in low_secs}]
    if seniority == "entry" and pages > 1:
        d5 -= 3
        add(dim, f"{pages} pages for an entry-level resume",
            f"Early-career resumes are usually expected on one page. "
            f"{len(low_secs)} low-signal sections ({', '.join(s.heading for s in low_secs)}) use "
            f"{len(low_lines)} lines that could hold project evidence instead.",
            "Cut or merge low-signal sections (hobbies, languages, areas of interest) and move workshops "
            "into a single line, then aim for one page.",
            3, line_ids=[s.heading_line_id for s in low_secs if s.heading_line_id], action="remove",
            severity=Severity.MEDIUM)
    elif low_lines and len(low_lines) > 8:
        d5 -= 1.5
    # low-value section sitting between high-value ones on page 1
    order = [s for s in resume.doc_sections]
    key_idx = [i for i, s in enumerate(order) if s.kind in ("experience", "projects", "education", "skills", "publications")]
    if key_idx:
        last_key = max(key_idx)
        interrupt = [s for i, s in enumerate(order) if i < last_key and s.kind in LOW_VALUE_KINDS]
        for s in interrupt:
            d5 -= 1.5
            add(dim, f'"{s.heading}" interrupts your core sections',
                f'It sits above sections a reviewer cares about more, pushing them further down the page.',
                "Move it to the end, or remove it — its content can live in your profile line or skills.",
                1.5, line_ids=[s.heading_line_id] if s.heading_line_id else [], action="reorder",
                severity=Severity.LOW)
    if seniority == "entry":
        idx = {s.kind: i for i, s in reversed(list(enumerate(order)))}
        if "projects" in idx and "skills" in idx and idx["skills"] < idx["projects"] and not resume.experience:
            pass
    d5 = max(0, d5)

    # ═════════ 6. Narrative coherence (10) ═══════════════════════
    dim = "Narrative coherence"
    d6 = 10.0
    evidence_raw = " ".join(
        [st.text for _, _, st in _iter_statements(resume, GRADED_KINDS | {"summary", "publications"})]
        + [e.title + " " + " ".join(e.tags) for s in resume.doc_sections if s.kind not in ("skills",) for e in s.entries]
    )
    evidence_text = evidence_raw.lower()
    listed = []
    for cat in resume.skills:
        for sk in cat.skills:
            listed.append((cat.category, sk))
    if listed:
        def _used(sk: str) -> bool:
            base = sk.split(" (")[0].strip()
            if len(base) <= 2:  # "R", "C", "Go": case-sensitive whole word
                return bool(re.search(rf"(?<![\w+#]){re.escape(base)}(?![\w+#])", evidence_raw))
            return bool(re.search(rf"(?<![\w]){re.escape(base.lower())}(?![\w])", evidence_text))
        undemo = [(c, sk) for c, sk in listed if not _used(sk) and not _non_tool_category(c)]
        frac = len(undemo) / len(listed)
        d6 -= 5 * frac
        if undemo:
            skill_line_ids = [l.id for l in resume.lines if l.section_id in {s.id for s in resume.doc_sections if s.kind == "skills"}]
            relevant = [sk for c, sk in undemo if full_role and _infer_role(sk) == full_role or sk.lower() in GENERIC_DEV]
            add(dim, f"{len(undemo)} of {len(listed)} listed skills never appear in a project or role",
                "Unbacked skills: " + ", ".join(sk for _, sk in undemo[:12]) +
                (". Reviewers trust skills they can see used." ),
                ("Where you have used " + ", ".join(relevant[:4]) + ", name it in the project bullet. "
                 if relevant else "") + "Remove tools you couldn't discuss in an interview.",
                5 * frac, line_ids=skill_line_ids, action="edit")
    if full_role:
        off = []
        for cat in resume.skills:
            fams = {_infer_role(sk) for sk in cat.skills}
            fams.discard(None)
            generic = any(sk.lower() in GENERIC_DEV or sk.lower() in ("git", "matlab") for sk in cat.skills)
            if fams and fams <= {"creative"} and full_role != "creative" and not generic:
                off.append(cat)
            elif re.search(r"\bsoft skills?\b", cat.category, re.I):
                off.append(cat)
        if off:
            d6 -= min(2, 0.75 * len(off))
            ids = [l.id for l in resume.lines if any(c.category.lower() in l.text.lower() for c in off)]
            add(dim, f"Skill groups that pull away from your {ROLE_FAMILIES[full_role][0]} profile",
                "These groups don't support the role the rest of your resume points to: " +
                ", ".join(f'"{c.category}"' for c in off) + ". Soft skills listed as words carry little weight.",
                "Drop them for this application (or keep one line under 'Other'); show soft skills through results.",
                min(2, 0.75 * len(off)), line_ids=ids, action="remove", severity=Severity.LOW)
    if summary_text and grades:
        topics = [t for t in re.findall(r"\b(computer vision|machine learning|iot|llms?|nlp|automation|"
                                        r"web|data science|robotics|deep learning)\b", summary_text.lower())]
        unsupported = sorted({t for t in topics if t not in evidence_text.replace(summary_text.lower(), "")})
        if unsupported:
            d6 -= 1
            add(dim, "Profile claims topics the body doesn't show",
                "Mentioned in your profile but not evidenced elsewhere: " + ", ".join(unsupported) + ".",
                "Either add the project/role that shows it or remove it from the profile.", 1,
                line_ids=[i for st in summary_stmts for i in st.line_ids], severity=Severity.LOW)
    d6 = max(0, d6)

    # ═════════ 7. Role-norm alignment (10) ═══════════════════════
    dim = "Role-norm alignment"
    norm_id = ROLE_FAMILIES[full_role][1] if full_role else None
    norm = _load_norm(norm_id) if norm_id else None
    d7 = 5.0
    if norm:
        lvl = norm.get("seniority_levels", {}).get(seniority) or next(iter(norm.get("seniority_levels", {}).values()), {})
        ref = f"{norm_id}/{seniority}"
        have = {s.kind for s in resume.doc_sections}
        exp_secs = lvl.get("expected_sections", [])
        miss_secs = [x for x in exp_secs if x not in have]
        d7 = 10.0 - 1.5 * len(miss_secs)
        for x in miss_secs:
            add(dim, f"No {x} section", f"For {norm.get('canonical_title')} ({seniority}) reviewers expect: "
                + ", ".join(exp_secs) + ".", f"Add a {x} section if you have relevant content.", 1.5,
                action="add", norm_ref=f"{ref}/expected_sections")
        tools = lvl.get("typical_tools", [])
        res_low = (resume.raw_text or "").lower()
        missing_tools = [t for t in tools if t.lower() not in res_low]
        if tools:
            cover = 1 - len(missing_tools) / len(tools)
            d7 -= 3 * (1 - cover)
            if missing_tools and cover < 0.75:
                add(dim, f"Common {ROLE_FAMILIES[full_role][0]} tools you don't mention",
                    "Typical for this role: " + ", ".join(missing_tools) +
                    ". If you used any of them in your projects, they're currently invisible.",
                    "Only add the ones you actually used — name them inside the project bullet where you used them.",
                    3 * (1 - cover), action="add", norm_ref=f"{ref}/typical_tools", severity=Severity.LOW)
        mets = lvl.get("expected_metrics", [])
        if mets:
            hit = [m for m in mets if any(w in res_low for w in re.findall(r"[a-z]{4,}", m.lower())[:2])]
            if len(hit) < len(mets):
                d7 -= 1
                add(dim, "Missing the evidence types reviewers look for",
                    "For this role reviewers look for: " + "; ".join(mets) + ". Not found: " +
                    "; ".join(m for m in mets if m not in hit) + ".",
                    "Where you know them, state dataset size, baselines you beat, or evaluation metrics.",
                    1, action="add", norm_ref=f"{ref}/expected_metrics", severity=Severity.LOW)
        anti = lvl.get("anti_patterns", [])
        if anti and not re.search(r"baseline|compared|vs\.?|outperform", res_low):
            for a in anti:
                if "baseline" in a.lower():
                    d7 -= 1
                    add(dim, "No baseline comparison in your ML results",
                        "Accuracy numbers mean more next to a baseline (e.g. 'vs. 91% supervised ResNet-50').",
                        "If you ran a baseline, add it to the bullet with the result.", 1,
                        action="add", norm_ref=f"{ref}/anti_patterns", severity=Severity.LOW)
        d7 = max(0, min(10, d7))
    # JD-aware skim check
    if jd_requirements:
        top = jd_requirements[:3]
        not_skim = [r for r in top if not any(w in skim_low for w in re.findall(r"[a-z]{4,}", r.lower())[:3])]
        if not_skim:
            add("First-impression clarity", "Top JD requirements aren't visible in the skim",
                "Not visible in headings, titles or bullet openings: " + "; ".join(not_skim) + ".",
                "If your resume has evidence for these, surface it in the first words of a bullet.", 3)

    # ── assemble ────────────────────────────────────────────────
    raw = {
        "First-impression clarity": d1, "Impact & evidence density": d2,
        "Specificity & concreteness": d3, "Clarity & concision": d4,
        "Visual hierarchy & scan flow": d5, "Narrative coherence": d6, "Role-norm alignment": d7,
    }
    dims = []
    for name, w in WEIGHTS.items():
        sc = round(max(0.0, min(w, raw[name])), 1)
        own = [f for f in findings if f.dimension == name]
        dims.append(ReadabilityDimensionScore(
            dimension=name, score=sc, max_score=w,
            details=[f.title for f in own][:4], tips=[f.fix for f in own if f.fix][:3]))
    total = round(sum(d.score for d in dims), 1)

    findings.sort(key=lambda f: (-_SEV_ORDER[f.severity], -f.points))
    # one finding per statement in the "top fixes" list, highest recoverable points first
    top, used = [], set()
    for f in sorted(findings, key=lambda f: -f.points):
        key = tuple(f.statement_ids) or (f.title,)
        if key in used:
            continue
        used.add(key)
        top.append(f)
        if len(top) == 5:
            break

    snapshot = SkimSnapshot(
        skim_text=skim_text[:1500], skim_line_ids=skim_ids,
        skim_role=ROLE_FAMILIES[skim_role][0] if skim_role else None,
        full_role=ROLE_FAMILIES[full_role][0] if full_role else None, seniority=seniority,
        skim_strengths=[s[0] for s in visible], full_strengths=[s[0] for s in strengths],
        missed_strengths=[s[0] for s in missed],
        agreement=round(len(visible) / len(strengths), 2) if strengths else 0.0,
        method="rules+llm" if llm_skim else "rules")

    conf = "high" if has_layout and len(grades) >= 4 else ("medium" if grades else "low")
    return ReadabilityResult(
        overall_score=total, max_possible=100.0, rri_percentage=total,
        dimensions=dims, rubric_version=RRI_VERSION, findings=findings, top_fixes=top,
        statements=grades, snapshot=snapshot,
        inferred_role=ROLE_FAMILIES[full_role][0] if full_role else None,
        role_norm_id=norm_id, confidence=conf, llm_used=bool(llm_used),
        disclosure=("The Recruiter Readability Index is ResumeX's own versioned rubric (v" + RRI_VERSION +
                    ") for how quickly a human reviewer understands your resume. It is not an industry "
                    "standard and does not predict hiring outcomes."),
    )


_SEV_ORDER = {Severity.CRITICAL: 4, Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1, Severity.INFO: 0}


def _non_tool_category(c: str) -> bool:
    c = c.lower().strip()
    return bool(re.search(r"\bsoft skills?\b|\binterpersonal\b", c)) or c in ("languages", "spoken languages", "language proficiency")


def _short(t: str, n: int = 48) -> str:
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


def _identity_line(resume: ResumeData, role: Optional[str]) -> Optional[str]:
    """Build an opening line ONLY from facts present in the resume."""
    parts = []
    deg = next((e for e in resume.education if e.degree and re.search(r"tech|science|engineering|b\.?e|bachelor|master", e.degree, re.I)), None)
    if deg:
        field = re.sub(r"^(bachelor|master)\s+of\s+\w+\s+in\s+", "", deg.degree, flags=re.I)
        level = "undergraduate" if (deg.end_date or "").lower() in ("present", "current") else "graduate"
        parts.append(f"{field} {level}")
        if deg.gpa:
            parts[-1] += f" (CGPA {deg.gpa})"
    focus = []
    low = (resume.raw_text or "").lower()
    for k, label in [("computer vision", "computer vision"), ("llm", "LLMs"), ("iot", "IoT"),
                     ("self-supervised", "self-supervised learning"), ("predictive maintenance", "predictive maintenance"),
                     ("nlp", "NLP"), ("backend", "backend systems"), ("react", "web apps")]:
        if k in low and label not in focus:
            focus.append(label)
    if focus:
        f = focus[:3]
        parts.append("building " + (", ".join(f[:-1]) + " and " + f[-1] if len(f) > 1 else f[0]) + " systems")
    if resume.publications:
        v = resume.publications[0].venue or ""
        m = re.search(r"(IEEE|ACM|Springer)\s*[A-Z]*\s*\d{4}", v)
        parts.append(f"published at {m.group(0)}" if m else "published researcher")
    best = None
    for sec, e, st in _iter_statements(resume, {"projects", "experience"}):
        mp = _metric_phrase(st.text)
        if mp and "%" in mp:
            best = (mp, re.sub(r"\s+using\s+.*$", "", e.title))
            break
    if not parts:
        return None
    s = parts[0][0].upper() + parts[0][1:]
    if len(parts) > 1:
        s += " " + parts[1]
    if len(parts) > 2:
        s += "; " + parts[2]
    if best:
        s += f"; {best[0]} on {best[1].lower() if best[1][:1].isupper() and not best[1][:2].isupper() else best[1]}"
    return s + "."


def _question_for(g: StatementGrade) -> str:
    if "action" in g.missing:
        return ("Say what YOU did, starting with a verb (Built / Evaluated / Fine-tuned / Automated), "
                "then the specific thing, then the result.")
    if "outcome" in g.missing:
        return "Add the result: what improved, how much, or who used it? (accuracy, time saved, users, size of data)"
    if "specifics" in g.missing:
        return "Name the concrete thing: which model, dataset, tool, or system?"
    if "metric" in g.missing:
        return "You state an outcome — can you put a number on it?"
    return "Tighten the wording."


def _template_for(g: StatementGrade, e: DocEntry) -> Optional[str]:
    """Fill-in version of the user's own bullet. Blanks are marked with [ ] and
    must be completed by the user — the app never fills them itself."""
    text = trim_filler(g.text) or g.text
    text = text.rstrip(". ")
    if "action" in g.missing and WEAK_OPENERS.search(text):
        rest = WEAK_OPENERS.sub("", text).strip(" ,")
        text = f"[Built / Evaluated / Automated — what you did] {rest}"
    if "outcome" in g.missing:
        return text + ", [result — e.g. accuracy, time saved, users, size of data]."
    if "metric" in g.missing:
        return text + " [add a number if you have one]."
    return text + "." if text != g.text.rstrip(". ") else None


# ── Optional LLM votes (labels only, never scores) ───────────────

def _llm_available():
    try:
        from backend.llm.client import get_llm_client
        c = get_llm_client()
        return c if c.is_online() else None
    except Exception:
        return None


def _llm_grade_vote(grades: list[StatementGrade], entry_of) -> Optional[bool]:
    client = _llm_available()
    if not client:
        return None
    from backend.llm.prompts import BULLET_GRADER_SYSTEM
    payload = [{"id": g.id, "entry": g.entry, "text": g.text} for g in grades]
    schema = {"type": "object", "properties": {"grades": {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "string"}, "grade": {"type": "string", "enum": ["A", "B", "C", "D"]},
                                          "reason": {"type": "string"}}, "required": ["id", "grade"]}}},
              "required": ["grades"]}
    resp = client.generate(BULLET_GRADER_SYSTEM, json.dumps(payload), json_schema=schema, temperature=0.0)
    if not resp.raw_json:
        return None
    by_id = {x.get("id"): x for x in resp.raw_json.get("grades", []) if isinstance(x, dict)}
    order = "ABCD"
    for g in grades:
        v = by_id.get(g.id)
        if not v or v.get("grade") not in order:
            continue
        # fixed aggregation: rules and LLM each vote; when they disagree by more than one
        # grade the rules win (they are auditable); otherwise take the lower (stricter) grade.
        r, l = order.index(g.grade), order.index(v["grade"])
        if abs(r - l) <= 1:
            g.grade = order[max(r, l)]
        g.method = "rules+llm"
        if v.get("reason") and len(g.reasons) < 4:
            g.reasons.append("AI reviewer: " + v["reason"][:160])
    return True


def _llm_skim_vote(skim_text: str) -> Optional[dict]:
    client = _llm_available()
    if not client:
        return None
    from backend.llm.prompts import SKIM_TEST_SYSTEM
    schema = {"type": "object", "properties": {
        "role_family": {"type": "string", "enum": list(ROLE_FAMILIES.keys()) + ["unclear"]},
        "seniority": {"type": "string"}, "strengths": {"type": "array", "items": {"type": "string"}}},
        "required": ["role_family", "strengths"]}
    votes = []
    for seed in (11, 23, 37):  # 3 fixed seeds, majority vote (plan §10)
        r = client.generate(SKIM_TEST_SYSTEM, skim_text[:3000], json_schema=schema, temperature=0.0, seed=seed)
        if r.raw_json:
            votes.append(r.raw_json)
    if not votes:
        return None
    from collections import Counter
    fam = Counter(v.get("role_family") for v in votes).most_common(1)[0][0]
    return {"role_family": fam, "votes": votes}

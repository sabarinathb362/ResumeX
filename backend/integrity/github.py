"""
GitHub claim check (Phase 5, opt-in).

For each project on the resume, finds the matching public repo of the candidate's GitHub account
and looks for evidence of the skills the project claims: the repo's languages, topics, description
and dependency manifests (requirements.txt, package.json, ...). Only the username and repo names
leave the machine; resume text is never sent.

Output per project: matched repo (or none), skills found / not found in the repo, plus neutral notes
(fork, repo created after the dates on the resume). The Claim Verification Index (CVI) is the share
of checkable skill claims with evidence. "Not found" means "not visible in this public repo", never
"false": private repos, monorepos and work code are invisible to this check.
"""
from __future__ import annotations

import base64
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional

import httpx

API = "https://api.github.com"
MANIFESTS = ("requirements.txt", "pyproject.toml", "package.json", "go.mod", "Cargo.toml", "pom.xml",
             "build.gradle", "environment.yml", "Pipfile", "Gemfile", "composer.json")
REPO_URL = re.compile(r"github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9_.-]{1,100})", re.I)
USER_URL = re.compile(r"github\.com/([A-Za-z0-9-]{1,39})(?:/|$|\s|\))", re.I)
# GitHub language names that differ from the canonical skill names
LANG_ALIASES = {"Jupyter Notebook": "Python", "HCL": "Terraform", "Dockerfile": "Docker", "Vue": "Vue.js",
                "Shell": "Bash", "C++": "C++", "C#": "C#"}

# Dependency names that imply a skill the package name does not spell out
PACKAGE_HINTS = {"psycopg2": "PostgreSQL", "psycopg": "PostgreSQL", "asyncpg": "PostgreSQL", "pg": "PostgreSQL",
                 "redis": "Redis", "ioredis": "Redis", "torch": "PyTorch", "tensorflow": "TensorFlow",
                 "pymongo": "MongoDB", "mongoose": "MongoDB", "mysqlclient": "MySQL", "mysql2": "MySQL",
                 "sklearn": "scikit-learn", "scikit-learn": "scikit-learn", "boto3": "AWS", "aws-sdk": "AWS",
                 "@aws-sdk/client-s3": "AWS", "kafka-python": "Kafka", "confluent-kafka": "Kafka", "kafkajs": "Kafka",
                 "celery": "Celery", "pika": "RabbitMQ", "amqplib": "RabbitMQ", "@nestjs/core": "NestJS",
                 "next": "Next.js", "react": "React", "express": "Express.js", "vue": "Vue.js", "@angular/core": "Angular"}
PKG_TOKEN = re.compile(r"[@A-Za-z0-9][\w./@-]*")


def _manifest_skills(text: str) -> set[str]:
    from backend.feedback.taxonomy import grounded_canonicals
    found = grounded_canonicals(text.replace("-", " ").replace("_", " "))
    for tok in PKG_TOKEN.findall(text.lower()):
        base = re.split(r"[=<>~^\[;]", tok)[0].strip("\"'")
        hint = PACKAGE_HINTS.get(base) or PACKAGE_HINTS.get(base.split("-")[0])   # psycopg2-binary, react-dom
        if hint:
            found.add(hint)
    return found


class RateLimited(Exception):
    pass


@dataclass
class ProjectCheck:
    entry_id: str
    title: str
    repo: Optional[str]
    match: str                                    # url | name | none
    found: list[str] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class GithubReport:
    username: Optional[str]
    projects: list[ProjectCheck]
    cvi: Optional[float]                          # 0-100 over projects with a matched repo
    checked_claims: int
    partial: bool = False                         # stopped early (rate limit)
    message: str = ""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def username_from(resume) -> Optional[str]:
    c = resume.contact
    for link in [c.github or "", *c.links, resume.raw_text or ""]:
        m = USER_URL.search(link + " ")
        if m and m.group(1).lower() not in ("orgs", "features", "about", "topics", "sponsors"):
            return m.group(1)
    return None


def _entry_text(e) -> str:
    return " ".join([e.title, e.subtitle, " ".join(e.tags), *[s.text for s in e.statements]])


def _match_repo(e, repos: list[dict], user: str) -> tuple[Optional[dict], str]:
    for m in REPO_URL.finditer(_entry_text(e)):
        name = m.group(2).removesuffix(".git").rstrip(".")
        owner = m.group(1)
        hit = next((r for r in repos if r["name"].lower() == name.lower()), None) if owner.lower() == user.lower() else None
        return (hit or {"name": name, "full_name": f"{owner}/{name}", "_fetch": True}), "url"
    title = _norm(re.split(r"[|–—:(]", e.title or "")[0])
    if len(title) < 3:
        return None, "none"
    best, score = None, 0.0
    for r in repos:
        n = _norm(r["name"])
        if not n:
            continue
        s = 1.0 if n == title else (0.8 if (n in title or title in n) and min(len(n), len(title)) >= 4 else 0.0)
        if s > score:
            best, score = r, s
    return (best, "name") if score >= 0.8 else (None, "none")


class GithubClient:
    def __init__(self, token: str = "", client: Optional[httpx.Client] = None):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "ResumeX-local"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.http = client or httpx.Client(base_url=API, headers=headers, timeout=10.0)
        if client is not None:
            self.http.headers.update(headers)
        self.calls = 0

    def get(self, path: str, **params):
        r = self.http.get(path, params=params or None)
        self.calls += 1
        if r.status_code in (403, 429) and r.headers.get("x-ratelimit-remaining") == "0":
            raise RateLimited()
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def text_file(self, full: str, path: str) -> str:
        d = self.get(f"/repos/{full}/contents/{path}")
        if not d or d.get("encoding") != "base64":
            return ""
        return base64.b64decode(d.get("content", "")).decode("utf-8", errors="replace")[:50_000]


def _evidence(gh: GithubClient, repo: dict) -> set[str]:
    from backend.feedback.taxonomy import canonical, grounded_canonicals
    full = repo["full_name"]
    ev: set[str] = set()
    langs = gh.get(f"/repos/{full}/languages") or {}
    for lang in langs:
        name = LANG_ALIASES.get(lang, lang)
        ev.add(canonical(name) or name)
    meta_text = " ".join([repo.get("description") or "", " ".join(repo.get("topics") or [])])
    ev |= grounded_canonicals(meta_text.replace("-", " "))
    root = gh.get(f"/repos/{full}/contents/") or []
    names = {f["name"] for f in root if isinstance(f, dict) and f.get("type") == "file"}
    for m in [m for m in MANIFESTS if m in names][:3]:
        ev |= _manifest_skills(gh.text_file(full, m))
    return ev


def check_github(resume, username: Optional[str] = None, token: str = "", client: Optional[httpx.Client] = None,
                 today: Optional[date] = None) -> GithubReport:
    user = username or username_from(resume)
    if not user:
        return GithubReport(None, [], None, 0, message="No GitHub profile link found on the resume.")
    gh = GithubClient(token, client)
    today = today or date.today()
    try:
        return _check(resume, user, gh, today)
    finally:
        if client is None:
            gh.http.close()


def _check(resume, user: str, gh: GithubClient, today: date) -> GithubReport:
    from backend.feedback.taxonomy import grounded_canonicals
    from backend.integrity.timeline import parse_range
    projects, partial = [], False
    try:
        repos = gh.get(f"/users/{user}/repos", per_page=100, sort="pushed", type="owner")
        if repos is None:
            return GithubReport(user, [], None, 0, message=f"GitHub user {user} was not found.")
        for sec in resume.doc_sections:
            if sec.kind != "projects":
                continue
            for e in sec.entries:
                # A repo link is not a skill claim: without this, "github.com/user/repo" counts as "GitHub".
                claims = sorted(grounded_canonicals(REPO_URL.sub(" ", _entry_text(e))))
                repo, how = _match_repo(e, repos, user)
                pc = ProjectCheck(e.id, e.title[:80], repo["full_name"] if repo else None, how)
                if not repo:
                    pc.notes.append("No public repo with this name. Link the repo in the project line if it is public.")
                    projects.append(pc)
                    continue
                if repo.get("_fetch"):
                    full = gh.get(f"/repos/{repo['full_name']}")
                    if not full:
                        pc.notes.append("The linked repo is not public or does not exist.")
                        projects.append(pc)
                        continue
                    repo = full
                    if repo["owner"]["login"].lower() != user.lower():
                        pc.notes.append("The linked repo belongs to another account; your share of the work is not checked.")
                ev = _evidence(gh, repo)
                ev_low = {x.lower() for x in ev}
                pc.found = [c for c in claims if c.lower() in ev_low]
                pc.not_found = [c for c in claims if c.lower() not in ev_low]
                if repo.get("fork"):
                    pc.notes.append("This repo is a fork. Say what you added to it.")
                start = parse_range(e.dates, today)[0]
                created = repo.get("created_at", "")[:7]
                if start is not None and re.fullmatch(r"\d{4}-\d{2}", created or ""):
                    c_m = int(created[:4]) * 12 + int(created[5:7]) - 1
                    if c_m - start > 3:
                        pc.notes.append(f"The repo was created {created}, after the start date on the resume. "
                                        f"Fine if the code lived elsewhere first.")
                projects.append(pc)
    except RateLimited:
        partial = True
    except httpx.HTTPError as ex:
        return GithubReport(user, projects, None, 0, partial=True, message=f"GitHub request failed: {type(ex).__name__}")
    checked = sum(len(p.found) + len(p.not_found) for p in projects if p.repo)
    found = sum(len(p.found) for p in projects if p.repo)
    cvi = round(100 * found / checked, 1) if checked else None
    msg = ("GitHub's hourly limit for anonymous requests was reached; set RESUMEIQ_GITHUB_TOKEN in .env to check the rest."
           if partial else f"Checked {len([p for p in projects if p.repo])} of {len(projects)} projects against public repos.")
    return GithubReport(user, projects, cvi, checked, partial, msg)


def to_dict(r: GithubReport) -> dict:
    return asdict(r)

"""
Phase 1 — Directional skill taxonomy for the rewrite fact-checker.

Three relations, deliberately asymmetric:
  * ALIAS      k8s <-> Kubernetes, AWS <-> Amazon Web Services   (same thing, both directions)
  * HYPERNYM   PostgreSQL -> "relational database", React -> "UI"  (specific -> general ONLY)
  * nothing    "relational database" -> PostgreSQL is NOT allowed: that would invent a fact.

A rewrite may swap a grounded tool for its alias or for a broader category. It may
never name a more specific tool than the evidence does.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable, Optional

# Extra aliases the base SKILL_ALIASES table (backend/nlp/skills.py) does not carry.
EXTRA_ALIASES: dict[str, str] = {
    "amazon web services": "AWS", "google cloud": "GCP", "google cloud platform": "GCP",
    "microsoft azure": "Azure", "k8s": "Kubernetes", "kube": "Kubernetes",
    "ml": "Machine Learning", "machine learning": "Machine Learning",
    "dl": "Deep Learning", "deep learning": "Deep Learning",
    "ai": "AI", "artificial intelligence": "AI",
    "llm": "LLM", "llms": "LLM", "large language model": "LLM", "large language models": "LLM",
    "nlp": "NLP", "natural language processing": "NLP",
    "computer vision": "Computer Vision",
    "ci/cd": "CI/CD", "cicd": "CI/CD", "ci-cd": "CI/CD",
    "rest": "REST", "restful": "REST", "rest api": "REST", "rest apis": "REST",
    "postgres": "PostgreSQL", "psql": "PostgreSQL",
    "mongo": "MongoDB", "es": "Elasticsearch",
    "hf": "Hugging Face", "huggingface": "Hugging Face", "hugging face": "Hugging Face",
    "gh actions": "GitHub Actions",
}

# Specific -> broader phrases a rewrite may use instead of (or in addition to) the specific term.
_DB_SQL = {"database", "databases", "relational database", "sql database", "rdbms", "sql"}
_WEB_BACKEND = {"backend", "back-end", "api", "apis", "rest api", "web service", "web services",
                "service", "services", "web framework", "server"}
_FRONTEND = {"frontend", "front-end", "ui", "web app", "web application", "single-page app", "spa"}
_DL = {"deep learning", "deep learning framework", "neural network", "neural networks", "dl", "ml",
       "machine learning"}
_CLOUD = {"cloud", "cloud infrastructure", "cloud platform", "cloud services"}
_CI = {"ci", "ci/cd", "pipeline", "pipelines", "build pipeline", "automated builds"}

HYPERNYMS: dict[str, set[str]] = {
    "PostgreSQL": _DB_SQL, "MySQL": _DB_SQL, "SQLite": _DB_SQL, "SQL Server": _DB_SQL, "Oracle": _DB_SQL,
    "MongoDB": {"database", "databases", "nosql", "nosql database", "document database"},
    "DynamoDB": {"database", "nosql", "nosql database", "key-value store"},
    "Cassandra": {"database", "nosql", "nosql database"},
    "Redis": {"cache", "caching", "in-memory cache", "key-value store", "in-memory store"},
    "Elasticsearch": {"search", "search engine", "full-text search"},
    "Kubernetes": {"container orchestration", "orchestration", "cluster", "containers"},
    "Docker": {"container", "containers", "containerized", "containerised", "containerization"},
    "AWS": _CLOUD, "GCP": _CLOUD, "Azure": _CLOUD,
    "PyTorch": _DL, "TensorFlow": _DL, "Keras": _DL, "JAX": _DL,
    "scikit-learn": {"machine learning", "ml", "classical ml"},
    "Hugging Face": {"transformers", "nlp", "llm"},
    "React": _FRONTEND, "Vue.js": _FRONTEND, "Angular": _FRONTEND, "Next.js": _FRONTEND | {"ssr"},
    "Svelte": _FRONTEND,
    "FastAPI": _WEB_BACKEND, "Flask": _WEB_BACKEND, "Django": _WEB_BACKEND,
    "Express.js": _WEB_BACKEND, "Spring Boot": _WEB_BACKEND, "Node.js": _WEB_BACKEND,
    "REST": {"api", "apis", "web service", "web services"},
    "GraphQL": {"api", "apis"}, "gRPC": {"api", "apis", "rpc"},
    "Kafka": {"message queue", "event streaming", "streaming", "message broker", "pub/sub"},
    "RabbitMQ": {"message queue", "message broker", "queue"},
    "GitHub Actions": _CI, "Jenkins": _CI, "GitLab CI": _CI, "CI/CD": _CI,
    "Terraform": {"infrastructure as code", "iac"},
    "OpenCV": {"computer vision", "image processing"},
    "YOLO": {"object detection", "detector", "computer vision"},
    "LLM": {"ai", "language model", "language models", "nlp"},
    "Machine Learning": {"ml", "ai", "model", "models"},
    "Deep Learning": {"ml", "ai", "neural network", "neural networks"},
    "Computer Vision": {"cv", "vision", "image processing"},
    "NLP": {"language processing", "text processing", "ai"},
    "Tableau": {"dashboard", "dashboards", "bi", "visualization"},
    "Power BI": {"dashboard", "dashboards", "bi", "visualization"},
}

# Aliases that are also everyday English words. They only count as a tool when written
# like one (capitalised mid-sentence, or with .js / a version), never as lowercase prose.
AMBIGUOUS_ALIASES = {"next", "spring", "express", "node", "shell", "swift", "rust", "rest", "slack",
                     "apache", "oracle", "go", "excel", "ruby", "dart", "scala", "agile", "scrum",
                     "postman", "vercel", "heroku", "torch", "tf", "r", "c"}


def _load_base_aliases() -> dict[str, str]:
    try:
        from backend.nlp.skills import SKILL_ALIASES
        return dict(SKILL_ALIASES)
    except Exception:  # pragma: no cover - keeps the module importable in isolation
        return {}


@lru_cache(maxsize=1)
def alias_table() -> dict[str, str]:
    table = {k.lower(): v for k, v in _load_base_aliases().items()}
    table.update({k.lower(): v for k, v in EXTRA_ALIASES.items()})
    for canon in set(table.values()) | set(HYPERNYMS):
        table.setdefault(canon.lower(), canon)
    return table


def canonical(term: str) -> Optional[str]:
    """Canonical skill name for a surface form, or None if it is not a known skill."""
    t = term.strip().lower().rstrip(".,;:")
    return alias_table().get(t)


def _phrase_in(phrase: str, text_low: str) -> bool:
    return re.search(rf"(?<![\w+#]){re.escape(phrase)}(?![\w+#])", text_low) is not None


def grounded_canonicals(text: str) -> set[str]:
    """Every known skill mentioned in `text`, as canonical names (multi-word aware)."""
    low = text.lower()
    found: set[str] = set()
    for alias, canon in alias_table().items():
        if len(alias) <= 2 or alias in AMBIGUOUS_ALIASES:
            # short / ambiguous aliases: require the original casing of a tool name
            if re.search(rf"(?<![\w+#]){re.escape(canon)}(?![\w+#])", text):
                found.add(canon)
            continue
        if _phrase_in(alias, low):
            found.add(canon)
    return found


@lru_cache(maxsize=1)
def _onet_hypernyms() -> dict[str, set[str]]:
    """Optional: O*NET Technology Skills (CC BY 4.0) commodity titles, written by
    training/01_collect_sources.py --onet. 'Database management system software' also
    yields 'database management system'."""
    try:
        import json
        from backend.config import settings
        raw = json.loads((settings.knowledge_base_dir / "skill_hypernyms.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, set[str]] = {}
    for tool, titles in raw.items():
        c = canonical(tool) or tool
        forms = set()
        for t in titles:
            t = t.lower().strip()
            forms |= {t, re.sub(r"\s+software$", "", t)}
        out.setdefault(c, set()).update(forms)
    return out


def allowed_generalisations(grounded: Iterable[str]) -> set[str]:
    out: set[str] = set()
    extra = _onet_hypernyms()
    for c in grounded:
        out |= {h.lower() for h in HYPERNYMS.get(c, set())}
        out |= extra.get(c, set())
    return out


def is_supported_term(term: str, ground_text: str, grounded: set[str], generalisations: set[str]) -> tuple[bool, str]:
    """Return (ok, how). `how` is one of: literal | alias | generalisation | ''."""
    low = term.lower().strip(".,;:")
    if _phrase_in(low, ground_text.lower()):
        return True, "literal"
    c = canonical(term)
    if c and c in grounded:
        return True, "alias"
    if low in generalisations:
        return True, "generalisation"
    return False, ""

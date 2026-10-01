"""
Phase 3 — Skill Normalization Layer.
Canonical skill names + aliases (e.g. "JS" → "JavaScript").
"""


# ── Skill alias dictionary ───────────────────────────────────────
# Maps alias (lowercased) → canonical name

SKILL_ALIASES: dict[str, str] = {
    # Languages
    "js": "JavaScript", "javascript": "JavaScript", "es6": "JavaScript",
    "ts": "TypeScript", "typescript": "TypeScript",
    "py": "Python", "python": "Python", "python3": "Python",
    "java": "Java",
    "c++": "C++", "cpp": "C++",
    "c#": "C#", "csharp": "C#", "c sharp": "C#",
    "go": "Go", "golang": "Go",
    "rb": "Ruby", "ruby": "Ruby",
    "rs": "Rust", "rust": "Rust",
    "swift": "Swift",
    "kotlin": "Kotlin", "kt": "Kotlin",
    "r": "R", "r language": "R",
    "sql": "SQL",
    "html": "HTML", "html5": "HTML",
    "css": "CSS", "css3": "CSS",
    "php": "PHP",
    "scala": "Scala",
    "perl": "Perl",
    "bash": "Bash", "shell": "Bash", "shell scripting": "Bash",
    "matlab": "MATLAB",
    "dart": "Dart",

    # Frameworks / Libraries
    "react": "React", "reactjs": "React", "react.js": "React",
    "next": "Next.js", "nextjs": "Next.js", "next.js": "Next.js",
    "angular": "Angular", "angularjs": "Angular",
    "vue": "Vue.js", "vuejs": "Vue.js", "vue.js": "Vue.js",
    "svelte": "Svelte",
    "node": "Node.js", "nodejs": "Node.js", "node.js": "Node.js",
    "express": "Express.js", "expressjs": "Express.js",
    "django": "Django",
    "flask": "Flask",
    "fastapi": "FastAPI",
    "spring": "Spring", "spring boot": "Spring Boot", "springboot": "Spring Boot",
    "rails": "Ruby on Rails", "ruby on rails": "Ruby on Rails",
    "dotnet": ".NET", ".net": ".NET", "asp.net": "ASP.NET",
    "laravel": "Laravel",
    "tensorflow": "TensorFlow", "tf": "TensorFlow",
    "pytorch": "PyTorch", "torch": "PyTorch",
    "keras": "Keras",
    "scikit-learn": "scikit-learn", "sklearn": "scikit-learn",
    "pandas": "pandas",
    "numpy": "NumPy",
    "matplotlib": "Matplotlib",
    "opencv": "OpenCV",
    "scipy": "SciPy",
    "tailwind": "Tailwind CSS", "tailwindcss": "Tailwind CSS",
    "bootstrap": "Bootstrap",
    "jquery": "jQuery",

    # Databases
    "postgres": "PostgreSQL", "postgresql": "PostgreSQL", "pg": "PostgreSQL",
    "mysql": "MySQL",
    "mongodb": "MongoDB", "mongo": "MongoDB",
    "redis": "Redis",
    "sqlite": "SQLite",
    "cassandra": "Cassandra",
    "dynamodb": "DynamoDB",
    "elasticsearch": "Elasticsearch", "elastic search": "Elasticsearch", "es": "Elasticsearch",
    "oracle": "Oracle DB", "oracle db": "Oracle DB",
    "ms sql": "SQL Server", "sql server": "SQL Server", "mssql": "SQL Server",
    "neo4j": "Neo4j",

    # Cloud / DevOps
    "aws": "AWS", "amazon web services": "AWS",
    "gcp": "GCP", "google cloud": "GCP", "google cloud platform": "GCP",
    "azure": "Azure", "microsoft azure": "Azure",
    "docker": "Docker",
    "k8s": "Kubernetes", "kubernetes": "Kubernetes",
    "terraform": "Terraform",
    "ansible": "Ansible",
    "jenkins": "Jenkins",
    "ci/cd": "CI/CD", "cicd": "CI/CD",
    "github actions": "GitHub Actions",
    "gitlab ci": "GitLab CI",
    "heroku": "Heroku",
    "vercel": "Vercel",
    "nginx": "NGINX",
    "apache": "Apache",
    "linux": "Linux",

    # Tools
    "git": "Git",
    "github": "GitHub",
    "gitlab": "GitLab",
    "jira": "Jira",
    "confluence": "Confluence",
    "slack": "Slack",
    "figma": "Figma",
    "postman": "Postman",
    "swagger": "Swagger",
    "grafana": "Grafana",
    "prometheus": "Prometheus",
    "kibana": "Kibana",
    "tableau": "Tableau",
    "power bi": "Power BI", "powerbi": "Power BI",
    "excel": "Excel",
    "vscode": "VS Code", "visual studio code": "VS Code",

    # Concepts
    "ml": "Machine Learning", "machine learning": "Machine Learning",
    "dl": "Deep Learning", "deep learning": "Deep Learning",
    "nlp": "NLP", "natural language processing": "NLP",
    "cv": "Computer Vision", "computer vision": "Computer Vision",
    "ai": "Artificial Intelligence", "artificial intelligence": "Artificial Intelligence",
    "oop": "OOP", "object oriented programming": "OOP",
    "rest": "REST", "restful": "REST", "rest api": "REST API",
    "graphql": "GraphQL",
    "grpc": "gRPC",
    "microservices": "Microservices",
    "devops": "DevOps",
    "agile": "Agile",
    "scrum": "Scrum",
    "tdd": "TDD", "test driven development": "TDD",
    "data structures": "Data Structures",
    "algorithms": "Algorithms",
    "system design": "System Design",
}

# ── Related skills (taxonomy) ────────────────────────────────────
# Maps a canonical skill → list of related (not equivalent) skills

SKILL_RELATIONS: dict[str, list[str]] = {
    "JavaScript": ["TypeScript", "React", "Node.js", "Vue.js", "Angular"],
    "TypeScript": ["JavaScript", "React", "Node.js", "Angular"],
    "Python": ["Django", "Flask", "FastAPI", "pandas", "NumPy", "scikit-learn"],
    "Java": ["Spring Boot", "Kotlin", "Scala"],
    "React": ["JavaScript", "TypeScript", "Next.js", "Redux"],
    "Node.js": ["JavaScript", "Express.js", "TypeScript"],
    "PostgreSQL": ["MySQL", "SQL", "SQL Server", "SQLite"],
    "MySQL": ["PostgreSQL", "SQL", "SQL Server", "SQLite"],
    "MongoDB": ["Redis", "Cassandra", "DynamoDB"],
    "AWS": ["GCP", "Azure", "Docker", "Kubernetes"],
    "Docker": ["Kubernetes", "CI/CD", "DevOps"],
    "Machine Learning": ["Deep Learning", "NLP", "Computer Vision", "scikit-learn", "TensorFlow", "PyTorch"],
    "TensorFlow": ["PyTorch", "Keras", "Deep Learning"],
    "PyTorch": ["TensorFlow", "Keras", "Deep Learning"],
}


def normalize_skill(skill: str) -> str:
    """Normalize a skill name to its canonical form."""
    cleaned = skill.strip()
    lower = cleaned.lower()
    return SKILL_ALIASES.get(lower, cleaned)


def get_related_skills(skill: str) -> list[str]:
    """Get skills related to (but not equivalent to) the given skill."""
    canonical = normalize_skill(skill)
    return SKILL_RELATIONS.get(canonical, [])


def normalize_skill_list(skills: list[str]) -> list[str]:
    """Normalize a list of skills, deduplicating by canonical name."""
    seen = set()
    result = []
    for s in skills:
        canonical = normalize_skill(s)
        if canonical.lower() not in seen:
            seen.add(canonical.lower())
            result.append(canonical)
    return result


def find_skill_match_type(jd_skill: str, resume_skills: list[str]) -> tuple[str, str | None]:
    """
    Classify how a JD skill matches against resume skills.
    Returns: (match_type, matched_resume_skill | None)
    """
    jd_canonical = normalize_skill(jd_skill)
    resume_canonical = {normalize_skill(s): s for s in resume_skills}

    # Direct match
    if jd_canonical.lower() in {k.lower() for k in resume_canonical}:
        matched_key = next(k for k in resume_canonical if k.lower() == jd_canonical.lower())
        return "direct", resume_canonical[matched_key]

    # Related/taxonomy match
    related = get_related_skills(jd_skill)
    for rel in related:
        if rel.lower() in {k.lower() for k in resume_canonical}:
            matched_key = next(k for k in resume_canonical if k.lower() == rel.lower())
            return "related", resume_canonical[matched_key]

    # Partial match (substring)
    for canon, orig in resume_canonical.items():
        if jd_canonical.lower() in canon.lower() or canon.lower() in jd_canonical.lower():
            return "partial", orig

    return "missing", None

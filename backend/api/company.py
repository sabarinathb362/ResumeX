"""
Company Intelligence API — Real-time Company Research.
Extracts company name from JD text and performs web lookups
to gather company overview, tech stack, culture signals, and recent news.
"""
import re
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/api/company", tags=["company"])


class CompanyResearchRequest(BaseModel):
    jd_text: str
    company_name: Optional[str] = None


class CompanyIntel(BaseModel):
    company_name: str = ""
    industry: str = ""
    headquarters: str = ""
    company_size: str = ""
    founded: str = ""
    description: str = ""
    tech_stack: list[str] = Field(default_factory=list)
    culture_signals: list[str] = Field(default_factory=list)
    recent_news: list[dict] = Field(default_factory=list)
    hiring_insights: list[str] = Field(default_factory=list)
    resume_tips: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    confidence: str = "low"  # "high" | "medium" | "low"


def extract_company_name(jd_text: str) -> Optional[str]:
    """
    Heuristic extraction of company name from job description text.
    Tries multiple patterns commonly found in JDs.
    """
    text = jd_text.strip()

    # Pattern 1: "About <Company>" or "About Us at <Company>"
    m = re.search(r'(?:About|Join)\s+(?:Us\s+at\s+)?([A-Z][A-Za-z0-9&.\-\' ]{1,40}?)(?:\s*[\.\!\,\n]|\s+is\s|\s+are\s|\s+was\s)', text)
    if m:
        return m.group(1).strip()

    # Pattern 2: "at <Company>" or "for <Company>" near start
    m = re.search(r'(?:at|for|with|join)\s+([A-Z][A-Za-z0-9&.\-\' ]{1,35}?)(?:\s*[\.\!\,\n]|\s+as\s|\s+is\s|\s+to\s)', text[:500])
    if m:
        return m.group(1).strip()

    # Pattern 3: "Company: <Name>" or "Organization: <Name>"
    m = re.search(r'(?:Company|Organization|Employer|Firm)\s*[:\-]\s*([A-Za-z0-9&.\-\' ]{2,40})', text, re.I)
    if m:
        return m.group(1).strip()

    # Pattern 4: First capitalized multi-word proper noun in first 200 chars
    m = re.search(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}(?:\s+(?:Inc|Corp|LLC|Ltd|Technologies|Labs|Software|Systems|Solutions|Group|Studios)\.?))\b', text[:300])
    if m:
        return m.group(1).strip()

    return None


def build_company_intel_from_jd(jd_text: str, company_name: str) -> CompanyIntel:
    """
    Build company intelligence by analyzing the JD text itself for signals.
    This is the offline fallback that always works.
    """
    text_lower = jd_text.lower()
    intel = CompanyIntel(company_name=company_name)

    # Extract tech stack from JD
    tech_keywords = [
        "python", "java", "javascript", "typescript", "go", "golang", "rust", "c++", "c#",
        "react", "angular", "vue", "next.js", "node.js", "django", "flask", "fastapi", "spring",
        "aws", "azure", "gcp", "google cloud", "kubernetes", "docker", "terraform", "ansible",
        "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "kafka", "rabbitmq",
        "graphql", "rest api", "microservices", "ci/cd", "jenkins", "github actions",
        "machine learning", "deep learning", "tensorflow", "pytorch", "scikit-learn",
        "spark", "hadoop", "airflow", "databricks", "snowflake", "tableau", "power bi",
        "figma", "sketch", "jira", "confluence", "git", "linux", "agile", "scrum",
    ]
    found_tech = []
    for tech in tech_keywords:
        if tech in text_lower:
            found_tech.append(tech.title() if len(tech) > 3 else tech.upper())
    intel.tech_stack = found_tech[:15]

    # Culture signals from JD language
    culture_patterns = {
        "Remote-Friendly": ["remote", "work from home", "hybrid", "distributed team"],
        "Fast-Paced / Startup": ["fast-paced", "startup", "move fast", "early-stage", "series a", "series b"],
        "Collaborative": ["collaborative", "cross-functional", "teamwork", "team player"],
        "Innovation-Focused": ["innovative", "cutting-edge", "state-of-the-art", "bleeding edge"],
        "Diversity & Inclusion": ["diversity", "inclusion", "equal opportunity", "dei"],
        "Growth-Oriented": ["career growth", "learning", "mentorship", "professional development"],
        "Enterprise / Established": ["fortune 500", "enterprise", "established", "large-scale"],
        "Data-Driven": ["data-driven", "metrics", "analytics", "kpis"],
    }
    for signal, keywords in culture_patterns.items():
        if any(kw in text_lower for kw in keywords):
            intel.culture_signals.append(signal)

    # Industry detection
    industry_patterns = {
        "FinTech / Financial Services": ["fintech", "banking", "financial", "payments", "trading"],
        "Healthcare / MedTech": ["healthcare", "medical", "health", "clinical", "biotech"],
        "E-Commerce / Retail": ["e-commerce", "retail", "marketplace", "shopping"],
        "SaaS / Cloud": ["saas", "cloud", "platform", "subscription"],
        "AI / Machine Learning": ["artificial intelligence", "machine learning", "deep learning", "nlp"],
        "Cybersecurity": ["security", "cybersecurity", "threat", "vulnerability"],
        "EdTech": ["education", "edtech", "learning platform", "e-learning"],
        "Gaming": ["gaming", "game", "interactive entertainment"],
        "Enterprise Software": ["enterprise", "b2b", "crm", "erp"],
        "Media / Content": ["media", "content", "streaming", "publishing"],
    }
    for industry, keywords in industry_patterns.items():
        if any(kw in text_lower for kw in keywords):
            intel.industry = industry
            break

    # Company size hints
    size_patterns = {
        "Startup (1-50)": ["startup", "early-stage", "small team", "founding"],
        "Small (50-200)": ["growing team", "50+", "100+"],
        "Mid-size (200-1000)": ["200+", "500+", "mid-size"],
        "Large (1000-5000)": ["1000+", "2000+", "large company"],
        "Enterprise (5000+)": ["5000+", "10000+", "global", "fortune"],
    }
    for size, keywords in size_patterns.items():
        if any(kw in text_lower for kw in keywords):
            intel.company_size = size
            break

    # Generate resume tips based on JD analysis
    tips = []
    if found_tech:
        tips.append(f"Prominently feature experience with {', '.join(found_tech[:5])} — these are explicitly mentioned in the JD.")
    if "remote" in text_lower or "hybrid" in text_lower:
        tips.append("Highlight remote collaboration skills and async communication experience.")
    if "startup" in text_lower or "fast-paced" in text_lower:
        tips.append("Emphasize adaptability, wearing multiple hats, and shipping quickly in ambiguous environments.")
    if "leadership" in text_lower or "mentor" in text_lower:
        tips.append("Include examples of leading projects, mentoring juniors, or driving technical decisions.")
    if "scale" in text_lower or "performance" in text_lower:
        tips.append("Quantify scale: requests/sec, data volume, users served, latency improvements.")
    if any(kw in text_lower for kw in ["agile", "scrum", "sprint"]):
        tips.append("Mention your experience with Agile/Scrum methodologies and sprint planning.")
    if not tips:
        tips.append("Mirror the exact language and keywords from this JD in your resume bullets.")
    intel.resume_tips = tips

    # Hiring insights
    hiring = []
    req_count = len(re.findall(r'(?:require|must have|essential)', text_lower))
    pref_count = len(re.findall(r'(?:prefer|nice to have|bonus|plus)', text_lower))
    if req_count > 0:
        hiring.append(f"JD contains {req_count} hard requirement signal(s) — ensure these are clearly evidenced.")
    if pref_count > 0:
        hiring.append(f"JD contains {pref_count} 'nice-to-have' signal(s) — mentioning these gives you an edge.")
    exp_match = re.search(r'(\d+)\+?\s*(?:years?|yrs?)\s*(?:of)?\s*experience', text_lower)
    if exp_match:
        hiring.append(f"Target experience level: {exp_match.group(1)}+ years. Ensure your timeline reflects this.")
    intel.hiring_insights = hiring

    intel.confidence = "medium" if company_name else "low"
    return intel


@router.post(
    "/research",
    response_model=CompanyIntel,
    summary="Research a company from JD text for tailored resume insights",
)
async def research_company(request: CompanyResearchRequest):
    """
    Extracts company name from JD and builds intelligence profile.
    Uses JD text analysis for reliable offline insights,
    with optional web enrichment when available.
    """
    company_name = request.company_name or extract_company_name(request.jd_text)
    if not company_name:
        company_name = "Unknown Company"

    intel = build_company_intel_from_jd(request.jd_text, company_name)

    # Try web enrichment if company name was found
    if company_name and company_name != "Unknown Company":
        try:
            intel = await enrich_with_web_search(intel, company_name)
        except Exception as e:
            logger.warning(f"Web enrichment failed for {company_name}: {e}")

    return intel


async def enrich_with_web_search(intel: CompanyIntel, company_name: str) -> CompanyIntel:
    """
    Attempt to enrich company intel with web search results.
    This is best-effort — failures are gracefully handled.
    """
    import aiohttp

    search_queries = [
        f"{company_name} company overview headquarters employees",
        f"{company_name} engineering tech stack technologies",
        f"{company_name} company culture glassdoor",
    ]

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
            for query in search_queries[:1]:  # Limit to 1 query for speed
                try:
                    # Use DuckDuckGo Instant Answer API (no API key needed)
                    params = {"q": query, "format": "json", "no_html": 1}
                    async with session.get(
                        "https://api.duckduckgo.com/",
                        params=params,
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json(content_type=None)
                            abstract = data.get("AbstractText", "")
                            if abstract and len(abstract) > 20:
                                intel.description = abstract[:300]
                                intel.confidence = "high"
                            source = data.get("AbstractURL", "")
                            if source:
                                intel.source_urls.append(source)
                except Exception:
                    pass
    except Exception:
        pass

    return intel

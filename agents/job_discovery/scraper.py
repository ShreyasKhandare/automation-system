"""
agents/job_discovery/scraper.py — Multi-source job scraper.

Implemented sources (Session 4):
  - SerpAPI Google Jobs
  - Otta RSS
  - Indeed RSS
  - Greenhouse (board scrape via requests)

Skipped for now (enabled in config but wired up later):
  - Wellfound API (requires auth token)
  - LinkedIn via Apify (toggle-gated)

All sources normalize output to the standard JobListing dataclass
matching the schema in SYSTEM_DESIGN.md Section 3.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.config_loader import load_config
from shared.secrets import get_secret

log = get_logger("job_discovery")

try:
    import feedparser
    _HAS_FEEDPARSER = True
except ImportError:
    _HAS_FEEDPARSER = False
    log.warning("feedparser_missing", msg="pip install feedparser")

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False


# ---------------------------------------------------------------------------
# Data model — matches Section 3 schema exactly
# ---------------------------------------------------------------------------

@dataclass
class JobListing:
    id: str
    title: str
    company: str
    url: str
    source: str
    location: str
    salary_min: int | None
    salary_max: int | None
    salary_currency: str
    employment_type: str
    remote: bool
    tech_stack: list[str]
    description_raw: str
    description_snippet: str       # first ~400 chars for Claude scoring
    posted_date: str               # YYYY-MM-DD or ""
    score: float | None = None
    score_reason: str = ""
    status: str = "new"
    applied_date: str | None = None
    notes: str = ""

    def to_db_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "company": self.company,
            "url": self.url,
            "source": self.source,
            "location": self.location,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "salary_currency": self.salary_currency,
            "employment_type": self.employment_type,
            "remote": int(self.remote),
            "tech_stack": json.dumps(self.tech_stack),
            "description_raw": self.description_raw[:5000],
            "description_clean": self.description_snippet,
            "posted_date": self.posted_date,
            "score": self.score,
            "score_reason": self.score_reason,
            "status": self.status,
        }

    def to_sheet_row(self) -> list:
        """Row for Google Sheets Job Tracker."""
        return [
            self.id,
            self.title,
            self.company,
            self.location,
            "Yes" if self.remote else "No",
            self.posted_date,
            self.source,
            f"{self.salary_min or ''}–{self.salary_max or ''}",
            self.score or "",
            self.score_reason[:200] if self.score_reason else "",
            self.status,
            self.url,
            ", ".join(self.tech_stack[:8]),
        ]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_job_id(company: str, title: str, posted: str) -> str:
    """Stable ID from (company, title, posted_date)."""
    slug = re.sub(r"[^a-z0-9]+", "_", f"{company}_{title}".lower())[:40].strip("_")
    date_part = (posted or datetime.now(timezone.utc).strftime("%Y%m%d")).replace("-", "")[:8]
    return f"job_{date_part}_{slug}"


def _clean(text: str | None, max_len: int = 0) -> str:
    if not text:
        return ""
    cleaned = " ".join(str(text).split())
    return cleaned[:max_len] if max_len else cleaned


def _extract_salary(text: str) -> tuple[int | None, int | None]:
    """Parse salary range from text like '$130K–$160K' or '$130,000 - $160,000'."""
    text = text.replace(",", "").replace("USD", "")
    matches = re.findall(r"\$?\s*(\d{2,3})[Kk]?", text)
    if len(matches) >= 2:
        a, b = int(matches[0]), int(matches[1])
        # Normalize K values
        if a < 1000:
            a *= 1000
        if b < 1000:
            b *= 1000
        return (a, b) if a < b else (b, a)
    return None, None


def _is_remote(location: str, title: str, desc: str) -> bool:
    combined = f"{location} {title} {desc}".lower()
    return bool(re.search(r"\bremote\b", combined))


def _extract_tech_stack(text: str) -> list[str]:
    """Pull known tech keywords from raw text."""
    known = [
        "Python", "FastAPI", "LangChain", "LangGraph", "RAG", "LLM",
        "GPT", "Claude", "OpenAI", "Anthropic", "HuggingFace",
        "ChromaDB", "Pinecone", "Weaviate", "Qdrant", "pgvector",
        "Streamlit", "Docker", "Kubernetes", "AWS", "GCP", "Azure",
        "TypeScript", "JavaScript", "React", "Node.js", "PostgreSQL",
        "Redis", "MongoDB", "Spark", "Kafka", "MLflow", "Airflow",
        "PyTorch", "TensorFlow", "scikit-learn", "Pandas", "NumPy",
        "Git", "GitHub", "CI/CD", "REST", "GraphQL",
    ]
    found = []
    for tech in known:
        if re.search(r"\b" + re.escape(tech) + r"\b", text, re.IGNORECASE):
            found.append(tech)
    return found[:15]


def _parse_rss_date(raw: str | None) -> str:
    """Convert feedparser date tuple or string to YYYY-MM-DD."""
    if not raw:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        # feedparser sometimes returns a struct_time
        if hasattr(raw, "tm_year"):
            return f"{raw.tm_year:04d}-{raw.tm_mon:02d}-{raw.tm_mday:02d}"
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Source: SerpAPI Google Jobs
# ---------------------------------------------------------------------------

_SERPAPI_URL = "https://serpapi.com/search"


def fetch_serpapi(stealth: bool = False) -> list[JobListing]:
    """Query SerpAPI Google Jobs for each target title."""
    try:
        api_key = get_secret("SERPAPI_API_KEY")
    except Exception:
        log.warning("serpapi_skip", msg="SERPAPI_API_KEY not set")
        return []

    cfg = load_config()
    prefs = cfg.job_search_preferences
    titles = cfg.profile.target_titles[:4]   # cap queries to save credits
    locations = ["United States"]            # Google Jobs works best with country

    listings: list[JobListing] = []
    seen_fingerprints: set[str] = set()

    for title in titles:
        for loc in locations[:1]:
            try:
                params = {
                    "engine": "google_jobs",
                    "q": f"{title} {' OR '.join(prefs.preferred_tech_stack[:3])}",
                    "location": loc,
                    "hl": "en",
                    "chips": "date_posted:week",
                    "api_key": api_key,
                }
                if stealth:
                    params["chips"] = "date_posted:month"

                resp = requests.get(_SERPAPI_URL, params=params, timeout=20)
                resp.raise_for_status()
                data = resp.json()

                for job in data.get("jobs_results", [])[:10]:
                    company = _clean(job.get("company_name", ""), 80)
                    job_title = _clean(job.get("title", ""), 120)
                    if not company or not job_title:
                        continue

                    fingerprint = f"{company.lower()}:{job_title.lower()}"
                    if fingerprint in seen_fingerprints:
                        continue
                    seen_fingerprints.add(fingerprint)

                    desc = _clean(job.get("description", ""))
                    highlights = job.get("job_highlights", [])
                    highlight_text = " ".join(
                        " ".join(h.get("items", []))
                        for h in highlights
                    )

                    full_desc = f"{desc} {highlight_text}"
                    extensions = job.get("extensions", [])
                    ext_text = " ".join(extensions)

                    salary_min, salary_max = _extract_salary(ext_text + full_desc)
                    remote = _is_remote(loc, job_title, full_desc)
                    posted = ""
                    for ext in extensions:
                        if "ago" in ext.lower() or "day" in ext.lower() or "week" in ext.lower():
                            pass  # SerpAPI doesn't always give exact dates
                    posted = datetime.now(timezone.utc).strftime("%Y-%m-%d")

                    listings.append(JobListing(
                        id=_make_job_id(company, job_title, posted),
                        title=job_title,
                        company=company,
                        url=job.get("related_links", [{}])[0].get("link", "") or
                            f"https://www.google.com/search?q={company}+{job_title}+jobs",
                        source="serpapi",
                        location=_clean(job.get("location", loc), 100),
                        salary_min=salary_min,
                        salary_max=salary_max,
                        salary_currency="USD",
                        employment_type="full-time",
                        remote=remote,
                        tech_stack=_extract_tech_stack(full_desc),
                        description_raw=full_desc[:5000],
                        description_snippet=full_desc[:400],
                        posted_date=posted,
                    ))

                time.sleep(1.5 if not stealth else 3.0)

            except Exception as e:
                log.error("serpapi_query_failed", title=title, error=str(e))

    log.info("serpapi_fetched", count=len(listings))
    return listings


# ---------------------------------------------------------------------------
# Source: Otta RSS
# ---------------------------------------------------------------------------

_OTTA_RSS = "https://otta.com/jobs/rss"


def fetch_otta_rss() -> list[JobListing]:
    if not _HAS_FEEDPARSER:
        return []
    try:
        feed = feedparser.parse(_OTTA_RSS)
        listings: list[JobListing] = []
        for entry in feed.entries[:20]:
            title = _clean(getattr(entry, "title", ""), 120)
            company = _clean(getattr(entry, "author", "") or
                             getattr(entry, "source", {}).get("title", ""), 80)
            if not title:
                continue
            url = getattr(entry, "link", "")
            desc = _clean(getattr(entry, "summary", "") or
                          getattr(entry, "description", ""))
            posted = _parse_rss_date(getattr(entry, "published_parsed", None) or
                                     getattr(entry, "updated_parsed", None))

            # Try to extract company from title pattern "Title at Company"
            if not company and " at " in title:
                parts = title.split(" at ", 1)
                title, company = parts[0].strip(), parts[1].strip()

            if not company:
                company = "Unknown"

            listings.append(JobListing(
                id=_make_job_id(company, title, posted),
                title=title,
                company=company,
                url=url,
                source="otta",
                location="Remote",
                salary_min=None,
                salary_max=None,
                salary_currency="USD",
                employment_type="full-time",
                remote=_is_remote("", title, desc),
                tech_stack=_extract_tech_stack(desc),
                description_raw=desc[:5000],
                description_snippet=desc[:400],
                posted_date=posted,
            ))
        log.info("otta_fetched", count=len(listings))
        return listings
    except Exception as e:
        log.error("otta_fetch_failed", error=str(e))
        return []


# ---------------------------------------------------------------------------
# Source: Indeed RSS
# ---------------------------------------------------------------------------

_INDEED_RSS_TMPL = (
    "https://www.indeed.com/rss?q={query}&l=Remote&jt=fulltime&sort=date"
)


def fetch_indeed_rss() -> list[JobListing]:
    if not _HAS_FEEDPARSER:
        return []

    cfg = load_config()
    titles = cfg.profile.target_titles[:3]
    listings: list[JobListing] = []
    seen: set[str] = set()

    for title in titles:
        try:
            query = title.replace(" ", "+")
            url = _INDEED_RSS_TMPL.format(query=query)
            feed = feedparser.parse(url)

            for entry in feed.entries[:8]:
                job_title = _clean(getattr(entry, "title", ""), 120)
                link = getattr(entry, "link", "")
                desc = _clean(getattr(entry, "summary", ""))
                posted = _parse_rss_date(getattr(entry, "published_parsed", None))

                # Extract company from title pattern "Job Title - Company"
                company = "Unknown"
                if " - " in job_title:
                    parts = job_title.rsplit(" - ", 1)
                    job_title, company = parts[0].strip(), parts[1].strip()

                fp = f"{company.lower()}:{job_title.lower()}"
                if fp in seen:
                    continue
                seen.add(fp)

                listings.append(JobListing(
                    id=_make_job_id(company, job_title, posted),
                    title=job_title,
                    company=company,
                    url=link,
                    source="indeed",
                    location="Remote",
                    salary_min=None,
                    salary_max=None,
                    salary_currency="USD",
                    employment_type="full-time",
                    remote=True,
                    tech_stack=_extract_tech_stack(desc),
                    description_raw=desc[:5000],
                    description_snippet=desc[:400],
                    posted_date=posted,
                ))
            time.sleep(1.0)
        except Exception as e:
            log.error("indeed_fetch_failed", title=title, error=str(e))

    log.info("indeed_fetched", count=len(listings))
    return listings


# ---------------------------------------------------------------------------
# Source: Greenhouse board scrape
# ---------------------------------------------------------------------------

# Well-known AI-hiring companies on Greenhouse
_GREENHOUSE_BOARDS = [
    "anthropic", "cohere", "adept", "imbue", "together",
    "perplexity", "descript", "hebbia", "mosaic", "replit",
]

_GH_BOARD_URL = "https://boards.greenhouse.io/{company}/jobs.json"
_GH_JOB_URL   = "https://boards.greenhouse.io/{company}/jobs/{job_id}"


def _fetch_greenhouse_board(company: str) -> list[JobListing]:
    if not _HAS_BS4:
        return []
    cfg = load_config()
    target_titles_lower = [t.lower() for t in cfg.profile.target_titles]

    try:
        resp = requests.get(
            _GH_BOARD_URL.format(company=company),
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        data = resp.json()

        listings: list[JobListing] = []
        for job in data.get("jobs", [])[:30]:
            title = _clean(job.get("title", ""), 120)
            if not title:
                continue
            # Filter to AI-adjacent titles
            if not any(kw in title.lower() for kw in ["ai", "ml", "machine learning",
                                                        "llm", "engineer", "data", "nlp"]):
                continue
            # Also check against target titles
            title_match = any(
                kw in title.lower() for kw in
                ["ai", "llm", "ml", "machine learning", "engineer", "nlp", "data scientist"]
            )
            if not title_match:
                continue

            job_id = job.get("id", "")
            url = _GH_JOB_URL.format(company=company, job_id=job_id)
            location_data = job.get("location", {})
            location = _clean(location_data.get("name", ""), 100)
            updated = job.get("updated_at", "")
            posted = updated[:10] if updated else datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Fetch full description
            desc = ""
            try:
                detail_resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                detail_resp.raise_for_status()
                detail_data = detail_resp.json()
                soup = BeautifulSoup(detail_data.get("content", ""), "html.parser")
                desc = _clean(soup.get_text(" ", strip=True))
            except Exception:
                pass

            listings.append(JobListing(
                id=_make_job_id(company, title, posted),
                title=title,
                company=company.title(),
                url=url,
                source="greenhouse",
                location=location,
                salary_min=None,
                salary_max=None,
                salary_currency="USD",
                employment_type="full-time",
                remote=_is_remote(location, title, desc),
                tech_stack=_extract_tech_stack(desc),
                description_raw=desc[:5000],
                description_snippet=desc[:400],
                posted_date=posted,
            ))
            time.sleep(0.3)

        return listings
    except Exception as e:
        log.error("greenhouse_fetch_failed", company=company, error=str(e))
        return []


def fetch_greenhouse() -> list[JobListing]:
    all_listings: list[JobListing] = []
    for company in _GREENHOUSE_BOARDS:
        listings = _fetch_greenhouse_board(company)
        all_listings.extend(listings)
        time.sleep(0.5)
    log.info("greenhouse_fetched", count=len(all_listings))
    return all_listings


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _deduplicate(listings: list[JobListing]) -> list[JobListing]:
    """
    Deduplicate by (company_slug, title_slug).
    Prefer listings with more description content if duplicated.
    """
    seen: dict[str, JobListing] = {}
    for job in listings:
        key = re.sub(r"[^a-z0-9]", "", f"{job.company}{job.title}".lower())[:60]
        existing = seen.get(key)
        if existing is None or len(job.description_raw) > len(existing.description_raw):
            seen[key] = job
    return list(seen.values())


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def scrape(stealth: bool = False, dry_run: bool = False) -> list[JobListing]:
    """
    Run all enabled scrapers, deduplicate, and return raw listings.
    Scoring is done separately in scorer.py.
    """
    cfg = load_config()
    platforms = cfg.platforms

    all_listings: list[JobListing] = []

    if platforms.serpapi_google_jobs.enabled:
        all_listings.extend(fetch_serpapi(stealth=stealth))

    if platforms.otta.enabled:
        all_listings.extend(fetch_otta_rss())

    if platforms.indeed.enabled:
        all_listings.extend(fetch_indeed_rss())

    if platforms.greenhouse.enabled:
        all_listings.extend(fetch_greenhouse())

    deduped = _deduplicate(all_listings)
    log.info("scrape_complete", raw=len(all_listings), deduped=len(deduped), dry_run=dry_run)
    return deduped


if __name__ == "__main__":
    jobs = scrape(dry_run=True)
    print(f"Scraped {len(jobs)} jobs")
    for j in jobs[:5]:
        print(f"  [{j.source}] {j.title} @ {j.company} ({j.location})")

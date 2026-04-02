"""
agents/market_research/scraper.py — Weekly intelligence aggregation.

Sources (controlled by config.research_and_discovery.sources):
  - GitHub Trending (BeautifulSoup scrape)
  - HuggingFace Papers API (unauthenticated)
  - arXiv RSS (cs.AI, cs.LG)
  - Reddit r/MachineLearning, r/LocalLLaMA (PRAW)
  - Hacker News (Algolia API)
  - Wellfound/Greenhouse job postings (SerpAPI)

All fetchers return list of RawResearchItem and fail silently on error.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger

log = get_logger("market_research")


@dataclass
class RawResearchItem:
    title: str
    url: str
    source: str             # github_trending | huggingface | arxiv | reddit | hn | jobs
    snippet: str = ""
    author: str = ""
    score: float = 0.0      # upvotes / stars / citations
    published_at: str = ""  # ISO date string

    def item_id(self) -> str:
        import hashlib
        key = (self.source + self.title).lower().replace(" ", "")
        return hashlib.md5(key.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# GitHub Trending
# ---------------------------------------------------------------------------

def fetch_github_trending(language: str = "python", since: str = "weekly") -> list[RawResearchItem]:
    """Scrape GitHub Trending page for the given language/period."""
    try:
        import requests
        from bs4 import BeautifulSoup

        url = f"https://github.com/trending/{language}?since={since}"
        resp = requests.get(url, headers={"User-Agent": "automation-system/1.0"}, timeout=15)
        if not resp.ok:
            log.warning("github_trending_fetch_failed", status=resp.status_code)
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        for article in soup.select("article.Box-row")[:15]:
            name_tag = article.select_one("h2 a")
            if not name_tag:
                continue
            repo_path = name_tag.get("href", "").strip("/")
            description_tag = article.select_one("p")
            snippet = description_tag.get_text(strip=True) if description_tag else ""
            stars_tag = article.select_one("a[href$='/stargazers']")
            stars_text = stars_tag.get_text(strip=True).replace(",", "") if stars_tag else "0"
            try:
                stars = float(stars_text.replace("k", "")) * (1000 if "k" in stars_text else 1)
            except ValueError:
                stars = 0

            items.append(RawResearchItem(
                title=repo_path,
                url=f"https://github.com/{repo_path}",
                source="github_trending",
                snippet=snippet[:200],
                score=stars,
                published_at=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            ))

        log.info("github_trending_fetched", count=len(items))
        return items
    except Exception as e:
        log.warning("github_trending_error", error=str(e))
        return []


# ---------------------------------------------------------------------------
# HuggingFace Papers
# ---------------------------------------------------------------------------

def fetch_huggingface_papers(limit: int = 20) -> list[RawResearchItem]:
    """Fetch top papers from HuggingFace Papers API."""
    try:
        import requests

        resp = requests.get(
            "https://huggingface.co/api/daily_papers",
            params={"limit": limit},
            headers={"User-Agent": "automation-system/1.0"},
            timeout=15,
        )
        if not resp.ok:
            log.warning("hf_papers_fetch_failed", status=resp.status_code)
            return []

        papers = resp.json() if isinstance(resp.json(), list) else resp.json().get("papers", [])
        items = []
        for p in papers[:limit]:
            paper = p.get("paper", p)
            arxiv_id = paper.get("id", "")
            title = paper.get("title", "")
            abstract = paper.get("summary", "")[:300]
            authors = ", ".join(
                a.get("name", "") for a in (paper.get("authors") or [])[:3]
            )
            upvotes = p.get("numComments", 0) or 0

            items.append(RawResearchItem(
                title=title,
                url=f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "https://huggingface.co/papers",
                source="huggingface",
                snippet=abstract,
                author=authors,
                score=float(upvotes),
                published_at=p.get("publishedAt", "")[:10],
            ))

        log.info("hf_papers_fetched", count=len(items))
        return items
    except Exception as e:
        log.warning("hf_papers_error", error=str(e))
        return []


# ---------------------------------------------------------------------------
# arXiv RSS
# ---------------------------------------------------------------------------

def fetch_arxiv(feeds: list[str] | None = None) -> list[RawResearchItem]:
    """Fetch recent papers from arXiv RSS feeds."""
    if feeds is None:
        feeds = [
            "https://arxiv.org/rss/cs.AI",
            "https://arxiv.org/rss/cs.LG",
            "https://arxiv.org/rss/cs.CL",
        ]
    try:
        import feedparser
    except ImportError:
        log.warning("feedparser_not_installed")
        return []

    items = []
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:10]:
                items.append(RawResearchItem(
                    title=entry.get("title", ""),
                    url=entry.get("link", ""),
                    source="arxiv",
                    snippet=(entry.get("summary", "") or "")[:300],
                    author=entry.get("author", ""),
                    published_at=(entry.get("published", "") or "")[:10],
                ))
            time.sleep(0.5)
        except Exception as e:
            log.warning("arxiv_feed_error", url=feed_url, error=str(e))

    log.info("arxiv_fetched", count=len(items))
    return items


# ---------------------------------------------------------------------------
# Hacker News (Algolia)
# ---------------------------------------------------------------------------

def fetch_hacker_news(queries: list[str] | None = None, days: int = 7) -> list[RawResearchItem]:
    """Search Hacker News via Algolia API for AI/LLM stories."""
    if queries is None:
        queries = ["LLM agent", "RAG pipeline", "LangChain", "AI engineer", "LangGraph"]
    try:
        import requests
        from datetime import timedelta

        since_ts = int(
            (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
        )
        items: list[RawResearchItem] = []
        seen_ids: set[str] = set()

        for q in queries[:3]:  # limit to 3 queries
            resp = requests.get(
                "https://hn.algolia.com/api/v1/search",
                params={
                    "query": q,
                    "tags": "story",
                    "numericFilters": f"created_at_i>{since_ts},points>10",
                    "hitsPerPage": 10,
                },
                timeout=10,
            )
            if not resp.ok:
                continue
            for hit in resp.json().get("hits", []):
                hn_id = hit.get("objectID", "")
                if hn_id in seen_ids:
                    continue
                seen_ids.add(hn_id)
                items.append(RawResearchItem(
                    title=hit.get("title", ""),
                    url=hit.get("url") or f"https://news.ycombinator.com/item?id={hn_id}",
                    source="hn",
                    snippet="",
                    author=hit.get("author", ""),
                    score=float(hit.get("points", 0)),
                    published_at=hit.get("created_at", "")[:10],
                ))
            time.sleep(0.3)

        log.info("hn_fetched", count=len(items))
        return items
    except Exception as e:
        log.warning("hn_error", error=str(e))
        return []


# ---------------------------------------------------------------------------
# Wellfound/Job Postings (SerpAPI)
# ---------------------------------------------------------------------------

def fetch_job_postings(keywords: list[str] | None = None, dry_run: bool = False) -> list[RawResearchItem]:
    """
    Fetch AI engineer job postings via SerpAPI Google Jobs.
    Returns job titles and companies as RawResearchItem.
    """
    if dry_run:
        return []
    if keywords is None:
        keywords = ["AI Engineer LangGraph RAG", "LLM Engineer FinTech remote"]

    try:
        import requests
        from shared.secrets import get_secret

        api_key = get_secret("SERPAPI_API_KEY")
        items: list[RawResearchItem] = []
        seen: set[str] = set()

        for query in keywords[:2]:
            resp = requests.get(
                "https://serpapi.com/search",
                params={"engine": "google_jobs", "q": query, "api_key": api_key, "num": 10},
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            for job in resp.json().get("jobs_results", []):
                key = (job.get("title", "") + job.get("company_name", "")).lower()
                if key in seen:
                    continue
                seen.add(key)
                items.append(RawResearchItem(
                    title=f"{job.get('title','')} @ {job.get('company_name','')}",
                    url=job.get("share_link") or "",
                    source="jobs",
                    snippet=job.get("description", "")[:200],
                    published_at=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                ))
            time.sleep(1)

        log.info("job_postings_fetched", count=len(items))
        return items
    except Exception as e:
        log.warning("job_postings_error", error=str(e))
        return []


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

def aggregate_all(dry_run: bool = False) -> list[RawResearchItem]:
    """
    Aggregate from all enabled sources and deduplicate by item_id.
    Source toggles respected from config.research_and_discovery.sources.
    """
    from shared.config_loader import load_config

    cfg = load_config()
    sources = cfg.research_and_discovery.sources
    all_items: list[RawResearchItem] = []

    if sources.github_trending:
        all_items.extend(fetch_github_trending())
    if sources.huggingface_papers:
        all_items.extend(fetch_huggingface_papers())
    if sources.arxiv:
        all_items.extend(fetch_arxiv())
    if sources.hacker_news:
        all_items.extend(fetch_hacker_news())
    if sources.wellfound_jobs:
        all_items.extend(fetch_job_postings(dry_run=dry_run))

    # Deduplicate by item_id
    seen: set[str] = set()
    deduped: list[RawResearchItem] = []
    for item in all_items:
        iid = item.item_id()
        if iid not in seen:
            seen.add(iid)
            deduped.append(item)

    log.info("aggregated", total=len(all_items), deduped=len(deduped))
    return deduped

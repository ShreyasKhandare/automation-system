"""
agents/ai_radar/aggregator.py — Fetch items from all configured AI sources.

Sources:
  RSS feeds  : TLDR AI, The Rundown AI, Ben's Bites, arXiv cs.AI/cs.LG
  HuggingFace: Daily Papers API  (papers.huggingface.co)
  HN Algolia : Hacker News search API for "AI", "LLM", "LangChain", etc.
  GitHub     : GitHub Trending (scraped via requests + BeautifulSoup)
  Product Hunt: RSS feed

Returns a list of RawItem dicts ready for filter.py to score.
"""

from __future__ import annotations

import hashlib
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

log = get_logger("ai_radar")

# Try feedparser — required for RSS sources
try:
    import feedparser
    _HAS_FEEDPARSER = True
except ImportError:
    _HAS_FEEDPARSER = False
    log.warning("feedparser_missing", msg="Install feedparser for RSS support: pip install feedparser")

# Try BeautifulSoup — used only for GitHub Trending scrape
try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RawItem:
    """A single aggregated item before Claude scoring."""
    id: str                   # stable hash(url or title+source)
    title: str
    url: str
    source: str               # hn | huggingface | arxiv | github_trending | product_hunt | rss_*
    published_at: str         # ISO string or ""
    summary: str              # raw text snippet (max ~500 chars)
    raw_content: str = ""     # full text for Claude (trimmed)
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "summary": self.summary,
            "raw_content": self.raw_content[:2000],  # cap for Claude prompt
        }


def _make_id(source: str, key: str) -> str:
    """Stable deterministic ID for deduplication."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    return hashlib.md5(f"{today}:{source}:{key}".encode()).hexdigest()[:16]


def _clean(text: str | None, max_len: int = 500) -> str:
    if not text:
        return ""
    return " ".join(str(text).split())[:max_len]


def _parse_date(entry: Any) -> str:
    """Try to extract a date string from a feedparser entry."""
    for attr in ("published", "updated", "created"):
        val = getattr(entry, attr, None)
        if val:
            return str(val)
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# RSS fetcher (feedparser)
# ---------------------------------------------------------------------------

_RSS_FEEDS = {
    "tldr_ai":    "https://tldr.tech/ai/rss",
    "rundown_ai": "https://www.therundown.ai/rss",
    "bens_bites": "https://www.bensbites.co/feed",
    "arxiv_cs_ai": "http://rss.arxiv.org/rss/cs.AI",
    "arxiv_cs_lg": "http://rss.arxiv.org/rss/cs.LG",
}


def fetch_rss(source_key: str, url: str, max_items: int = 15) -> list[RawItem]:
    if not _HAS_FEEDPARSER:
        return []
    try:
        feed = feedparser.parse(url)
        items: list[RawItem] = []
        for entry in feed.entries[:max_items]:
            title = _clean(getattr(entry, "title", ""), 200)
            link = getattr(entry, "link", "") or ""
            summary = _clean(getattr(entry, "summary", "") or getattr(entry, "description", ""), 500)
            if not title:
                continue
            items.append(RawItem(
                id=_make_id(source_key, link or title),
                title=title,
                url=link,
                source=f"rss_{source_key}",
                published_at=_parse_date(entry),
                summary=summary,
                raw_content=summary,
            ))
        log.info("rss_fetched", source=source_key, count=len(items))
        return items
    except Exception as e:
        log.error("rss_fetch_failed", source=source_key, error=str(e))
        return []


def fetch_all_rss(enabled_sources: dict) -> list[RawItem]:
    items: list[RawItem] = []
    for key, url in _RSS_FEEDS.items():
        # Map config key → check if source is enabled
        if key.startswith("arxiv") and not enabled_sources.get("arxiv", True):
            continue
        items.extend(fetch_rss(key, url))
    return items


# ---------------------------------------------------------------------------
# HuggingFace Daily Papers
# ---------------------------------------------------------------------------

_HF_PAPERS_URL = "https://huggingface.co/api/daily_papers"


def fetch_huggingface_papers(max_items: int = 10) -> list[RawItem]:
    try:
        resp = requests.get(_HF_PAPERS_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        items: list[RawItem] = []
        for paper in data[:max_items]:
            p = paper.get("paper", paper)
            title = _clean(p.get("title", ""), 200)
            arxiv_id = p.get("id", "")
            url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "https://huggingface.co/papers"
            abstract = _clean(p.get("summary") or p.get("abstract", ""), 600)
            published = p.get("publishedAt", "")
            if not title:
                continue
            items.append(RawItem(
                id=_make_id("huggingface", arxiv_id or title),
                title=title,
                url=url,
                source="huggingface",
                published_at=str(published),
                summary=abstract[:300],
                raw_content=abstract,
            ))
        log.info("huggingface_fetched", count=len(items))
        return items
    except Exception as e:
        log.error("huggingface_fetch_failed", error=str(e))
        return []


# ---------------------------------------------------------------------------
# Hacker News via Algolia API
# ---------------------------------------------------------------------------

_HN_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"
_HN_QUERIES = ["LLM", "AI agent", "RAG", "LangChain", "Claude", "GPT", "fine-tuning", "vector database"]


def fetch_hacker_news(max_items: int = 15) -> list[RawItem]:
    try:
        all_hits: list[dict] = []
        seen_ids: set[str] = set()

        for query in _HN_QUERIES[:4]:  # limit API calls
            params = {
                "query": query,
                "tags": "story",
                "hitsPerPage": 8,
                "numericFilters": "points>10",
            }
            resp = requests.get(_HN_ALGOLIA_URL, params=params, timeout=10)
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
            for h in hits:
                oid = str(h.get("objectID", ""))
                if oid not in seen_ids:
                    seen_ids.add(oid)
                    all_hits.append(h)

        # Sort by points desc, take top N
        all_hits.sort(key=lambda h: h.get("points", 0), reverse=True)

        items: list[RawItem] = []
        for h in all_hits[:max_items]:
            title = _clean(h.get("title", ""), 200)
            url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
            summary = f"{h.get('points', 0)} points · {h.get('num_comments', 0)} comments"
            if not title:
                continue
            items.append(RawItem(
                id=_make_id("hn", str(h.get("objectID", title))),
                title=title,
                url=url,
                source="hn",
                published_at=str(h.get("created_at", "")),
                summary=summary,
                raw_content=f"{title}. {summary}",
            ))

        log.info("hn_fetched", count=len(items))
        return items
    except Exception as e:
        log.error("hn_fetch_failed", error=str(e))
        return []


# ---------------------------------------------------------------------------
# GitHub Trending (scrape)
# ---------------------------------------------------------------------------

_GH_TRENDING_URL = "https://github.com/trending?l=python&since=daily"


def fetch_github_trending(max_items: int = 10) -> list[RawItem]:
    if not _HAS_BS4:
        log.warning("github_trending_skip", msg="beautifulsoup4 not installed")
        return []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; AutomationBot/1.0)"}
        resp = requests.get(_GH_TRENDING_URL, headers=headers, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        articles = soup.select("article.Box-row")[:max_items]

        items: list[RawItem] = []
        for article in articles:
            h2 = article.select_one("h2 a")
            if not h2:
                continue
            repo_path = h2.get("href", "").strip("/")
            title = repo_path.replace("/", " / ")
            url = f"https://github.com/{repo_path}"
            desc_el = article.select_one("p")
            summary = _clean(desc_el.text if desc_el else "", 300)
            stars_el = article.select_one("span[aria-label*='star']")
            stars = _clean(stars_el.text if stars_el else "")

            items.append(RawItem(
                id=_make_id("github_trending", repo_path),
                title=title,
                url=url,
                source="github_trending",
                published_at=datetime.now(timezone.utc).isoformat(),
                summary=f"{summary} ({stars} stars)" if stars else summary,
                raw_content=f"{title}. {summary}",
            ))

        log.info("github_trending_fetched", count=len(items))
        return items
    except Exception as e:
        log.error("github_trending_failed", error=str(e))
        return []


# ---------------------------------------------------------------------------
# Product Hunt RSS
# ---------------------------------------------------------------------------

_PH_RSS_URL = "https://www.producthunt.com/feed?category=artificial-intelligence"


def fetch_product_hunt(max_items: int = 8) -> list[RawItem]:
    return fetch_rss("product_hunt", _PH_RSS_URL, max_items)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _deduplicate(items: list[RawItem]) -> list[RawItem]:
    """Remove duplicate IDs and near-duplicate titles."""
    seen_ids: set[str] = set()
    seen_title_keys: set[str] = set()
    out: list[RawItem] = []
    for item in items:
        title_key = "".join(c.lower() for c in item.title if c.isalnum())[:60]
        if item.id in seen_ids or title_key in seen_title_keys:
            continue
        seen_ids.add(item.id)
        seen_title_keys.add(title_key)
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# Main aggregation entry point
# ---------------------------------------------------------------------------

def aggregate(dry_run: bool = False) -> list[RawItem]:
    """
    Fetch from all enabled sources, deduplicate, and return a combined list.
    Respects config.research_and_discovery.sources toggles.
    """
    cfg = load_config()
    sources = cfg.research_and_discovery.sources

    all_items: list[RawItem] = []

    if sources.hacker_news:
        all_items.extend(fetch_hacker_news())
        time.sleep(0.5)

    if sources.huggingface_papers:
        all_items.extend(fetch_huggingface_papers())
        time.sleep(0.5)

    if sources.arxiv:
        all_items.extend(fetch_rss("arxiv_cs_ai", _RSS_FEEDS["arxiv_cs_ai"]))
        all_items.extend(fetch_rss("arxiv_cs_lg", _RSS_FEEDS["arxiv_cs_lg"]))
        time.sleep(0.5)

    if sources.github_trending:
        all_items.extend(fetch_github_trending())
        time.sleep(0.5)

    if sources.product_hunt:
        all_items.extend(fetch_product_hunt())
        time.sleep(0.5)

    # Always try TLDR AI and The Rundown (high signal, no config toggle needed)
    for key in ("tldr_ai", "rundown_ai", "bens_bites"):
        all_items.extend(fetch_rss(key, _RSS_FEEDS[key]))
        time.sleep(0.3)

    deduped = _deduplicate(all_items)
    log.info("aggregation_complete", total_raw=len(all_items), after_dedup=len(deduped), dry_run=dry_run)
    return deduped


if __name__ == "__main__":
    import json
    items = aggregate(dry_run=True)
    print(f"Fetched {len(items)} items")
    for item in items[:5]:
        print(f"  [{item.source}] {item.title[:80]}")

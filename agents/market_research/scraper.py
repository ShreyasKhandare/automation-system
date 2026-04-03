"""
agents/market_research/scraper.py — Scrape market intelligence from all enabled sources.

Sources: GitHub Trending, HuggingFace Papers, arXiv, ProductHunt, Reddit (PRAW), HN
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.config_loader import load_config

log = get_logger("market_research")


def _scrape_github_trending() -> list[dict[str, Any]]:
    """Scrape GitHub Trending page for AI/ML repos."""
    try:
        import requests
        from bs4 import BeautifulSoup

        resp = requests.get("https://github.com/trending/python?since=weekly", timeout=15,
                            headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(resp.text, "html.parser")
        repos = []

        for article in soup.select("article.Box-row")[:10]:
            name_tag = article.select_one("h2 a")
            desc_tag = article.select_one("p")
            if name_tag:
                repo_path = name_tag.get("href", "").strip("/")
                repos.append({
                    "title": repo_path,
                    "url": f"https://github.com/{repo_path}",
                    "description": desc_tag.text.strip() if desc_tag else "",
                    "source": "github_trending",
                })
        return repos
    except Exception as e:
        log.warning("github_trending_failed", error=str(e))
        return []


def _scrape_huggingface_papers() -> list[dict[str, Any]]:
    """Fetch HuggingFace Daily Papers."""
    try:
        import requests
        resp = requests.get("https://huggingface.co/api/daily_papers", timeout=15)
        data = resp.json()
        papers = []
        for item in data[:10]:
            paper = item.get("paper", {})
            papers.append({
                "title": paper.get("title", ""),
                "url": f"https://huggingface.co/papers/{paper.get('id', '')}",
                "description": paper.get("summary", "")[:300],
                "source": "huggingface",
            })
        return papers
    except Exception as e:
        log.warning("huggingface_failed", error=str(e))
        return []


def _scrape_arxiv() -> list[dict[str, Any]]:
    """Fetch recent arXiv papers in cs.AI and cs.LG."""
    try:
        import feedparser
        papers = []
        for category in ["cs.AI", "cs.LG"]:
            feed = feedparser.parse(f"https://rss.arxiv.org/rss/{category}")
            for entry in feed.entries[:5]:
                papers.append({
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "description": entry.get("summary", "")[:300],
                    "source": "arxiv",
                })
        return papers
    except Exception as e:
        log.warning("arxiv_failed", error=str(e))
        return []


def _scrape_reddit_ml() -> list[dict[str, Any]]:
    """Scrape r/MachineLearning and r/LocalLLaMA via PRAW."""
    try:
        import praw
        from shared.secrets import get_secret

        reddit = praw.Reddit(
            client_id=get_secret("REDDIT_CLIENT_ID") if False else "",
            client_secret="",
            user_agent="Shreyas-Automation/1.0",
        )
        # PRAW requires credentials. Use public API instead.
        raise ImportError("PRAW requires credentials")
    except Exception:
        pass

    # Fallback: use Reddit JSON API (no auth needed for public subs)
    try:
        import requests
        posts = []
        for subreddit in ["MachineLearning", "LocalLLaMA"]:
            resp = requests.get(
                f"https://www.reddit.com/r/{subreddit}/hot.json?limit=5",
                headers={"User-Agent": "Shreyas-Automation/1.0"},
                timeout=15,
            )
            data = resp.json()
            for post in data.get("data", {}).get("children", []):
                p = post.get("data", {})
                posts.append({
                    "title": p.get("title", ""),
                    "url": f"https://reddit.com{p.get('permalink', '')}",
                    "description": p.get("selftext", "")[:200],
                    "source": "reddit",
                })
        return posts
    except Exception as e:
        log.warning("reddit_failed", error=str(e))
        return []


def _scrape_hacker_news() -> list[dict[str, Any]]:
    """Scrape HN top AI stories via Algolia API."""
    try:
        import requests
        resp = requests.get(
            "https://hn.algolia.com/api/v1/search",
            params={"query": "AI LLM machine learning", "tags": "story", "hitsPerPage": 10},
            timeout=15,
        )
        data = resp.json()
        items = []
        for hit in data.get("hits", []):
            items.append({
                "title": hit.get("title", ""),
                "url": hit.get("url", f"https://news.ycombinator.com/item?id={hit.get('objectID')}"),
                "description": "",
                "source": "hacker_news",
                "points": hit.get("points", 0),
            })
        return items
    except Exception as e:
        log.warning("hn_failed", error=str(e))
        return []


def scrape_all() -> list[dict[str, Any]]:
    """
    Scrape all enabled market research sources.

    Returns:
        List of raw item dicts.
    """
    cfg = load_config()
    sources = cfg.research_and_discovery.sources
    all_items = []

    if sources.get("github_trending", True):
        items = _scrape_github_trending()
        all_items.extend(items)
        log.info("scraped_github_trending", count=len(items))

    if sources.get("huggingface_papers", True):
        items = _scrape_huggingface_papers()
        all_items.extend(items)
        log.info("scraped_huggingface", count=len(items))

    if sources.get("arxiv", True):
        items = _scrape_arxiv()
        all_items.extend(items)
        log.info("scraped_arxiv", count=len(items))

    if sources.get("reddit_ml", True):
        items = _scrape_reddit_ml()
        all_items.extend(items)
        log.info("scraped_reddit", count=len(items))

    if sources.get("hacker_news", True):
        items = _scrape_hacker_news()
        all_items.extend(items)
        log.info("scraped_hn", count=len(items))

    log.info("market_scrape_complete", total=len(all_items))
    return all_items


def run() -> str:
    """Entry point called by orchestrator RESCAN_MARKET command."""
    from agents.market_research.analyzer import analyze_market
    from agents.market_research.reporter import generate_report

    log.info("market_research_start")
    items = scrape_all()
    if not items:
        return "📊 Market research: no items scraped."

    analysis = analyze_market(items)
    report = generate_report(analysis)
    return report

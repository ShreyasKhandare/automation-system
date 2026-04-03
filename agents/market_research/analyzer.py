"""
agents/market_research/analyzer.py — Analyze market items with Claude.

Asks Claude:
  - What should Shreyas build next?
  - Where should he apply?
  - What skill gaps are growing?
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.config_loader import load_config

log = get_logger("market_research")


def analyze_market(items: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Use Claude to analyze scraped market items.

    Args:
        items: List of scraped items from scraper.py.

    Returns:
        Analysis dict with build_next, apply_here, skill_gaps, summary.
    """
    cfg = load_config()

    if not items:
        return {"build_next": [], "apply_here": [], "skill_gaps": [], "summary": "No items to analyze."}

    # Format items for Claude
    items_text = "\n".join(
        f"[{i.get('source', 'unknown')}] {i.get('title', '')} — {i.get('description', '')[:100]}"
        for i in items[:40]
    )

    profile_text = (
        f"Name: {cfg.profile.name}\n"
        f"Skills: {', '.join(cfg.profile.skills.primary)}\n"
        f"Target roles: {', '.join(cfg.profile.target_titles)}\n"
        f"Target industries: {', '.join(cfg.profile.target_industries)}\n"
        f"Currently learning: {', '.join(cfg.profile.skills.learning)}"
    )

    prompt = f"""You are a market intelligence analyst for an AI/LLM engineer's job search.

ENGINEER PROFILE:
{profile_text}

RECENT MARKET DATA (from GitHub, HuggingFace, arXiv, Reddit, HN):
{items_text}

Analyze this data and return JSON with exactly these keys:
{{
  "build_next": [
    {{"project": "...", "effort": "1-2 weeks", "why": "...", "relevance_score": 0.0-1.0}}
  ],
  "apply_here": [
    {{"company": "...", "reason": "...", "hiring_signal": "..."}}
  ],
  "skill_gaps": [
    {{"skill": "...", "urgency": "high/medium/low", "why": "..."}}
  ],
  "trending_tools": ["list of trending tools/frameworks this week"],
  "summary": "2-3 sentence summary of the most important market signals this week"
}}

Limit to top 5 items per category. Focus on what's most actionable for this engineer."""

    try:
        import anthropic
        from shared.secrets import get_secret

        client = anthropic.Anthropic(api_key=get_secret("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()

        analysis = json.loads(raw)
        log.info("market_analysis_complete",
                 build_next=len(analysis.get("build_next", [])),
                 skill_gaps=len(analysis.get("skill_gaps", [])))
        return analysis

    except Exception as e:
        log.error("market_analysis_failed", error=str(e))
        return {
            "build_next": [],
            "apply_here": [],
            "skill_gaps": [],
            "trending_tools": [],
            "summary": f"Analysis failed: {e}",
        }

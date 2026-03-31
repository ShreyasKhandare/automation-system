"""
agents/market_research/analyzer.py — Claude API synthesis and ranking.

Takes raw research items, calls Claude to:
  1. Rank items by relevance to Shreyas's stack and goals
  2. Generate "what to build next" recommendations
  3. Generate "where to apply" company list
  4. Identify skill gaps and trending requirements
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.config_loader import load_config
from agents.market_research.scraper import RawResearchItem

log = get_logger("market_research")

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 3000

_SYSTEM_PROMPT = """You are a career and technology analyst for Shreyas Khandare, an AI/LLM Engineer.

SHREYAS'S PROFILE:
- Stack: Python, LangChain, LangGraph, ChromaDB, FastAPI, Streamlit, RAG, multi-agent systems
- Target: AI/LLM Engineer roles in FinTech/RegTech
- Flagship: FinOps Sentinel (LangGraph multi-agent RAG, production)
- Learning: deeper agent orchestration, vector DB scaling, model fine-tuning
- Goals: job placement, portfolio growth, skill advancement

You will receive a list of research items (papers, repos, jobs, news).
Analyze them and produce a structured intelligence report."""


@dataclass
class AnalysisReport:
    top_items: list[dict]               # [{title, url, source, relevance_score, why}]
    build_next: list[dict]              # [{idea, effort_days, skills_demonstrated, why}]
    apply_here: list[dict]              # [{company, role, why, url}]
    skill_gaps: list[str]               # trending skills not yet in Shreyas's stack
    trending_tech: list[str]            # tech/tools appearing most in this week's data
    summary: str                        # 3-4 sentence executive summary


def analyze(items: list[RawResearchItem], dry_run: bool = False) -> AnalysisReport:
    """
    Run Claude analysis on aggregated research items.
    Returns an AnalysisReport.
    """
    if dry_run or not items:
        return AnalysisReport(
            top_items=[{"title": i.title, "url": i.url, "source": i.source,
                        "relevance_score": 0.5, "why": "dry run"} for i in items[:5]],
            build_next=[{"idea": "Example project", "effort_days": 3,
                         "skills_demonstrated": ["LangGraph"], "why": "dry run"}],
            apply_here=[{"company": "Example Co", "role": "AI Engineer",
                         "why": "dry run", "url": ""}],
            skill_gaps=["dry-run-skill"],
            trending_tech=["dry-run-tech"],
            summary="Dry run — no Claude analysis performed.",
        )

    # Build items list for the prompt
    items_text = ""
    for i, item in enumerate(items[:60], 1):
        items_text += (
            f"{i}. [{item.source}] {item.title}\n"
            f"   URL: {item.url}\n"
            f"   {item.snippet[:150]}\n\n"
        )

    cfg = load_config()
    goals = ", ".join(cfg.research_and_discovery.goals)

    prompt = (
        f"{_SYSTEM_PROMPT}\n\n"
        f"GOALS THIS WEEK: {goals}\n\n"
        f"RESEARCH ITEMS ({len(items)} total, showing top 60):\n\n"
        f"{items_text}\n"
        f"Produce a JSON report with exactly these keys:\n"
        f"- top_items: array of up to 10 objects with (title, url, source, relevance_score 0-1, why)\n"
        f"- build_next: array of up to 5 project ideas with (idea, effort_days, skills_demonstrated, why)\n"
        f"- apply_here: array of up to 10 companies/roles from the jobs data with (company, role, why, url)\n"
        f"- skill_gaps: array of up to 8 string skill names trending in job postings not in Shreyas's stack\n"
        f"- trending_tech: array of up to 10 string tech names appearing frequently this week\n"
        f"- summary: 3-4 sentence executive summary paragraph\n\n"
        f"Output ONLY valid JSON, no markdown fences."
    )

    try:
        import anthropic
        from shared.secrets import get_secret

        api_key = get_secret("ANTHROPIC_API_KEY")
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        data = json.loads(raw)

        report = AnalysisReport(
            top_items=data.get("top_items", [])[:10],
            build_next=data.get("build_next", [])[:5],
            apply_here=data.get("apply_here", [])[:10],
            skill_gaps=data.get("skill_gaps", [])[:8],
            trending_tech=data.get("trending_tech", [])[:10],
            summary=data.get("summary", ""),
        )
        log.info(
            "analysis_complete",
            top_items=len(report.top_items),
            build_next=len(report.build_next),
            apply_here=len(report.apply_here),
        )
        return report

    except json.JSONDecodeError as e:
        log.error("analysis_json_parse_failed", error=str(e))
        return _fallback_report(items)
    except Exception as e:
        log.error("analysis_claude_failed", error=str(e))
        return _fallback_report(items)


def _fallback_report(items: list[RawResearchItem]) -> AnalysisReport:
    """Build a minimal report without Claude when API fails."""
    # Sort by score descending
    sorted_items = sorted(items, key=lambda x: x.score, reverse=True)
    top = [
        {"title": i.title, "url": i.url, "source": i.source,
         "relevance_score": 0.5, "why": "top by engagement score"}
        for i in sorted_items[:10]
    ]
    return AnalysisReport(
        top_items=top,
        build_next=[],
        apply_here=[
            {"company": i.title.split("@")[-1].strip(),
             "role": i.title.split("@")[0].strip(),
             "why": "appeared in job search results", "url": i.url}
            for i in items if i.source == "jobs"
        ][:5],
        skill_gaps=[],
        trending_tech=[],
        summary="Claude analysis unavailable — showing top items by engagement.",
    )

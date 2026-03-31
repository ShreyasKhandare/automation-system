"""
agents/ai_radar/formatter.py — Format scored items into a Telegram message.

Output example:

🤖 AI Radar — Mon 31 Mar 2026

🔥 TRY ASAP (2)
• [tool] LangGraph Cloud GA — Managed deployment for LangGraph agents, 1-click scaling
  → https://langchain.com/...
• [framework] smolagents v0.4 — Minimal multi-agent framework, 200 lines core, HuggingFace
  → https://github.com/...

👁️ WATCH (3)
• [paper] Mixture-of-Agents outperforms GPT-4 on MMLU — ensemble routing strategy
  → https://arxiv.org/...
• [tool] Cursor Composer 2.0 — multi-file edits with live terminal integration
  → https://cursor.sh/...
• [news] Anthropic raises $2B Series E at $18B valuation
  → https://...

_8 items scanned · 2 try-asap · 3 watch · 3 ignored_
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from agents.ai_radar.filter import ScoredItem

# Category emoji map
_CATEGORY_EMOJI = {
    "model":     "🧠",
    "tool":      "🛠️",
    "framework": "⚙️",
    "paper":     "📄",
    "tutorial":  "📚",
    "news":      "📰",
}


def _category_tag(item: ScoredItem) -> str:
    emoji = _CATEGORY_EMOJI.get(item.category, "•")
    return f"{emoji} [{item.category}]"


def _source_label(source: str) -> str:
    """Human-friendly source label."""
    mapping = {
        "hn":             "HN",
        "huggingface":    "HuggingFace",
        "github_trending": "GitHub",
        "rss_tldr_ai":    "TLDR AI",
        "rss_rundown_ai": "The Rundown",
        "rss_bens_bites": "Ben's Bites",
        "rss_arxiv_cs_ai": "arXiv",
        "rss_arxiv_cs_lg": "arXiv",
        "rss_product_hunt": "Product Hunt",
    }
    return mapping.get(source, source)


def format_briefing(
    items: list[ScoredItem],
    total_scanned: int,
    dry_run: bool = False,
) -> str:
    """
    Build the full Telegram briefing message.
    Returns a Markdown-formatted string (Telegram MarkdownV1 compatible).
    """
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%a %d %b %Y")

    prefix = "🧪 _DRY RUN_ — " if dry_run else ""
    lines = [f"🤖 *{prefix}AI Radar — {date_str}*\n"]

    try_asap = [i for i in items if i.action_tag == "TRY_ASAP"]
    watch = [i for i in items if i.action_tag == "WATCH"]

    ignored_count = total_scanned - len(items)

    # TRY ASAP section
    if try_asap:
        lines.append(f"🔥 *TRY ASAP ({len(try_asap)})*")
        for item in try_asap:
            tag = _category_tag(item)
            src = _source_label(item.source)
            summary = item.summary[:100]
            lines.append(f"• {tag} *{item.title[:70]}*")
            lines.append(f"  _{summary}_ [{src}]")
            if item.url:
                lines.append(f"  → {item.url}")
        lines.append("")

    # WATCH section
    if watch:
        lines.append(f"👁️ *WATCH ({len(watch)})*")
        for item in watch:
            tag = _category_tag(item)
            src = _source_label(item.source)
            summary = item.summary[:100]
            lines.append(f"• {tag} *{item.title[:70]}*")
            lines.append(f"  _{summary}_ [{src}]")
            if item.url:
                lines.append(f"  → {item.url}")
        lines.append("")

    if not try_asap and not watch:
        lines.append("_Nothing relevant found today._\n")

    # Footer stats
    lines.append(
        f"_{total_scanned} items scanned · "
        f"{len(try_asap)} try-asap · "
        f"{len(watch)} watch · "
        f"{ignored_count} ignored_"
    )

    return "\n".join(lines)


def format_weekly_markdown(
    items: list[ScoredItem],
    week_label: str,
    total_scanned: int,
) -> str:
    """
    Format a weekly rollup as a Markdown document for GitHub commit.
    week_label example: "2026-W14"
    """
    lines = [
        f"# AI Tools Radar — {week_label}",
        "",
        f"*{total_scanned} items scanned this week.*",
        "",
    ]

    try_asap = [i for i in items if i.action_tag == "TRY_ASAP"]
    watch = [i for i in items if i.action_tag == "WATCH"]

    if try_asap:
        lines += ["## 🔥 TRY ASAP", ""]
        for item in try_asap:
            src = _source_label(item.source)
            lines.append(f"### [{item.title}]({item.url})")
            lines.append(f"**Source:** {src} | **Category:** {item.category} | **Score:** {item.relevance_score:.2f}")
            lines.append("")
            lines.append(item.summary)
            lines.append("")

    if watch:
        lines += ["## 👁️ WATCH", ""]
        for item in watch:
            src = _source_label(item.source)
            lines.append(f"### [{item.title}]({item.url})")
            lines.append(f"**Source:** {src} | **Category:** {item.category} | **Score:** {item.relevance_score:.2f}")
            lines.append("")
            lines.append(item.summary)
            lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    # Quick formatting smoke-test with dummy data
    dummy = [
        ScoredItem(
            id="abc123", title="LangGraph Cloud now GA", url="https://langchain.com",
            source="rss_tldr_ai", published_at="", summary="Managed LangGraph deployment, 1-click scaling",
            raw_summary="", relevance_score=0.92, action_tag="TRY_ASAP", category="tool",
        ),
        ScoredItem(
            id="def456", title="Mixture-of-Agents beats GPT-4", url="https://arxiv.org/abs/test",
            source="huggingface", published_at="", summary="Ensemble routing strategy for LLMs",
            raw_summary="", relevance_score=0.72, action_tag="WATCH", category="paper",
        ),
    ]
    print(format_briefing(dummy, total_scanned=20, dry_run=True))

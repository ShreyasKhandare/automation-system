"""
agents/ai_radar/filter.py — Claude API batch relevance classification.

Sends ALL items in a single Claude API call for token efficiency.
Each item is rated:
  TRY_ASAP  — relevance ≥ 0.85  (immediately useful to Shreyas's stack/goals)
  WATCH     — relevance ≥ 0.60  (worth tracking, may become relevant)
  IGNORE    — relevance < 0.60  (not relevant)

Returns a list of ScoredItem dataclasses with action_tag, score, and summary.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.secrets import get_secret
from shared.config_loader import load_config
from agents.ai_radar.aggregator import RawItem

log = get_logger("ai_radar")

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ScoredItem:
    """A RawItem after Claude scoring."""
    id: str
    title: str
    url: str
    source: str
    published_at: str
    summary: str              # Claude-generated one-liner (≤ 120 chars)
    raw_summary: str          # original fetched summary
    relevance_score: float    # 0.0 – 1.0
    action_tag: str           # TRY_ASAP | WATCH | IGNORE
    category: str             # model | tool | framework | paper | tutorial | news

    def to_db_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "summary": self.summary,
            "raw_content": self.raw_summary,
            "relevance_score": self.relevance_score,
            "action_tag": self.action_tag,
            "category": self.category,
        }


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are the AI Radar filter for Shreyas Khandare, an AI/LLM Engineer.

Your job: rate the relevance of each item below for Shreyas's specific context.

SHREYAS'S PROFILE:
- Primary stack: LangChain, LangGraph, ChromaDB, FastAPI, Streamlit, Python, RAG, Multi-Agent AI
- Learning: MCP servers, Fine-tuning, Multimodal LLMs
- Goals: productivity, job search, learning, portfolio growth
- Interests: production RAG pipelines, multi-agent orchestration, LLM APIs, FinTech/compliance AI

RATING SCALE:
- TRY_ASAP (≥ 0.85): immediately useful or directly applicable to Shreyas's current work/stack
- WATCH    (≥ 0.60): worth monitoring; may become relevant soon or complements current work
- IGNORE   (< 0.60): not relevant (general business news, unrelated tech, marketing content)

CATEGORIES (pick one per item):
  model | tool | framework | paper | tutorial | news

OUTPUT FORMAT — respond ONLY with a valid JSON array, one object per item:
[
  {
    "id": "<item_id>",
    "relevance_score": 0.92,
    "action_tag": "TRY_ASAP",
    "category": "tool",
    "summary": "One-line description of why this is relevant (≤ 120 chars)"
  },
  ...
]

Do not include any other text. Do not wrap in markdown code fences.
"""


def _build_user_prompt(items: list[RawItem], profile_skills: list[str]) -> str:
    lines = [f"Rate these {len(items)} items for relevance:\n"]
    for item in items:
        lines.append(
            f"ID: {item.id}\n"
            f"Title: {item.title}\n"
            f"Source: {item.source}\n"
            f"Summary: {item.summary[:300]}\n"
        )
    return "\n---\n".join(lines)


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------

def _call_claude(items: list[RawItem]) -> list[dict]:
    """
    Send all items to Claude in one batch. Returns parsed JSON list.
    Falls back to WATCH for all items if Claude call fails.
    """
    import anthropic

    api_key = get_secret("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)

    cfg = load_config()
    skills = cfg.profile.skills.primary + cfg.profile.skills.learning

    user_prompt = _build_user_prompt(items, skills)

    log.info("claude_batch_start", item_count=len(items))

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = response.content[0].text.strip()
    tokens_used = response.usage.input_tokens + response.usage.output_tokens
    log.info("claude_batch_done", tokens=tokens_used, items=len(items))

    # Strip any accidental markdown fence
    if raw_text.startswith("```"):
        raw_text = "\n".join(raw_text.split("\n")[1:])
    if raw_text.endswith("```"):
        raw_text = "\n".join(raw_text.split("\n")[:-1])

    return json.loads(raw_text)


def _fallback_scores(items: list[RawItem]) -> list[dict]:
    """Return WATCH for everything when Claude is unavailable."""
    return [
        {
            "id": item.id,
            "relevance_score": 0.65,
            "action_tag": "WATCH",
            "category": "news",
            "summary": item.summary[:120],
        }
        for item in items
    ]


# ---------------------------------------------------------------------------
# Main filter entry point
# ---------------------------------------------------------------------------

_BATCH_SIZE = 30  # items per Claude call (stay within token limits)


def score_items(
    items: list[RawItem],
    dry_run: bool = False,
) -> list[ScoredItem]:
    """
    Score all items via Claude API (batched).
    In dry_run mode, skips the Claude call and assigns WATCH to everything.
    Returns only TRY_ASAP + WATCH items (IGNORE items are discarded).
    """
    if not items:
        return []

    cfg = load_config()
    try_threshold = cfg.research_and_discovery.try_asap_threshold   # 0.85
    watch_threshold = cfg.research_and_discovery.watch_threshold     # 0.60

    # Build id → RawItem map for lookup
    item_map = {item.id: item for item in items}

    all_scores: list[dict] = []

    if dry_run:
        log.info("dry_run_mode", msg="Skipping Claude API, using fallback scores")
        all_scores = _fallback_scores(items)
    else:
        # Process in batches
        for i in range(0, len(items), _BATCH_SIZE):
            batch = items[i:i + _BATCH_SIZE]
            try:
                scores = _call_claude(batch)
                all_scores.extend(scores)
            except json.JSONDecodeError as e:
                log.error("claude_json_parse_failed", error=str(e))
                all_scores.extend(_fallback_scores(batch))
            except Exception as e:
                log.error("claude_call_failed", error=str(e), exc_info=True)
                all_scores.extend(_fallback_scores(batch))

    # Build ScoredItems, keep only relevant ones
    scored: list[ScoredItem] = []
    for score_data in all_scores:
        item_id = score_data.get("id", "")
        raw = item_map.get(item_id)
        if raw is None:
            continue

        rel_score = float(score_data.get("relevance_score", 0.0))
        action_tag = score_data.get("action_tag", "IGNORE").upper()

        # Normalize action_tag based on score thresholds
        if rel_score >= try_threshold:
            action_tag = "TRY_ASAP"
        elif rel_score >= watch_threshold:
            action_tag = "WATCH"
        else:
            action_tag = "IGNORE"

        if action_tag == "IGNORE":
            continue

        scored.append(ScoredItem(
            id=raw.id,
            title=raw.title,
            url=raw.url,
            source=raw.source,
            published_at=raw.published_at,
            summary=score_data.get("summary", raw.summary)[:120],
            raw_summary=raw.summary,
            relevance_score=rel_score,
            action_tag=action_tag,
            category=score_data.get("category", "news"),
        ))

    # Sort: TRY_ASAP first, then WATCH, each group by score desc
    scored.sort(key=lambda x: (0 if x.action_tag == "TRY_ASAP" else 1, -x.relevance_score))

    cfg_max = cfg.research_and_discovery.summary_max_items
    result = scored[:cfg_max]

    log.info(
        "scoring_complete",
        total_in=len(items),
        try_asap=sum(1 for s in result if s.action_tag == "TRY_ASAP"),
        watch=sum(1 for s in result if s.action_tag == "WATCH"),
        ignored=len(items) - len(scored),
    )
    return result


if __name__ == "__main__":
    from agents.ai_radar.aggregator import aggregate
    raw = aggregate(dry_run=True)
    results = score_items(raw, dry_run=True)
    for r in results:
        print(f"[{r.action_tag}] {r.title[:70]} — {r.relevance_score:.2f}")

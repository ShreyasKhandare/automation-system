"""
agents/market_research/notion_writer.py — Write weekly intelligence to Notion.

Creates a new page under the configured parent database/page:
  Title: "Market Research — Week of YYYY-MM-DD"
  Sections: Executive Summary, Top Items, Build Next, Apply Here, Skill Gaps
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from agents.market_research.analyzer import AnalysisReport

log = get_logger("market_research")

_NOTION_API_BASE = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"


def _notion_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": _NOTION_VERSION,
    }


def _text_block(content: str, bold: bool = False) -> dict:
    annotations = {}
    if bold:
        annotations["bold"] = True
    text = {"type": "text", "text": {"content": content[:2000]}}
    if annotations:
        text["annotations"] = annotations
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [text]},
    }


def _heading_block(content: str, level: int = 2) -> dict:
    heading_type = f"heading_{level}"
    return {
        "object": "block",
        "type": heading_type,
        heading_type: {"rich_text": [{"type": "text", "text": {"content": content[:100]}}]},
    }


def _bullet_block(content: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [{"type": "text", "text": {"content": content[:2000]}}]
        },
    }


def _divider_block() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _build_page_blocks(report: AnalysisReport, week_label: str) -> list[dict]:
    """Convert AnalysisReport to Notion block children list."""
    blocks: list[dict] = []

    # Summary
    blocks.append(_heading_block("Executive Summary", level=2))
    blocks.append(_text_block(report.summary or "No summary available."))
    blocks.append(_divider_block())

    # Top Items
    blocks.append(_heading_block("🔥 Top Items This Week", level=2))
    for item in report.top_items[:10]:
        title = item.get("title", "")
        url = item.get("url", "")
        why = item.get("why", "")
        score = item.get("relevance_score", 0)
        label = f"[{item.get('source','?')}] {title} — {why} (relevance: {score:.0%})"
        if url:
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [
                        {"type": "text", "text": {"content": f"{label}\n"}, "plain_text": label},
                        {"type": "text", "text": {"content": url, "link": {"url": url}}},
                    ]
                },
            })
        else:
            blocks.append(_bullet_block(label))
    blocks.append(_divider_block())

    # Build Next
    if report.build_next:
        blocks.append(_heading_block("🚀 What to Build Next", level=2))
        for idea in report.build_next:
            text = (
                f"{idea.get('idea', '')} — "
                f"~{idea.get('effort_days', '?')} days | "
                f"Skills: {', '.join(idea.get('skills_demonstrated', []))} | "
                f"{idea.get('why', '')}"
            )
            blocks.append(_bullet_block(text))
        blocks.append(_divider_block())

    # Apply Here
    if report.apply_here:
        blocks.append(_heading_block("📋 Where to Apply", level=2))
        for job in report.apply_here:
            text = f"{job.get('company','')} — {job.get('role','')} | {job.get('why','')}"
            url = job.get("url", "")
            if url:
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [
                            {"type": "text", "text": {"content": text + " "}},
                            {"type": "text", "text": {"content": "↗", "link": {"url": url}}},
                        ]
                    },
                })
            else:
                blocks.append(_bullet_block(text))
        blocks.append(_divider_block())

    # Skill Gaps
    if report.skill_gaps:
        blocks.append(_heading_block("📈 Trending Skill Gaps", level=2))
        blocks.append(_bullet_block(", ".join(report.skill_gaps)))
        blocks.append(_divider_block())

    # Trending Tech
    if report.trending_tech:
        blocks.append(_heading_block("🛠️ Trending Tech", level=2))
        blocks.append(_bullet_block(", ".join(report.trending_tech)))

    return blocks


def write_to_notion(
    report: AnalysisReport,
    week_label: str,
    dry_run: bool = False,
) -> Optional[str]:
    """
    Create a Notion page with the market research report.

    Args:
        report:     AnalysisReport from analyzer.py
        week_label: e.g. "2026-W13"
        dry_run:    If True, return a fake URL without calling Notion API.

    Returns:
        Notion page URL or None on failure.
    """
    if dry_run:
        log.info("notion_write_dry_run", week=week_label)
        return "https://notion.so/DRY_RUN_PAGE"

    try:
        import requests
        from shared.secrets import get_secret
        from shared.config_loader import load_config

        api_key = get_secret("NOTION_API_KEY")
        cfg = load_config()
        parent_db_id = get_secret("NOTION_DATABASE_ID_MARKET")

        title_str = f"Market Research — Week of {week_label}"
        blocks = _build_page_blocks(report, week_label)

        # Notion API limits to 100 blocks per request
        page_payload = {
            "parent": {"database_id": parent_db_id},
            "properties": {
                "Name": {"title": [{"text": {"content": title_str}}]},
                "Week": {"rich_text": [{"text": {"content": week_label}}]},
                "Created": {"date": {"start": datetime.now(timezone.utc).strftime("%Y-%m-%d")}},
            },
            "children": blocks[:100],
        }

        headers = _notion_headers(api_key)
        resp = requests.post(
            f"{_NOTION_API_BASE}/pages",
            headers=headers,
            json=page_payload,
            timeout=20,
        )

        if resp.ok:
            page_id = resp.json().get("id", "")
            page_url = resp.json().get("url", f"https://notion.so/{page_id.replace('-','')}")
            log.info("notion_page_created", url=page_url, week=week_label)

            # Append remaining blocks if any
            if len(blocks) > 100:
                for chunk_start in range(100, len(blocks), 100):
                    requests.patch(
                        f"{_NOTION_API_BASE}/blocks/{page_id}/children",
                        headers=headers,
                        json={"children": blocks[chunk_start:chunk_start+100]},
                        timeout=20,
                    )

            return page_url
        else:
            log.error("notion_page_create_failed", status=resp.status_code, body=resp.text[:300])
            return None

    except Exception as e:
        log.error("notion_write_error", error=str(e))
        return None

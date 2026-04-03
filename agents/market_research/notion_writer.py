"""
agents/market_research/notion_writer.py — Write market research report to Notion.

Creates a new page in the configured Notion database for each weekly research run.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger

log = get_logger("market_research")


def write_to_notion(analysis: dict[str, Any], dry_run: bool = False) -> str:
    """
    Write market research analysis to Notion.

    Args:
        analysis: Output from analyzer.analyze_market().
        dry_run: Skip Notion API call.

    Returns:
        URL of created Notion page or error message.
    """
    if dry_run:
        log.info("notion_writer_dry_run")
        return "Dry run — Notion page not created."

    try:
        from shared.secrets import get_secret
        import requests

        token = get_secret("NOTION_API_KEY")
        database_id = get_secret("NOTION_DATABASE_ID_MARKET")

        today = datetime.now().strftime("%Y-%m-%d")
        week_num = datetime.now().isocalendar()[1]
        title = f"Market Research — Week {week_num}, {today}"

        # Build rich text blocks
        blocks = []

        # Summary
        if analysis.get("summary"):
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": analysis["summary"]}}]},
            })

        # Build Next
        if analysis.get("build_next"):
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": "What to Build Next"}}]},
            })
            for item in analysis["build_next"][:5]:
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{"type": "text", "text": {
                            "content": f"{item.get('project', '')} ({item.get('effort', '')}) — {item.get('why', '')}"
                        }}]
                    },
                })

        # Skill Gaps
        if analysis.get("skill_gaps"):
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Skill Gaps"}}]},
            })
            for gap in analysis["skill_gaps"][:5]:
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{"type": "text", "text": {
                            "content": f"[{gap.get('urgency', 'medium').upper()}] {gap.get('skill', '')} — {gap.get('why', '')}"
                        }}]
                    },
                })

        payload = {
            "parent": {"database_id": database_id},
            "properties": {
                "Name": {"title": [{"type": "text", "text": {"content": title}}]},
                "Date": {"date": {"start": today}},
            },
            "children": blocks[:100],  # Notion API limit
        }

        resp = requests.post(
            "https://api.notion.com/v1/pages",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        page = resp.json()
        page_url = page.get("url", "https://notion.so")
        log.info("notion_page_created", url=page_url)
        return page_url

    except Exception as e:
        log.error("notion_write_failed", error=str(e))
        return f"Notion write failed: {e}"

"""
agents/market_research/market_agent.py — Main orchestrator for market & profile research.

Weekly pipeline:
  1. scraper.py     → Aggregate from GitHub Trending, HuggingFace, arXiv, HN, jobs
  2. analyzer.py    → Claude API synthesis (build next, apply here, skill gaps)
  3. notion_writer.py → Create Notion page
  4. reporter.py    → Write markdown report to docs/reports/ + Telegram Sunday digest

Usage:
  python agents/market_research/market_agent.py
  python agents/market_research/market_agent.py --dry-run
  python agents/market_research/market_agent.py --verbose
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.db import get_conn, get_db_path, log_health
from agents.market_research.scraper import aggregate_all
from agents.market_research.analyzer import analyze
from agents.market_research.notion_writer import write_to_notion
from agents.market_research.reporter import (
    write_markdown_report,
    send_telegram_digest,
)

log = get_logger("market_research")


def run(dry_run: bool = False) -> str:
    run_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc)
    week_label = now.strftime("%Y-W%W")
    log.run_start(run_id, dry_run=dry_run, week=week_label)
    results: list[str] = []

    try:
        # Step 1: Aggregate
        items = aggregate_all(dry_run=dry_run)
        results.append(f"✅ Aggregated {len(items)} research items")

        # Step 2: Analyze
        report = analyze(items, dry_run=dry_run)
        results.append(
            f"✅ Analysis: {len(report.top_items)} top items, "
            f"{len(report.build_next)} build ideas, "
            f"{len(report.apply_here)} companies to apply"
        )

        # Step 3: Notion
        notion_url = write_to_notion(report, week_label, dry_run=dry_run)
        if notion_url:
            results.append(f"✅ Notion page: {notion_url}")
        else:
            results.append("⚠️ Notion write failed (check NOTION_API_KEY)")

        # Step 4: Markdown report
        md_path = write_markdown_report(report, week_label, notion_url=notion_url, dry_run=dry_run)
        if md_path:
            results.append(f"✅ Markdown: `{md_path.name}`")

        # Step 5: Telegram digest
        send_telegram_digest(report, week_label, notion_url=notion_url, dry_run=dry_run)
        results.append("✅ Telegram digest sent")

        summary = "🧠 *Market Research Agent*\n" + "\n".join(results)
        with get_conn(get_db_path()) as conn:
            log_health(conn, "market_research", "green",
                       f"Weekly research complete: {len(items)} items, week {week_label}")
        log.run_end(run_id, status="ok")
        return summary

    except Exception as e:
        log.run_error(run_id, error=str(e))
        try:
            with get_conn(get_db_path()) as conn:
                log_health(conn, "market_research", "red", str(e)[:200])
        except Exception:
            pass
        return f"🔴 Market research agent failed: {e}"


def get_latest_summary() -> str:
    """Return the latest market research summary for /market Telegram command."""
    try:
        with get_conn(get_db_path()) as conn:
            row = conn.execute(
                "SELECT message, checked_at FROM system_health "
                "WHERE agent_name='market_research' ORDER BY checked_at DESC LIMIT 1"
            ).fetchone()
        if row:
            return f"🧠 *Market Research*\n{row['message']}\n_{row['checked_at'][:10]}_"
        return "ℹ️ No market research run yet."
    except Exception as e:
        return f"⚠️ {e}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Market Research Agent")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    result = run(dry_run=args.dry_run)
    if args.dry_run or args.verbose:
        print(result)

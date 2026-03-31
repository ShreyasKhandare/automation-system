"""
agents/ai_radar/notifier.py — Main entry point for the AI Radar agent.

Pipeline:
  1. aggregate()  — fetch from all sources
  2. score_items() — Claude API batch classification
  3. format_briefing() — build Telegram message
  4. send to Telegram
  5. persist to SQLite ai_radar table
  6. (weekly) write markdown digest to docs/ai_radar/

Usage:
  python agents/ai_radar/notifier.py              # full run
  python agents/ai_radar/notifier.py --dry-run    # no Telegram send, no DB write
  python agents/ai_radar/notifier.py --dry-run --verbose
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
from shared.db import get_conn, get_db_path, init_db, upsert_ai_radar, log_health
from shared.secrets import get_secret
from agents.ai_radar.aggregator import aggregate, RawItem
from agents.ai_radar.filter import score_items, ScoredItem
from agents.ai_radar.formatter import format_briefing, format_weekly_markdown

log = get_logger("ai_radar")


# ---------------------------------------------------------------------------
# Telegram delivery
# ---------------------------------------------------------------------------

def _send_telegram(message: str) -> None:
    """Send message via Telegram. Imported from shared to avoid circular deps."""
    import requests
    token = get_secret("TELEGRAM_BOT_TOKEN")
    chat_id = get_secret("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    # Chunk to stay under Telegram's 4096-char limit
    max_len = 4000
    chunks = [message[i:i + max_len] for i in range(0, len(message), max_len)]
    for chunk in chunks:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }, timeout=30)
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------

def _persist_items(items: list[ScoredItem], digest_date: str) -> None:
    db_path = get_db_path()
    if not Path(str(db_path)).exists():
        init_db(db_path)

    with get_conn(db_path) as conn:
        for item in items:
            record = item.to_db_dict()
            record["included_in_digest"] = digest_date
            upsert_ai_radar(conn, record)
        log_health(conn, "ai_radar", "green", f"Briefing sent: {len(items)} items")

    log.info("items_persisted", count=len(items))


# ---------------------------------------------------------------------------
# Weekly markdown commit
# ---------------------------------------------------------------------------

def _maybe_write_weekly_digest(items: list[ScoredItem], total_scanned: int) -> None:
    """
    On Mondays, write a weekly rollup markdown to docs/ai_radar/.
    File is committed by the GitHub Docs agent (Session 7).
    """
    now = datetime.now(timezone.utc)
    if now.weekday() != 0:  # 0 = Monday
        return

    week_label = now.strftime("%Y-W%W")
    content = format_weekly_markdown(items, week_label, total_scanned)
    out_dir = _REPO_ROOT / "docs" / "ai_radar"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"ai_tools_radar_{week_label}.md"
    out_file.write_text(content, encoding="utf-8")
    log.info("weekly_digest_written", path=str(out_file))


# ---------------------------------------------------------------------------
# Public function used by orchestrator
# ---------------------------------------------------------------------------

def get_latest_briefing() -> str:
    """
    Return the most recent briefing from the DB (for /briefing Telegram command).
    Falls back to triggering a fresh run if nothing in DB today.
    """
    try:
        with get_conn(get_db_path()) as conn:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            rows = conn.execute(
                """
                SELECT title, action_tag, summary, source
                FROM ai_radar
                WHERE included_in_digest = ?
                ORDER BY action_tag ASC, relevance_score DESC
                LIMIT 10
                """,
                (today,),
            ).fetchall()
        if not rows:
            return "No briefing for today yet. Try `RESCAN AI_TOOLS` to run now."
        lines = [f"🤖 *AI Radar (cached) — {today}*\n"]
        for r in rows:
            tag_emoji = "🔥" if r["action_tag"] == "TRY_ASAP" else "👁️"
            lines.append(f"{tag_emoji} *{r['title'][:70]}*\n  _{r['summary'][:100]}_")
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Could not fetch cached briefing: {e}"


def run(dry_run: bool = False, verbose: bool = False) -> str:
    """
    Full pipeline. Returns the formatted briefing message string.
    Called by orchestrator for RESCAN_AI_TOOLS command.
    """
    run_id = str(uuid.uuid4())[:8]
    log.run_start(run_id, dry_run=dry_run)
    start = datetime.now(timezone.utc)

    try:
        # 1. Aggregate
        raw_items = aggregate(dry_run=dry_run)
        total_scanned = len(raw_items)

        if not raw_items:
            msg = "⚠️ AI Radar: No items fetched from any source."
            log.warning("no_items_fetched")
            return msg

        # 2. Score
        scored = score_items(raw_items, dry_run=dry_run)

        # 3. Format
        message = format_briefing(scored, total_scanned=total_scanned, dry_run=dry_run)

        if verbose:
            print(message)

        # 4. Send Telegram (skip in dry-run)
        if not dry_run:
            _send_telegram(message)
            log.info("telegram_sent")

        # 5. Persist to DB (skip in dry-run)
        today_str = start.strftime("%Y-%m-%d")
        if not dry_run:
            _persist_items(scored, digest_date=today_str)
            _maybe_write_weekly_digest(scored, total_scanned)

        duration = (datetime.now(timezone.utc) - start).total_seconds()
        log.run_end(run_id, status="ok", duration_seconds=duration, items=len(scored))
        return message

    except Exception as e:
        duration = (datetime.now(timezone.utc) - start).total_seconds()
        log.run_error(run_id, error=str(e))

        # Log failure to DB
        try:
            db_path = get_db_path()
            if Path(str(db_path)).exists():
                with get_conn(db_path) as conn:
                    log_health(conn, "ai_radar", "red", str(e)[:200])
        except Exception:
            pass

        return f"🔴 AI Radar failed: {e}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Radar Agent")
    parser.add_argument("--dry-run", action="store_true", help="Skip Telegram send and DB write")
    parser.add_argument("--verbose", action="store_true", help="Print output to stdout")
    args = parser.parse_args()

    result = run(dry_run=args.dry_run, verbose=args.verbose or args.dry_run)
    if args.dry_run:
        print("\n--- DRY RUN OUTPUT ---")
        print(result)
        sys.exit(0)

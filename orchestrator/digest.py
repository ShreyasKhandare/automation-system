"""
orchestrator/digest.py — Daily digest aggregator.

Collects summaries from all agents that ran today and composes a single
Telegram message. Called by:
  - `GENERATE DAILY_DIGEST` Telegram command
  - GitHub Actions daily cron (future)

Sections included (only if data exists):
  1. System health summary
  2. New jobs discovered today (top 5 by score)
  3. AI radar items (TRY_ASAP + WATCH)
  4. Email triage summary
  5. Outreach activity
  6. Any errors in last 24h
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.db import get_conn, get_db_path, init_db

log = get_logger("digest")


# ---------------------------------------------------------------------------
# Section builders — each returns a string block or "" if nothing to show
# ---------------------------------------------------------------------------

def _section_health() -> str:
    try:
        from .health import run_health_check
        report = run_health_check()
        return report.to_short_message()
    except Exception as e:
        return f"⚠️ Health check failed: {e}"


def _section_jobs(conn) -> str:
    try:
        rows = conn.execute(
            """
            SELECT title, company, location, score, url
            FROM jobs
            WHERE date(created_at) = date('now')
            ORDER BY score DESC
            LIMIT 5
            """
        ).fetchall()
        if not rows:
            return ""
        lines = ["💼 *New Jobs Today* (top 5)\n"]
        for r in rows:
            loc = r["location"] or "Remote"
            score = f"{r['score']:.1f}" if r["score"] is not None else "?"
            lines.append(f"• [{score}/10] *{r['title']}* @ {r['company']} ({loc})")
        lines.append(f"\n_/jobs today for full list_")
        return "\n".join(lines)
    except Exception as e:
        log.error("digest_jobs_failed", error=str(e))
        return ""


def _section_ai_radar(conn) -> str:
    try:
        rows = conn.execute(
            """
            SELECT title, source, action_tag, summary
            FROM ai_radar
            WHERE date(created_at) = date('now')
              AND action_tag IN ('TRY_ASAP', 'WATCH')
            ORDER BY action_tag ASC, relevance_score DESC
            LIMIT 5
            """
        ).fetchall()
        if not rows:
            return ""
        lines = ["🤖 *AI Radar Today*\n"]
        for r in rows:
            tag = "🔥" if r["action_tag"] == "TRY_ASAP" else "👁️"
            summary = (r["summary"] or "")[:80]
            lines.append(f"{tag} *{r['title']}* [{r['source']}]\n   _{summary}_")
        return "\n".join(lines)
    except Exception as e:
        log.error("digest_ai_radar_failed", error=str(e))
        return ""


def _section_outreach(conn) -> str:
    try:
        row = conn.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE date(sent_at) = date('now')) as sent_today,
                COUNT(*) FILTER (WHERE date(reply_at) = date('now')) as replied_today,
                COUNT(*) FILTER (WHERE status = 'pending_approval') as pending
            FROM outreach
            """
        ).fetchone()
        if not row or (row["sent_today"] == 0 and row["replied_today"] == 0 and row["pending"] == 0):
            return ""
        lines = ["📬 *Outreach Today*\n"]
        if row["sent_today"]:
            lines.append(f"• Sent: {row['sent_today']}")
        if row["replied_today"]:
            lines.append(f"• New replies: {row['replied_today']} 🎉")
        if row["pending"]:
            lines.append(f"• Awaiting your approval: {row['pending']}")
        return "\n".join(lines)
    except Exception as e:
        log.error("digest_outreach_failed", error=str(e))
        return ""


def _section_errors(conn) -> str:
    try:
        rows = conn.execute(
            """
            SELECT agent_name, message
            FROM system_health
            WHERE status = 'red'
              AND checked_at >= datetime('now', '-24 hours')
            ORDER BY checked_at DESC
            LIMIT 5
            """
        ).fetchall()
        if not rows:
            return ""
        lines = ["🔴 *Errors (24h)*\n"]
        for r in rows:
            lines.append(f"• *{r['agent_name']}*: {r['message'][:80]}")
        return "\n".join(lines)
    except Exception as e:
        log.error("digest_errors_failed", error=str(e))
        return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate_digest() -> str:
    """
    Build and return the full daily digest message as a Telegram-formatted string.
    """
    db_path = get_db_path()
    if not Path(str(db_path)).exists():
        init_db(db_path)

    today = date.today().isoformat()
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")

    sections: list[str] = [f"📋 *Daily Digest — {today} {now}*\n"]

    with get_conn(db_path) as conn:
        for builder in [
            _section_health,
            lambda: _section_jobs(conn),
            lambda: _section_ai_radar(conn),
            lambda: _section_outreach(conn),
            lambda: _section_errors(conn),
        ]:
            try:
                block = builder()
                if block:
                    sections.append(block)
            except Exception as e:
                log.error("digest_section_failed", error=str(e))

    if len(sections) == 1:
        sections.append("_No activity to report today._")

    message = "\n\n".join(sections)
    log.info("digest_generated", sections=len(sections) - 1)
    return message


def send_digest() -> None:
    """Generate digest and send to Telegram. Used by GitHub Actions."""
    from shared.secrets import get_secret
    from .telegram_bot import send_message

    token = get_secret("TELEGRAM_BOT_TOKEN")
    chat_id = get_secret("TELEGRAM_CHAT_ID")
    message = generate_digest()
    send_message(token, chat_id, message)
    log.info("digest_sent")


if __name__ == "__main__":
    print(generate_digest())

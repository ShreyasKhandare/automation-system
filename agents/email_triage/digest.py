"""
agents/email_triage/digest.py — Daily email triage summary for Telegram.

Two modes:
  1. run_triage_poll() — called every 2h; processes new emails, sends immediate
     alerts for flag_keyword matches only
  2. send_daily_digest() — called once at digest_time (6pm EST); builds and
     sends a summary of today's classified emails

The daily digest is grouped by label with counts and representative subjects.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.config_loader import load_config
from agents.email_triage.classifier import ClassifiedEmail, VALID_LABELS

log = get_logger("email_triage")

# ---------------------------------------------------------------------------
# Label display config
# ---------------------------------------------------------------------------

_LABEL_META = {
    "AI/IMPORTANT":       {"emoji": "🚨", "title": "Important",       "priority": 1},
    "AI/APPLICATION":     {"emoji": "📋", "title": "Applications",    "priority": 2},
    "AI/JOB_OPPORTUNITY": {"emoji": "💼", "title": "Job Opportunities","priority": 3},
    "AI/NETWORKING":      {"emoji": "🤝", "title": "Networking",       "priority": 4},
    "AI/NEWSLETTER":      {"emoji": "📰", "title": "Newsletters",      "priority": 5},
    "AI/SPAM":            {"emoji": "🗑️",  "title": "Spam (archived)", "priority": 6},
    "AI/OTHER":           {"emoji": "📁", "title": "Other",            "priority": 7},
}


# ---------------------------------------------------------------------------
# Immediate alert (for flag_keyword hits in the 2h poll)
# ---------------------------------------------------------------------------

def format_urgent_alert(classified: ClassifiedEmail) -> str:
    """Format an immediate Telegram alert for a flagged email."""
    kw = classified.flag_reason or "flag keyword"
    sender_short = classified.email.sender[:60]
    return (
        f"🚨 *URGENT EMAIL — \"{kw}\" detected*\n\n"
        f"*From:* {sender_short}\n"
        f"*Subject:* {classified.email.subject[:120]}\n"
        f"*Label:* {classified.label}\n\n"
        f"_{classified.email.snippet[:200]}_\n\n"
        f"_Received: {classified.email.date[:16]} UTC_"
    )


# ---------------------------------------------------------------------------
# Daily digest
# ---------------------------------------------------------------------------

def format_daily_digest(
    classified_emails: list[ClassifiedEmail],
    period_label: str = "today",
) -> str:
    """
    Build the daily email triage digest message for Telegram.
    Groups emails by label, shows counts + representative subjects.
    """
    cfg = load_config()
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%a %d %b %Y")

    lines = [f"📬 *Email Digest — {date_str}*\n"]

    if not classified_emails:
        lines.append("_No new emails triaged today._")
        return "\n".join(lines)

    # Group by label
    by_label: dict[str, list[ClassifiedEmail]] = defaultdict(list)
    for ce in classified_emails:
        by_label[ce.label].append(ce)

    # Sort label groups by priority
    sorted_labels = sorted(
        by_label.keys(),
        key=lambda lbl: _LABEL_META.get(lbl, {}).get("priority", 99),
    )

    for label in sorted_labels:
        items = by_label[label]
        meta = _LABEL_META.get(label, {"emoji": "•", "title": label})
        emoji = meta["emoji"]
        title = meta["title"]

        lines.append(f"{emoji} *{title}* ({len(items)})")

        # Show up to 3 representative subjects
        for item in items[:3]:
            sender_name = item.email.sender.split("<")[0].strip()[:30] or item.email.sender[:30]
            subject = item.email.subject[:70]
            urgent_tag = " 🚨" if item.flag_urgent else ""
            lines.append(f"  • {sender_name}: _{subject}_{urgent_tag}")

        if len(items) > 3:
            lines.append(f"  _...and {len(items) - 3} more_")
        lines.append("")

    total = len(classified_emails)
    urgent_count = sum(1 for ce in classified_emails if ce.flag_urgent)
    lines.append(f"_{total} emails triaged · {urgent_count} urgent_")

    return "\n".join(lines)


def get_summary() -> str:
    """
    Return a brief inbox triage summary from today's DB records.
    Used by /emails Telegram command.
    """
    try:
        from shared.db import get_conn, get_db_path
        # The email_triage agent doesn't store full email content (privacy).
        # It logs aggregate stats to system_health.
        with get_conn(get_db_path()) as conn:
            rows = conn.execute(
                """
                SELECT message, details, checked_at
                FROM system_health
                WHERE agent_name = 'email_triage'
                  AND date(checked_at) = date('now')
                ORDER BY checked_at DESC
                LIMIT 5
                """
            ).fetchall()

        if not rows:
            return "No email triage runs today. Runs every 2 hours."

        lines = ["📬 *Email Triage (today)*\n"]
        for row in rows:
            time_str = row["checked_at"][:16]
            lines.append(f"• [{time_str}] {row['message']}")
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Could not fetch email summary: {e}"

"""
agents/email_triage/digest.py — Build and send daily email digest to Telegram.

Aggregates classified emails for the day and formats a Telegram digest message.
Also provides get_summary() for the /emails orchestrator command.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.db import get_conn, get_db_path

log = get_logger("email_triage")

# In-memory store for classified emails during a run
# This gets populated by notifier.py after each poll
_EMAIL_STORE: list[dict[str, Any]] = []

_EMAIL_DB_TABLE = """
CREATE TABLE IF NOT EXISTS email_triage (
    id          TEXT PRIMARY KEY,
    subject     TEXT,
    sender      TEXT,
    label       TEXT,
    is_flagged  INTEGER DEFAULT 0,
    confidence  REAL,
    reasoning   TEXT,
    received_at TEXT,
    processed_at TEXT DEFAULT (datetime('now'))
);
"""


def _ensure_table() -> None:
    """Ensure the email_triage table exists."""
    try:
        with get_conn(get_db_path()) as conn:
            conn.executescript(_EMAIL_DB_TABLE)
    except Exception as e:
        log.warning("email_table_create_failed", error=str(e))


def store_classified_emails(messages: list[dict[str, Any]]) -> None:
    """Persist classified emails to SQLite for digest building."""
    _ensure_table()
    try:
        with get_conn(get_db_path()) as conn:
            for msg in messages:
                conn.execute(
                    """INSERT OR REPLACE INTO email_triage
                    (id, subject, sender, label, is_flagged, confidence, reasoning, received_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        msg.get("id", ""),
                        msg.get("subject", "")[:200],
                        msg.get("from", "")[:100],
                        msg.get("label", "AI/OTHER"),
                        1 if msg.get("is_flagged") else 0,
                        msg.get("confidence", 0.0),
                        msg.get("reasoning", "")[:200],
                        msg.get("date", ""),
                    ),
                )
    except Exception as e:
        log.error("store_emails_failed", error=str(e))


def get_today_emails() -> list[dict[str, Any]]:
    """Fetch today's classified emails from SQLite."""
    _ensure_table()
    try:
        with get_conn(get_db_path()) as conn:
            rows = conn.execute(
                """SELECT * FROM email_triage
                WHERE date(processed_at) = date('now')
                ORDER BY processed_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        log.error("get_today_emails_failed", error=str(e))
        return []


def build_digest(messages: list[dict[str, Any]] | None = None) -> str:
    """
    Build the daily email digest message for Telegram.

    Args:
        messages: List of classified messages. If None, loads from today's DB records.

    Returns:
        Telegram-formatted digest string.
    """
    if messages is None:
        messages = get_today_emails()

    if not messages:
        return "📧 *Email Digest* — No emails processed today."

    # Group by label
    by_label: dict[str, list[dict]] = defaultdict(list)
    flagged: list[dict] = []

    for msg in messages:
        label = msg.get("label", "AI/OTHER")
        by_label[label].append(msg)
        if msg.get("is_flagged"):
            flagged.append(msg)

    lines = [f"📧 *Email Digest — {datetime.now().strftime('%b %d, %Y')}*\n"]
    lines.append(f"Total processed: {len(messages)}\n")

    # Flagged first
    if flagged:
        lines.append("🚨 *FLAGGED (action needed):*")
        for msg in flagged[:5]:
            subject = msg.get("subject", "")[:60]
            sender = msg.get("sender", msg.get("from", ""))[:40]
            lines.append(f"  • {subject} — _{sender}_")
        lines.append("")

    # Label breakdown
    label_emojis = {
        "AI/JOB_OPPORTUNITY": "💼",
        "AI/APPLICATION": "📋",
        "AI/NETWORKING": "🤝",
        "AI/IMPORTANT": "⭐",
        "AI/NEWSLETTER": "📰",
        "AI/SPAM": "🗑️",
        "AI/OTHER": "📌",
    }

    for label, emoji in label_emojis.items():
        msgs = by_label.get(label, [])
        if not msgs:
            continue
        lines.append(f"{emoji} *{label}* ({len(msgs)})")
        for msg in msgs[:3]:
            subject = msg.get("subject", "")[:50]
            lines.append(f"  • {subject}")
        if len(msgs) > 3:
            lines.append(f"  _...and {len(msgs) - 3} more_")
        lines.append("")

    return "\n".join(lines)


def get_summary() -> str:
    """
    Return a short inbox summary for the /emails orchestrator command.
    Used by orchestrator.py cmd_emails().
    """
    messages = get_today_emails()

    if not messages:
        return "📧 No emails processed yet today. Triage runs every 2 hours."

    by_label: dict[str, int] = defaultdict(int)
    flagged_count = 0
    for msg in messages:
        by_label[msg.get("label", "AI/OTHER")] += 1
        if msg.get("is_flagged"):
            flagged_count += 1

    parts = [f"📧 *Inbox Summary* ({len(messages)} emails today)"]
    if flagged_count:
        parts.append(f"🚨 {flagged_count} flagged for immediate attention")
    for label, count in sorted(by_label.items()):
        parts.append(f"• {label}: {count}")
    parts.append("\nSend `/emails digest` for full breakdown.")
    return "\n".join(parts)


if __name__ == "__main__":
    print(get_summary())

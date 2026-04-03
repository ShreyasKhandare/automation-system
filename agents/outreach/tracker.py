"""
agents/outreach/tracker.py — Track outreach status, replies, opt-outs, and pauses.

Provides:
  - pause(hours) / resume_outreach() — paused state persisted in SQLite
  - log_reply(outreach_id) — mark as replied
  - log_opt_out(outreach_id) — mark as opted out, never contact again
  - get_status() — full CRM stats
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.db import get_conn, get_db_path, log_health, upsert_outreach

log = get_logger("outreach")

_PAUSE_KEY = "outreach_pause"


def _save_pause_state(until_iso: str | None) -> None:
    """Persist pause state in system_health table."""
    try:
        with get_conn(get_db_path()) as conn:
            log_health(conn, _PAUSE_KEY, "yellow" if until_iso else "green",
                       "paused" if until_iso else "resumed",
                       {"paused_until": until_iso})
    except Exception as e:
        log.warning("save_pause_state_failed", error=str(e))


def is_paused() -> bool:
    """Check if outreach is currently paused."""
    try:
        with get_conn(get_db_path()) as conn:
            row = conn.execute(
                "SELECT details FROM system_health WHERE agent_name = ? ORDER BY checked_at DESC LIMIT 1",
                (_PAUSE_KEY,),
            ).fetchone()
        if row and row["details"]:
            data = json.loads(row["details"])
            until_str = data.get("paused_until")
            if until_str:
                until = datetime.fromisoformat(until_str.replace("Z", "+00:00"))
                return datetime.now(timezone.utc) < until
    except Exception:
        pass
    return False


def pause(hours: int = 24) -> str:
    """Pause outreach for N hours."""
    from datetime import timedelta
    until = datetime.now(timezone.utc) + timedelta(hours=hours)
    _save_pause_state(until.isoformat())
    log.info("outreach_paused", hours=hours, until=until.isoformat())
    return f"⏸️ Outreach paused for {hours} hours (until {until.strftime('%b %d %H:%M UTC')})"


def resume_outreach() -> str:
    """Resume paused outreach."""
    _save_pause_state(None)
    log.info("outreach_resumed")
    return "▶️ Outreach resumed."


def log_reply(outreach_id: str, reply_text: str = "") -> bool:
    """Mark an outreach record as replied."""
    try:
        with get_conn(get_db_path()) as conn:
            conn.execute(
                """UPDATE outreach
                SET reply_received = 1, reply_at = ?, status = 'replied'
                WHERE id = ?""",
                (datetime.now(timezone.utc).isoformat(), outreach_id),
            )
        log.info("reply_logged", outreach_id=outreach_id)
        return True
    except Exception as e:
        log.error("log_reply_failed", outreach_id=outreach_id, error=str(e))
        return False


def log_opt_out(outreach_id: str) -> bool:
    """Mark a contact as opted out. Never contact them again."""
    try:
        with get_conn(get_db_path()) as conn:
            conn.execute(
                "UPDATE outreach SET status = 'opted_out' WHERE id = ?",
                (outreach_id,),
            )
        log.info("opt_out_logged", outreach_id=outreach_id)
        return True
    except Exception as e:
        log.error("log_opt_out_failed", error=str(e))
        return False


def approve_outreach(outreach_id: str) -> bool:
    """Mark an outreach as approved for sending."""
    try:
        with get_conn(get_db_path()) as conn:
            conn.execute(
                "UPDATE outreach SET status = 'pending_approval', approved_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), outreach_id),
            )
        log.info("outreach_approved", outreach_id=outreach_id)
        return True
    except Exception as e:
        log.error("approve_outreach_failed", error=str(e))
        return False


def reject_outreach(outreach_id: str) -> bool:
    """Reject an outreach draft."""
    try:
        with get_conn(get_db_path()) as conn:
            conn.execute(
                "UPDATE outreach SET status = 'rejected' WHERE id = ?",
                (outreach_id,),
            )
        log.info("outreach_rejected", outreach_id=outreach_id)
        return True
    except Exception as e:
        log.error("reject_outreach_failed", error=str(e))
        return False


def get_status() -> str:
    """Return full CRM stats for Telegram."""
    try:
        with get_conn(get_db_path()) as conn:
            row = conn.execute(
                """SELECT
                    COUNT(*) FILTER (WHERE status = 'sent') as sent,
                    COUNT(*) FILTER (WHERE status = 'replied') as replied,
                    COUNT(*) FILTER (WHERE status = 'pending_approval') as pending,
                    COUNT(*) FILTER (WHERE status = 'draft') as drafts,
                    COUNT(*) FILTER (WHERE status = 'opted_out') as opted_out,
                    COUNT(*) as total
                FROM outreach"""
            ).fetchone()

        paused_status = "⏸️ PAUSED" if is_paused() else "▶️ Active"

        return (
            f"📬 *Outreach CRM*\n"
            f"Status: {paused_status}\n\n"
            f"• Sent: {row['sent']}\n"
            f"• Replied: {row['replied']}\n"
            f"• Pending approval: {row['pending']}\n"
            f"• Drafts: {row['drafts']}\n"
            f"• Opted out: {row['opted_out']}\n"
            f"• Total: {row['total']}"
        )
    except Exception as e:
        return f"⚠️ Could not fetch outreach status: {e}"

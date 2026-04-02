"""
agents/outreach/follow_up.py — Auto-draft follow-up emails for non-replies.

Scans outreach table for sent emails where next_follow_up_at <= today,
reply_received=0, and follow_up_count < max_follow_ups. Drafts follow-up
via Claude and submits for Telegram approval (same gate as initial sends).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.config_loader import load_config
from shared.db import get_conn, get_db_path
from agents.outreach.drafter import draft_follow_up
from agents.outreach.tracker import mark_pending_approval, sync_to_sheet

log = get_logger("outreach")


def _compute_next_follow_up(current_count: int, cadence_days: list[int]) -> str | None:
    """Return ISO date string for the next follow-up, or None if at max."""
    if current_count >= len(cadence_days):
        return None
    delta = cadence_days[current_count]  # 0-indexed: count 0 → first follow-up
    next_dt = datetime.now(timezone.utc) + timedelta(days=delta)
    return next_dt.strftime("%Y-%m-%d")


def set_initial_follow_up(outreach_id: str) -> None:
    """
    Set the first follow-up date on a newly sent email.
    Called by outreach_agent.py immediately after send.
    """
    cfg = load_config()
    cadence = cfg.recruiter_outreach.follow_up_cadence_days
    if not cadence:
        return
    next_date = _compute_next_follow_up(0, cadence)
    if not next_date:
        return
    try:
        with get_conn(get_db_path()) as conn:
            conn.execute(
                "UPDATE outreach SET next_follow_up_at=? WHERE id=?",
                (next_date, outreach_id),
            )
        log.info("initial_follow_up_set", outreach_id=outreach_id, next=next_date)
    except Exception as e:
        log.error("set_follow_up_failed", outreach_id=outreach_id, error=str(e))


def run_follow_ups(dry_run: bool = False) -> list[str]:
    """
    Find all due follow-ups and draft + queue them for approval.

    Args:
        dry_run: If True, draft but don't change DB status.

    Returns:
        List of outreach_ids that were drafted for follow-up.
    """
    cfg = load_config()
    max_follow_ups = cfg.recruiter_outreach.max_follow_ups
    cadence = cfg.recruiter_outreach.follow_up_cadence_days

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        with get_conn(get_db_path()) as conn:
            due = conn.execute(
                "SELECT * FROM outreach WHERE status='sent' "
                "AND reply_received=0 "
                "AND next_follow_up_at IS NOT NULL "
                "AND next_follow_up_at <= ? "
                "AND follow_up_count < ? "
                "ORDER BY next_follow_up_at ASC",
                (today, max_follow_ups),
            ).fetchall()
        due_records = [dict(r) for r in due]
    except Exception as e:
        log.error("follow_up_query_failed", error=str(e))
        return []

    if not due_records:
        log.info("no_follow_ups_due")
        return []

    log.info("follow_ups_due", count=len(due_records))
    queued_ids: list[str] = []

    for record in due_records:
        outreach_id = record["id"]
        follow_up_number = record["follow_up_count"] + 1

        draft = draft_follow_up(
            outreach_record=record,
            follow_up_number=follow_up_number,
            max_follow_ups=max_follow_ups,
            dry_run=dry_run,
        )

        if not draft:
            log.warning("follow_up_draft_failed", outreach_id=outreach_id)
            continue

        if not dry_run:
            # Update the outreach record with the follow-up draft
            next_date = _compute_next_follow_up(follow_up_number, cadence)
            try:
                with get_conn(get_db_path()) as conn:
                    conn.execute(
                        "UPDATE outreach SET "
                        "draft_subject=?, draft_body=?, status='pending_approval', "
                        "follow_up_count=?, next_follow_up_at=? "
                        "WHERE id=?",
                        (
                            draft["subject"],
                            draft["body"],
                            follow_up_number,
                            next_date or "",
                            outreach_id,
                        ),
                    )
                sync_to_sheet(outreach_id)
                log.info("follow_up_queued", outreach_id=outreach_id, number=follow_up_number)
                queued_ids.append(outreach_id)
            except Exception as e:
                log.error("follow_up_save_failed", outreach_id=outreach_id, error=str(e))
        else:
            log.info("follow_up_dry_run", outreach_id=outreach_id,
                     subject=draft["subject"][:60])
            queued_ids.append(outreach_id)

    return queued_ids


def get_follow_up_summary() -> str:
    """Return a brief Telegram-ready summary of pending follow-ups."""
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with get_conn(get_db_path()) as conn:
            due_count = conn.execute(
                "SELECT COUNT(*) FROM outreach WHERE status='sent' "
                "AND reply_received=0 AND next_follow_up_at <= ? "
                "AND follow_up_count < ?",
                (today, load_config().recruiter_outreach.max_follow_ups),
            ).fetchone()[0]
            pending_count = conn.execute(
                "SELECT COUNT(*) FROM outreach WHERE status='pending_approval'"
            ).fetchone()[0]
    except Exception:
        return "⚠️ Could not fetch follow-up stats."

    lines = []
    if due_count:
        lines.append(f"📅 {due_count} follow-up(s) due today")
    if pending_count:
        lines.append(f"⏳ {pending_count} outreach email(s) pending your approval")
    return "\n".join(lines) if lines else "✅ No follow-ups due today."

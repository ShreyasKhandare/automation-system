"""
agents/outreach/sender.py — Gmail send with warm-up enforcement and approval gate.

SAFETY RULES (all are hard raises, not warnings):
  1. Approval gate: email must have status='pending_approval' before send.
  2. Warm-up cap: today's send count must be < daily_limit (week-based).
  3. Send window: current time must be within configured send_window hours.
  4. Opt-out guard: email body must NOT contain "Reply STOP" if recipient
     previously opted out (status='opted_out').

Never call this file directly. Always go through outreach_agent.py which
enforces the approval gate flow.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import zoneinfo

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.config_loader import load_config
from shared.db import get_conn, get_db_path, get_today_send_count
from agents.outreach.tracker import mark_sent, sync_to_sheet

log = get_logger("outreach")


class SendBlockedError(Exception):
    """Raised when any safety rule blocks the send."""


# ---------------------------------------------------------------------------
# Safety checks
# ---------------------------------------------------------------------------

def _check_approval_status(outreach_id: str, conn) -> dict:
    """Raise SendBlockedError if outreach is not in pending_approval status."""
    row = conn.execute(
        "SELECT * FROM outreach WHERE id=?", (outreach_id,)
    ).fetchone()
    if not row:
        raise SendBlockedError(f"outreach_id {outreach_id!r} not found in DB")
    row = dict(row)
    if row["status"] != "pending_approval":
        raise SendBlockedError(
            f"Cannot send: status is {row['status']!r}, must be 'pending_approval'"
        )
    if row.get("email") == "":
        raise SendBlockedError(f"No email address for outreach {outreach_id}")
    return row


def _check_warm_up_cap(conn) -> int:
    """Raise SendBlockedError if today's send count >= daily limit. Returns today's count."""
    cfg = load_config()
    warm_up = cfg.recruiter_outreach.warm_up

    # Determine which week we're in based on earliest sent record
    first_sent = conn.execute(
        "SELECT MIN(sent_at) FROM outreach WHERE status='sent'"
    ).fetchone()[0]

    if not first_sent:
        week_number = 1
    else:
        try:
            first_dt = datetime.fromisoformat(first_sent)
            weeks_active = (datetime.now(timezone.utc) - first_dt.replace(tzinfo=timezone.utc)).days // 7
            week_number = weeks_active + 1
        except Exception:
            week_number = 1

    if week_number == 1:
        daily_limit = warm_up.week_1_max
    elif week_number == 2:
        daily_limit = warm_up.week_2_max
    else:
        daily_limit = warm_up.week_3_plus_max

    today_count = get_today_send_count(conn)
    if today_count >= daily_limit:
        raise SendBlockedError(
            f"Daily warm-up cap reached: {today_count}/{daily_limit} emails sent today (week {week_number})"
        )
    return today_count


def _check_send_window() -> None:
    """Raise SendBlockedError if current time is outside the configured send window."""
    cfg = load_config()
    window = cfg.recruiter_outreach.send_window
    tz = zoneinfo.ZoneInfo(window.timezone)
    now_local = datetime.now(tz)
    current_hour = now_local.hour

    if not (window.start_hour <= current_hour < window.end_hour):
        raise SendBlockedError(
            f"Outside send window: current hour is {current_hour} {window.timezone}, "
            f"window is {window.start_hour}–{window.end_hour}"
        )


def _check_opt_out(email: str, conn) -> None:
    """Raise SendBlockedError if this email previously opted out."""
    row = conn.execute(
        "SELECT status FROM outreach WHERE email=? AND status='opted_out' LIMIT 1",
        (email,),
    ).fetchone()
    if row:
        raise SendBlockedError(f"Recipient {email} has previously opted out")


# ---------------------------------------------------------------------------
# Gmail send
# ---------------------------------------------------------------------------

def _build_gmail_service():
    """Build Gmail API service using OAuth2 refresh token."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from shared.secrets import get_secret

    creds = Credentials(
        token=None,
        refresh_token=get_secret("GMAIL_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=get_secret("GMAIL_CLIENT_ID"),
        client_secret=get_secret("GMAIL_CLIENT_SECRET"),
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    )
    return build("gmail", "v1", credentials=creds)


def _send_gmail(to_email: str, subject: str, body: str) -> bool:
    """Send a plain-text email via Gmail API. Returns True on success."""
    import base64
    from email.mime.text import MIMEText

    try:
        service = _build_gmail_service()
        msg = MIMEText(body, "plain", "utf-8")
        msg["to"] = to_email
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True
    except Exception as e:
        log.error("gmail_send_failed", to=to_email, error=str(e))
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_approved(outreach_id: str, dry_run: bool = False) -> bool:
    """
    Send an approved outreach email, enforcing all safety checks.

    Args:
        outreach_id: DB ID of the outreach record (must be status='pending_approval').
        dry_run:     If True, skip actual send but run all safety checks.

    Returns:
        True on success (or dry-run pass), False on send failure.
        Raises SendBlockedError if any safety check fails.
    """
    with get_conn(get_db_path()) as conn:
        # Safety gate 1: approval status
        row = _check_approval_status(outreach_id, conn)

        # Safety gate 2: warm-up cap
        today_count = _check_warm_up_cap(conn)

        # Safety gate 3: opt-out
        _check_opt_out(row["email"], conn)

    # Safety gate 4: send window (no DB needed)
    _check_send_window()

    log.info(
        "send_gates_passed",
        outreach_id=outreach_id,
        today_count=today_count,
        to=row["email"],
        dry_run=dry_run,
    )

    if dry_run:
        log.info("send_dry_run_skip", outreach_id=outreach_id)
        return True

    success = _send_gmail(row["email"], row["draft_subject"], row["draft_body"])
    if success:
        mark_sent(outreach_id)
        sync_to_sheet(outreach_id, dry_run=False)
        log.info("send_ok", outreach_id=outreach_id, to=row["email"])
    else:
        log.error("send_failed", outreach_id=outreach_id, to=row["email"])

    return success


def reject_outreach(outreach_id: str) -> None:
    """Mark an outreach record as rejected (user pressed Reject in Telegram)."""
    from agents.outreach.tracker import mark_rejected
    mark_rejected(outreach_id)
    log.info("outreach_rejected_by_user", outreach_id=outreach_id)

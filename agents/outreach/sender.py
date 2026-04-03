"""
agents/outreach/sender.py — Send approved outreach emails via Gmail API.

CRITICAL RULES:
  1. mode: "assisted" — NOTHING sends without Telegram approval. Hard-coded. Never bypassed.
  2. get_today_send_count() is checked before EVERY send — warm-up limits enforced.
  3. Staggered send timing to avoid spam detection.
"""

from __future__ import annotations

import base64
import sys
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.db import get_conn, get_db_path, get_today_send_count, upsert_outreach
from shared.config_loader import load_config

log = get_logger("outreach")

# Stagger delay between sends (seconds)
SEND_DELAY_SECONDS = 30


def _get_warm_up_limit() -> int:
    """Return today's send limit based on warm-up schedule."""
    cfg = load_config()
    warm_up = cfg.recruiter_outreach.warm_up

    # Calculate which week we're in (from first outreach record)
    try:
        with get_conn(get_db_path()) as conn:
            row = conn.execute(
                "SELECT MIN(created_at) as first_sent FROM outreach WHERE status = 'sent'"
            ).fetchone()
            if row and row["first_sent"]:
                from datetime import datetime
                first = datetime.fromisoformat(row["first_sent"])
                weeks_in = (datetime.now() - first).days // 7
            else:
                weeks_in = 0
    except Exception:
        weeks_in = 0

    if weeks_in == 0:
        return warm_up.week_1_max
    elif weeks_in == 1:
        return warm_up.week_2_max
    else:
        return warm_up.week_3_plus_max


def _is_in_send_window() -> bool:
    """Check if current time is within the configured send window."""
    import pytz
    cfg = load_config()
    send_window = cfg.recruiter_outreach.send_window

    try:
        tz = pytz.timezone(send_window.timezone)
        now_local = datetime.now(tz)
        hour = now_local.hour
        return send_window.start_hour <= hour < send_window.end_hour
    except Exception:
        # Default to always allowed if timezone check fails
        return True


def _build_gmail_message(to: str, subject: str, body: str, from_email: str) -> dict:
    """Build a Gmail API message object."""
    message = MIMEText(body, "plain")
    message["to"] = to
    message["from"] = from_email
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return {"raw": raw}


def _build_gmail_service():
    """Build Gmail API service."""
    import os
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from shared.secrets import get_secret

    creds = Credentials(
        token=None,
        refresh_token=get_secret("GMAIL_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=get_secret("GMAIL_CLIENT_ID"),
        client_secret=get_secret("GMAIL_CLIENT_SECRET"),
        scopes=["https://mail.google.com/"],
    )
    return build("gmail", "v1", credentials=creds)


def send_email(outreach_id: str, dry_run: bool = False) -> dict[str, Any]:
    """
    Send a single approved outreach email.

    CRITICAL: mode="assisted" is hard-coded — will never send without explicit approval.
    Checks warm-up limits before every send.

    Args:
        outreach_id: ID of the approved outreach record in SQLite.
        dry_run: Simulate send without actual API call.

    Returns:
        Result dict with 'success', 'message'.
    """
    cfg = load_config()

    # HARD CHECK: mode must be "assisted" — never bypass this
    mode = cfg.recruiter_outreach.mode
    assert mode == "assisted", (
        f"SAFETY: mode='{mode}' but send_email requires mode='assisted'. "
        f"This check can never be bypassed."
    )

    # Load outreach record
    try:
        with get_conn(get_db_path()) as conn:
            row = conn.execute(
                "SELECT * FROM outreach WHERE id = ?", (outreach_id,)
            ).fetchone()
    except Exception as e:
        return {"success": False, "message": f"DB error: {e}"}

    if not row:
        return {"success": False, "message": f"Outreach record not found: {outreach_id}"}

    outreach = dict(row)

    # Verify it was explicitly approved
    if outreach.get("status") != "pending_approval":
        return {
            "success": False,
            "message": f"Cannot send — status is '{outreach.get('status')}', not 'pending_approval'."
        }

    if not outreach.get("approved_at"):
        return {
            "success": False,
            "message": "Cannot send — no approval timestamp. Human approval required."
        }

    # Check warm-up limit
    with get_conn(get_db_path()) as conn:
        today_count = get_today_send_count(conn)
    daily_limit = min(_get_warm_up_limit(), cfg.recruiter_outreach.max_contacts_per_day)

    if today_count >= daily_limit:
        msg = f"⚠️ Daily send limit reached ({today_count}/{daily_limit}). Will resume tomorrow."
        log.warning("daily_limit_reached", count=today_count, limit=daily_limit)
        return {"success": False, "message": msg}

    # Check send window
    if not _is_in_send_window():
        msg = "⏰ Outside send window. Queued for next window."
        log.info("outside_send_window")
        return {"success": False, "message": msg}

    # Get from_email
    from_email = cfg.profile.email

    subject = outreach.get("draft_subject", "")
    body = outreach.get("draft_body", "")
    to_email = outreach.get("email", "")

    if not to_email or not subject or not body:
        return {"success": False, "message": "Missing email, subject, or body in outreach record."}

    if dry_run:
        log.info("send_dry_run", outreach_id=outreach_id, to=to_email[:30])
        return {"success": True, "message": f"Dry run — would send to {to_email}"}

    # Send via Gmail API
    try:
        service = _build_gmail_service()
        gmail_msg = _build_gmail_message(to_email, subject, body, from_email)
        service.users().messages().send(userId="me", body=gmail_msg).execute()

        # Update record
        sent_at = datetime.now(timezone.utc).isoformat()
        with get_conn(get_db_path()) as conn:
            conn.execute(
                "UPDATE outreach SET status = 'sent', sent_at = ? WHERE id = ?",
                (sent_at, outreach_id),
            )

        log.info("email_sent", outreach_id=outreach_id, to=to_email[:30])

        # Stagger
        time.sleep(SEND_DELAY_SECONDS)

        return {"success": True, "message": f"Sent to {to_email}"}

    except Exception as e:
        log.error("email_send_failed", outreach_id=outreach_id, error=str(e))
        return {"success": False, "message": f"Send failed: {e}"}


def send_approved_batch(outreach_ids: list[str], dry_run: bool = False) -> str:
    """Send a batch of approved outreach emails."""
    results = []
    sent = 0
    failed = 0

    for outreach_id in outreach_ids:
        result = send_email(outreach_id, dry_run=dry_run)
        if result["success"]:
            sent += 1
            results.append(f"✅ {outreach_id}: sent")
        else:
            failed += 1
            results.append(f"❌ {outreach_id}: {result['message']}")

    return f"📤 Sent {sent}/{len(outreach_ids)} | Failed: {failed}\n" + "\n".join(results[:5])

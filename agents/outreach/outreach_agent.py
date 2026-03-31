"""
agents/outreach/outreach_agent.py — Main orchestrator for the outreach pipeline.

Pipeline:
  1. finder.py      → Apollo.io recruiter/hiring manager lookup
  2. verifier.py    → Hunter.io email verification
  3. drafter.py     → Claude API email drafting
  4. tracker.py     → SQLite persist + Google Sheets sync
  5. [manual gate]  → Telegram approval (via n8n outreach_approval.json)
  6. sender.py      → Gmail send with warm-up enforcement
  7. follow_up.py   → Auto-draft follow-ups for non-replies

Usage:
  python agents/outreach/outreach_agent.py --companies "Stripe,Sardine,Brex"
  python agents/outreach/outreach_agent.py --follow-ups        # process due follow-ups
  python agents/outreach/outreach_agent.py --send <outreach_id>  # send an approved email
  python agents/outreach/outreach_agent.py --reject <outreach_id>
  python agents/outreach/outreach_agent.py --dry-run --companies "Stripe"
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
from agents.outreach.finder import find_contacts, get_existing_outreach_emails
from agents.outreach.verifier import verify_contacts
from agents.outreach.drafter import draft_batch
from agents.outreach.tracker import save_draft, mark_pending_approval, sync_to_sheet
from agents.outreach.sender import send_approved, reject_outreach, SendBlockedError
from agents.outreach.follow_up import run_follow_ups, set_initial_follow_up

log = get_logger("outreach")


def _notify_telegram(text: str, outreach_id: str | None = None) -> None:
    """Send a Telegram notification. Also triggers the n8n approval webhook if outreach_id given."""
    try:
        from shared.secrets import get_secret
        import requests

        token = get_secret("TELEGRAM_BOT_TOKEN")
        chat_id = get_secret("TELEGRAM_CHAT_ID")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }, timeout=10)
    except Exception as e:
        log.warning("telegram_notify_failed", error=str(e))


def _post_to_n8n_approval(outreach_id: str, record: dict) -> None:
    """
    POST draft details to n8n outreach_approval webhook so the user
    receives an Approve/Reject Telegram message with inline buttons.
    """
    try:
        from shared.secrets import get_secret
        import requests
        import os

        n8n_url = os.environ.get("N8N_OUTREACH_APPROVAL_URL", "")
        if not n8n_url:
            # Fallback: plain Telegram message without buttons
            _notify_telegram(
                f"📧 *Outreach draft ready for approval*\n\n"
                f"*To:* {record['recruiter_name']} <{record['email']}>\n"
                f"*Company:* {record['company']}\n"
                f"*Subject:* {record['draft_subject']}\n\n"
                f"Send `/approve_outreach {outreach_id}` or `/reject_outreach {outreach_id}`"
            )
            return

        requests.post(n8n_url, json={
            "outreach_id": outreach_id,
            "recipient_name": record["recruiter_name"],
            "recipient_email": record["email"],
            "company": record["company"],
            "subject": record["draft_subject"],
            "email_body": record["draft_body"],
        }, timeout=15)
        log.info("n8n_approval_triggered", outreach_id=outreach_id)
    except Exception as e:
        log.warning("n8n_approval_failed", outreach_id=outreach_id, error=str(e))


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def run_find_and_draft(
    companies: list[str],
    job_id: str | None = None,
    dry_run: bool = False,
) -> list[str]:
    """
    Full find → verify → draft → save pipeline.
    Returns list of outreach_ids queued for approval.
    """
    existing_emails = get_existing_outreach_emails()
    contacts = find_contacts(companies, existing_emails=existing_emails, dry_run=dry_run)

    if not contacts:
        log.info("no_contacts_found", companies=companies)
        return []

    verified = verify_contacts(contacts, dry_run=dry_run)
    if not verified:
        log.info("no_verified_contacts", count=len(contacts))
        return []

    drafted = draft_batch(verified, dry_run=dry_run)
    if not drafted:
        log.info("no_drafts_created")
        return []

    outreach_ids: list[str] = []
    for draft in drafted:
        outreach_id = save_draft(draft, job_id=job_id)
        mark_pending_approval(outreach_id)
        sync_to_sheet(outreach_id, dry_run=dry_run)
        outreach_ids.append(outreach_id)

        if not dry_run:
            # Fetch saved record for n8n payload
            try:
                with get_conn(get_db_path()) as conn:
                    record = dict(conn.execute(
                        "SELECT * FROM outreach WHERE id=?", (outreach_id,)
                    ).fetchone())
                _post_to_n8n_approval(outreach_id, record)
            except Exception as e:
                log.warning("approval_notify_failed", outreach_id=outreach_id, error=str(e))

    log.info("run_find_and_draft_done", queued=len(outreach_ids))
    return outreach_ids


def run_send(outreach_id: str, dry_run: bool = False) -> str:
    """Send a single approved outreach email."""
    try:
        success = send_approved(outreach_id, dry_run=dry_run)
        if success:
            if not dry_run:
                set_initial_follow_up(outreach_id)
            return f"✅ Outreach `{outreach_id}` sent."
        return f"⚠️ Send failed for `{outreach_id}`. Check logs."
    except SendBlockedError as e:
        log.error("send_blocked", outreach_id=outreach_id, reason=str(e))
        return f"🚫 Send blocked: {e}"


def run_reject(outreach_id: str) -> str:
    """Reject an outreach draft."""
    reject_outreach(outreach_id)
    return f"❌ Outreach `{outreach_id}` rejected."


# ---------------------------------------------------------------------------
# Public entry point for orchestrator
# ---------------------------------------------------------------------------

def run(
    companies: list[str] | None = None,
    job_id: str | None = None,
    process_follow_ups: bool = False,
    send_id: str | None = None,
    reject_id: str | None = None,
    dry_run: bool = False,
) -> str:
    run_id = str(uuid.uuid4())[:8]
    log.run_start(run_id, dry_run=dry_run, companies=companies, process_follow_ups=process_follow_ups)
    results: list[str] = []

    try:
        if reject_id:
            results.append(run_reject(reject_id))

        elif send_id:
            results.append(run_send(send_id, dry_run=dry_run))

        elif process_follow_ups:
            queued = run_follow_ups(dry_run=dry_run)
            results.append(
                f"✅ {len(queued)} follow-up(s) queued for approval." if queued
                else "ℹ️ No follow-ups due."
            )

        elif companies:
            queued = run_find_and_draft(companies, job_id=job_id, dry_run=dry_run)
            results.append(
                f"✅ {len(queued)} outreach draft(s) queued for Telegram approval."
                if queued else "ℹ️ No new contacts found."
            )
        else:
            results.append("⚠️ No action specified. Use --companies, --follow-ups, --send, or --reject.")

        summary = "📧 *Outreach Agent*\n" + "\n".join(results)
        with get_conn(get_db_path()) as conn:
            log_health(conn, "outreach", "green", f"Run complete: {len(results)} actions")
        log.run_end(run_id, status="ok")
        return summary

    except Exception as e:
        log.run_error(run_id, error=str(e))
        try:
            with get_conn(get_db_path()) as conn:
                log_health(conn, "outreach", "red", str(e)[:200])
        except Exception:
            pass
        return f"🔴 Outreach agent failed: {e}"


def get_outreach_summary() -> str:
    """Return Telegram-ready summary for /outreach command."""
    try:
        with get_conn(get_db_path()) as conn:
            row = conn.execute(
                "SELECT "
                "COUNT(*) FILTER (WHERE status='pending_approval') pending,"
                "COUNT(*) FILTER (WHERE status='sent') sent,"
                "COUNT(*) FILTER (WHERE status='replied') replied,"
                "COUNT(*) FILTER (WHERE date(sent_at)>=date('now','-7 days')) sent_week "
                "FROM outreach"
            ).fetchone()
        return (
            f"📧 *Outreach Summary*\n"
            f"• Pending approval: {row['pending']}\n"
            f"• Sent (7 days): {row['sent_week']}\n"
            f"• Total sent: {row['sent']}\n"
            f"• Replies: {row['replied']}"
        )
    except Exception as e:
        return f"⚠️ Could not fetch outreach stats: {e}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Outreach Agent")
    parser.add_argument("--companies", type=str, help="Comma-separated company names")
    parser.add_argument("--job-id", type=str, help="Related job ID")
    parser.add_argument("--follow-ups", action="store_true", help="Process due follow-ups")
    parser.add_argument("--send", type=str, metavar="OUTREACH_ID", help="Send approved outreach")
    parser.add_argument("--reject", type=str, metavar="OUTREACH_ID", help="Reject outreach draft")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    companies_list = [c.strip() for c in args.companies.split(",")] if args.companies else None

    result = run(
        companies=companies_list,
        job_id=args.job_id,
        process_follow_ups=args.follow_ups,
        send_id=args.send,
        reject_id=args.reject,
        dry_run=args.dry_run,
    )

    if args.dry_run or args.verbose:
        print(result)

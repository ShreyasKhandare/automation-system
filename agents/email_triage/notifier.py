"""
agents/email_triage/notifier.py — Email triage entry point and Telegram notifier.

Orchestrates:
  1. Poll new messages (poller.py)
  2. Classify each (classifier.py)
  3. Apply Gmail labels (labeler.py)
  4. Immediate Telegram alert for flagged emails (NEVER wait for digest)
  5. Store classified emails for daily digest (digest.py)

CLI:
  python -m agents.email_triage.notifier
  python -m agents.email_triage.notifier --dry-run
  python -m agents.email_triage.notifier --dry-run --verbose
  python -m agents.email_triage.notifier --digest-now
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.db import get_conn, get_db_path, init_db, log_health

log = get_logger("email_triage")


def _send_telegram(message: str) -> None:
    """Send a message to Telegram. Fails silently on error."""
    try:
        import requests
        from shared.secrets import get_secret
        token = get_secret("TELEGRAM_BOT_TOKEN")
        chat_id = get_secret("TELEGRAM_CHAT_ID")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
        }, timeout=10)
    except Exception as e:
        log.warning("telegram_send_failed", error=str(e))


def _send_immediate_alert(message: dict) -> None:
    """Fire immediate Telegram alert for flagged emails — NEVER waits for digest."""
    subject = message.get("subject", "")[:80]
    sender = message.get("from", "")[:60]
    reasoning = message.get("reasoning", "")[:100]

    alert = (
        f"🚨 *URGENT EMAIL — Action Required*\n\n"
        f"*From:* {sender}\n"
        f"*Subject:* {subject}\n"
        f"*Why flagged:* {reasoning}\n\n"
        f"Check your inbox now."
    )
    log.info("sending_immediate_alert", subject=subject, sender=sender)
    _send_telegram(alert)


def run(dry_run: bool = False, verbose: bool = False, digest_now: bool = False) -> str:
    """
    Main email triage run function.

    Args:
        dry_run: Skip API calls and label writes.
        verbose: Extra logging.
        digest_now: Send today's digest immediately after triage.

    Returns:
        Summary string.
    """
    log.info("email_triage_start", dry_run=dry_run, verbose=verbose)
    start_time = datetime.now(timezone.utc)

    # --- Step 1: Poll new messages ---
    from agents.email_triage.poller import poll_new_messages
    try:
        messages = poll_new_messages(dry_run=dry_run)
    except Exception as e:
        msg = f"Polling failed: {e}"
        log.error("triage_poll_failed", error=str(e))
        db_path = get_db_path()
        init_db(db_path)
        with get_conn(db_path) as conn:
            log_health(conn, "email_triage", "red", msg)
        return f"❌ Email triage failed (poll): {e}"

    if verbose:
        log.info("polled_messages", count=len(messages))

    if not messages:
        log.info("no_new_messages")
        db_path = get_db_path()
        init_db(db_path)
        with get_conn(db_path) as conn:
            log_health(conn, "email_triage", "green", "no new messages")
        return "📧 Email triage: no new messages."

    # --- Step 2: Classify ---
    from agents.email_triage.classifier import classify_batch
    classified = classify_batch(messages, dry_run=dry_run)

    if verbose:
        for msg in classified:
            log.info("classified", subject=msg.get("subject", "")[:50], label=msg.get("label"))

    # --- Step 3: Apply Gmail labels ---
    if not dry_run:
        try:
            from agents.email_triage.poller import _build_gmail_service
            from agents.email_triage.labeler import apply_labels_batch
            service = _build_gmail_service()
            stats = apply_labels_batch(service, classified, dry_run=dry_run)
            log.info("labeling_complete", **stats)
        except Exception as e:
            log.error("labeling_failed", error=str(e))

    # --- Step 4: Immediate alerts for flagged emails ---
    flagged = [m for m in classified if m.get("is_flagged")]
    for msg in flagged:
        if not dry_run:
            _send_immediate_alert(msg)
        else:
            log.info("dry_run_would_alert", subject=msg.get("subject", "")[:60])

    # --- Step 5: Store for digest ---
    from agents.email_triage.digest import store_classified_emails
    if not dry_run:
        store_classified_emails(classified)

    # --- Step 6: Optionally send digest now ---
    if digest_now and not dry_run:
        from agents.email_triage.digest import build_digest
        digest_msg = build_digest(classified)
        _send_telegram(digest_msg)
        log.info("digest_sent_now")

    # --- Log health ---
    duration = (datetime.now(timezone.utc) - start_time).total_seconds()
    summary = (
        f"Processed {len(classified)} emails | "
        f"{len(flagged)} flagged | "
        f"{sum(1 for m in classified if m.get('label') == 'AI/SPAM')} spam | "
        f"{duration:.1f}s"
    )

    db_path = get_db_path()
    init_db(db_path)
    with get_conn(db_path) as conn:
        log_health(conn, "email_triage", "green", summary, {
            "total": len(classified),
            "flagged": len(flagged),
            "duration_seconds": duration,
        })

    log.info("email_triage_complete", summary=summary)
    return f"📧 {summary}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Email triage agent")
    parser.add_argument("--dry-run", action="store_true", help="Skip API calls and writes")
    parser.add_argument("--verbose", action="store_true", help="Extra logging")
    parser.add_argument("--digest-now", action="store_true", help="Send digest immediately after triage")
    args = parser.parse_args()

    result = run(dry_run=args.dry_run, verbose=args.verbose, digest_now=args.digest_now)
    print(result)

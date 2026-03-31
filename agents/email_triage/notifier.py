"""
agents/email_triage/notifier.py — Main entry point for the Email Triage agent.

Two distinct run modes (selected via --mode flag):

  poll  (default) — run every 2 hours via GitHub Actions
    1. poller.poll_new_messages()       — fetch unread since last cursor
    2. classifier.classify_emails()     — Claude batch classification
    3. labeler.apply_labels_bulk()      — apply Gmail labels, archive spam
    4. Send IMMEDIATE Telegram alerts for any flag_urgent emails
    5. Log run stats to SQLite system_health
    6. Update poll cursor

  digest — run once at 6pm EST via GitHub Actions
    1. Build daily digest from today's health logs
    2. Send digest to Telegram

Usage:
  python agents/email_triage/notifier.py                     # poll mode
  python agents/email_triage/notifier.py --mode digest       # daily digest
  python agents/email_triage/notifier.py --dry-run           # poll, no sends/writes
  python agents/email_triage/notifier.py --dry-run --verbose
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.db import get_conn, get_db_path, init_db, log_health
from shared.secrets import get_secret
from agents.email_triage.poller import poll_new_messages, _build_gmail_service
from agents.email_triage.classifier import classify_emails
from agents.email_triage.labeler import apply_labels_bulk
from agents.email_triage.digest import format_urgent_alert, format_daily_digest, get_summary

log = get_logger("email_triage")


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def _send_telegram(message: str) -> None:
    import requests
    token = get_secret("TELEGRAM_BOT_TOKEN")
    chat_id = get_secret("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    max_len = 4000
    for chunk in [message[i:i + max_len] for i in range(0, len(message), max_len)]:
        requests.post(url, json={
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }, timeout=30).raise_for_status()


# ---------------------------------------------------------------------------
# Poll run
# ---------------------------------------------------------------------------

def run_poll(dry_run: bool = False, verbose: bool = False) -> str:
    """
    2-hour poll: fetch → classify → label → alert.
    Returns summary string.
    """
    run_id = str(uuid.uuid4())[:8]
    log.run_start(run_id, mode="poll", dry_run=dry_run)
    start = datetime.now(timezone.utc)

    db_path = get_db_path()
    if not Path(str(db_path)).exists():
        init_db(db_path)

    try:
        # 1. Poll
        emails = poll_new_messages(dry_run=dry_run)

        if not emails:
            msg = f"✅ Email triage: 0 new messages at {start.strftime('%H:%M UTC')}"
            if not dry_run:
                with get_conn(db_path) as conn:
                    log_health(conn, "email_triage", "green", "0 new messages")
            log.run_end(run_id, status="ok", emails=0)
            return msg

        # 2. Classify
        classified = classify_emails(emails, dry_run=dry_run)

        # 3. Label (needs Gmail service)
        if not dry_run:
            service = _build_gmail_service()
            stats = apply_labels_bulk(service, classified, dry_run=False)
        else:
            stats = apply_labels_bulk(None, classified, dry_run=True)

        # 4. Immediate alerts for flag_urgent — fires within the SAME run
        urgent = [ce for ce in classified if ce.flag_urgent]
        if urgent and not dry_run:
            for ce in urgent:
                alert = format_urgent_alert(ce)
                _send_telegram(alert)
                log.info("urgent_alert_sent", msg_id=ce.email.msg_id, flag=ce.flag_reason)

        # 5. Log to DB
        total = len(classified)
        summary_msg = (
            f"Triaged {total} emails — "
            f"{len(urgent)} urgent, "
            f"{stats.get('AI/SPAM', 0)} spam archived"
        )
        if not dry_run:
            with get_conn(db_path) as conn:
                log_health(conn, "email_triage", "green", summary_msg, {
                    "total": total,
                    "urgent": len(urgent),
                    "by_label": {k: v for k, v in stats.items() if k != "failed"},
                })

        duration = (datetime.now(timezone.utc) - start).total_seconds()
        log.run_end(run_id, status="ok", duration_seconds=duration,
                    total=total, urgent=len(urgent))

        result = f"📬 Email triage: {total} emails processed, {len(urgent)} urgent"
        if verbose:
            print(result)
            print(f"Stats: {json.dumps(stats, indent=2)}")
        return result

    except Exception as e:
        log.run_error(run_id, error=str(e))
        try:
            with get_conn(db_path) as conn:
                log_health(conn, "email_triage", "red", str(e)[:200])
        except Exception:
            pass
        return f"🔴 Email triage failed: {e}"


# ---------------------------------------------------------------------------
# Daily digest run
# ---------------------------------------------------------------------------

def run_digest(dry_run: bool = False, verbose: bool = False) -> str:
    """
    Build and send the daily email digest.
    Called once at 6pm EST.
    """
    run_id = str(uuid.uuid4())[:8]
    log.run_start(run_id, mode="digest", dry_run=dry_run)

    # We don't store email subjects in DB (privacy), so build the digest
    # from today's classified emails if we have them in memory,
    # otherwise use the health-log summary.
    summary = get_summary()

    if not dry_run:
        _send_telegram(summary)
        log.info("daily_digest_sent")

    if verbose:
        print(summary)

    log.run_end(run_id, status="ok", mode="digest")
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Email Triage Agent")
    parser.add_argument("--mode", choices=["poll", "digest"], default="poll",
                        help="poll=2h triage run, digest=daily summary send")
    parser.add_argument("--dry-run", action="store_true",
                        help="No Gmail writes, no Telegram sends")
    parser.add_argument("--verbose", action="store_true",
                        help="Print output to stdout")
    args = parser.parse_args()

    if args.mode == "digest":
        result = run_digest(dry_run=args.dry_run, verbose=args.verbose or args.dry_run)
    else:
        result = run_poll(dry_run=args.dry_run, verbose=args.verbose or args.dry_run)

    if args.dry_run:
        print("\n--- DRY RUN OUTPUT ---")
        print(result)

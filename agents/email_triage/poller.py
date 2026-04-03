"""
agents/email_triage/poller.py — Poll Gmail inbox for new messages.

Fetches all messages received since the last stored watermark (stored in SQLite).
Returns a list of raw message dicts for classifier.py to process.

Gmail API uses OAuth2 with env vars:
  GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN
"""

from __future__ import annotations

import base64
import email as email_lib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.db import get_conn, get_db_path

log = get_logger("email_triage")

# ---------------------------------------------------------------------------
# Gmail API setup
# ---------------------------------------------------------------------------

def _build_gmail_service():
    """Build an authenticated Gmail API service using OAuth2 refresh token."""
    import os
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    client_id = os.environ.get("GMAIL_CLIENT_ID", "")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "")
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN", "")

    if not all([client_id, client_secret, refresh_token]):
        # Try loading from .env via secrets
        from shared.secrets import get_secret
        try:
            client_id = get_secret("GMAIL_CLIENT_ID")
            client_secret = get_secret("GMAIL_CLIENT_SECRET")
            refresh_token = get_secret("GMAIL_REFRESH_TOKEN")
        except Exception:
            raise RuntimeError(
                "Gmail credentials not found. Set GMAIL_CLIENT_ID, "
                "GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN in .env"
            )

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://mail.google.com/"],
    )
    return build("gmail", "v1", credentials=creds)


# ---------------------------------------------------------------------------
# Watermark management (stored in SQLite system_health table)
# ---------------------------------------------------------------------------

_WATERMARK_KEY = "email_triage_last_poll"


def _get_last_poll_time() -> str | None:
    """Return the ISO timestamp of the last successful poll, or None."""
    try:
        with get_conn(get_db_path()) as conn:
            row = conn.execute(
                "SELECT details FROM system_health WHERE agent_name = ? ORDER BY checked_at DESC LIMIT 1",
                (_WATERMARK_KEY,),
            ).fetchone()
            if row and row["details"]:
                data = json.loads(row["details"])
                return data.get("last_poll_time")
    except Exception as e:
        log.warning("watermark_read_failed", error=str(e))
    return None


def _save_poll_time(ts: str) -> None:
    """Persist the poll timestamp so next run fetches only new messages."""
    try:
        with get_conn(get_db_path()) as conn:
            conn.execute(
                "INSERT INTO system_health (agent_name, status, message, details) VALUES (?, ?, ?, ?)",
                (_WATERMARK_KEY, "green", "poll completed", json.dumps({"last_poll_time": ts})),
            )
    except Exception as e:
        log.warning("watermark_save_failed", error=str(e))


# ---------------------------------------------------------------------------
# Message parsing
# ---------------------------------------------------------------------------

def _parse_message(service, msg_id: str) -> dict[str, Any]:
    """Fetch and parse a single Gmail message into a flat dict."""
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()

    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}

    # Extract body text
    body = _extract_body(msg.get("payload", {}))

    # Build snippet
    snippet = msg.get("snippet", "")

    return {
        "id": msg_id,
        "thread_id": msg.get("threadId", ""),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", "(no subject)"),
        "date": headers.get("date", ""),
        "snippet": snippet,
        "body": body[:2000],  # cap at 2000 chars for Claude
        "label_ids": msg.get("labelIds", []),
        "internal_date": msg.get("internalDate", "0"),
    }


def _extract_body(payload: dict) -> str:
    """Recursively extract plain text body from Gmail message payload."""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")

    if body_data and mime_type == "text/plain":
        return base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")

    parts = payload.get("parts", [])
    for part in parts:
        text = _extract_body(part)
        if text:
            return text

    # Fallback: try HTML parts
    if body_data and mime_type == "text/html":
        raw = base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")
        # Strip HTML tags naively
        import re
        return re.sub(r"<[^>]+>", " ", raw)

    return ""


# ---------------------------------------------------------------------------
# Main poller function
# ---------------------------------------------------------------------------

def poll_new_messages(max_results: int = 100, dry_run: bool = False) -> list[dict[str, Any]]:
    """
    Fetch new Gmail messages since the last poll watermark.

    Args:
        max_results: Maximum number of messages to fetch per run.
        dry_run: If True, skip writing the watermark.

    Returns:
        List of parsed message dicts.
    """
    log.info("email_poller_start", max_results=max_results, dry_run=dry_run)

    service = _build_gmail_service()
    last_poll = _get_last_poll_time()
    now_ts = datetime.now(timezone.utc).isoformat()

    # Build query: INBOX messages after last poll
    query = "in:inbox"
    if last_poll:
        # Gmail uses Unix epoch seconds for after:
        try:
            dt = datetime.fromisoformat(last_poll.replace("Z", "+00:00"))
            epoch_sec = int(dt.timestamp())
            query += f" after:{epoch_sec}"
        except Exception:
            pass  # fall back to no time filter

    log.info("email_poll_query", query=query, last_poll=last_poll)

    # Fetch message IDs
    try:
        result = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results,
        ).execute()
    except Exception as e:
        log.error("gmail_list_failed", error=str(e))
        raise

    messages_meta = result.get("messages", [])
    log.info("email_poll_found", count=len(messages_meta))

    # Fetch full message details
    parsed: list[dict[str, Any]] = []
    for meta in messages_meta:
        try:
            msg = _parse_message(service, meta["id"])
            parsed.append(msg)
        except Exception as e:
            log.warning("message_parse_failed", msg_id=meta["id"], error=str(e))

    if not dry_run:
        _save_poll_time(now_ts)

    log.info("email_poll_complete", parsed=len(parsed))
    return parsed


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Poll Gmail inbox")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    msgs = poll_new_messages(dry_run=args.dry_run)
    if args.verbose:
        for m in msgs:
            print(f"[{m['date']}] From: {m['from']} | Subject: {m['subject']}")
    print(f"Fetched {len(msgs)} new messages.")

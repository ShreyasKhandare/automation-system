"""
agents/email_triage/poller.py — Fetch new Gmail messages since last poll.

Uses OAuth2 with a stored refresh token (generated once, stored in .env).
Tracks the last-processed message ID in SQLite to avoid reprocessing.

Poll cursor strategy:
  - Stores last_history_id in system_health table details JSON
  - Falls back to fetching messages from the last 3 hours if no cursor found
  - Never deletes messages; only reads and labels

Gmail API scopes required:
  https://www.googleapis.com/auth/gmail.modify
  (allows read + label + archive; does NOT allow delete)
"""

from __future__ import annotations

import base64
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.secrets import get_secret

log = get_logger("email_triage")

_GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
_MAX_RESULTS = 50     # messages per poll
_SNIPPET_LEN = 300    # chars of body snippet to pass to Claude


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class EmailMessage:
    msg_id: str          # Gmail message ID
    thread_id: str
    sender: str          # "Name <email>" or just "email"
    subject: str
    snippet: str         # first ~300 chars of body (plain text)
    date: str            # ISO string
    labels: list[str]    # existing Gmail label IDs
    is_unread: bool


# ---------------------------------------------------------------------------
# Gmail service factory
# ---------------------------------------------------------------------------

def _build_gmail_service():
    """Build an authenticated Gmail API service using OAuth2 refresh token."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        raise ImportError(
            "Google API client not installed. "
            "Run: pip install google-api-python-client google-auth google-auth-oauthlib"
        )

    client_id = get_secret("GMAIL_CLIENT_ID")
    client_secret = get_secret("GMAIL_CLIENT_SECRET")
    refresh_token = get_secret("GMAIL_REFRESH_TOKEN")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=_GMAIL_SCOPES,
    )

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


# ---------------------------------------------------------------------------
# Poll cursor (stored in SQLite system_health table)
# ---------------------------------------------------------------------------

def _get_last_history_id() -> str | None:
    """Retrieve the last Gmail history ID from the DB."""
    try:
        from shared.db import get_conn, get_db_path
        with get_conn(get_db_path()) as conn:
            row = conn.execute(
                """
                SELECT details FROM system_health
                WHERE agent_name = 'email_triage'
                ORDER BY checked_at DESC LIMIT 1
                """
            ).fetchone()
        if row and row["details"]:
            details = json.loads(row["details"])
            return details.get("last_history_id")
    except Exception as e:
        log.warning("cursor_fetch_failed", error=str(e))
    return None


def _save_last_history_id(history_id: str) -> None:
    """Persist the latest Gmail history ID to DB."""
    try:
        from shared.db import get_conn, get_db_path, log_health
        with get_conn(get_db_path()) as conn:
            log_health(
                conn, "email_triage", "green",
                "Poll complete",
                {"last_history_id": history_id},
            )
    except Exception as e:
        log.warning("cursor_save_failed", error=str(e))


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def _parse_headers(headers: list[dict]) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in headers}


def _extract_snippet(payload: dict) -> str:
    """Pull plain-text body snippet from a message payload."""
    def _decode(data: str) -> str:
        try:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        except Exception:
            return ""

    mime = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")

    if mime == "text/plain" and body_data:
        return _decode(body_data)[:_SNIPPET_LEN]

    # Recurse into multipart parts
    for part in payload.get("parts", []):
        result = _extract_snippet(part)
        if result:
            return result[:_SNIPPET_LEN]

    return ""


def _parse_message(raw: dict) -> EmailMessage:
    headers = _parse_headers(raw.get("payload", {}).get("headers", []))
    snippet = raw.get("snippet", "") or _extract_snippet(raw.get("payload", {}))

    date_str = headers.get("date", "")
    try:
        # Try to parse RFC 2822 date
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        date_iso = dt.astimezone(timezone.utc).isoformat()
    except Exception:
        date_iso = datetime.now(timezone.utc).isoformat()

    return EmailMessage(
        msg_id=raw["id"],
        thread_id=raw.get("threadId", ""),
        sender=headers.get("from", ""),
        subject=headers.get("subject", "(no subject)"),
        snippet=snippet[:_SNIPPET_LEN],
        date=date_iso,
        labels=raw.get("labelIds", []),
        is_unread="UNREAD" in raw.get("labelIds", []),
    )


# ---------------------------------------------------------------------------
# Main poll function
# ---------------------------------------------------------------------------

def poll_new_messages(dry_run: bool = False) -> list[EmailMessage]:
    """
    Fetch new Gmail messages since the last poll.
    Uses history API if a cursor exists, otherwise falls back to
    querying messages from the last 3 hours.
    Returns a list of EmailMessage objects (unread only).
    """
    service = _build_gmail_service()
    messages: list[EmailMessage] = []
    last_history_id = _get_last_history_id()

    try:
        if last_history_id:
            messages = _fetch_via_history(service, last_history_id)
        else:
            messages = _fetch_recent_messages(service)

        # Update cursor with the latest message's historyId
        if messages and not dry_run:
            latest_id = _get_current_history_id(service)
            if latest_id:
                _save_last_history_id(latest_id)

        log.info("poll_complete", new_messages=len(messages), dry_run=dry_run)
        return messages

    except Exception as e:
        log.error("poll_failed", error=str(e), exc_info=True)
        return []


def _get_current_history_id(service) -> str | None:
    """Get the current profile historyId for cursor tracking."""
    try:
        profile = service.users().getProfile(userId="me").execute()
        return str(profile.get("historyId", ""))
    except Exception:
        return None


def _fetch_via_history(service, start_history_id: str) -> list[EmailMessage]:
    """Fetch messages added since last history ID via Gmail History API."""
    messages: list[EmailMessage] = []
    page_token = None

    while True:
        kwargs = {
            "userId": "me",
            "startHistoryId": start_history_id,
            "historyTypes": ["messageAdded"],
            "labelId": "INBOX",
        }
        if page_token:
            kwargs["pageToken"] = page_token

        try:
            result = service.users().history().list(**kwargs).execute()
        except Exception as e:
            # historyId too old — fall back to recent fetch
            log.warning("history_id_stale", error=str(e))
            return _fetch_recent_messages(service)

        for history_record in result.get("history", []):
            for msg_added in history_record.get("messagesAdded", []):
                msg_stub = msg_added.get("message", {})
                msg_id = msg_stub.get("id")
                if not msg_id:
                    continue
                if "UNREAD" not in msg_stub.get("labelIds", []):
                    continue
                try:
                    raw = service.users().messages().get(
                        userId="me", id=msg_id,
                        format="full",
                    ).execute()
                    messages.append(_parse_message(raw))
                    time.sleep(0.1)
                except Exception as e:
                    log.error("message_fetch_failed", msg_id=msg_id, error=str(e))

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    return messages


def _fetch_recent_messages(service, hours_back: int = 3) -> list[EmailMessage]:
    """Fallback: fetch unread messages from the last N hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    after_epoch = int(cutoff.timestamp())
    query = f"is:unread in:inbox after:{after_epoch}"

    result = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=_MAX_RESULTS,
    ).execute()

    messages: list[EmailMessage] = []
    for stub in result.get("messages", []):
        try:
            raw = service.users().messages().get(
                userId="me", id=stub["id"], format="full"
            ).execute()
            messages.append(_parse_message(raw))
            time.sleep(0.1)
        except Exception as e:
            log.error("message_fetch_failed", msg_id=stub["id"], error=str(e))

    return messages


if __name__ == "__main__":
    msgs = poll_new_messages(dry_run=True)
    print(f"Found {len(msgs)} new messages")
    for m in msgs[:5]:
        print(f"  From: {m.sender[:50]}")
        print(f"  Subject: {m.subject[:80]}")
        print()

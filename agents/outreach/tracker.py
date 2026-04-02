"""
agents/outreach/tracker.py — SQLite + Google Sheets outreach CRM.

Persists outreach records to SQLite and syncs to the Outreach CRM
Google Sheet for mobile visibility.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.db import get_conn, get_db_path, upsert_outreach
from agents.outreach.drafter import DraftedEmail

log = get_logger("outreach")

_SHEET_HEADERS = [
    "Outreach ID", "Name", "Title", "Company", "Email", "Verified",
    "Subject", "Status", "Created", "Sent At", "Replied", "Follow-ups Sent",
    "Next Follow-up", "Job ID", "Notes",
]


def _make_outreach_id(name: str, company: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    slug_name = name.lower().replace(" ", "_")[:12]
    slug_company = company.lower().replace(" ", "_")[:12]
    return f"out_{today}_{slug_name}_{slug_company}"


def save_draft(draft: DraftedEmail, job_id: Optional[str] = None) -> str:
    """
    Save a drafted email to SQLite with status='draft'.

    Returns the outreach_id.
    """
    outreach_id = _make_outreach_id(draft.contact.contact.full_name, draft.contact.contact.company)

    record = {
        "id": outreach_id,
        "recruiter_name": draft.contact.contact.full_name,
        "recruiter_title": draft.contact.contact.title or "",
        "company": draft.contact.contact.company,
        "email": draft.contact.email,
        "email_verified": int(draft.contact.verified),
        "linkedin_url": draft.contact.contact.linkedin_url or "",
        "source": draft.contact.contact.source,
        "draft_subject": draft.subject,
        "draft_body": draft.body,
        "status": "draft",
        "job_id": job_id or "",
        "notes": json.dumps({"hunter_status": draft.contact.hunter_status,
                             "confidence": draft.contact.confidence}),
    }

    try:
        with get_conn(get_db_path()) as conn:
            upsert_outreach(conn, record)
        log.info("draft_saved", outreach_id=outreach_id, company=draft.contact.contact.company)
    except Exception as e:
        log.error("draft_save_failed", error=str(e))

    return outreach_id


def mark_pending_approval(outreach_id: str) -> None:
    """Move status from draft → pending_approval."""
    try:
        with get_conn(get_db_path()) as conn:
            conn.execute(
                "UPDATE outreach SET status='pending_approval' WHERE id=?",
                (outreach_id,),
            )
        log.info("outreach_pending", outreach_id=outreach_id)
    except Exception as e:
        log.error("mark_pending_failed", outreach_id=outreach_id, error=str(e))


def mark_sent(outreach_id: str) -> None:
    """Set status=sent, sent_at=now."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_conn(get_db_path()) as conn:
            conn.execute(
                "UPDATE outreach SET status='sent', sent_at=? WHERE id=?",
                (now, outreach_id),
            )
        log.info("outreach_sent", outreach_id=outreach_id)
    except Exception as e:
        log.error("mark_sent_failed", outreach_id=outreach_id, error=str(e))


def mark_rejected(outreach_id: str, reason: str = "") -> None:
    """Set status=draft with a rejection note (user can re-draft later)."""
    note = f"rejected_by_user: {reason}" if reason else "rejected_by_user"
    try:
        with get_conn(get_db_path()) as conn:
            conn.execute(
                "UPDATE outreach SET status='draft', notes=notes||? WHERE id=?",
                (f"\n{note}", outreach_id),
            )
        log.info("outreach_rejected", outreach_id=outreach_id)
    except Exception as e:
        log.error("mark_rejected_failed", outreach_id=outreach_id, error=str(e))


def record_reply(outreach_id: str) -> None:
    """Mark that a reply was received."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_conn(get_db_path()) as conn:
            conn.execute(
                "UPDATE outreach SET status='replied', reply_received=1, reply_at=? WHERE id=?",
                (now, outreach_id),
            )
        log.info("outreach_reply_recorded", outreach_id=outreach_id)
    except Exception as e:
        log.error("record_reply_failed", outreach_id=outreach_id, error=str(e))


def increment_follow_up(outreach_id: str, next_follow_up_date: str) -> None:
    """Increment follow_up_count and set next_follow_up_at."""
    try:
        with get_conn(get_db_path()) as conn:
            conn.execute(
                "UPDATE outreach SET follow_up_count = follow_up_count + 1, next_follow_up_at=? WHERE id=?",
                (next_follow_up_date, outreach_id),
            )
        log.info("follow_up_incremented", outreach_id=outreach_id, next=next_follow_up_date)
    except Exception as e:
        log.error("increment_follow_up_failed", outreach_id=outreach_id, error=str(e))


def get_pending_approvals() -> list[dict]:
    """Return all outreach records with status='pending_approval'."""
    try:
        with get_conn(get_db_path()) as conn:
            rows = conn.execute(
                "SELECT * FROM outreach WHERE status='pending_approval' ORDER BY created_at ASC"
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        log.error("get_pending_failed", error=str(e))
        return []


def get_due_follow_ups() -> list[dict]:
    """Return outreach records where follow-up is due today or overdue."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with get_conn(get_db_path()) as conn:
            rows = conn.execute(
                "SELECT * FROM outreach WHERE status='sent' "
                "AND reply_received=0 AND next_follow_up_at IS NOT NULL "
                "AND next_follow_up_at <= ? "
                "ORDER BY next_follow_up_at ASC",
                (today,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        log.error("get_follow_ups_failed", error=str(e))
        return []


# ---------------------------------------------------------------------------
# Google Sheets sync
# ---------------------------------------------------------------------------

def _get_sheets_service():
    """Build Google Sheets API service using credentials JSON secret."""
    import json as _json
    import tempfile
    import os
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds_raw = get_secret = __import__("shared.secrets", fromlist=["get_secret"]).get_secret
    creds_json_str = get_secret("GOOGLE_SHEETS_CREDENTIALS_JSON")

    # Write to temp file if raw JSON, else treat as file path
    try:
        creds_dict = _json.loads(creds_json_str)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            _json.dump(creds_dict, f)
            creds_path = f.name
    except (ValueError, _json.JSONDecodeError):
        creds_path = creds_json_str

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    return build("sheets", "v4", credentials=creds)


def sync_to_sheet(outreach_id: str, dry_run: bool = False) -> bool:
    """
    Sync a single outreach record to the Google Sheets Outreach CRM.
    Appends if new, otherwise updates the matching row.
    """
    if dry_run:
        log.info("sheets_sync_dry_run", outreach_id=outreach_id)
        return True

    try:
        from shared.secrets import get_secret

        sheet_id = get_secret("GOOGLE_SHEET_ID_OUTREACH")
        service = _get_sheets_service()

        # Fetch the outreach record
        with get_conn(get_db_path()) as conn:
            row = conn.execute(
                "SELECT * FROM outreach WHERE id=?", (outreach_id,)
            ).fetchone()
        if not row:
            log.warning("sheets_sync_record_not_found", outreach_id=outreach_id)
            return False

        row = dict(row)
        values = [[
            row["id"],
            row["recruiter_name"],
            row["recruiter_title"] or "",
            row["company"],
            row["email"] or "",
            "✓" if row["email_verified"] else "",
            row["draft_subject"] or "",
            row["status"],
            (row["created_at"] or "")[:16],
            (row["sent_at"] or "")[:16],
            "Yes" if row["reply_received"] else "No",
            str(row["follow_up_count"] or 0),
            (row["next_follow_up_at"] or "")[:10],
            row["job_id"] or "",
            "",  # Notes col left for manual use
        ]]

        # Check if row already exists
        existing = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range="Outreach CRM!A:A",
        ).execute()
        existing_ids = [r[0] for r in existing.get("values", []) if r]

        if outreach_id in existing_ids:
            row_idx = existing_ids.index(outreach_id) + 1  # 1-indexed
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=f"Outreach CRM!A{row_idx}",
                valueInputOption="USER_ENTERED",
                body={"values": values},
            ).execute()
            log.info("sheets_row_updated", outreach_id=outreach_id, row=row_idx)
        else:
            # Ensure headers
            if not existing_ids or existing_ids[0] != "Outreach ID":
                service.spreadsheets().values().update(
                    spreadsheetId=sheet_id,
                    range="Outreach CRM!A1",
                    valueInputOption="USER_ENTERED",
                    body={"values": [_SHEET_HEADERS]},
                ).execute()
            service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range="Outreach CRM!A:A",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": values},
            ).execute()
            log.info("sheets_row_appended", outreach_id=outreach_id)

        return True

    except Exception as e:
        log.error("sheets_sync_failed", outreach_id=outreach_id, error=str(e))
        return False

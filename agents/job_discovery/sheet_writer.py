"""
agents/job_discovery/sheet_writer.py — Write scored job listings to Google Sheets.

Sheet: "Job Tracker"
  - Creates headers if sheet is empty (first-run safe)
  - Appends new rows only (skips jobs already in sheet by ID)
  - Tab name: "Jobs"

Requires:
  GOOGLE_SHEETS_CREDENTIALS_JSON — path to service account JSON
  GOOGLE_SHEET_ID_JOBS            — spreadsheet ID from URL
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.secrets import get_secret
from agents.job_discovery.scraper import JobListing

log = get_logger("job_discovery")

# ---------------------------------------------------------------------------
# Sheet schema
# ---------------------------------------------------------------------------

SHEET_HEADERS = [
    "ID",
    "Title",
    "Company",
    "Location",
    "Remote",
    "Posted Date",
    "Source",
    "Salary Range",
    "Score",
    "Score Reason",
    "Status",
    "URL",
    "Tech Stack",
]

_TAB_NAME = "Jobs"


# ---------------------------------------------------------------------------
# Google Sheets client
# ---------------------------------------------------------------------------

def _get_sheets_service():
    """Build and return a Google Sheets API service client."""
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        raise ImportError(
            "Google API client not installed. "
            "Run: pip install google-api-python-client google-auth"
        )

    creds_path = get_secret("GOOGLE_SHEETS_CREDENTIALS_JSON")
    if not Path(creds_path).exists():
        raise FileNotFoundError(f"Service account JSON not found: {creds_path}")

    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _get_spreadsheet_id() -> str:
    return get_secret("GOOGLE_SHEET_ID_JOBS")


# ---------------------------------------------------------------------------
# Sheet operations
# ---------------------------------------------------------------------------

def _ensure_headers(service, spreadsheet_id: str) -> None:
    """Write header row if the sheet is empty."""
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{_TAB_NAME}!A1:Z1",
    ).execute()

    values = result.get("values", [])
    if not values or values[0] != SHEET_HEADERS:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{_TAB_NAME}!A1",
            valueInputOption="RAW",
            body={"values": [SHEET_HEADERS]},
        ).execute()
        log.info("sheet_headers_written", tab=_TAB_NAME)


def _get_existing_ids(service, spreadsheet_id: str) -> set[str]:
    """Return set of job IDs already in the sheet (column A)."""
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{_TAB_NAME}!A2:A",
    ).execute()
    values = result.get("values", [])
    return {row[0] for row in values if row}


def _append_rows(service, spreadsheet_id: str, rows: list[list]) -> int:
    """Append multiple rows to the sheet. Returns count appended."""
    if not rows:
        return 0
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{_TAB_NAME}!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()
    return len(rows)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_jobs_to_sheet(
    listings: list[JobListing],
    dry_run: bool = False,
) -> int:
    """
    Write new job listings to Google Sheets.
    Skips listings already in the sheet (by ID).
    Returns count of rows written.
    """
    if not listings:
        return 0

    if dry_run:
        log.info("sheet_dry_run", count=len(listings))
        for job in listings[:3]:
            log.info("sheet_would_write", id=job.id, title=job.title, company=job.company)
        return 0

    try:
        service = _get_sheets_service()
        spreadsheet_id = _get_spreadsheet_id()

        _ensure_headers(service, spreadsheet_id)
        existing_ids = _get_existing_ids(service, spreadsheet_id)

        new_rows = []
        for job in listings:
            if job.id in existing_ids:
                log.debug("sheet_skip_duplicate", id=job.id)
                continue
            new_rows.append(job.to_sheet_row())

        count = _append_rows(service, spreadsheet_id, new_rows)
        log.info("sheet_write_complete", written=count, skipped=len(listings) - count)
        return count

    except ImportError as e:
        log.error("sheets_import_error", error=str(e))
        return 0
    except Exception as e:
        log.error("sheets_write_failed", error=str(e), exc_info=True)
        return 0


def update_job_status(job_id: str, status: str, notes: str = "") -> bool:
    """
    Update the status column for a specific job row.
    Used when user marks a job as applied/rejected.
    """
    try:
        service = _get_sheets_service()
        spreadsheet_id = _get_spreadsheet_id()

        # Find row number by ID
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{_TAB_NAME}!A:A",
        ).execute()
        id_col = result.get("values", [])

        row_num = None
        for i, row in enumerate(id_col):
            if row and row[0] == job_id:
                row_num = i + 1  # 1-indexed
                break

        if row_num is None:
            log.warning("sheet_job_not_found", job_id=job_id)
            return False

        # Status is column K (index 10, 1-indexed = 11)
        status_col = "K"
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{_TAB_NAME}!{status_col}{row_num}",
            valueInputOption="RAW",
            body={"values": [[status]]},
        ).execute()

        log.info("sheet_status_updated", job_id=job_id, status=status)
        return True

    except Exception as e:
        log.error("sheet_update_failed", job_id=job_id, error=str(e))
        return False


if __name__ == "__main__":
    from agents.job_discovery.scraper import JobListing
    dummy = [
        JobListing(
            id="job_20260331_test_co_ai_eng",
            title="AI Engineer", company="Test Co", url="https://example.com",
            source="test", location="Remote", salary_min=130000, salary_max=160000,
            salary_currency="USD", employment_type="full-time", remote=True,
            tech_stack=["Python", "LangChain"], description_raw="Test job",
            description_snippet="Test job snippet", posted_date="2026-03-31",
            score=8.0, score_reason="Good match",
        )
    ]
    count = write_jobs_to_sheet(dummy, dry_run=True)
    print(f"Would have written {count} rows (dry run)")

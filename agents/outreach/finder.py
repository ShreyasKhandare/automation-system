"""
agents/outreach/finder.py — Find recruiters via Apollo.io with credit guard.

CRITICAL: Apollo credit guard must check get_monthly_apollo_spend() before EVERY API call.
If spend >= 40 (budget 45 minus buffer 5), skip Apollo, alert Telegram, use Hunter fallback.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.db import get_conn, get_db_path
from shared.config_loader import load_config

log = get_logger("outreach")

APOLLO_BUDGET = 45
APOLLO_BUFFER = 5
APOLLO_SPEND_LIMIT = APOLLO_BUDGET - APOLLO_BUFFER  # 40


# ---------------------------------------------------------------------------
# Apollo credit guard
# ---------------------------------------------------------------------------

def get_monthly_apollo_spend() -> int:
    """Return count of Apollo API calls made this calendar month."""
    try:
        with get_conn(get_db_path()) as conn:
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM outreach
                WHERE source = 'apollo'
                AND date(created_at) >= date('now', 'start of month')"""
            ).fetchone()
        return row["cnt"] if row else 0
    except Exception as e:
        log.warning("apollo_spend_check_failed", error=str(e))
        return 0


def _check_apollo_budget() -> bool:
    """
    Returns True if Apollo API calls are allowed.
    Sends Telegram alert and returns False if budget exceeded.
    """
    spend = get_monthly_apollo_spend()
    if spend >= APOLLO_SPEND_LIMIT:
        log.warning("apollo_budget_exceeded", spend=spend, limit=APOLLO_SPEND_LIMIT)
        _send_telegram_alert(
            f"⚠️ Apollo credit guard triggered!\n"
            f"Monthly spend: {spend}/{APOLLO_BUDGET} calls (limit: {APOLLO_SPEND_LIMIT})\n"
            f"Switching to Hunter fallback. Use `/outreach credits` to check status."
        )
        return False
    return True


def _send_telegram_alert(message: str) -> None:
    try:
        import requests
        from shared.secrets import get_secret
        token = get_secret("TELEGRAM_BOT_TOKEN")
        chat_id = get_secret("TELEGRAM_CHAT_ID")
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        log.warning("telegram_alert_failed", error=str(e))


# ---------------------------------------------------------------------------
# Apollo API
# ---------------------------------------------------------------------------

def _apollo_search(company: str, titles: list[str], max_results: int = 5) -> list[dict[str, Any]]:
    """Search Apollo.io for recruiters at a company."""
    import requests
    from shared.secrets import get_secret

    api_key = get_secret("APOLLO_API_KEY")
    url = "https://api.apollo.io/v1/mixed_people/search"

    payload = {
        "q_organization_name": company,
        "person_titles": titles,
        "page": 1,
        "per_page": max_results,
    }

    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": api_key,
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    people = data.get("people", [])
    contacts = []
    for person in people:
        contacts.append({
            "name": f"{person.get('first_name', '')} {person.get('last_name', '')}".strip(),
            "title": person.get("title", ""),
            "email": person.get("email", ""),
            "linkedin_url": person.get("linkedin_url", ""),
            "company": company,
            "source": "apollo",
        })
    return contacts


# ---------------------------------------------------------------------------
# Hunter fallback
# ---------------------------------------------------------------------------

def _hunter_domain_search(company: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Use Hunter.io domain search as Apollo fallback."""
    import requests
    from shared.secrets import get_secret

    api_key = get_secret("HUNTER_API_KEY")

    # Derive domain from company name (simplified)
    domain = company.lower().replace(" ", "") + ".com"

    url = "https://api.hunter.io/v2/domain-search"
    params = {
        "domain": domain,
        "api_key": api_key,
        "limit": max_results,
        "type": "personal",
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        emails = data.get("data", {}).get("emails", [])
        contacts = []
        for e in emails:
            contacts.append({
                "name": f"{e.get('first_name', '')} {e.get('last_name', '')}".strip(),
                "title": e.get("position", ""),
                "email": e.get("value", ""),
                "linkedin_url": "",
                "company": company,
                "source": "hunter_fallback",
            })
        return contacts
    except Exception as e:
        log.warning("hunter_fallback_failed", company=company, error=str(e))
        return []


# ---------------------------------------------------------------------------
# Main finder function
# ---------------------------------------------------------------------------

def find_recruiters(
    company: str,
    job_id: str | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """
    Find recruiters at a company using Apollo (with credit guard) or Hunter fallback.

    Args:
        company: Company name to search.
        job_id: Related job ID for tracking.
        dry_run: Skip API calls.

    Returns:
        List of contact dicts.
    """
    cfg = load_config()
    target_titles = cfg.recruiter_outreach.target_titles

    log.info("finder_start", company=company, job_id=job_id, dry_run=dry_run)

    if dry_run:
        log.info("finder_dry_run", company=company)
        return []

    # Apollo credit guard — check BEFORE every Apollo call
    use_apollo = _check_apollo_budget()

    contacts = []
    if use_apollo:
        try:
            contacts = _apollo_search(company, target_titles)
            log.info("apollo_found", company=company, count=len(contacts))
        except Exception as e:
            log.error("apollo_search_failed", company=company, error=str(e))
            contacts = _hunter_domain_search(company)
    else:
        log.info("using_hunter_fallback", company=company, reason="apollo_budget_exceeded")
        contacts = _hunter_domain_search(company)

    return contacts


def run_assisted(companies: list[str] | None = None, dry_run: bool = False) -> str:
    """
    Run outreach finder for a list of companies.
    Called by orchestrator: RUN OUTREACH SAFE

    Returns summary string.
    """
    log.info("outreach_finder_run", dry_run=dry_run)

    if companies is None:
        # Load top-scoring companies from recent jobs
        companies = _get_top_companies()

    if not companies:
        return "📭 No companies to process. Run job discovery first."

    total_found = 0
    results = []
    for company in companies[:5]:  # Max 5 companies per run
        contacts = find_recruiters(company, dry_run=dry_run)
        total_found += len(contacts)
        if contacts:
            results.append(f"• {company}: {len(contacts)} contacts found")
        else:
            results.append(f"• {company}: no contacts found")

    spend = get_monthly_apollo_spend()
    summary = (
        f"🔍 *Outreach Finder Complete*\n\n"
        f"{chr(10).join(results)}\n\n"
        f"Total contacts: {total_found}\n"
        f"Apollo calls used: {spend}/{APOLLO_BUDGET}\n"
        f"Contacts queued for drafting."
    )
    return summary


def _get_top_companies(limit: int = 5) -> list[str]:
    """Get company names from top-scoring recent jobs."""
    try:
        with get_conn(get_db_path()) as conn:
            rows = conn.execute(
                """SELECT DISTINCT company FROM jobs
                WHERE score >= 7 AND status = 'new'
                ORDER BY score DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [row["company"] for row in rows]
    except Exception as e:
        log.warning("get_top_companies_failed", error=str(e))
        return []


def get_credits_status() -> str:
    """Return Apollo credits status for /outreach credits command."""
    spend = get_monthly_apollo_spend()
    remaining = APOLLO_BUDGET - spend
    status = "🟢" if remaining > 10 else ("🟡" if remaining > 5 else "🔴")
    return (
        f"💳 *Apollo Credits*\n"
        f"{status} Used: {spend}/{APOLLO_BUDGET} this month\n"
        f"Remaining: {remaining} calls\n"
        f"Budget limit: {APOLLO_SPEND_LIMIT} (buffer: {APOLLO_BUFFER})"
    )

"""
agents/outreach/finder.py — Apollo.io recruiter/hiring manager discovery.

Queries Apollo.io people search API for contacts at target companies,
filtered by configured target_titles. Returns up to max_contacts_per_company
contacts per company, deduplicated against existing outreach records.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.config_loader import load_config
from shared.secrets import get_secret
from shared.db import get_conn, get_db_path, get_monthly_apollo_spend

log = get_logger("outreach")

_APOLLO_API_URL = "https://api.apollo.io/v1/mixed_people/search"
_REQUEST_DELAY = 1.2  # seconds between Apollo API calls (rate limit safety)


@dataclass
class ApolloContact:
    first_name: str
    last_name: str
    full_name: str
    title: str
    company: str
    email: Optional[str]
    linkedin_url: Optional[str]
    apollo_id: str
    source: str = "apollo"

    @property
    def contact_id(self) -> str:
        """Stable ID for dedup: company slug + email or name slug."""
        slug_company = self.company.lower().replace(" ", "_")[:20]
        if self.email:
            slug_name = self.email.split("@")[0].replace(".", "_")
        else:
            slug_name = (self.first_name + "_" + self.last_name).lower().replace(" ", "_")
        return f"{slug_company}_{slug_name}"


def _call_apollo(company: str, titles: list[str], per_page: int, api_key: str) -> list[dict]:
    """Single Apollo people search call. Returns raw people list."""
    try:
        import requests
    except ImportError:
        log.error("requests_not_installed")
        return []

    payload = {
        "api_key": api_key,
        "q_organization_name": company,
        "person_titles": titles,
        "page": 1,
        "per_page": per_page,
    }

    try:
        resp = requests.post(_APOLLO_API_URL, json=payload, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            people = data.get("people") or []
            log.info("apollo_search_ok", company=company, found=len(people))
            return people
        elif resp.status_code == 422:
            log.warning("apollo_no_results", company=company, status=resp.status_code)
            return []
        else:
            log.error("apollo_api_error", company=company, status=resp.status_code,
                      body=resp.text[:200])
            return []
    except Exception as e:
        log.error("apollo_request_failed", company=company, error=str(e))
        return []


def _parse_person(person: dict, company: str) -> Optional[ApolloContact]:
    """Convert raw Apollo person dict to ApolloContact."""
    first = (person.get("first_name") or "").strip()
    last = (person.get("last_name") or "").strip()
    if not first and not last:
        return None

    email = person.get("email") or None
    # Apollo sometimes returns "email_not_found@apollo.io" placeholder
    if email and ("apollo.io" in email or "email_not_found" in email):
        email = None

    return ApolloContact(
        first_name=first,
        last_name=last,
        full_name=person.get("name") or f"{first} {last}".strip(),
        title=person.get("title") or "",
        company=person.get("organization_name") or company,
        email=email,
        linkedin_url=person.get("linkedin_url") or None,
        apollo_id=person.get("id") or "",
    )


def _send_credits_exhausted_alert(used: int, budget: int, buffer: int) -> None:
    """Send a one-time Telegram alert when Apollo monthly credits are exhausted."""
    try:
        import requests as _requests
        from shared.secrets import get_secret as _get_secret
        from datetime import datetime as _dt, timezone as _tz
        import calendar as _cal

        token = _get_secret("TELEGRAM_BOT_TOKEN")
        chat_id = _get_secret("TELEGRAM_CHAT_ID")

        now = _dt.now(_tz.utc)
        # First day of next month
        if now.month == 12:
            next_month_first = _dt(now.year + 1, 1, 1, tzinfo=_tz.utc)
        else:
            next_month_first = _dt(now.year, now.month + 1, 1, tzinfo=_tz.utc)
        resume_date = next_month_first.strftime("%B 1, %Y")

        text = (
            f"⚠️ *Apollo credits exhausted for this month* (used {used}/{budget}).\n"
            f"Outreach paused until next month.\n"
            f"Resume date: *{resume_date}*\n\n"
            f"_Hunter.io email-pattern fallback is active for any contacts where you "
            f"already have a name. Use `/outreach credits` to check usage._"
        )
        _requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        log.warning("credits_alert_send_failed", error=str(e))


def _hunter_pattern_verify(first: str, last: str, domain: str, api_key: str) -> Optional[str]:
    """
    Try common email patterns via Hunter.io verify endpoint (costs 0 Hunter credits).
    Returns the first pattern that verifies as non-invalid, or None.
    Patterns tried: firstname.lastname@domain, firstname@domain
    """
    try:
        import requests as _requests
        _HUNTER_VERIFY = "https://api.hunter.io/v2/email-verifier"
        candidates = [
            f"{first.lower()}.{last.lower()}@{domain}",
            f"{first.lower()}@{domain}",
        ]
        for email in candidates:
            resp = _requests.get(
                _HUNTER_VERIFY,
                params={"email": email, "api_key": api_key},
                timeout=10,
            )
            if resp.status_code == 200:
                status = resp.json().get("data", {}).get("status", "unknown")
                if status != "invalid":
                    log.info(
                        "hunter_pattern_match",
                        email=email,
                        hunter_status=status,
                        fallback_method="pattern_verify",
                    )
                    return email
            time.sleep(0.5)
    except Exception as e:
        log.warning("hunter_pattern_verify_failed", error=str(e))
    return None


# ---------------------------------------------------------------------------
# Manual LinkedIn contact list for Hunter fallback
# (populated by user — name + company domain pairs for people found manually)
# ---------------------------------------------------------------------------
# Format: list of dicts with keys: first_name, last_name, company, domain, title
# Users add entries here or via a future Telegram command.
_MANUAL_LINKEDIN_CONTACTS: list[dict] = []


def _find_via_hunter_fallback(
    existing_emails: set[str],
) -> list[ApolloContact]:
    """
    When Apollo credits are exhausted, attempt to verify emails for contacts
    in _MANUAL_LINKEDIN_CONTACTS using Hunter.io pattern verification only
    (verify endpoint costs 0 Hunter free-tier credits for known email addresses).
    """
    if not _MANUAL_LINKEDIN_CONTACTS:
        return []

    try:
        hunter_key = get_secret("HUNTER_API_KEY")
    except Exception:
        return []

    fallback_contacts: list[ApolloContact] = []
    for entry in _MANUAL_LINKEDIN_CONTACTS:
        first = entry.get("first_name", "").strip()
        last = entry.get("last_name", "").strip()
        domain = entry.get("domain", "").strip()
        company = entry.get("company", "").strip()
        title = entry.get("title", "").strip()

        if not (first and last and domain):
            continue

        email = _hunter_pattern_verify(first, last, domain, hunter_key)
        if not email or email in existing_emails:
            continue

        fallback_contacts.append(ApolloContact(
            first_name=first,
            last_name=last,
            full_name=f"{first} {last}",
            title=title,
            company=company,
            email=email,
            linkedin_url=entry.get("linkedin_url") or None,
            apollo_id="",
            source="hunter_fallback",
        ))
        log.info(
            "hunter_fallback_contact_found",
            name=f"{first} {last}",
            company=company,
            fallback_method="pattern_verify",
        )

    return fallback_contacts


def find_contacts(
    companies: list[str],
    existing_emails: set[str] | None = None,
    dry_run: bool = False,
) -> list[ApolloContact]:
    """
    Find recruiter/hiring manager contacts for a list of companies.

    Checks Apollo monthly credit budget before every API call.
    If credits are exhausted (used >= budget - buffer), skips Apollo entirely,
    sends a Telegram alert, and falls back to Hunter.io pattern verification
    for any contacts in _MANUAL_LINKEDIN_CONTACTS.

    Args:
        companies:       List of company names to search.
        existing_emails: Set of emails already in outreach DB — used to skip duplicates.
        dry_run:         If True, skip all API calls and return empty list.

    Returns:
        List of ApolloContact objects (source='apollo' or 'hunter_fallback').
    """
    if dry_run:
        log.info("finder_dry_run_skip")
        return []

    cfg = load_config()
    target_titles = cfg.recruiter_outreach.target_titles
    max_per_company = cfg.recruiter_outreach.max_contacts_per_company
    budget = cfg.recruiter_outreach.apollo_credits_budget_per_month
    buffer = cfg.recruiter_outreach.apollo_credits_safety_buffer
    existing_emails = existing_emails or set()

    # --- Apollo credit guard ---
    try:
        with get_conn(get_db_path()) as conn:
            monthly_spend = get_monthly_apollo_spend(conn)
    except Exception as e:
        log.warning("apollo_spend_query_failed", error=str(e))
        monthly_spend = 0

    if monthly_spend >= (budget - buffer):
        log.warning(
            "apollo_credits_exhausted",
            used=monthly_spend,
            budget=budget,
            buffer=buffer,
        )
        _send_credits_exhausted_alert(monthly_spend, budget, buffer)
        # Fallback: Hunter pattern verification for manual LinkedIn contacts
        return _find_via_hunter_fallback(existing_emails)

    try:
        api_key = get_secret("APOLLO_API_KEY")
    except Exception as e:
        log.error("apollo_key_missing", error=str(e))
        return []

    all_contacts: list[ApolloContact] = []
    seen_ids: set[str] = set()

    for company in companies:
        # Re-check credits before each company to handle the case where
        # multiple companies are being searched in one run.
        try:
            with get_conn(get_db_path()) as conn:
                current_spend = get_monthly_apollo_spend(conn)
        except Exception:
            current_spend = monthly_spend

        if current_spend >= (budget - buffer):
            log.warning(
                "apollo_credits_exhausted_mid_run",
                used=current_spend,
                budget=budget,
                remaining_companies=len(companies),
            )
            _send_credits_exhausted_alert(current_spend, budget, buffer)
            break

        raw_people = _call_apollo(company, target_titles, per_page=10, api_key=api_key)
        time.sleep(_REQUEST_DELAY)

        company_contacts: list[ApolloContact] = []
        for person in raw_people:
            contact = _parse_person(person, company)
            if not contact:
                continue
            # Skip contacts already in outreach DB
            if contact.email and contact.email in existing_emails:
                log.info("finder_skip_existing", email=contact.email)
                continue
            # Skip duplicate within this batch
            if contact.contact_id in seen_ids:
                continue
            seen_ids.add(contact.contact_id)
            company_contacts.append(contact)
            if len(company_contacts) >= max_per_company:
                break

        log.info("finder_company_done", company=company, contacts=len(company_contacts))
        all_contacts.extend(company_contacts)

    log.info("finder_total", total=len(all_contacts), companies=len(companies))
    return all_contacts


def get_existing_outreach_emails() -> set[str]:
    """Load all emails already in the outreach table to avoid re-contacting."""
    from shared.db import get_conn, get_db_path
    try:
        with get_conn(get_db_path()) as conn:
            rows = conn.execute("SELECT email FROM outreach WHERE email IS NOT NULL").fetchall()
        return {r["email"] for r in rows if r["email"]}
    except Exception as e:
        log.warning("existing_emails_fetch_failed", error=str(e))
        return set()

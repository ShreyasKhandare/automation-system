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


def find_contacts(
    companies: list[str],
    existing_emails: set[str] | None = None,
    dry_run: bool = False,
) -> list[ApolloContact]:
    """
    Find recruiter/hiring manager contacts for a list of companies.

    Args:
        companies:       List of company names to search.
        existing_emails: Set of emails already in outreach DB — used to skip duplicates.
        dry_run:         If True, skip API calls and return empty list.

    Returns:
        List of ApolloContact objects (deduplicated, capped per company).
    """
    if dry_run:
        log.info("finder_dry_run_skip")
        return []

    cfg = load_config()
    target_titles = cfg.recruiter_outreach.target_titles
    max_per_company = cfg.recruiter_outreach.max_contacts_per_company
    existing_emails = existing_emails or set()

    try:
        api_key = get_secret("APOLLO_API_KEY")
    except Exception as e:
        log.error("apollo_key_missing", error=str(e))
        return []

    all_contacts: list[ApolloContact] = []
    seen_ids: set[str] = set()

    for company in companies:
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

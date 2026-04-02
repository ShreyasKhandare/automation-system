"""
agents/outreach/verifier.py — Hunter.io email verification.

Verifies email addresses found by Apollo.io. Only contacts with
confidence >= CONFIDENCE_THRESHOLD pass; others are flagged unverified
but still kept if the Apollo email exists (to allow manual review).
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.secrets import get_secret
from agents.outreach.finder import ApolloContact

log = get_logger("outreach")

_HUNTER_VERIFY_URL = "https://api.hunter.io/v2/email-verifier"
_HUNTER_FIND_URL   = "https://api.hunter.io/v2/email-finder"
_CONFIDENCE_THRESHOLD = 0.90
_REQUEST_DELAY = 1.0  # seconds between Hunter API calls


@dataclass
class VerifiedContact:
    contact: ApolloContact
    email: str
    verified: bool
    confidence: float
    hunter_status: str  # valid | invalid | unknown | catch_all | webmail
    disposable: bool = False


def _hunter_verify(email: str, api_key: str) -> dict:
    """Call Hunter.io email verifier. Returns parsed result dict."""
    try:
        import requests
        resp = requests.get(
            _HUNTER_VERIFY_URL,
            params={"email": email, "api_key": api_key},
            timeout=12,
        )
        if resp.status_code == 200:
            return resp.json().get("data", {})
        log.warning("hunter_verify_http_error", email=email, status=resp.status_code)
        return {}
    except Exception as e:
        log.error("hunter_verify_failed", email=email, error=str(e))
        return {}


def _hunter_find(first_name: str, last_name: str, domain: str, api_key: str) -> Optional[str]:
    """Try to find email via Hunter.io email-finder endpoint. Returns email or None."""
    if not domain:
        return None
    try:
        import requests
        resp = requests.get(
            _HUNTER_FIND_URL,
            params={
                "first_name": first_name,
                "last_name": last_name,
                "domain": domain,
                "api_key": api_key,
            },
            timeout=12,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            return data.get("email") or None
        return None
    except Exception:
        return None


def _extract_domain(company: str) -> str:
    """
    Best-effort domain extraction from company name.
    In production this would come from Apollo's organization data.
    """
    slug = company.lower().strip()
    slug = "".join(c if c.isalnum() else "" for c in slug)
    return f"{slug}.com" if slug else ""


def verify_contacts(
    contacts: list[ApolloContact],
    dry_run: bool = False,
) -> list[VerifiedContact]:
    """
    Verify/enrich each ApolloContact via Hunter.io.

    Contacts without an Apollo email get a Hunter email-finder attempt.
    Contacts with an Apollo email get a verifier check.
    Only contacts with email != invalid are returned (confidence check is logged but not hard-filtered
    so user can still see low-confidence contacts in the approval step).

    Args:
        contacts: List of ApolloContact objects from finder.py.
        dry_run:  If True, return all contacts as unverified (no API calls).

    Returns:
        List of VerifiedContact objects, invalid emails excluded.
    """
    if dry_run:
        log.info("verifier_dry_run_skip", count=len(contacts))
        return [
            VerifiedContact(
                contact=c,
                email=c.email or f"{c.first_name.lower()}.{c.last_name.lower()}@{_extract_domain(c.company)}",
                verified=False,
                confidence=0.0,
                hunter_status="unknown",
            )
            for c in contacts
            if c.email
        ]

    try:
        api_key = get_secret("HUNTER_API_KEY")
    except Exception as e:
        log.error("hunter_key_missing", error=str(e))
        # Fall through with Apollo emails unverified
        return [
            VerifiedContact(
                contact=c, email=c.email or "", verified=False,
                confidence=0.0, hunter_status="unknown",
            )
            for c in contacts if c.email
        ]

    results: list[VerifiedContact] = []

    for contact in contacts:
        email = contact.email

        if not email:
            # Try Hunter email-finder
            domain = _extract_domain(contact.company)
            found = _hunter_find(contact.first_name, contact.last_name, domain, api_key)
            time.sleep(_REQUEST_DELAY)
            if not found:
                log.info("verifier_no_email_found", name=contact.full_name, company=contact.company)
                continue
            email = found

        # Verify the email
        data = _hunter_verify(email, api_key)
        time.sleep(_REQUEST_DELAY)

        status = data.get("status") or "unknown"
        score = float(data.get("score") or 0) / 100  # Hunter returns 0-100
        disposable = bool(data.get("disposable"))

        if status == "invalid":
            log.info("verifier_invalid_skip", email=email, company=contact.company)
            continue

        verified = score >= _CONFIDENCE_THRESHOLD
        log.info(
            "verifier_result",
            email=email,
            company=contact.company,
            status=status,
            score=round(score, 2),
            verified=verified,
        )

        results.append(VerifiedContact(
            contact=contact,
            email=email,
            verified=verified,
            confidence=score,
            hunter_status=status,
            disposable=disposable,
        ))

    log.info("verifier_done", total_in=len(contacts), total_out=len(results))
    return results

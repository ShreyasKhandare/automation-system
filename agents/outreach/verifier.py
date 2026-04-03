"""
agents/outreach/verifier.py — Verify email addresses via Hunter.io.

Only proceeds with emails that have confidence >= 90%.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger

log = get_logger("outreach")

CONFIDENCE_THRESHOLD = 0.90


def verify_email(email: str) -> dict[str, Any]:
    """
    Verify a single email address via Hunter.io email verifier.

    Returns:
        Dict with 'email', 'confidence', 'valid', 'status'.
    """
    if not email:
        return {"email": "", "confidence": 0.0, "valid": False, "status": "empty"}

    try:
        import requests
        from shared.secrets import get_secret

        api_key = get_secret("HUNTER_API_KEY")
        resp = requests.get(
            "https://api.hunter.io/v2/email-verifier",
            params={"email": email, "api_key": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})

        confidence = float(data.get("score", 0)) / 100  # Hunter score is 0-100
        status = data.get("result", "unknown")
        valid = confidence >= CONFIDENCE_THRESHOLD and status not in ("undeliverable", "risky")

        log.info("email_verified", email=email[:30], confidence=confidence, valid=valid)
        return {"email": email, "confidence": confidence, "valid": valid, "status": status}

    except Exception as e:
        log.warning("email_verify_failed", email=email[:30], error=str(e))
        return {"email": email, "confidence": 0.0, "valid": False, "status": "error"}


def verify_contacts(contacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Verify emails for a list of contacts. Filters to confidence >= 90%.

    Returns:
        List of contacts with 'email_verified' and 'email_confidence' fields added.
        Only includes contacts with valid emails.
    """
    verified = []
    for contact in contacts:
        email = contact.get("email", "")
        if not email:
            log.info("contact_no_email", name=contact.get("name", ""))
            continue

        result = verify_email(email)
        contact = dict(contact)
        contact["email_verified"] = result["valid"]
        contact["email_confidence"] = result["confidence"]

        if result["valid"]:
            verified.append(contact)
            log.info("contact_verified",
                     name=contact.get("name", ""),
                     company=contact.get("company", ""),
                     confidence=result["confidence"])
        else:
            log.info("contact_rejected",
                     name=contact.get("name", ""),
                     confidence=result["confidence"],
                     status=result["status"])

    log.info("verification_complete",
             total=len(contacts),
             verified=len(verified),
             rejected=len(contacts) - len(verified))
    return verified

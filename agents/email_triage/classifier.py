"""
agents/email_triage/classifier.py — Classify emails using Claude API.

Classification labels:
  AI/JOB_OPPORTUNITY   → recruiter outreach, job alerts, job board emails
  AI/APPLICATION       → ATS status updates (received, under review, rejected, interview)
  AI/NETWORKING        → replies to cold emails, referral mentions
  AI/IMPORTANT         → flag_keywords match (interview, offer, start date)
  AI/NEWSLETTER        → subscriptions, AI digests, blogs
  AI/SPAM              → ads, promos, irrelevant
  AI/OTHER             → unclassified, leave in inbox
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.config_loader import load_config

log = get_logger("email_triage")

VALID_LABELS = [
    "AI/JOB_OPPORTUNITY",
    "AI/APPLICATION",
    "AI/NETWORKING",
    "AI/IMPORTANT",
    "AI/NEWSLETTER",
    "AI/SPAM",
    "AI/OTHER",
]


def _check_flag_keywords(subject: str, body: str, snippet: str, flag_keywords: list[str]) -> bool:
    """Return True if any flag keyword is found in subject, body, or snippet."""
    combined = f"{subject} {snippet} {body}".lower()
    return any(kw.lower() in combined for kw in flag_keywords)


def classify_email(message: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    """
    Classify a single email message using Claude API.

    Returns the message dict enriched with:
      - label: one of VALID_LABELS
      - confidence: float 0-1
      - is_flagged: bool (immediate alert needed)
      - reasoning: str
    """
    cfg = load_config()
    flag_keywords = cfg.email_routing_rules.flag_keywords

    subject = message.get("subject", "")
    sender = message.get("from", "")
    snippet = message.get("snippet", "")
    body = message.get("body", "")[:1000]  # truncate for prompt

    # Fast path: check flag keywords before calling Claude
    is_flagged = _check_flag_keywords(subject, body, snippet, flag_keywords)

    if dry_run:
        label = "AI/OTHER"
        confidence = 0.5
        reasoning = "dry-run mode, classification skipped"
        log.info("classifier_dry_run", subject=subject[:60], label=label)
        result = dict(message)
        result.update({"label": label, "confidence": confidence, "is_flagged": is_flagged, "reasoning": reasoning})
        return result

    # Call Claude API
    try:
        import anthropic
        from shared.secrets import get_secret

        client = anthropic.Anthropic(api_key=get_secret("ANTHROPIC_API_KEY"))

        system_prompt = """You are an email classifier for a job search automation system.
Classify the email into exactly one of these labels:
- AI/JOB_OPPORTUNITY: recruiter outreach, job alerts, job board emails, role invitations
- AI/APPLICATION: ATS status updates (application received, under review, rejected, interview invite, offer)
- AI/NETWORKING: replies to cold emails, referral mentions, professional connections
- AI/IMPORTANT: contains high-priority keywords (interview scheduled, offer extended, next steps, start date)
- AI/NEWSLETTER: subscriptions, AI digests, blogs, newsletters, announcements
- AI/SPAM: ads, promotions, irrelevant marketing, unsubscribe footers dominant
- AI/OTHER: does not fit any of the above

Respond with JSON only:
{"label": "<one of the above>", "confidence": <0.0-1.0>, "reasoning": "<one sentence>"}"""

        user_content = f"""From: {sender}
Subject: {subject}
Snippet: {snippet}
Body (truncated): {body}"""

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=150,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )

        raw = response.content[0].text.strip()
        # Strip code fences if present
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()

        parsed = json.loads(raw)
        label = parsed.get("label", "AI/OTHER")
        confidence = float(parsed.get("confidence", 0.5))
        reasoning = parsed.get("reasoning", "")

        # Validate label
        if label not in VALID_LABELS:
            log.warning("invalid_label_from_claude", label=label)
            label = "AI/OTHER"

        # Override to AI/IMPORTANT if flagged
        if is_flagged and label not in ("AI/SPAM",):
            label = "AI/IMPORTANT"

    except Exception as e:
        log.error("classification_failed", subject=subject[:60], error=str(e))
        label = "AI/OTHER"
        confidence = 0.0
        reasoning = f"classification error: {e}"

    log.info("email_classified",
              subject=subject[:60],
              sender=sender[:40],
              label=label,
              confidence=confidence,
              is_flagged=is_flagged)

    result = dict(message)
    result.update({
        "label": label,
        "confidence": confidence,
        "is_flagged": is_flagged,
        "reasoning": reasoning,
    })
    return result


def classify_batch(messages: list[dict[str, Any]], dry_run: bool = False) -> list[dict[str, Any]]:
    """Classify a list of messages. Returns enriched message dicts."""
    results = []
    for msg in messages:
        classified = classify_email(msg, dry_run=dry_run)
        results.append(classified)
    return results

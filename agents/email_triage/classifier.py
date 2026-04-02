"""
agents/email_triage/classifier.py — Claude API batch email classification.

Classifies each email into one of the exact label names from Section 5:
  AI/JOB_OPPORTUNITY   AI/APPLICATION   AI/NETWORKING
  AI/IMPORTANT         AI/NEWSLETTER    AI/SPAM   AI/OTHER

Batches all emails in a single Claude call for efficiency.
Also detects flag_keywords (interview scheduled, offer extended, next steps,
start date) — these trigger immediate Telegram alerts regardless of label.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.secrets import get_secret
from shared.config_loader import load_config
from agents.email_triage.poller import EmailMessage

log = get_logger("email_triage")

# ---------------------------------------------------------------------------
# Valid labels (exact strings used by Gmail)
# ---------------------------------------------------------------------------

VALID_LABELS = {
    "AI/JOB_OPPORTUNITY",
    "AI/APPLICATION",
    "AI/NETWORKING",
    "AI/IMPORTANT",
    "AI/NEWSLETTER",
    "AI/SPAM",
    "AI/OTHER",
}

_BATCH_SIZE = 20  # emails per Claude call


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class ClassifiedEmail:
    email: EmailMessage
    label: str                  # one of VALID_LABELS
    confidence: float           # 0.0–1.0
    reasoning: str
    flag_urgent: bool           # True if flag_keywords matched
    flag_reason: str            # which keyword triggered, if any


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are the email triage assistant for Shreyas Khandare, an AI/LLM Engineer actively job searching.

Classify each email into EXACTLY ONE of these labels:

  AI/JOB_OPPORTUNITY  — recruiter outreach, job board alerts, "we found a role for you"
  AI/APPLICATION      — ATS system emails: application received/under review/rejected/interview invite
  AI/NETWORKING       — replies to cold outreach Shreyas sent, referral mentions, "coffee chat" replies
  AI/IMPORTANT        — anything containing these exact phrases: "interview scheduled", "offer extended",
                        "next steps", "start date", "background check", "onboarding"
  AI/NEWSLETTER       — subscriptions, digests, blog updates, AI newsletters
  AI/SPAM             — ads, promos, sales pitches, "% off", unsubscribe-heavy content
  AI/OTHER            — everything else that doesn't fit above

CONFIDENCE: rate your certainty 0.0–1.0.

FLAG_URGENT: set true if the email contains ANY of these phrases (case-insensitive):
  "interview scheduled", "offer extended", "next steps", "start date",
  "background check", "technical interview", "final round", "onboarding"

OUTPUT FORMAT — respond ONLY with a valid JSON array, one object per email:
[
  {
    "id": "<msg_id>",
    "label": "AI/APPLICATION",
    "confidence": 0.95,
    "reasoning": "ATS email from Greenhouse confirming application received",
    "flag_urgent": false,
    "flag_reason": ""
  },
  ...
]
No markdown. No other text.
"""


def _build_user_prompt(emails: list[EmailMessage]) -> str:
    parts = [f"Classify these {len(emails)} emails:\n"]
    for email in emails:
        parts.append(
            f"ID: {email.msg_id}\n"
            f"From: {email.sender[:100]}\n"
            f"Subject: {email.subject[:150]}\n"
            f"Snippet: {email.snippet[:250]}\n"
        )
    return "\n---\n".join(parts)


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------

def _call_claude(emails: list[EmailMessage]) -> list[dict]:
    import anthropic
    api_key = get_secret("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)

    log.info("claude_classify_start", count=len(emails))
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_prompt(emails)}],
    )
    tokens = response.usage.input_tokens + response.usage.output_tokens
    log.info("claude_classify_done", tokens=tokens)

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = "\n".join(raw.split("\n")[:-1])
    return json.loads(raw)


def _fallback_classification(emails: list[EmailMessage]) -> list[dict]:
    """Rule-based fallback when Claude is unavailable."""
    cfg = load_config()
    rules = cfg.email_routing_rules
    results = []

    for email in emails:
        text = f"{email.sender} {email.subject} {email.snippet}".lower()
        label = "AI/OTHER"
        confidence = 0.6
        flag_urgent = False
        flag_reason = ""

        # Check flag keywords first (highest priority)
        for kw in rules.flag_keywords:
            if kw.lower() in text:
                label = "AI/IMPORTANT"
                flag_urgent = True
                flag_reason = kw
                confidence = 0.9
                break

        if not flag_urgent:
            if any(kw in text for kw in rules.spam_keywords):
                label = "AI/SPAM"
                confidence = 0.85
            elif any(kw in text for kw in rules.job_important_keywords):
                label = "AI/JOB_OPPORTUNITY"
                confidence = 0.75
            elif any(domain in email.sender for domain in rules.job_important_domains):
                label = "AI/APPLICATION"
                confidence = 0.8
            elif any(kw in text for kw in rules.networking_keywords):
                label = "AI/NETWORKING"
                confidence = 0.7

        results.append({
            "id": email.msg_id,
            "label": label,
            "confidence": confidence,
            "reasoning": "rule-based fallback (Claude unavailable)",
            "flag_urgent": flag_urgent,
            "flag_reason": flag_reason,
        })

    return results


# ---------------------------------------------------------------------------
# Post-processing: enforce flag_keywords from config
# ---------------------------------------------------------------------------

def _enforce_flag_keywords(result: dict, email: EmailMessage) -> dict:
    """
    Regardless of Claude's output, force flag_urgent=True if any
    config.email_routing_rules.flag_keywords appear in the email.
    This is the hard-coded guarantee from the spec.
    """
    cfg = load_config()
    text = f"{email.subject} {email.snippet}".lower()
    for kw in cfg.email_routing_rules.flag_keywords:
        if kw.lower() in text:
            result["flag_urgent"] = True
            result["flag_reason"] = kw
            # Upgrade label to IMPORTANT if not already
            if result.get("label") not in ("AI/IMPORTANT", "AI/APPLICATION"):
                result["label"] = "AI/IMPORTANT"
            break
    return result


# ---------------------------------------------------------------------------
# Main classification entry point
# ---------------------------------------------------------------------------

def classify_emails(
    emails: list[EmailMessage],
    dry_run: bool = False,
) -> list[ClassifiedEmail]:
    """
    Classify all emails. Returns ClassifiedEmail list.
    In dry_run mode, uses rule-based fallback (no Claude call).
    Always enforces flag_keywords check regardless of Claude output.
    """
    if not emails:
        return []

    cfg = load_config()
    threshold = cfg.email_routing_rules.classification_confidence_threshold

    id_map = {e.msg_id: e for e in emails}
    all_results: list[dict] = []

    if dry_run:
        all_results = _fallback_classification(emails)
    else:
        for i in range(0, len(emails), _BATCH_SIZE):
            batch = emails[i:i + _BATCH_SIZE]
            try:
                results = _call_claude(batch)
                all_results.extend(results)
            except json.JSONDecodeError as e:
                log.error("claude_json_parse_failed", error=str(e))
                all_results.extend(_fallback_classification(batch))
            except Exception as e:
                log.error("claude_classify_failed", error=str(e), exc_info=True)
                all_results.extend(_fallback_classification(batch))

    classified: list[ClassifiedEmail] = []
    for result in all_results:
        email = id_map.get(result.get("id", ""))
        if email is None:
            continue

        # Enforce flag_keywords from config regardless of Claude output
        result = _enforce_flag_keywords(result, email)

        label = result.get("label", "AI/OTHER")
        if label not in VALID_LABELS:
            label = "AI/OTHER"

        confidence = float(result.get("confidence", 0.5))

        # Low-confidence items default to AI/OTHER
        if confidence < threshold and label not in ("AI/IMPORTANT",):
            label = "AI/OTHER"

        classified.append(ClassifiedEmail(
            email=email,
            label=label,
            confidence=confidence,
            reasoning=result.get("reasoning", "")[:200],
            flag_urgent=bool(result.get("flag_urgent", False)),
            flag_reason=result.get("flag_reason", ""),
        ))

    urgent = sum(1 for c in classified if c.flag_urgent)
    log.info(
        "classification_complete",
        total=len(classified),
        urgent=urgent,
        by_label={lbl: sum(1 for c in classified if c.label == lbl) for lbl in VALID_LABELS},
    )
    return classified


if __name__ == "__main__":
    from agents.email_triage.poller import EmailMessage
    dummy = [
        EmailMessage(
            msg_id="abc1", thread_id="t1",
            sender="recruiter@sardine.ai",
            subject="Interview scheduled for AI Engineer role",
            snippet="Hi Shreyas, we'd like to schedule a technical interview next week.",
            date="2026-03-31T10:00:00+00:00",
            labels=["UNREAD", "INBOX"],
            is_unread=True,
        ),
        EmailMessage(
            msg_id="abc2", thread_id="t2",
            sender="noreply@newsletter.com",
            subject="This week in AI — top tools roundup",
            snippet="Subscribe to our premium tier and get 50% off...",
            date="2026-03-31T09:00:00+00:00",
            labels=["UNREAD", "INBOX"],
            is_unread=True,
        ),
    ]
    results = classify_emails(dummy, dry_run=True)
    for r in results:
        urgent_tag = "🚨 URGENT" if r.flag_urgent else ""
        print(f"[{r.label}] ({r.confidence:.2f}) {r.email.subject[:60]} {urgent_tag}")

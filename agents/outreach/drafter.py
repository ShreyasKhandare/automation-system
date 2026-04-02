"""
agents/outreach/drafter.py — Claude API email drafting for outreach.

Loads the base_email.txt prompt template, fills placeholders, and calls
claude-sonnet-4-6 to produce a personalized {subject, body} JSON pair.
Enrichment context (recent news, open roles, tech stack) is fetched via
SerpAPI if available; gracefully degrades to empty strings if not.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.secrets import get_secret
from agents.outreach.verifier import VerifiedContact

log = get_logger("outreach")

_PROMPT_PATH = Path(__file__).parent / "prompts" / "base_email.txt"
_FOLLOW_UP_PROMPT_PATH = Path(__file__).parent / "prompts" / "follow_up.txt"
_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 512


@dataclass
class DraftedEmail:
    contact: VerifiedContact
    subject: str
    body: str
    enrichment: dict  # raw context used for drafting


def _fetch_enrichment(company: str, dry_run: bool = False) -> dict:
    """
    Fetch company context via SerpAPI: recent news + open roles.
    Returns dict with keys: recent_news, open_roles, tech_stack.
    Gracefully returns empty strings on any failure.
    """
    enrichment = {"recent_news": "", "open_roles": "", "tech_stack": ""}
    if dry_run:
        return enrichment

    try:
        api_key = get_secret("SERPAPI_API_KEY")
    except Exception:
        return enrichment  # SerpAPI key not configured — skip enrichment

    try:
        import requests
        # Recent news search
        news_resp = requests.get(
            "https://serpapi.com/search",
            params={
                "engine": "google",
                "q": f"{company} AI engineering news 2026",
                "num": 3,
                "api_key": api_key,
            },
            timeout=10,
        )
        if news_resp.status_code == 200:
            results = news_resp.json().get("organic_results", [])
            snippets = [r.get("snippet", "") for r in results[:2] if r.get("snippet")]
            enrichment["recent_news"] = "; ".join(snippets)[:300]
    except Exception as e:
        log.warning("enrichment_news_failed", company=company, error=str(e))

    return enrichment


def _call_claude(prompt: str, dry_run: bool = False) -> Optional[dict]:
    """
    Call Claude claude-sonnet-4-6 with the filled prompt.
    Returns dict with 'subject' and 'body', or None on failure.
    """
    if dry_run:
        return {
            "subject": "AI Engineer with LangGraph expertise",
            "body": "[DRY RUN] This is a placeholder email body. Reply STOP if you'd prefer I don't reach out again.",
        }

    try:
        import anthropic
    except ImportError:
        log.error("anthropic_not_installed")
        return None

    try:
        api_key = get_secret("ANTHROPIC_API_KEY")
        client = anthropic.Anthropic(api_key=api_key)

        message = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        result = json.loads(raw)
        if "subject" not in result or "body" not in result:
            log.error("draft_missing_keys", raw=raw[:200])
            return None
        return result

    except json.JSONDecodeError as e:
        log.error("draft_json_parse_failed", error=str(e))
        return None
    except Exception as e:
        log.error("draft_claude_failed", error=str(e))
        return None


def draft_email(
    verified: VerifiedContact,
    dry_run: bool = False,
) -> Optional[DraftedEmail]:
    """
    Draft a cold outreach email for a single VerifiedContact.

    Args:
        verified: VerifiedContact with name, title, company, email.
        dry_run:  If True, return a placeholder draft without calling Claude.

    Returns:
        DraftedEmail or None if drafting failed.
    """
    enrichment = _fetch_enrichment(verified.contact.company, dry_run=dry_run)

    template = _PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.format(
        name=verified.contact.full_name,
        title=verified.contact.title or "Recruiter",
        company=verified.contact.company,
        tech_stack=enrichment.get("tech_stack") or "not specified",
        open_roles=enrichment.get("open_roles") or "see your careers page",
        recent_news=enrichment.get("recent_news") or "your recent work",
    )

    result = _call_claude(prompt, dry_run=dry_run)
    if not result:
        log.warning("draft_failed", name=verified.contact.full_name, company=verified.contact.company)
        return None

    log.info(
        "draft_created",
        name=verified.contact.full_name,
        company=verified.contact.company,
        subject=result["subject"][:60],
        words=len(result["body"].split()),
    )
    return DraftedEmail(
        contact=verified,
        subject=result["subject"],
        body=result["body"],
        enrichment=enrichment,
    )


def draft_follow_up(
    outreach_record: dict,
    follow_up_number: int,
    max_follow_ups: int,
    dry_run: bool = False,
) -> Optional[dict]:
    """
    Draft a follow-up email for an existing outreach record.

    Args:
        outreach_record: Row dict from the outreach SQLite table.
        follow_up_number: 1-indexed follow-up count (1 = first follow-up).
        max_follow_ups:   Max follow-ups from config.
        dry_run:          If True, return placeholder.

    Returns:
        Dict with 'subject' and 'body', or None on failure.
    """
    if dry_run:
        return {
            "subject": f"Re: {outreach_record.get('draft_subject', 'Following up')}",
            "body": "[DRY RUN] Follow-up placeholder. Reply STOP if you'd prefer I don't reach out again.",
        }

    import datetime
    sent_at = outreach_record.get("sent_at") or outreach_record.get("created_at", "")
    try:
        sent_dt = datetime.datetime.fromisoformat(sent_at)
        days_since = (datetime.datetime.now(datetime.timezone.utc) - sent_dt.replace(
            tzinfo=datetime.timezone.utc)).days
    except Exception:
        days_since = "a few"

    template = _FOLLOW_UP_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.format(
        name=outreach_record.get("recruiter_name", ""),
        title=outreach_record.get("recruiter_title", "Recruiter"),
        company=outreach_record.get("company", ""),
        days_since_sent=days_since,
        original_subject=outreach_record.get("draft_subject", ""),
        follow_up_number=follow_up_number,
        max_follow_ups=max_follow_ups,
        original_body=outreach_record.get("draft_body", "")[:300],
    )

    return _call_claude(prompt, dry_run=dry_run)


def draft_batch(
    verified_contacts: list[VerifiedContact],
    dry_run: bool = False,
) -> list[DraftedEmail]:
    """Draft emails for a list of verified contacts."""
    drafted = []
    for vc in verified_contacts:
        result = draft_email(vc, dry_run=dry_run)
        if result:
            drafted.append(result)
    log.info("draft_batch_done", total=len(drafted), of=len(verified_contacts))
    return drafted

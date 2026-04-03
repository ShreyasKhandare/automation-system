"""
agents/outreach/drafter.py — Draft personalized outreach emails using Claude API.

Uses the base_email.txt prompt template from SYSTEM_DESIGN.md Section 4.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger

log = get_logger("outreach")

_PROMPT_PATH = Path(__file__).parent / "prompts" / "base_email.txt"


def _get_recent_news(company: str) -> str:
    """Get recent news about a company using SerpAPI."""
    try:
        import requests
        from shared.secrets import get_secret
        api_key = get_secret("SERPAPI_API_KEY")
        resp = requests.get(
            "https://serpapi.com/search",
            params={"q": f"{company} AI engineering hiring", "api_key": api_key, "num": 3},
            timeout=10,
        )
        results = resp.json().get("organic_results", [])
        if results:
            return results[0].get("snippet", "")[:200]
    except Exception:
        pass
    return ""


def _get_open_roles(company: str) -> str:
    """Get open AI/ML roles at company from SQLite jobs table."""
    try:
        from shared.db import get_conn, get_db_path
        with get_conn(get_db_path()) as conn:
            rows = conn.execute(
                "SELECT title FROM jobs WHERE company = ? AND status = 'new' LIMIT 3",
                (company,),
            ).fetchall()
        if rows:
            return ", ".join(r["title"] for r in rows)
    except Exception:
        pass
    return "AI/ML Engineering roles"


def draft_email(contact: dict[str, Any], job: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Draft a personalized cold outreach email for a single contact.

    Args:
        contact: Contact dict with name, title, company, email.
        job: Optional job record for context.

    Returns:
        Dict with 'subject', 'body', 'contact', and 'draft_id'.
    """
    name = contact.get("name", "Hiring Team")
    title = contact.get("title", "Recruiter")
    company = contact.get("company", "")

    # Gather context
    tech_stack = ""
    if job:
        tech_stack = json.dumps(json.loads(job.get("tech_stack", "[]"))) if job.get("tech_stack") else ""
    recent_news = _get_recent_news(company)
    open_roles = _get_open_roles(company)

    # Load and fill prompt template
    if not _PROMPT_PATH.exists():
        raise FileNotFoundError(f"Email prompt template not found: {_PROMPT_PATH}")

    prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.format(
        name=name,
        title=title,
        company=company,
        tech_stack=tech_stack or "Python, AI/ML",
        open_roles=open_roles,
        recent_news=recent_news or "building innovative AI products",
    )

    try:
        import anthropic
        from shared.secrets import get_secret

        client = anthropic.Anthropic(api_key=get_secret("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()

        draft = json.loads(raw)
        subject = draft.get("subject", f"AI Engineer — LangGraph + RAG background")
        body = draft.get("body", "")

        # Truncate if needed (max 120 words)
        words = body.split()
        if len(words) > 125:
            body = " ".join(words[:120]) + "..."

        log.info("email_drafted", name=name, company=company, words=len(words))

        return {
            "subject": subject,
            "body": body,
            "contact": contact,
            "draft_ok": True,
        }

    except Exception as e:
        log.error("email_draft_failed", name=name, company=company, error=str(e))
        return {
            "subject": f"AI Engineer — LangGraph + RAG — {name}",
            "body": f"Hi {name}, I'm Shreyas, an AI/LLM Engineer. I'd love to connect about AI opportunities at {company}. Reply STOP if you'd prefer I don't reach out again.",
            "contact": contact,
            "draft_ok": False,
            "error": str(e),
        }


def draft_batch(contacts: list[dict[str, Any]], job: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Draft emails for a batch of verified contacts."""
    drafts = []
    for contact in contacts:
        draft = draft_email(contact, job=job)
        drafts.append(draft)
    return drafts

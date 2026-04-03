"""
agents/outreach/follow_up.py — Auto-draft follow-up emails for non-replies.

Follow-up cadence from config: follow_up_cadence_days = [5, 10]
Max follow-ups: 2
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.db import get_conn, get_db_path
from shared.config_loader import load_config

log = get_logger("outreach")


def _get_due_follow_ups() -> list[dict[str, Any]]:
    """Get outreach records where a follow-up is due."""
    try:
        with get_conn(get_db_path()) as conn:
            rows = conn.execute(
                """SELECT * FROM outreach
                WHERE status = 'sent'
                AND reply_received = 0
                AND follow_up_count < 2
                AND next_follow_up_at IS NOT NULL
                AND date(next_follow_up_at) <= date('now')
                ORDER BY next_follow_up_at ASC
                LIMIT 20"""
            ).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        log.error("get_due_follow_ups_failed", error=str(e))
        return []


def _draft_follow_up_email(outreach: dict[str, Any]) -> dict[str, Any]:
    """Draft a follow-up email using Claude."""
    name = outreach.get("recruiter_name", "there")
    company = outreach.get("company", "")
    follow_up_num = outreach.get("follow_up_count", 0) + 1
    original_subject = outreach.get("draft_subject", "")

    try:
        import anthropic
        from shared.secrets import get_secret

        client = anthropic.Anthropic(api_key=get_secret("ANTHROPIC_API_KEY"))

        prompt = f"""Write a brief follow-up email (follow-up #{follow_up_num}) from Shreyas Khandare.

Original email subject: {original_subject}
To: {name} at {company}

RULES:
- Max 60 words. Reference the original email.
- Tone: casual, not pushy. Brief check-in only.
- Do NOT repeat the full pitch from the original.
- End with: "Reply STOP to opt out."
- Follow-up #{follow_up_num} should {'be slightly more casual than #1' if follow_up_num > 1 else 'just be a brief check-in'}

Return JSON: {{"subject": "Re: <original_subject>", "body": "<follow-up body>"}}"""

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()

        draft = json.loads(raw)
        return {"subject": draft.get("subject", f"Re: {original_subject}"), "body": draft.get("body", ""), "ok": True}

    except Exception as e:
        log.error("follow_up_draft_failed", error=str(e))
        return {
            "subject": f"Re: {original_subject}",
            "body": f"Hi {name}, just wanted to check if you had a chance to see my previous email. Happy to connect if the timing works. Reply STOP to opt out.",
            "ok": False,
        }


def _send_follow_up_for_approval(outreach: dict, draft: dict) -> None:
    """Send follow-up draft to Telegram for approval."""
    try:
        import requests
        from shared.secrets import get_secret
        token = get_secret("TELEGRAM_BOT_TOKEN")
        chat_id = get_secret("TELEGRAM_CHAT_ID")

        msg = (
            f"📬 *Follow-up Draft #{outreach.get('follow_up_count', 0) + 1}*\n\n"
            f"*To:* {outreach.get('recruiter_name', '')} @ {outreach.get('company', '')}\n"
            f"*Subject:* {draft.get('subject', '')}\n\n"
            f"*Body:*\n{draft.get('body', '')}\n\n"
            f"ID: `{outreach.get('id', '')}`"
        )

        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": msg,
                "parse_mode": "Markdown",
                "reply_markup": json.dumps({
                    "inline_keyboard": [[
                        {"text": "✅ Approve", "callback_data": f"APPROVE:{outreach.get('id', '')}"},
                        {"text": "❌ Skip", "callback_data": f"REJECT:{outreach.get('id', '')}"},
                    ]]
                }),
            },
            timeout=10,
        )
    except Exception as e:
        log.warning("follow_up_telegram_failed", error=str(e))


def run_follow_ups(dry_run: bool = False) -> str:
    """
    Process all due follow-ups: draft and send to Telegram for approval.

    Args:
        dry_run: Skip drafting and Telegram sends.

    Returns:
        Summary string.
    """
    from agents.outreach.tracker import is_paused

    if is_paused():
        return "⏸️ Outreach is paused. Follow-ups skipped."

    due = _get_due_follow_ups()
    log.info("follow_ups_due", count=len(due))

    if not due:
        return "📬 No follow-ups due today."

    drafted = 0
    for outreach in due:
        draft = _draft_follow_up_email(outreach)

        if not dry_run:
            # Save draft to DB
            follow_up_id = f"{outreach['id']}_fu{outreach['follow_up_count'] + 1}"
            try:
                with get_conn(get_db_path()) as conn:
                    conn.execute(
                        """UPDATE outreach
                        SET follow_up_count = follow_up_count + 1,
                            draft_subject = ?,
                            draft_body = ?,
                            status = 'pending_approval'
                        WHERE id = ?""",
                        (draft["subject"], draft["body"], outreach["id"]),
                    )
            except Exception as e:
                log.error("save_follow_up_failed", error=str(e))
                continue

            # Send for Telegram approval
            _send_follow_up_for_approval(outreach, draft)

        drafted += 1

    return f"📬 {drafted} follow-up(s) drafted and sent for approval."


def set_follow_up_date(outreach_id: str, days: int) -> None:
    """Set the next follow-up date for an outreach record."""
    due_date = (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()
    try:
        with get_conn(get_db_path()) as conn:
            conn.execute(
                "UPDATE outreach SET next_follow_up_at = ? WHERE id = ?",
                (due_date, outreach_id),
            )
    except Exception as e:
        log.warning("set_follow_up_date_failed", error=str(e))

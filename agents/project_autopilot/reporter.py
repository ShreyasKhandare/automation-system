"""
agents/project_autopilot/reporter.py — Report project autopilot run results.

Provides:
  - get_status() — summary of recent runs for /projects status command
  - report_run() — Telegram notification after a run completes
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.db import get_conn, get_db_path

log = get_logger("project_autopilot")


def _send_telegram(message: str) -> None:
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
        log.warning("telegram_send_failed", error=str(e))


def get_status() -> str:
    """Return recent project run status for /projects status command."""
    try:
        with get_conn(get_db_path()) as conn:
            rows = conn.execute(
                """SELECT repo_name, task_type, status, pr_url, lines_changed, created_at
                FROM project_runs ORDER BY created_at DESC LIMIT 5"""
            ).fetchall()

        if not rows:
            return "📂 No project runs yet. Use `START PROJECT <repo> <task> \"description\"` to begin."

        lines = ["📂 *Recent Project Runs*\n"]
        status_emoji = {"completed": "✅", "failed": "❌", "running": "⏳", "pending": "🕐"}
        for row in rows:
            emoji = status_emoji.get(row["status"], "•")
            pr = f" | [PR]({row['pr_url']})" if row["pr_url"] else ""
            lines_txt = f" | {row['lines_changed']}L" if row["lines_changed"] else ""
            lines.append(
                f"{emoji} *{row['repo_name']}* — {row['task_type']}{lines_txt}{pr}"
            )
        return "\n".join(lines)

    except Exception as e:
        return f"⚠️ Could not fetch project status: {e}"


def report_run(run_record: dict[str, Any]) -> str:
    """
    Generate and send Telegram notification for a completed project run.

    Args:
        run_record: Dict with run details (repo, task, status, pr_url, lines, etc.)

    Returns:
        Telegram message string.
    """
    status = run_record.get("status", "unknown")
    repo = run_record.get("repo_name", "")
    task = run_record.get("task_type", "")
    description = run_record.get("description", "")[:100]
    pr_url = run_record.get("pr_url", "")
    lines = run_record.get("lines_changed", 0)
    error = run_record.get("error_message", "")
    duration = run_record.get("duration_seconds", 0)

    if status == "completed":
        msg = (
            f"✅ *Project Run Complete*\n\n"
            f"*Repo:* {repo}\n"
            f"*Task:* {task}\n"
            f"*Description:* {description}\n"
            f"*Lines changed:* {lines}\n"
            f"*Duration:* {duration:.0f}s\n"
        )
        if pr_url:
            msg += f"*PR:* {pr_url}\n"
    else:
        msg = (
            f"❌ *Project Run Failed*\n\n"
            f"*Repo:* {repo}\n"
            f"*Task:* {task}\n"
            f"*Error:* {error[:200]}\n"
        )

    _send_telegram(msg)
    return msg

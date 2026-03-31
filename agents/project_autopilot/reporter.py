"""
agents/project_autopilot/reporter.py — Telegram reporting for project autopilot runs.

Generates run summaries from project_runs DB table and formats Telegram messages.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.db import get_conn, get_db_path

log = get_logger("project_autopilot")


def _notify_telegram(text: str) -> None:
    """Send a Telegram message. Truncates to 4000 chars."""
    try:
        import requests
        from shared.secrets import get_secret

        token = get_secret("TELEGRAM_BOT_TOKEN")
        chat_id = get_secret("TELEGRAM_CHAT_ID")
        # Chunk if over limit
        for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"},
                timeout=10,
            )
    except Exception as e:
        log.warning("telegram_notify_failed", error=str(e))


def report_run_start(repo_name: str, task_type: str, description: str, dry_run: bool) -> None:
    """Notify Telegram that a project autopilot run has started."""
    dr = " *(dry run)*" if dry_run else ""
    _notify_telegram(
        f"🤖 *Project Autopilot Starting*{dr}\n\n"
        f"*Repo:* `{repo_name}`\n"
        f"*Task:* `{task_type}`\n"
        f"*Description:* {description[:200]}"
    )


def report_run_complete(
    repo_name: str,
    task_type: str,
    description: str,
    branch: str,
    pr_url: str | None,
    tests_passed: bool | None,
    lines_added: int,
    lines_removed: int,
    files_changed: int,
    dry_run: bool,
) -> None:
    """Notify Telegram that a run completed."""
    dr = " *(dry run)*" if dry_run else ""
    test_line = ""
    if tests_passed is True:
        test_line = "\n✅ Tests passed"
    elif tests_passed is False:
        test_line = "\n⚠️ Tests FAILED — manual review needed"

    pr_line = f"\n🔗 [View PR]({pr_url})" if pr_url else ""

    _notify_telegram(
        f"✅ *Project Autopilot Complete*{dr}\n\n"
        f"*Repo:* `{repo_name}`\n"
        f"*Task:* `{task_type}`\n"
        f"*Branch:* `{branch}`\n"
        f"*Changes:* +{lines_added}/-{lines_removed} lines, {files_changed} files"
        f"{test_line}"
        f"{pr_line}"
    )


def report_constraint_violation(repo_name: str, task_type: str, error: str) -> None:
    """Notify Telegram that a constraint violation blocked the run."""
    _notify_telegram(
        f"🚫 *Project Autopilot Blocked*\n\n"
        f"*Repo:* `{repo_name}`\n"
        f"*Task:* `{task_type}`\n"
        f"*Reason:* {error[:300]}"
    )


def report_error(repo_name: str, task_type: str, error: str) -> None:
    """Notify Telegram of an unexpected error."""
    _notify_telegram(
        f"🔴 *Project Autopilot Error*\n\n"
        f"*Repo:* `{repo_name}`\n"
        f"*Task:* `{task_type}`\n"
        f"*Error:* {error[:300]}"
    )


def get_recent_runs_summary(limit: int = 5) -> str:
    """Return a Telegram-formatted summary of recent project runs."""
    try:
        with get_conn(get_db_path()) as conn:
            rows = conn.execute(
                "SELECT repo_name, task_type, status, pr_url, created_at "
                "FROM project_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except Exception as e:
        return f"⚠️ Could not fetch project runs: {e}"

    if not rows:
        return "ℹ️ No project autopilot runs yet."

    lines = ["🤖 *Recent Project Runs*\n"]
    for row in rows:
        icon = "✅" if row["status"] == "completed" else ("🚫" if row["status"] == "blocked" else "🔴")
        pr = f" | [PR]({row['pr_url']})" if row["pr_url"] else ""
        lines.append(
            f"{icon} `{row['repo_name']}` — {row['task_type']} "
            f"({(row['created_at'] or '')[:10]}){pr}"
        )
    return "\n".join(lines)


def log_run_to_db(
    repo_name: str,
    task_type: str,
    description: str,
    branch: str,
    status: str,
    pr_url: str | None,
    tests_passed: bool | None,
    lines_added: int,
    lines_removed: int,
    files_changed: int,
) -> None:
    """Persist a run record to project_runs table."""
    try:
        with get_conn(get_db_path()) as conn:
            conn.execute(
                "INSERT INTO project_runs "
                "(id, repo_name, task_type, description, branch, status, pr_url, "
                "tests_passed, lines_added, lines_removed, files_changed, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{repo_name[:10]}",
                    repo_name,
                    task_type,
                    description[:500],
                    branch,
                    status,
                    pr_url or "",
                    int(tests_passed) if tests_passed is not None else None,
                    lines_added,
                    lines_removed,
                    files_changed,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        log.info("run_logged", repo=repo_name, status=status)
    except Exception as e:
        log.error("run_log_failed", error=str(e))

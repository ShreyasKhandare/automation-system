"""
agents/github_docs/changelog_updater.py — Update CHANGELOG.md with automation improvements.

Uses conventional commit format:
  chore(docs): update weekly job search report [Week 14, 2026]
  feat(resume): add AI Engineer variant for FinTech roles
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.config_loader import load_config

log = get_logger("github_docs")


def _get_changelog_path() -> Path:
    cfg = load_config()
    return _REPO_ROOT / cfg.documentation_and_github.docs_convention.changelog


def _get_week_number() -> tuple[int, int]:
    """Return (year, week_number) for today."""
    now = datetime.now()
    return now.year, now.isocalendar()[1]


def update_changelog(entries: list[dict[str, str]], dry_run: bool = False) -> str:
    """
    Prepend new entries to CHANGELOG.md.

    Args:
        entries: List of dicts with 'type', 'scope', 'message'.
                 E.g. {"type": "chore", "scope": "docs", "message": "weekly report [Week 14]"}
        dry_run: If True, return the new content without writing.

    Returns:
        The changelog entry text that was (or would be) added.
    """
    changelog_path = _get_changelog_path()
    year, week = _get_week_number()
    today = datetime.now().strftime("%Y-%m-%d")

    # Build new entries block
    new_block_lines = [f"\n## [{today}] — Week {week}, {year}\n"]
    for entry in entries:
        scope = entry.get("scope", "")
        msg = entry.get("message", "")
        etype = entry.get("type", "chore")
        if scope:
            new_block_lines.append(f"- {etype}({scope}): {msg}")
        else:
            new_block_lines.append(f"- {etype}: {msg}")

    new_block = "\n".join(new_block_lines) + "\n"

    if dry_run:
        log.info("changelog_dry_run", entries=len(entries))
        return new_block

    # Load existing changelog or create new
    if changelog_path.exists():
        existing = changelog_path.read_text(encoding="utf-8")
    else:
        existing = "# Changelog\n\nAll notable automation changes are documented here.\n"

    # Prepend new block after the header
    header_end = existing.find("\n\n")
    if header_end == -1:
        header_end = len(existing)

    updated = existing[: header_end + 2] + new_block + existing[header_end + 2:]
    changelog_path.write_text(updated, encoding="utf-8")

    log.info("changelog_updated", entries=len(entries), path=str(changelog_path))
    return new_block


def generate_changelog_entries_from_agents() -> list[dict[str, str]]:
    """
    Auto-generate changelog entries from recent agent activity in SQLite.
    """
    entries = []

    try:
        from shared.db import get_conn, get_db_path
        with get_conn(get_db_path()) as conn:
            # Recent job discoveries
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM jobs WHERE date(created_at) = date('now')"
            ).fetchone()
            job_count = row["cnt"] if row else 0
            if job_count > 0:
                entries.append({"type": "chore", "scope": "jobs", "message": f"discovered {job_count} new jobs"})

            # Recent outreach
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM outreach WHERE date(created_at) = date('now')"
            ).fetchone()
            outreach_count = row["cnt"] if row else 0
            if outreach_count > 0:
                entries.append({"type": "chore", "scope": "outreach", "message": f"drafted {outreach_count} outreach emails"})

            # Recent resumes
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM resumes WHERE date(created_at) = date('now')"
            ).fetchone()
            resume_count = row["cnt"] if row else 0
            if resume_count > 0:
                entries.append({"type": "feat", "scope": "resume", "message": f"generated {resume_count} tailored resume variants"})

    except Exception as e:
        log.warning("changelog_auto_entries_failed", error=str(e))

    if not entries:
        entries.append({"type": "chore", "scope": "system", "message": "daily automation health check"})

    return entries

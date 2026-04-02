"""
agents/github_docs/changelog_updater.py — Prepend new entries to CHANGELOG.md.

Uses conventional commit style from config:
  feat, fix, chore, docs — as specified in documentation_and_github.commit_style
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger

log = get_logger("github_docs")

_CHANGELOG_PATH = _REPO_ROOT / "CHANGELOG.md"

_HEADER = "# Changelog\n\nAll notable changes auto-committed by the automation system.\n\n"


def _ensure_changelog() -> None:
    if not _CHANGELOG_PATH.exists():
        _CHANGELOG_PATH.write_text(_HEADER, encoding="utf-8")


def prepend_entry(title: str, bullets: list[str], category: str = "chore") -> None:
    """
    Prepend a new dated entry to CHANGELOG.md.

    Args:
        title:    Short description, e.g. "Weekly automation update"
        bullets:  List of bullet items under this entry
        category: conventional commit type (feat, fix, chore, docs)
    """
    _ensure_changelog()
    existing = _CHANGELOG_PATH.read_text(encoding="utf-8")

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_str = datetime.now(timezone.utc).strftime("Week %W, %Y")

    lines = [f"## [{date_str}] {category}: {title} [{week_str}]\n"]
    for b in bullets:
        lines.append(f"- {b}")
    lines.append("")

    new_entry = "\n".join(lines) + "\n"

    # Insert after the header block
    if _HEADER.strip() in existing:
        updated = existing.replace(_HEADER, _HEADER + new_entry, 1)
    else:
        updated = new_entry + existing

    _CHANGELOG_PATH.write_text(updated, encoding="utf-8")
    log.info("changelog_updated", date=date_str, category=category)


def build_weekly_bullets(stats: dict) -> list[str]:
    """Build bullet list from weekly stats dict."""
    bullets = []
    if stats.get("jobs_discovered"):
        bullets.append(f"Job sweep: {stats['jobs_discovered']} listings discovered, "
                       f"{stats.get('jobs_above_threshold', 0)} above threshold")
    if stats.get("outreach_sent"):
        bullets.append(f"Outreach: {stats['outreach_sent']} emails sent, "
                       f"{stats.get('outreach_replied', 0)} replies")
    if stats.get("resumes_tailored"):
        bullets.append(f"Resume: {stats['resumes_tailored']} variants tailored")
    if stats.get("radar_try_asap"):
        bullets.append(f"AI Radar: {stats['radar_try_asap']} TRY ASAP, "
                       f"{stats.get('radar_watch', 0)} WATCH items")
    if not bullets:
        bullets.append("Automation system running normally")
    return bullets

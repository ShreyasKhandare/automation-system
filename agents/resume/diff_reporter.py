"""
agents/resume/diff_reporter.py — Human-readable diff between base and tailored resume.

Produces:
  - Short Telegram summary (≤ 200 chars)
  - Full JSON diff report written to file
"""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger

log = get_logger("resume")


def compute_text_diff(original: str, revised: str) -> list[str]:
    """Return unified diff lines between two resume strings."""
    orig_lines = original.splitlines(keepends=True)
    rev_lines = revised.splitlines(keepends=True)
    diff = list(difflib.unified_diff(orig_lines, rev_lines,
                                     fromfile="resume_base.md",
                                     tofile="resume_tailored.md",
                                     n=2))
    return diff


def format_telegram_summary(
    diff: dict,
    keyword_report: dict,
    job_title: str,
    company: str,
) -> str:
    """
    Build a ≤ 200-char Telegram summary plus a structured section.
    Short first line for notification preview, details below.
    """
    injected = keyword_report.get("injected", [])
    removed_weak = keyword_report.get("removed_weak", [])
    ats = keyword_report.get("ats_score", {})
    ats_before = ats.get("before", "?")
    ats_after = ats.get("after", "?")
    reasoning = diff.get("reasoning", "Tailored for role requirements.")[:120]

    short = (
        f"📄 *Resume tailored* for *{job_title}* @ {company}\n"
        f"ATS: {ats_before}→{ats_after}/10 · +{len(injected)} keywords · "
        f"-{len(removed_weak)} weak phrases"
    )

    details = [
        f"\n_{reasoning}_",
    ]
    if injected:
        details.append(f"\n*Keywords added:* {', '.join(injected[:8])}")
    if removed_weak:
        details.append(f"*Phrases removed:* {', '.join(removed_weak[:5])}")

    return short + "\n".join(details)


def write_diff_report(
    report_path: Path,
    diff: dict,
    keyword_report: dict,
    text_diff_lines: list[str],
    job_id: str,
) -> None:
    """Write the full diff report as JSON to disk."""
    report = {
        "job_id": job_id,
        "diff": diff,
        "keyword_report": keyword_report,
        "text_diff": "".join(text_diff_lines[:200]),  # cap for file size
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("diff_report_written", path=str(report_path))

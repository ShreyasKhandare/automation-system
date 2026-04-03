"""
agents/resume/diff_reporter.py — Generate diff report between base and tailored resume.

Outputs:
  1. Short Telegram message (max 200 chars)
  2. Full JSON diff to file
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger

log = get_logger("resume")


def generate_diff_report(
    rewrite_result: dict[str, Any],
    job_id: str,
    output_dir: Path,
    file_paths: dict[str, Path],
) -> dict[str, Any]:
    """
    Generate diff report from rewriter output.

    Args:
        rewrite_result: Output from rewriter.rewrite_resume().
        job_id: Job ID this resume was tailored for.
        output_dir: Directory to write the JSON diff file.
        file_paths: Dict with 'md', 'pdf', 'docx' paths.

    Returns:
        Dict with 'telegram_message' (max 200 chars) and 'json_path'.
    """
    diff = rewrite_result.get("diff", {})
    keyword_report = rewrite_result.get("keyword_report", {})

    added = diff.get("added", [])
    modified = diff.get("modified", [])
    reasoning = diff.get("reasoning", "")
    injected = keyword_report.get("injected", [])
    removed_weak = keyword_report.get("removed_weak", [])
    ats_before = keyword_report.get("ats_score_before", "N/A")
    ats_after = keyword_report.get("ats_score_after", "N/A")

    # --- Short Telegram message (max 200 chars) ---
    kw_count = len(injected)
    mod_count = len(modified) + len(added)
    short_msg = f"Resume tailored for {job_id}: +{kw_count} keywords, {mod_count} sections updated. ATS: {ats_before}→{ats_after}"
    if len(short_msg) > 200:
        short_msg = short_msg[:197] + "..."

    # --- Full JSON diff ---
    full_report = {
        "job_id": job_id,
        "generated_at": datetime.utcnow().isoformat(),
        "file_paths": {k: str(v) for k, v in file_paths.items()},
        "diff": {
            "added": added,
            "modified": modified,
            "reasoning": reasoning,
        },
        "keyword_report": {
            "injected": injected,
            "removed_weak": removed_weak,
            "ats_score_before": ats_before,
            "ats_score_after": ats_after,
        },
        "summary": {
            "keywords_added": kw_count,
            "sections_modified": mod_count,
            "weak_phrases_removed": len(removed_weak),
        },
    }

    # Write JSON to file
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"diff_{job_id}.json"
    json_path.write_text(json.dumps(full_report, indent=2), encoding="utf-8")

    log.info("diff_report_generated",
             job_id=job_id,
             json_path=str(json_path),
             telegram_length=len(short_msg))

    return {
        "telegram_message": short_msg,
        "json_path": json_path,
        "full_report": full_report,
    }


def build_telegram_notification(
    diff_report: dict[str, Any],
    job: dict[str, Any],
    file_paths: dict[str, Path],
) -> str:
    """
    Build the full Telegram notification for a completed resume tailoring.

    Args:
        diff_report: Output from generate_diff_report().
        job: Job record dict from SQLite.
        file_paths: Dict with 'md', 'pdf', 'docx' paths.

    Returns:
        Telegram-formatted message string.
    """
    company = job.get("company", "Unknown")
    title = job.get("title", "Unknown")
    score = job.get("score", "?")
    short_msg = diff_report.get("telegram_message", "")
    full = diff_report.get("full_report", {})
    kw_report = full.get("keyword_report", {})
    injected = kw_report.get("injected", [])[:5]
    ats_after = kw_report.get("ats_score_after", "N/A")

    files_text = ""
    for fmt in ["md", "pdf", "docx"]:
        p = file_paths.get(fmt)
        if p and Path(p).exists():
            files_text += f"\n• {fmt.upper()}: `{Path(p).name}`"

    msg = (
        f"📄 *Resume Tailored*\n"
        f"*Job:* {title} @ {company} (score: {score})\n\n"
        f"{short_msg}\n\n"
    )
    if injected:
        msg += f"*Keywords added:* {', '.join(injected)}\n"
    msg += f"*ATS score:* {ats_after}\n"
    if files_text:
        msg += f"\n*Files generated:*{files_text}"

    return msg

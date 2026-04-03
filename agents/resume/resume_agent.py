"""
agents/resume/resume_agent.py — Main resume tailoring orchestrator.

Entry point called by the Telegram bot:
  from agents.resume.resume_agent import run
  run(job_id="job_20260330_sardine_ai_eng")

Also usable as CLI:
  python -m agents.resume.resume_agent --job-id JOB_ID [--dry-run]

Pipeline:
  1. Load job from SQLite
  2. Parse JD (jd_parser.py)
  3. Keyword analysis (keyword_analyzer.py)
  4. Gap analysis (gap_analyzer.py)
  5. ATS audit on base resume (ats_auditor.py)
  6. Rewrite with Claude (rewriter.py)
  7. ATS audit on tailored resume
  8. Convert to PDF + DOCX (converter.py)
  9. Generate diff report (diff_reporter.py)
  10. Write to SQLite resumes table
  11. Send Telegram notification
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.db import get_conn, get_db_path, init_db, log_health
from shared.config_loader import load_config

log = get_logger("resume")


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


def _load_job(job_id: str) -> dict[str, Any] | None:
    """Load job record from SQLite."""
    try:
        db_path = get_db_path()
        init_db(db_path)
        with get_conn(db_path) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None
    except Exception as e:
        log.error("load_job_failed", job_id=job_id, error=str(e))
        return None


def _load_base_resume(cfg) -> str:
    """Load the base resume markdown file."""
    resume_path = _REPO_ROOT / cfg.profile.resume_base_path
    if not resume_path.exists():
        # Try assets/ directly
        resume_path = _REPO_ROOT / "assets" / "resume_base.md"
    if not resume_path.exists():
        return f"# {cfg.profile.name}\n{cfg.profile.bio}\n\n## Skills\n{', '.join(cfg.profile.skills.primary)}\n"
    return resume_path.read_text(encoding="utf-8")


def _save_resume_record(job: dict, resume_id: str, file_paths: dict, keyword_report: dict, diff_summary: str) -> None:
    """Save resume version to SQLite resumes table."""
    try:
        db_path = get_db_path()
        init_db(db_path)
        with get_conn(db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO resumes
                (id, job_id, version, output_md_path, output_pdf_path, output_docx_path,
                 keywords_added, diff_summary, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    resume_id,
                    job.get("id", ""),
                    1,
                    str(file_paths.get("md", "")),
                    str(file_paths.get("pdf", "")),
                    str(file_paths.get("docx", "")),
                    json.dumps(keyword_report.get("injected", [])),
                    diff_summary[:500],
                    "generated",
                ),
            )
    except Exception as e:
        log.error("save_resume_record_failed", error=str(e))


def run(job_id: str, dry_run: bool = False) -> str:
    """
    Main resume tailoring pipeline.

    Args:
        job_id: Job ID from SQLite jobs table.
        dry_run: Skip file writes and API calls.

    Returns:
        Summary string (sent to Telegram by orchestrator).
    """
    log.info("resume_agent_start", job_id=job_id, dry_run=dry_run)
    cfg = load_config()
    start_time = datetime.now(timezone.utc)

    # --- Step 1: Load job ---
    job = _load_job(job_id)
    if not job:
        msg = f"❌ Job not found in DB: `{job_id}`"
        log.error("job_not_found", job_id=job_id)
        return msg

    company = job.get("company", "unknown")
    title = job.get("title", "unknown")
    jd_text = job.get("description_raw") or job.get("description_clean") or ""

    if not jd_text:
        msg = f"❌ No job description for `{job_id}`. Cannot tailor resume."
        return msg

    log.info("resume_tailoring", company=company, title=title, job_id=job_id)

    # --- Step 2: Parse JD ---
    from agents.resume.jd_parser import parse_jd
    jd_parsed = parse_jd(jd_text, job_title=title)

    # --- Step 3: Keyword analysis ---
    from agents.resume.keyword_analyzer import analyze_keywords
    keyword_list = analyze_keywords(jd_text)

    # --- Step 4: Load base resume ---
    base_resume = _load_base_resume(cfg)

    # --- Step 5: Gap analysis ---
    from agents.resume.gap_analyzer import analyze_gaps
    gap_analysis = analyze_gaps(base_resume, jd_parsed, keyword_list)

    # --- Step 6: ATS audit on base resume ---
    from agents.resume.ats_auditor import get_ats_score
    ats_before = get_ats_score(base_resume)

    # --- Step 7: Rewrite ---
    from agents.resume.rewriter import rewrite_resume
    rewrite_result = rewrite_resume(
        base_resume=base_resume,
        job_description=jd_text,
        keyword_list=keyword_list,
        gap_analysis=gap_analysis,
        dry_run=dry_run,
    )
    tailored_resume = rewrite_result.get("tailored_resume", base_resume)

    # --- Step 8: ATS audit on tailored resume ---
    try:
        from agents.resume.ats_auditor import audit_resume
        ats_report = audit_resume(tailored_resume)
        ats_after = ats_report.get("score", 0.0)
    except AssertionError as e:
        log.warning("ats_violation_in_tailored", error=str(e))
        ats_after = 0.0
    except Exception:
        ats_after = ats_before

    # --- Step 9: Save tailored resume file ---
    safe_company = "".join(c if c.isalnum() else "_" for c in company.lower())
    safe_id = job_id.replace("/", "_")
    file_stem = f"resume_{safe_company}_{safe_id}"

    output_dir = _REPO_ROOT / cfg.resume_automation.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / f"{file_stem}.md"

    file_paths: dict[str, Path] = {"md": md_path}

    if not dry_run:
        md_path.write_text(tailored_resume, encoding="utf-8")
        log.info("resume_md_saved", path=str(md_path))

        # --- Step 10: Convert to PDF + DOCX ---
        from agents.resume.converter import convert_all
        try:
            converted = convert_all(md_path, output_dir)
            file_paths.update(converted)
        except Exception as e:
            log.error("conversion_failed", error=str(e))

    # --- Step 11: Diff report ---
    from agents.resume.diff_reporter import generate_diff_report, build_telegram_notification
    diff_report = generate_diff_report(
        rewrite_result=rewrite_result,
        job_id=job_id,
        output_dir=output_dir,
        file_paths=file_paths,
    )

    # --- Step 12: Save to DB ---
    resume_id = f"resume_{datetime.now().strftime('%Y%m%d')}_{safe_company}_{safe_id}_v1"
    keyword_report = rewrite_result.get("keyword_report", {})
    if not dry_run:
        _save_resume_record(job, resume_id, file_paths, keyword_report, diff_report.get("telegram_message", ""))

    # --- Step 13: Send Telegram notification ---
    tg_msg = build_telegram_notification(diff_report, job, file_paths)
    if not dry_run:
        _send_telegram(tg_msg)

    # --- Log health ---
    duration = (datetime.now(timezone.utc) - start_time).total_seconds()
    db_path = get_db_path()
    init_db(db_path)
    with get_conn(db_path) as conn:
        log_health(conn, "resume", "green", f"Tailored {job_id}", {
            "job_id": job_id,
            "duration_seconds": duration,
            "ats_before": ats_before,
            "ats_after": ats_after,
        })

    log.info("resume_agent_complete", job_id=job_id, duration=duration)
    return tg_msg


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Resume tailoring agent")
    parser.add_argument("--job-id", required=True, help="Job ID to tailor resume for")
    parser.add_argument("--dry-run", action="store_true", help="Skip API calls and file writes")
    args = parser.parse_args()

    result = run(job_id=args.job_id, dry_run=args.dry_run)
    print(result)

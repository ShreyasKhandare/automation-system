"""
agents/resume/resume_agent.py — Main orchestrator for the Resume Tailoring agent.

Pipeline (per job):
  1. Load base resume from assets/resume_base.md
  2. Load job record from SQLite by job_id
  3. Parse JD → structured requirements
  4. Analyze keywords across last 20 similar jobs
  5. Run gap analysis
  6. ATS audit of base resume (score before)
  7. Rewrite via Claude (uses prompts/tailor.txt exactly)
  8. ATS audit of tailored resume (score after)
  9. Convert to PDF + DOCX via pandoc / python-docx
 10. Write diff report to file
 11. Update assets/resumes/index.json
 12. Persist to SQLite resumes table
 13. Send Telegram notification with summary

Usage:
  python agents/resume/resume_agent.py --job-id job_20260331_sardine_ai_eng
  python agents/resume/resume_agent.py --job-id ... --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.secrets import get_secret
from shared.config_loader import load_config
from shared.db import get_conn, get_db_path, init_db, log_health
from agents.resume.jd_parser import parse_jd
from agents.resume.keyword_analyzer import analyze_keywords
from agents.resume.gap_analyzer import analyze_gaps
from agents.resume.ats_auditor import audit
from agents.resume.rewriter import rewrite
from agents.resume.converter import convert_all
from agents.resume.diff_reporter import compute_text_diff, format_telegram_summary, write_diff_report

log = get_logger("resume")

_BASE_RESUME_PATH = _REPO_ROOT / "assets" / "resume_base.md"
_OUTPUT_DIR = _REPO_ROOT / "assets" / "resumes"
_INDEX_PATH = _OUTPUT_DIR / "index.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _send_telegram(message: str) -> None:
    import requests
    token = get_secret("TELEGRAM_BOT_TOKEN")
    chat_id = get_secret("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in [message[i:i + 4000] for i in range(0, len(message), 4000)]:
        requests.post(url, json={
            "chat_id": chat_id, "text": chunk,
            "parse_mode": "Markdown", "disable_web_page_preview": True,
        }, timeout=30).raise_for_status()


def _load_job(job_id: str) -> dict | None:
    try:
        with get_conn(get_db_path()) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None
    except Exception as e:
        log.error("job_load_failed", job_id=job_id, error=str(e))
        return None


def _persist_resume(record: dict) -> None:
    db_path = get_db_path()
    if not Path(str(db_path)).exists():
        init_db(db_path)
    with get_conn(db_path) as conn:
        cols = ", ".join(record.keys())
        placeholders = ", ".join(["?"] * len(record))
        conn.execute(
            f"INSERT OR REPLACE INTO resumes ({cols}) VALUES ({placeholders})",
            list(record.values()),
        )
        log_health(conn, "resume", "green", f"Resume tailored for {record.get('job_id', '?')}")


def _update_index(entry: dict) -> None:
    """Append or update entry in assets/resumes/index.json."""
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    index: list[dict] = []
    if _INDEX_PATH.exists():
        try:
            index = json.loads(_INDEX_PATH.read_text())
        except Exception:
            index = []

    # Replace existing entry for same resume_id
    index = [e for e in index if e.get("id") != entry.get("id")]
    index.insert(0, entry)
    _INDEX_PATH.write_text(json.dumps(index, indent=2), encoding="utf-8")
    log.info("index_updated", id=entry.get("id"))


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(job_id: str, dry_run: bool = False) -> str:
    """
    Full resume tailoring pipeline for one job.
    Returns a Telegram-formatted result string.
    """
    run_id = str(uuid.uuid4())[:8]
    log.run_start(run_id, job_id=job_id, dry_run=dry_run)
    start = datetime.now(timezone.utc)

    # 1. Load base resume
    if not _BASE_RESUME_PATH.exists():
        return f"🔴 Resume agent: base resume not found at {_BASE_RESUME_PATH}\nCreate assets/resume_base.md first."
    base_resume = _BASE_RESUME_PATH.read_text(encoding="utf-8")

    # 2. Load job from DB
    job = _load_job(job_id)
    if not job:
        return f"🔴 Resume agent: job `{job_id}` not found in database.\nRun job discovery first or check the ID."

    job_title = job.get("title", "Unknown")
    company = job.get("company", "Unknown")
    job_desc = job.get("description_raw") or job.get("description_clean") or ""

    if not job_desc:
        return f"🔴 Resume agent: no job description for `{job_id}`."

    cfg = load_config()

    try:
        # 3. Parse JD
        log.info("step_parse_jd", job_id=job_id)
        parsed_jd = parse_jd(job_desc)

        # 4. Keyword frequency analysis
        log.info("step_keyword_analysis")
        keyword_list = analyze_keywords(limit=20)

        # 5. Gap analysis
        log.info("step_gap_analysis")
        gap = analyze_gaps(base_resume, parsed_jd)
        gap_text = gap.to_prompt_text()

        # 6. ATS audit — before
        ats_before = audit(base_resume)
        log.info("ats_before", score=ats_before.score)

        # 7. Rewrite
        log.info("step_rewrite")
        if dry_run:
            # Skip Claude call — return base resume with a note
            from agents.resume.rewriter import RewriteResult
            result = RewriteResult(
                tailored_md=base_resume + "\n\n<!-- DRY RUN: no Claude call -->",
                diff={"added": [], "modified": [], "reasoning": "dry-run"},
                keyword_report={"injected": [], "removed_weak": [], "ats_score": {"before": ats_before.score, "after": ats_before.score}},
            )
        else:
            result = rewrite(base_resume, job_desc, keyword_list, gap_text)

        # 8. ATS audit — after
        ats_after = audit(result.tailored_md)
        log.info("ats_after", score=ats_after.score)

        # Inject actual ATS scores into keyword_report
        result.keyword_report.setdefault("ats_score", {})
        result.keyword_report["ats_score"]["before"] = ats_before.score
        result.keyword_report["ats_score"]["after"] = ats_after.score

        # 9. Write tailored MD
        slug = job_id.replace("job_", "")
        md_filename = f"resume_{slug}.md"
        md_path = _OUTPUT_DIR / md_filename
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        if not dry_run:
            md_path.write_text(result.tailored_md, encoding="utf-8")

            # 10. Convert to PDF + DOCX
            output_files = convert_all(md_path, cfg.resume_automation.output_formats)
        else:
            output_files = {"markdown": md_path}

        # 11. Diff report
        text_diff = compute_text_diff(base_resume, result.tailored_md)
        diff_path = _OUTPUT_DIR / f"diff_{slug}.json"
        if not dry_run:
            write_diff_report(diff_path, result.diff, result.keyword_report, text_diff, job_id)

        # 12. Persist to DB + update index
        resume_id = f"resume_{slug}_v1"
        db_record = {
            "id": resume_id,
            "job_id": job_id,
            "version": 1,
            "template": "ats_single_column",
            "output_md_path": str(md_path),
            "output_pdf_path": str(output_files.get("pdf") or ""),
            "output_docx_path": str(output_files.get("docx") or ""),
            "keywords_added": json.dumps(result.keyword_report.get("injected", [])),
            "keywords_removed": json.dumps(result.keyword_report.get("removed_weak", [])),
            "ats_score_before": float(ats_before.score),
            "ats_score_after": float(ats_after.score),
            "diff_summary": result.diff.get("reasoning", "")[:300],
            "status": "generated",
        }

        index_entry = {
            "id": resume_id,
            "job_id": job_id,
            "job_title": job_title,
            "company": company,
            "created_at": start.isoformat(),
            "ats_score": ats_after.score,
            "files": {k: str(v) for k, v in output_files.items() if v},
        }

        if not dry_run:
            _persist_resume(db_record)
            _update_index(index_entry)

        # 13. Telegram notification
        tg_msg = format_telegram_summary(result.diff, result.keyword_report, job_title, company)
        files_line = "\n".join(
            f"  `{fmt}`: {path.name}"
            for fmt, path in output_files.items()
            if path
        )
        if files_line:
            tg_msg += f"\n\n*Files:*\n{files_line}"

        if not dry_run:
            _send_telegram(tg_msg)

        duration = (datetime.now(timezone.utc) - start).total_seconds()
        log.run_end(run_id, status="ok", duration_seconds=duration,
                    ats_before=ats_before.score, ats_after=ats_after.score)
        return tg_msg

    except Exception as e:
        log.run_error(run_id, error=str(e))
        try:
            with get_conn(get_db_path()) as conn:
                log_health(conn, "resume", "red", str(e)[:200])
        except Exception:
            pass
        return f"🔴 Resume tailoring failed for `{job_id}`: {e}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Resume Tailoring Agent")
    parser.add_argument("--job-id", required=True, help="Job ID from the jobs table")
    parser.add_argument("--dry-run", action="store_true", help="Skip Claude call and file writes")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    result = run(job_id=args.job_id, dry_run=args.dry_run)
    if args.dry_run or args.verbose:
        print("\n--- OUTPUT ---")
        print(result)

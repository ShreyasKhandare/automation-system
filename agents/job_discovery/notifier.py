"""
agents/job_discovery/notifier.py — Telegram digest + full pipeline entry point.

Pipeline:
  1. scrape()         — fetch raw listings from all enabled sources
  2. score_listings() — Claude API 0-10 scoring, filter below threshold
  3. write_jobs_to_sheet() — append new jobs to Google Sheets
  4. persist to SQLite jobs table
  5. send_digest()    — ranked Telegram digest (top jobs)
  6. send_urgent_alert() — immediate alert for score ≥ 9 jobs

Usage:
  python agents/job_discovery/notifier.py              # full run
  python agents/job_discovery/notifier.py --dry-run    # no sends, no DB writes
  python agents/job_discovery/notifier.py --stealth    # lower rate limits
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
from shared.db import get_conn, get_db_path, init_db, upsert_job, log_health
from shared.secrets import get_secret
from shared.config_loader import load_config
from agents.job_discovery.scraper import scrape, JobListing
from agents.job_discovery.scorer import score_listings
from agents.job_discovery.sheet_writer import write_jobs_to_sheet

log = get_logger("job_discovery")


# ---------------------------------------------------------------------------
# Telegram helpers
# ---------------------------------------------------------------------------

def _send_telegram(message: str, disable_preview: bool = True) -> None:
    import requests
    token = get_secret("TELEGRAM_BOT_TOKEN")
    chat_id = get_secret("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    max_len = 4000
    chunks = [message[i:i + max_len] for i in range(0, len(message), max_len)]
    for chunk in chunks:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": disable_preview,
        }, timeout=30)
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# Message formatters
# ---------------------------------------------------------------------------

def _format_digest(listings: list[JobListing], total_scraped: int, dry_run: bool = False) -> str:
    """Format the daily job digest Telegram message."""
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%a %d %b %Y")
    prefix = "🧪 _DRY RUN_ — " if dry_run else ""

    lines = [f"💼 *{prefix}Job Digest — {date_str}*\n"]

    if not listings:
        lines.append("_No new jobs above threshold today._")
        lines.append(f"\n_{total_scraped} listings scanned_")
        return "\n".join(lines)

    # Group into bands
    urgent = [j for j in listings if (j.score or 0) >= 9]
    strong = [j for j in listings if 7 <= (j.score or 0) < 9]
    good   = [j for j in listings if (j.score or 0) < 7]

    cfg = load_config()
    threshold = cfg.job_search_preferences.score_threshold

    if urgent:
        lines.append(f"🔥 *MUST APPLY TODAY ({len(urgent)})*")
        for j in urgent:
            lines.append(_format_job_line(j))
        lines.append("")

    if strong:
        lines.append(f"⭐ *Strong Matches ({len(strong)})*")
        for j in strong[:5]:
            lines.append(_format_job_line(j))
        lines.append("")

    if good:
        lines.append(f"👍 *Good Matches ({len(good)})*")
        for j in good[:3]:
            lines.append(_format_job_line(j))
        lines.append("")

    above = len([j for j in listings if (j.score or 0) >= threshold])
    lines.append(
        f"_{total_scraped} scraped · {above} above threshold · "
        f"{len(urgent)} urgent_"
    )
    lines.append("_Use `RUN RESUME_TAILORING JOB_ID=<id>` to tailor resume_")
    return "\n".join(lines)


def _format_job_line(job: JobListing) -> str:
    score = f"{job.score:.0f}" if job.score is not None else "?"
    salary = ""
    if job.salary_min or job.salary_max:
        lo = f"${job.salary_min // 1000}K" if job.salary_min else ""
        hi = f"${job.salary_max // 1000}K" if job.salary_max else ""
        salary = f" · {lo}–{hi}" if lo and hi else f" · {lo or hi}"
    remote_tag = " 🌐" if job.remote else ""
    reason = job.score_reason[:80] if job.score_reason else ""
    lines = [f"• [{score}/10] *{job.title}* @ {job.company}{remote_tag}{salary}"]
    if reason:
        lines.append(f"  _{reason}_")
    if job.url:
        lines.append(f"  → {job.url}")
    return "\n".join(lines)


def _format_urgent_alert(job: JobListing) -> str:
    return (
        f"🚨 *URGENT JOB MATCH — Score {job.score:.0f}/10*\n\n"
        f"*{job.title}* at *{job.company}*\n"
        f"📍 {job.location} {'🌐' if job.remote else ''}\n"
        f"💰 {f'${job.salary_min // 1000}K–${job.salary_max // 1000}K' if job.salary_min else 'Salary not listed'}\n"
        f"🔧 {', '.join(job.tech_stack[:6]) or 'N/A'}\n\n"
        f"_{job.score_reason[:200]}_\n\n"
        f"→ {job.url}\n\n"
        f"_Tailor resume: `RUN RESUME_TAILORING JOB_ID={job.id}`_"
    )


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------

def _persist_jobs(listings: list[JobListing]) -> None:
    db_path = get_db_path()
    if not Path(str(db_path)).exists():
        init_db(db_path)

    with get_conn(db_path) as conn:
        for job in listings:
            upsert_job(conn, job.to_db_dict())
        log_health(conn, "job_discovery", "green",
                   f"Sweep complete: {len(listings)} jobs above threshold")
    log.info("jobs_persisted", count=len(listings))


# ---------------------------------------------------------------------------
# Public API — used by orchestrator /jobs today command
# ---------------------------------------------------------------------------

def get_today_digest() -> str:
    """Return a cached today-digest from DB. Used by /jobs today command."""
    try:
        with get_conn(get_db_path()) as conn:
            rows = conn.execute(
                """
                SELECT id, title, company, location, remote, score, score_reason, url, salary_min, salary_max
                FROM jobs
                WHERE date(created_at) = date('now')
                ORDER BY score DESC
                LIMIT 10
                """,
            ).fetchall()
        if not rows:
            return "No jobs found today. Try `RUN JOB_SWEEP` to run a sweep."
        lines = [f"💼 *Today's Jobs (cached)*\n"]
        for r in rows:
            score = f"{r['score']:.0f}" if r["score"] else "?"
            remote_tag = " 🌐" if r["remote"] else ""
            lines.append(f"• [{score}/10] *{r['title']}* @ {r['company']}{remote_tag}")
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Could not fetch today's jobs: {e}"


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(stealth: bool = False, dry_run: bool = False) -> str:
    """
    Full job discovery pipeline.
    Returns summary string for Telegram/orchestrator.
    """
    run_id = str(uuid.uuid4())[:8]
    log.run_start(run_id, stealth=stealth, dry_run=dry_run)
    start = datetime.now(timezone.utc)

    try:
        # 1. Scrape
        raw_listings = scrape(stealth=stealth, dry_run=dry_run)
        total_scraped = len(raw_listings)

        if not raw_listings:
            msg = "⚠️ Job Discovery: No listings fetched from any source."
            log.warning("no_listings_scraped")
            return msg

        # 2. Score
        scored = score_listings(raw_listings, dry_run=dry_run)

        # 3. Write to Google Sheets
        write_jobs_to_sheet(scored, dry_run=dry_run)

        # 4. Persist to SQLite
        if not dry_run:
            _persist_jobs(scored)

        # 5. Send urgent alerts first (score ≥ 9, posted < 24h)
        urgent = [j for j in scored if (j.score or 0) >= 9]
        if urgent and not dry_run:
            for job in urgent:
                alert = _format_urgent_alert(job)
                _send_telegram(alert)
                log.info("urgent_alert_sent", job_id=job.id, score=job.score)

        # 6. Send digest
        digest = _format_digest(scored, total_scraped=total_scraped, dry_run=dry_run)
        if not dry_run:
            _send_telegram(digest)
            log.info("digest_sent", jobs=len(scored), urgent=len(urgent))

        duration = (datetime.now(timezone.utc) - start).total_seconds()
        log.run_end(run_id, status="ok", duration_seconds=duration,
                    scraped=total_scraped, scored=len(scored), urgent=len(urgent))
        return digest

    except Exception as e:
        duration = (datetime.now(timezone.utc) - start).total_seconds()
        log.run_error(run_id, error=str(e))
        try:
            db_path = get_db_path()
            if Path(str(db_path)).exists():
                with get_conn(db_path) as conn:
                    log_health(conn, "job_discovery", "red", str(e)[:200])
        except Exception:
            pass
        return f"🔴 Job Discovery failed: {e}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Discovery Agent")
    parser.add_argument("--dry-run", action="store_true", help="Skip sends and DB writes")
    parser.add_argument("--stealth", action="store_true", help="Lower rate limits")
    parser.add_argument("--verbose", action="store_true", help="Print output to stdout")
    args = parser.parse_args()

    result = run(stealth=args.stealth, dry_run=args.dry_run)
    if args.dry_run or args.verbose:
        print("\n--- OUTPUT ---")
        print(result)

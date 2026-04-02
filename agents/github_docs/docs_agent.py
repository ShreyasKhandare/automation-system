"""
agents/github_docs/docs_agent.py — Daily/weekly docs generation and commit.

Daily tasks:
  1. Scan staged files for secrets (commit_scanner)
  2. Commit any new docs/ai_radar/ or docs/reports/ artifacts
  3. Update CHANGELOG.md with today's activity summary

Weekly tasks (Sundays):
  4. Generate docs/reports/week_YYYY_WW.md via Jinja2 template
  5. Update GitHub profile README

Usage:
  python agents/github_docs/docs_agent.py              # full run
  python agents/github_docs/docs_agent.py --dry-run    # no git ops, no GitHub API
  python agents/github_docs/docs_agent.py --weekly     # force weekly tasks
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.db import get_conn, get_db_path, log_health
from shared.config_loader import load_config
from shared.secrets import get_secret
from agents.github_docs.commit_scanner import scan_staged_files, CommitScanViolation
from agents.github_docs.changelog_updater import prepend_entry, build_weekly_bullets
from agents.github_docs.readme_updater import update_profile_readme

log = get_logger("github_docs")

_DOCS_REPORTS_DIR = _REPO_ROOT / "docs" / "reports"
_DOCS_RADAR_DIR   = _REPO_ROOT / "docs" / "ai_radar"


# ---------------------------------------------------------------------------
# Stats collection from DB
# ---------------------------------------------------------------------------

def _collect_weekly_stats() -> dict:
    """Pull this week's stats from SQLite for reports."""
    stats = {
        "jobs_discovered": 0, "jobs_above_threshold": 0, "jobs_applied": 0,
        "score_threshold": 6, "top_score": 0,
        "outreach_drafted": 0, "outreach_sent": 0, "outreach_replied": 0,
        "outreach_pending_followup": 0,
        "resumes_tailored": 0,
        "radar_try_asap": 0, "radar_watch": 0,
        "jobs_discovered_total": 0, "resumes_tailored_total": 0,
    }
    try:
        cfg = load_config()
        stats["score_threshold"] = cfg.job_search_preferences.score_threshold

        with get_conn(get_db_path()) as conn:
            # Jobs
            r = conn.execute(
                "SELECT COUNT(*) c, MAX(score) m FROM jobs WHERE date(created_at) >= date('now','-7 days')"
            ).fetchone()
            stats["jobs_discovered"] = r["c"] or 0
            stats["top_score"] = r["m"] or 0

            r2 = conn.execute(
                "SELECT COUNT(*) c FROM jobs WHERE date(created_at) >= date('now','-7 days') AND score >= ?",
                (stats["score_threshold"],),
            ).fetchone()
            stats["jobs_above_threshold"] = r2["c"] or 0

            r3 = conn.execute("SELECT COUNT(*) c FROM jobs WHERE status = 'applied'").fetchone()
            stats["jobs_applied"] = r3["c"] or 0
            r4 = conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()
            stats["jobs_discovered_total"] = r4["c"] or 0

            # Outreach
            r5 = conn.execute(
                "SELECT "
                "COUNT(*) FILTER (WHERE status='draft') drafted,"
                "COUNT(*) FILTER (WHERE date(sent_at)>=date('now','-7 days')) sent,"
                "COUNT(*) FILTER (WHERE date(reply_at)>=date('now','-7 days')) replied,"
                "COUNT(*) FILTER (WHERE status='pending_approval') pending "
                "FROM outreach"
            ).fetchone()
            stats.update({
                "outreach_drafted": r5["drafted"] or 0,
                "outreach_sent": r5["sent"] or 0,
                "outreach_replied": r5["replied"] or 0,
                "outreach_pending_followup": r5["pending"] or 0,
            })

            # Resumes
            r6 = conn.execute(
                "SELECT COUNT(*) c FROM resumes WHERE date(created_at) >= date('now','-7 days')"
            ).fetchone()
            stats["resumes_tailored"] = r6["c"] or 0
            r7 = conn.execute("SELECT COUNT(*) c FROM resumes").fetchone()
            stats["resumes_tailored_total"] = r7["c"] or 0

            # AI Radar
            r8 = conn.execute(
                "SELECT "
                "COUNT(*) FILTER (WHERE action_tag='TRY_ASAP') try_asap,"
                "COUNT(*) FILTER (WHERE action_tag='WATCH') watch "
                "FROM ai_radar WHERE date(created_at) >= date('now','-7 days')"
            ).fetchone()
            stats["radar_try_asap"] = r8["try_asap"] or 0
            stats["radar_watch"] = r8["watch"] or 0

    except Exception as e:
        log.warning("stats_collection_failed", error=str(e))

    return stats


def _collect_top_jobs(limit: int = 5) -> list[dict]:
    try:
        with get_conn(get_db_path()) as conn:
            rows = conn.execute(
                "SELECT title, company, location, score, source, posted_date FROM jobs "
                "WHERE date(created_at) >= date('now','-7 days') ORDER BY score DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _collect_email_stats() -> dict:
    try:
        with get_conn(get_db_path()) as conn:
            rows = conn.execute(
                "SELECT message, details FROM system_health "
                "WHERE agent_name='email_triage' AND date(checked_at) >= date('now','-7 days') "
                "ORDER BY checked_at DESC LIMIT 20"
            ).fetchall()

        totals: dict[str, int] = {}
        for row in rows:
            if row["details"]:
                d = json.loads(row["details"])
                for lbl, cnt in d.get("by_label", {}).items():
                    totals[lbl] = totals.get(lbl, 0) + cnt
        return totals
    except Exception:
        return {}


def _collect_health_summary() -> dict:
    try:
        with get_conn(get_db_path()) as conn:
            rows = conn.execute(
                "SELECT agent_name, status, message, checked_at FROM system_health "
                "WHERE date(checked_at) >= date('now','-7 days') "
                "ORDER BY checked_at DESC"
            ).fetchall()

        agents_seen: set[str] = set()
        green = yellow = red = 0
        errors = []
        for row in rows:
            if row["agent_name"] not in agents_seen:
                agents_seen.add(row["agent_name"])
                if row["status"] == "green":
                    green += 1
                elif row["status"] == "yellow":
                    yellow += 1
                else:
                    red += 1
                    errors.append({
                        "agent": row["agent_name"],
                        "message": row["message"][:80],
                        "time": row["checked_at"][:16],
                    })
        return {"green": green, "yellow": yellow, "red": red,
                "total": len(agents_seen), "errors": errors[:5]}
    except Exception:
        return {"green": 0, "yellow": 0, "red": 0, "total": 0, "errors": []}


def _collect_recent_resumes() -> list[dict]:
    try:
        with get_conn(get_db_path()) as conn:
            rows = conn.execute(
                "SELECT r.id, r.job_id, r.ats_score_after, j.title, j.company "
                "FROM resumes r LEFT JOIN jobs j ON r.job_id = j.id "
                "WHERE date(r.created_at) >= date('now','-7 days') "
                "ORDER BY r.created_at DESC LIMIT 5"
            ).fetchall()
        return [{"id": r["id"], "job_title": r["title"] or r["job_id"],
                 "company": r["company"] or "?", "ats_score": r["ats_score_after"] or 0}
                for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Weekly report generation (Jinja2)
# ---------------------------------------------------------------------------

def _generate_weekly_report(dry_run: bool = False) -> Path | None:
    try:
        from jinja2 import Template
    except ImportError:
        log.warning("jinja2_not_installed", msg="pip install jinja2")
        return None

    now = datetime.now(timezone.utc)
    week_label = now.strftime("%Y-W%W")
    period_start = (now - __import__("datetime").timedelta(days=7)).strftime("%Y-%m-%d")
    period_end = now.strftime("%Y-%m-%d")

    template_path = Path(__file__).parent / "report_templates" / "weekly_report.md.jinja"
    template = Template(template_path.read_text(encoding="utf-8"))

    stats = _collect_weekly_stats()
    rendered = template.render(
        week_label=week_label,
        generated_at=now.strftime("%Y-%m-%d %H:%M UTC"),
        period_start=period_start,
        period_end=period_end,
        stats=stats,
        top_jobs=_collect_top_jobs(),
        email_stats=_collect_email_stats(),
        resumes=_collect_recent_resumes(),
        health=_collect_health_summary(),
        top_radar_items=[],
    )

    _DOCS_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _DOCS_REPORTS_DIR / f"week_{week_label}.md"

    if not dry_run:
        out_path.write_text(rendered, encoding="utf-8")
        log.info("weekly_report_written", path=str(out_path))

    return out_path


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args, capture_output=True, text=True,
        cwd=str(_REPO_ROOT), check=check,
    )


def _commit_artifacts(message: str) -> bool:
    """Stage docs/ + assets/resumes/index.json and commit."""
    try:
        # Scan for secrets before commit
        scan_staged_files(raise_on_violation=True)
    except CommitScanViolation as e:
        log.error("commit_blocked_by_scanner", error=str(e))
        return False

    _git(["add", "docs/", "assets/resumes/index.json", "CHANGELOG.md"], check=False)

    status = _git(["status", "--porcelain"], check=False)
    if not status.stdout.strip():
        log.info("nothing_to_commit")
        return True

    result = _git(["commit", "-m", message], check=False)
    if result.returncode == 0:
        log.info("committed", message=message[:60])
        return True
    else:
        log.error("commit_failed", stderr=result.stderr[:200])
        return False


def _push() -> bool:
    result = _git(["push"], check=False)
    if result.returncode == 0:
        log.info("pushed")
        return True
    log.error("push_failed", stderr=result.stderr[:200])
    return False


# ---------------------------------------------------------------------------
# Public API for orchestrator
# ---------------------------------------------------------------------------

def get_recent_commits() -> str:
    """Return last 5 commits across tracked repos for /commits command."""
    try:
        result = _git(["log", "--oneline", "-10", "--format=%h %s (%ar)"], check=False)
        lines = result.stdout.strip().splitlines()[:10]
        if not lines:
            return "No commits found."
        return "🔀 *Recent Commits:*\n" + "\n".join(f"• `{l}`" for l in lines)
    except Exception as e:
        return f"⚠️ Could not fetch commits: {e}"


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

def run(dry_run: bool = False, force_weekly: bool = False) -> str:
    run_id = str(uuid.uuid4())[:8]
    log.run_start(run_id, dry_run=dry_run, force_weekly=force_weekly)
    now = datetime.now(timezone.utc)
    is_weekly = force_weekly or now.weekday() == 6  # Sunday

    results = []

    try:
        stats = _collect_weekly_stats()

        # Daily: update CHANGELOG
        bullets = build_weekly_bullets(stats)
        if not dry_run:
            prepend_entry("Daily automation update", bullets, category="chore")
        results.append(f"✅ CHANGELOG updated ({len(bullets)} entries)")

        # Weekly: generate report
        if is_weekly:
            report_path = _generate_weekly_report(dry_run=dry_run)
            if report_path:
                results.append(f"✅ Weekly report: `{report_path.name}`")

            # Update profile README
            success = update_profile_readme(stats, dry_run=dry_run)
            results.append("✅ Profile README updated" if success else "⚠️ Profile README update failed")

        # Commit and push artifacts
        if not dry_run:
            week_label = now.strftime("%Y-W%W")
            msg = f"chore(docs): update {'weekly' if is_weekly else 'daily'} artifacts [{week_label}]"
            committed = _commit_artifacts(msg)
            if committed:
                _push()
                results.append("✅ Artifacts committed and pushed")
            else:
                results.append("⚠️ Nothing new to commit")

        summary = "📚 *GitHub Docs Agent*\n" + "\n".join(results)
        with get_conn(get_db_path()) as conn:
            log_health(conn, "github_docs", "green", f"Docs run complete: {len(results)} tasks")
        log.run_end(run_id, status="ok")
        return summary

    except Exception as e:
        log.run_error(run_id, error=str(e))
        try:
            with get_conn(get_db_path()) as conn:
                log_health(conn, "github_docs", "red", str(e)[:200])
        except Exception:
            pass
        return f"🔴 GitHub Docs agent failed: {e}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GitHub Docs Agent")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--weekly", action="store_true", help="Force weekly tasks")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    result = run(dry_run=args.dry_run, force_weekly=args.weekly)
    if args.dry_run or args.verbose:
        print(result)

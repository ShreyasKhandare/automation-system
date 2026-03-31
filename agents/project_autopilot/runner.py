"""
agents/project_autopilot/runner.py — Main project autopilot pipeline.

Receives a task command, validates constraints, executes via Claude API
code generation, commits changes, runs tests, and creates a PR.

NOTE: In the production setup, task execution can also be delegated to
Claude Code Remote Control (via the Claude app on phone) or Cursor Automations.
This runner handles the GitHub API + git plumbing regardless of execution method.

Usage:
  python agents/project_autopilot/runner.py --repo finops-sentinel --task bugfix --description "fix cold start OOM"
  python agents/project_autopilot/runner.py --status
  python agents/project_autopilot/runner.py --dry-run --repo finops-sentinel --task docs --description "add setup guide"
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.config_loader import load_config
from shared.db import get_conn, get_db_path, log_health
from agents.project_autopilot.constraints import (
    validate_all,
    ConstraintViolation,
    SAFE_TASK_TYPES,
)
from agents.project_autopilot.git_ops import (
    create_feature_branch,
    commit_changes,
    push_branch,
    run_tests,
    create_github_pr,
    count_changed_lines,
    count_changed_files,
    get_current_branch,
)
from agents.project_autopilot.reporter import (
    report_run_start,
    report_run_complete,
    report_constraint_violation,
    report_error,
    log_run_to_db,
    get_recent_runs_summary,
)

log = get_logger("project_autopilot")


def _get_repo_config(repo_name: str) -> Optional[object]:
    """Find repo config by name."""
    cfg = load_config()
    for repo in cfg.project_automation.repos:
        if repo.name == repo_name:
            return repo
    return None


def _generate_code_changes(
    task_type: str,
    description: str,
    repo_path: str,
    tech_stack: list[str],
    dry_run: bool = False,
) -> tuple[bool, str]:
    """
    Use Claude API to generate and apply code changes to the repo.
    Returns (success: bool, summary: str).

    In dry-run mode, returns a placeholder without calling Claude.
    """
    if dry_run:
        return True, f"[DRY RUN] Would apply {task_type} changes: {description[:100]}"

    try:
        import anthropic
        from shared.secrets import get_secret

        # Gather repo context
        import subprocess
        git_status = subprocess.run(
            ["git", "status", "--short"], capture_output=True, text=True, cwd=repo_path
        ).stdout[:500]
        git_log = subprocess.run(
            ["git", "log", "--oneline", "-5"], capture_output=True, text=True, cwd=repo_path
        ).stdout[:300]

        prompt = (
            f"You are a software engineer working on the {Path(repo_path).name} project.\n"
            f"Tech stack: {', '.join(tech_stack)}\n\n"
            f"TASK TYPE: {task_type}\n"
            f"TASK DESCRIPTION: {description}\n\n"
            f"REPO STATE:\n{git_status}\n\nRECENT COMMITS:\n{git_log}\n\n"
            f"Generate a plan for this task. List the files to modify and what changes to make. "
            f"Be concise. Do not generate actual code — a human/Claude Code will apply the changes. "
            f"Focus on what, not how."
        )

        api_key = get_secret("ANTHROPIC_API_KEY")
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        plan = message.content[0].text.strip()
        log.info("task_plan_generated", task_type=task_type, plan_chars=len(plan))
        return True, plan

    except Exception as e:
        log.error("code_generation_failed", error=str(e))
        return False, str(e)


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

def run(
    repo_name: str,
    task_type: str,
    description: str,
    dry_run: bool = False,
) -> str:
    run_id = str(uuid.uuid4())[:8]
    log.run_start(run_id, repo=repo_name, task_type=task_type, dry_run=dry_run)

    # --- Step 1: Load repo config ---
    repo_cfg = _get_repo_config(repo_name)
    if not repo_cfg:
        msg = f"Repo {repo_name!r} not found in config.project_automation.repos"
        log.error("repo_not_found", repo=repo_name)
        return f"🚫 {msg}"

    repo_path = repo_cfg.local_path
    max_lines = repo_cfg.max_lines_changed_per_run

    # --- Step 2: Constraint validation (pre-execution) ---
    try:
        validate_all(
            task_type=task_type,
            task_description=description,
            repo_allowed_tasks=repo_cfg.allowed_tasks,
            target_branch=f"autopilot/{task_type}/preview",  # branch not yet created
            config_max_lines=max_lines,
        )
    except ConstraintViolation as e:
        log.error("constraint_violation", error=str(e))
        report_constraint_violation(repo_name, task_type, str(e))
        log_run_to_db(repo_name, task_type, description, "", "blocked",
                      None, None, 0, 0, 0)
        return f"🚫 Constraint violation: {e}"

    report_run_start(repo_name, task_type, description, dry_run)

    try:
        # --- Step 3: Create feature branch ---
        task_slug = description[:30].replace(" ", "-")
        if not dry_run:
            branch = create_feature_branch(repo_path, task_type, task_slug)
        else:
            branch = f"autopilot/{task_type}/dry-run-{task_slug}"

        # --- Step 4: Generate code changes (plan/apply) ---
        success, plan = _generate_code_changes(
            task_type, description, repo_path,
            tech_stack=repo_cfg.tech_stack,
            dry_run=dry_run,
        )
        if not success:
            report_error(repo_name, task_type, plan)
            return f"🔴 Code generation failed: {plan[:200]}"

        # --- Step 5: Post-change constraint checks ---
        if not dry_run:
            lines_added, lines_removed = count_changed_lines(repo_path)
            files_changed = count_changed_files(repo_path)
            try:
                from agents.project_autopilot.constraints import (
                    assert_lines_within_limit, assert_files_within_limit
                )
                assert_lines_within_limit(lines_added + lines_removed, max_lines)
                assert_files_within_limit(files_changed)
            except ConstraintViolation as e:
                log.error("post_change_constraint_violation", error=str(e))
                report_constraint_violation(repo_name, task_type, str(e))
                return f"🚫 Post-change constraint violation: {e}"
        else:
            lines_added = lines_removed = files_changed = 0

        # --- Step 6: Commit ---
        commit_msg = f"{task_type}({repo_name}): {description[:72]}"
        if not dry_run:
            commit_changes(repo_path, commit_msg)

        # --- Step 7: Run tests ---
        tests_passed = None
        test_output = ""
        if repo_cfg.require_tests and not dry_run:
            tests_passed, test_output = run_tests(repo_path)
            if not tests_passed:
                log.warning("tests_failed_post_commit", repo=repo_name)

        # --- Step 8: Push ---
        if not dry_run:
            push_branch(repo_path, branch)

        # --- Step 9: Create PR ---
        pr_url = None
        if repo_cfg.require_pr:
            pr_body = (
                f"## Summary\n\n**Task:** `{task_type}` — {description}\n\n"
                f"**Plan:**\n{plan[:1000]}\n\n"
                f"**Stats:** +{lines_added}/-{lines_removed} lines, {files_changed} files\n\n"
                f"**Tests:** {'✅ passed' if tests_passed else ('⚠️ failed' if tests_passed is False else 'N/A')}\n\n"
                f"*Auto-generated by project_autopilot agent.*"
            )
            pr_url = create_github_pr(
                repo_full_name=f"ShreyasKhandare/{repo_name}",
                branch=branch,
                title=f"{task_type}: {description[:60]}",
                body=pr_body,
                dry_run=dry_run,
            )

        # --- Step 10: Report + log ---
        report_run_complete(
            repo_name, task_type, description, branch, pr_url, tests_passed,
            lines_added, lines_removed, files_changed, dry_run,
        )
        log_run_to_db(
            repo_name, task_type, description, branch, "completed",
            pr_url, tests_passed, lines_added, lines_removed, files_changed,
        )

        with get_conn(get_db_path()) as conn:
            log_health(conn, "project_autopilot", "green", f"Run complete: {task_type} on {repo_name}")
        log.run_end(run_id, status="ok")

        result_lines = [
            f"✅ *Project Autopilot*",
            f"• Repo: `{repo_name}`",
            f"• Task: `{task_type}`",
            f"• Branch: `{branch}`",
            f"• Changes: +{lines_added}/-{lines_removed} lines",
        ]
        if pr_url:
            result_lines.append(f"• PR: {pr_url}")
        if tests_passed is False:
            result_lines.append("• ⚠️ Tests failed — manual review needed")
        return "\n".join(result_lines)

    except ConstraintViolation as e:
        log.error("runtime_constraint_violation", error=str(e))
        report_constraint_violation(repo_name, task_type, str(e))
        log_run_to_db(repo_name, task_type, description, "", "blocked", None, None, 0, 0, 0)
        return f"🚫 Constraint violation: {e}"

    except Exception as e:
        log.run_error(run_id, error=str(e))
        report_error(repo_name, task_type, str(e))
        try:
            with get_conn(get_db_path()) as conn:
                log_health(conn, "project_autopilot", "red", str(e)[:200])
            log_run_to_db(repo_name, task_type, description, "", "error", None, None, 0, 0, 0)
        except Exception:
            pass
        return f"🔴 Project autopilot failed: {e}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Project Autopilot")
    parser.add_argument("--repo", type=str, help="Repo name (from config)")
    parser.add_argument("--task", type=str, help=f"Task type: {sorted(SAFE_TASK_TYPES)}")
    parser.add_argument("--description", type=str, help="Task description")
    parser.add_argument("--status", action="store_true", help="Show recent runs")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.status:
        print(get_recent_runs_summary())
        sys.exit(0)

    if not args.repo or not args.task or not args.description:
        parser.error("--repo, --task, and --description are required")

    result = run(
        repo_name=args.repo,
        task_type=args.task,
        description=args.description,
        dry_run=args.dry_run,
    )
    if args.dry_run or args.verbose:
        print(result)

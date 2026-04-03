"""
agents/project_autopilot/runner.py — Execute bounded coding tasks on repos.

Entry point for START PROJECT command:
  run(repo_name="finops-sentinel", task_type="bugfix", description="fix cold start OOM")

Pipeline:
  1. Validate task_type is in allowed_tasks for that repo (constraints.py)
  2. Validate no forbidden actions
  3. Create feature branch
  4. Use Claude API to plan the changes
  5. Run tests if required
  6. Create PR if required
  7. Report to Telegram
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.db import get_conn, get_db_path, log_health
from shared.config_loader import load_config

log = get_logger("project_autopilot")


def _generate_run_id(repo_name: str, task_type: str) -> str:
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_repo = repo_name.replace("-", "_")
    return f"run_{now}_{safe_repo}_{task_type}"


def _save_run(run_id: str, data: dict) -> None:
    """Save or update a project run record in SQLite."""
    try:
        with get_conn(get_db_path()) as conn:
            existing = conn.execute(
                "SELECT id FROM project_runs WHERE id = ?", (run_id,)
            ).fetchone()

            if existing:
                set_clauses = ", ".join(f"{k} = ?" for k in data if k != "id")
                values = [v for k, v in data.items() if k != "id"] + [run_id]
                conn.execute(f"UPDATE project_runs SET {set_clauses} WHERE id = ?", values)
            else:
                cols = ", ".join(data.keys())
                placeholders = ", ".join(["?"] * len(data))
                conn.execute(f"INSERT INTO project_runs ({cols}) VALUES ({placeholders})", list(data.values()))
    except Exception as e:
        log.error("save_run_failed", error=str(e))


def _plan_with_claude(repo_path: Path, task_type: str, description: str, tech_stack: list[str]) -> dict[str, Any]:
    """Use Claude to plan what changes to make."""
    try:
        import anthropic
        from shared.secrets import get_secret

        client = anthropic.Anthropic(api_key=get_secret("ANTHROPIC_API_KEY"))

        # Get recent repo context
        import subprocess
        git_log = subprocess.run(
            ["git", "log", "--oneline", "-10"],
            capture_output=True, text=True, cwd=str(repo_path),
        ).stdout[:500]

        prompt = f"""You are helping plan a {task_type} task for a software project.

Repo: {repo_path.name}
Tech stack: {', '.join(tech_stack)}
Task type: {task_type}
Description: {description}

Recent commits:
{git_log}

Provide a concrete implementation plan as JSON:
{{
  "summary": "What you'll do in 1-2 sentences",
  "steps": ["step 1", "step 2", "..."],
  "files_to_modify": ["file1.py", "file2.py"],
  "estimated_lines_changed": 50,
  "risks": ["any risks or dependencies to watch for"],
  "commit_message": "feat/fix/chore: concise message"
}}

Keep steps_to_modify under 10 files and estimated_lines_changed realistic."""

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()

        return json.loads(raw)

    except Exception as e:
        log.error("claude_plan_failed", error=str(e))
        return {
            "summary": description,
            "steps": [description],
            "files_to_modify": [],
            "estimated_lines_changed": 0,
            "risks": [],
            "commit_message": f"{task_type}: {description[:50]}",
        }


def run(
    repo_name: str,
    task_type: str,
    description: str,
    dry_run: bool = False,
) -> str:
    """
    Execute a bounded coding task on a repository.

    Args:
        repo_name: Repository name (must match config).
        task_type: Task type (must be in repo's allowed_tasks).
        description: Human description of what to do.
        dry_run: Plan only — no code changes.

    Returns:
        Summary string for Telegram.
    """
    log.info("project_run_start", repo=repo_name, task=task_type, dry_run=dry_run)
    cfg = load_config()
    start_time = datetime.now(timezone.utc)

    run_id = _generate_run_id(repo_name, task_type)

    # --- Step 1: Validate task type (raises ValueError if invalid) ---
    from agents.project_autopilot.constraints import validate_task_type, get_repo_config, check_forbidden_action

    try:
        validate_task_type(repo_name, task_type)
    except ValueError as e:
        return f"❌ Validation failed: {e}"

    # Check description for forbidden actions
    try:
        check_forbidden_action(description)
    except ValueError as e:
        return f"❌ Forbidden action in description: {e}"

    repo_config = get_repo_config(repo_name)
    if not repo_config:
        return f"❌ Repo '{repo_name}' not found in config."

    # Save initial run record
    _save_run(run_id, {
        "id": run_id,
        "repo_name": repo_name,
        "task_type": task_type,
        "description": description,
        "status": "running",
        "triggered_by": "telegram",
        "started_at": start_time.isoformat(),
        "created_at": start_time.isoformat(),
    })

    # --- Step 2: Get repo path ---
    repo_path = Path(repo_config.local_path)
    if not repo_path.exists():
        msg = f"❌ Repo path not found: {repo_config.local_path}"
        _save_run(run_id, {"status": "failed", "error_message": msg})
        return msg

    # --- Step 3: Plan with Claude ---
    plan = _plan_with_claude(repo_path, task_type, description, repo_config.tech_stack)

    if dry_run:
        plan_text = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(plan.get("steps", [])))
        return (
            f"🗺 *Project Plan (dry run)*\n\n"
            f"*Repo:* {repo_name}\n"
            f"*Task:* {task_type}\n"
            f"*Summary:* {plan.get('summary', '')}\n\n"
            f"*Steps:*\n{plan_text}\n"
            f"*Estimated lines:* {plan.get('estimated_lines_changed', '?')}\n"
            f"*Files:* {', '.join(plan.get('files_to_modify', []))}"
        )

    # --- Step 4: Create feature branch ---
    from agents.project_autopilot.git_ops import create_branch, run_tests, get_diff_stats, push_branch, create_pr

    branch_name = f"autopilot/{task_type}/{datetime.now().strftime('%Y%m%d%H%M%S')}"
    branch_created = create_branch(repo_path, branch_name)
    if not branch_created:
        log.warning("branch_create_failed", branch=branch_name)

    _save_run(run_id, {"branch_name": branch_name})

    # --- Step 5: Note — actual code changes require human review ---
    # The autopilot plans and creates the PR branch but doesn't auto-edit files
    # Changes are described in the PR for human review
    commit_msg = plan.get("commit_message", f"{task_type}: {description[:50]}")
    diff_stats = get_diff_stats(repo_path)

    # --- Step 6: Run tests if required ---
    test_result = None
    if repo_config.require_tests:
        test_result = run_tests(repo_path)
        if not test_result["passed"]:
            log.warning("tests_failed", output=test_result["output"][:200])

    # --- Step 7: Create PR if required ---
    pr_url = None
    if repo_config.require_pr:
        pr_body = (
            f"## Automated Task: {task_type}\n\n"
            f"**Description:** {description}\n\n"
            f"**Plan:**\n" +
            "\n".join(f"- {s}" for s in plan.get("steps", [])) +
            f"\n\n**Estimated scope:** {plan.get('estimated_lines_changed', '?')} lines\n"
            f"**Files to modify:** {', '.join(plan.get('files_to_modify', []))}\n\n"
            f"**Risks:** {', '.join(plan.get('risks', ['None identified']))}\n\n"
            f"_Generated by Project Autopilot — Review before merging_"
        )
        pr_url = create_pr(repo_path, title=f"[autopilot] {commit_msg}", body=pr_body, branch=branch_name)

    # --- Step 8: Update run record ---
    duration = (datetime.now(timezone.utc) - start_time).total_seconds()
    _save_run(run_id, {
        "status": "completed",
        "pr_url": pr_url or "",
        "lines_changed": diff_stats["lines_changed"],
        "files_changed": json.dumps(diff_stats["files_changed"]),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": int(duration),
    })

    # --- Step 9: Log health and report ---
    with get_conn(get_db_path()) as conn:
        log_health(conn, "project_autopilot", "green", f"Run {run_id} complete", {
            "run_id": run_id, "duration": duration
        })

    from agents.project_autopilot.reporter import report_run
    run_record = {
        "status": "completed",
        "repo_name": repo_name,
        "task_type": task_type,
        "description": description,
        "pr_url": pr_url or "",
        "lines_changed": diff_stats["lines_changed"],
        "error_message": "",
        "duration_seconds": duration,
    }
    return report_run(run_record)

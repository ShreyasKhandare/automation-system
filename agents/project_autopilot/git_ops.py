"""
agents/project_autopilot/git_ops.py — Git branch management and GitHub PR creation.

Uses subprocess git commands for local operations and the GitHub API for PR creation.
All operations are validated against constraints.py before execution.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from agents.project_autopilot.constraints import (
    assert_branch_not_protected,
    assert_no_forbidden_action,
    ConstraintViolation,
)

log = get_logger("project_autopilot")


def _git(args: list[str], cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args, capture_output=True, text=True, cwd=cwd, check=False,
    )


def create_feature_branch(repo_path: str, task_type: str, task_slug: str) -> str:
    """
    Create and checkout a new feature branch. Returns the branch name.
    Branch name format: autopilot/{task_type}/{YYYYMMDD-task_slug}
    """
    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    slug = task_slug.lower().replace(" ", "-").replace("_", "-")[:30]
    branch_name = f"autopilot/{task_type}/{date_tag}-{slug}"

    # Verify not protected (shouldn't happen with this naming scheme but check anyway)
    assert_branch_not_protected(branch_name)

    # Fetch latest
    _git(["fetch", "origin"], cwd=repo_path, check=False)

    # Create branch from origin/main (or master)
    result = _git(["checkout", "-b", branch_name, "origin/main"], cwd=repo_path)
    if result.returncode != 0:
        # Try master
        result = _git(["checkout", "-b", branch_name, "origin/master"], cwd=repo_path)
    if result.returncode != 0:
        # Fall back to local HEAD
        result = _git(["checkout", "-b", branch_name], cwd=repo_path)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create branch {branch_name}: {result.stderr[:200]}")

    log.info("branch_created", branch=branch_name, repo=repo_path)
    return branch_name


def get_current_branch(repo_path: str) -> str:
    result = _git(["branch", "--show-current"], cwd=repo_path)
    return result.stdout.strip()


def count_changed_lines(repo_path: str) -> tuple[int, int]:
    """Return (lines_added, lines_removed) since last commit."""
    result = _git(["diff", "--stat", "HEAD"], cwd=repo_path, check=False)
    # Parse: "N insertions(+), M deletions(-)"
    import re
    text = result.stdout
    added = sum(int(m) for m in re.findall(r"(\d+) insertion", text))
    removed = sum(int(m) for m in re.findall(r"(\d+) deletion", text))
    return added, removed


def count_changed_files(repo_path: str) -> int:
    """Count files changed since last commit."""
    result = _git(["diff", "--name-only", "HEAD"], cwd=repo_path, check=False)
    files = [f for f in result.stdout.strip().splitlines() if f]
    return len(files)


def commit_changes(repo_path: str, message: str) -> bool:
    """
    Stage all changes and commit. Validates message for forbidden actions first.
    Returns True on success.
    """
    assert_no_forbidden_action(message)

    _git(["add", "-A"], cwd=repo_path, check=False)
    result = _git(["commit", "-m", message], cwd=repo_path)
    if result.returncode == 0:
        log.info("committed", message=message[:60], repo=repo_path)
        return True
    elif "nothing to commit" in result.stdout.lower() + result.stderr.lower():
        log.info("nothing_to_commit", repo=repo_path)
        return True
    else:
        log.error("commit_failed", stderr=result.stderr[:200])
        return False


def push_branch(repo_path: str, branch: str) -> bool:
    """Push a feature branch to origin. Never pushes to protected branches."""
    assert_branch_not_protected(branch)
    result = _git(["push", "-u", "origin", branch], cwd=repo_path)
    if result.returncode == 0:
        log.info("pushed", branch=branch)
        return True
    log.error("push_failed", branch=branch, stderr=result.stderr[:200])
    return False


def run_tests(repo_path: str, test_command: str = "pytest") -> tuple[bool, str]:
    """
    Run tests. Returns (passed: bool, output: str).
    test_command defaults to 'pytest' but can be overridden.
    """
    assert_no_forbidden_action(test_command)
    try:
        result = subprocess.run(
            test_command.split(),
            capture_output=True, text=True, cwd=repo_path, timeout=300,
        )
        passed = result.returncode == 0
        output = (result.stdout + result.stderr)[-2000:]  # last 2000 chars
        log.info("tests_run", passed=passed, repo=repo_path)
        return passed, output
    except subprocess.TimeoutExpired:
        log.error("tests_timed_out", repo=repo_path)
        return False, "Tests timed out after 300 seconds."
    except Exception as e:
        log.error("tests_failed", error=str(e))
        return False, str(e)


def create_github_pr(
    repo_full_name: str,
    branch: str,
    title: str,
    body: str,
    base: str = "main",
    dry_run: bool = False,
) -> Optional[str]:
    """
    Create a GitHub PR via the GitHub API. Returns PR URL or None.
    repo_full_name: e.g. "ShreyasKhandare/finops-sentinel"
    """
    assert_branch_not_protected(branch)
    assert_no_forbidden_action(title)

    if dry_run:
        log.info("pr_create_dry_run", repo=repo_full_name, branch=branch, title=title[:60])
        return f"https://github.com/{repo_full_name}/pull/DRY_RUN"

    try:
        import requests
        from shared.secrets import get_secret

        token = get_secret("GITHUB_TOKEN")
        api_url = f"https://api.github.com/repos/{repo_full_name}/pulls"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        payload = {
            "title": title,
            "body": body,
            "head": branch,
            "base": base,
        }
        resp = requests.post(api_url, headers=headers, json=payload, timeout=15)
        if resp.ok:
            pr_url = resp.json().get("html_url", "")
            log.info("pr_created", url=pr_url)
            return pr_url
        else:
            log.error("pr_create_failed", status=resp.status_code, body=resp.text[:300])
            return None
    except Exception as e:
        log.error("pr_create_error", error=str(e))
        return None

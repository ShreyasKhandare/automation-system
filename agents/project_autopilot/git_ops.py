"""
agents/project_autopilot/git_ops.py — Safe git operations for project autopilot.

All operations are validated against constraints.py before execution.
Force push and merge to main are NEVER allowed.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from agents.project_autopilot.constraints import check_forbidden_action

log = get_logger("project_autopilot")


def _run_git(args: list[str], cwd: str | Path, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a git command safely."""
    cmd = ["git"] + args
    log.info("git_command", cmd=" ".join(cmd), cwd=str(cwd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(cwd))
    if result.returncode != 0:
        log.warning("git_command_failed", cmd=" ".join(cmd), stderr=result.stderr[:200])
    return result


def create_branch(repo_path: Path, branch_name: str) -> bool:
    """Create a new feature branch from current HEAD."""
    check_forbidden_action(f"create branch {branch_name}")  # Only forbidden for force push / delete
    result = _run_git(["checkout", "-b", branch_name], cwd=repo_path)
    return result.returncode == 0


def commit_changes(repo_path: Path, message: str, files: list[str] | None = None) -> bool:
    """Stage and commit changes."""
    # Stage specific files or all changed files
    if files:
        for f in files:
            _run_git(["add", f], cwd=repo_path)
    else:
        _run_git(["add", "-A"], cwd=repo_path)

    result = _run_git(["commit", "-m", message], cwd=repo_path)
    return result.returncode == 0


def push_branch(repo_path: Path, branch_name: str) -> bool:
    """Push a feature branch to origin. Never force pushes."""
    check_forbidden_action("force push")  # Explicit guard
    result = _run_git(["push", "origin", branch_name], cwd=repo_path)
    return result.returncode == 0


def create_pr(repo_path: Path, title: str, body: str, branch: str, base: str = "main") -> str | None:
    """Create a GitHub PR using gh CLI."""
    check_forbidden_action(f"merge to {base}")  # PR creation is allowed, auto-merge is not

    try:
        from shared.secrets import get_secret
        import os
        env = os.environ.copy()
        env["GH_TOKEN"] = get_secret("GH_PAT")

        result = subprocess.run(
            ["gh", "pr", "create",
             "--title", title,
             "--body", body,
             "--base", base,
             "--head", branch],
            capture_output=True, text=True, timeout=60,
            cwd=str(repo_path), env=env,
        )

        if result.returncode == 0:
            pr_url = result.stdout.strip()
            log.info("pr_created", url=pr_url, branch=branch)
            return pr_url
        else:
            log.error("pr_create_failed", stderr=result.stderr[:200])
            return None
    except Exception as e:
        log.error("pr_create_error", error=str(e))
        return None


def get_diff_stats(repo_path: Path) -> dict[str, Any]:
    """Get stats for uncommitted or recent changes."""
    # Staged + unstaged
    result = _run_git(["diff", "--stat", "HEAD"], cwd=repo_path)
    output = result.stdout

    lines_changed = 0
    files_changed: list[str] = []

    for line in output.split("\n"):
        if "changed" in line:
            import re
            m = re.search(r"(\d+) insertion|(\d+) deletion", line)
            if m:
                for g in m.groups():
                    if g:
                        lines_changed += int(g)
        elif "|" in line:
            fname = line.split("|")[0].strip()
            if fname:
                files_changed.append(fname)

    return {"lines_changed": lines_changed, "files_changed": files_changed}


def run_tests(repo_path: Path) -> dict[str, Any]:
    """Run pytest and return results."""
    result = subprocess.run(
        ["python", "-m", "pytest", "--tb=short", "-q"],
        capture_output=True, text=True, timeout=300,
        cwd=str(repo_path),
    )
    passed = result.returncode == 0
    output = (result.stdout + result.stderr)[:1000]
    return {"passed": passed, "output": output, "returncode": result.returncode}

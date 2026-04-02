"""
agents/project_autopilot/constraints.py — Hard safety constraints for project autopilot.

All FORBIDDEN_ACTIONS are hard raises, not warnings.
These constraints can NEVER be bypassed via config or CLI flags.
"""

from __future__ import annotations

import re

# Task types allowed at all (must also be in repo's allowed_tasks config list)
SAFE_TASK_TYPES = frozenset([
    "bugfix", "docs", "small_feature", "refactor", "test", "content_update",
])

# Hard ceiling on files touched per run (regardless of config)
MAX_FILES_TOUCHED = 10

# Hard ceiling on lines changed — final value is min(this, config value)
ABSOLUTE_MAX_LINES_CHANGED = 500

# These strings (case-insensitive) are forbidden in task descriptions and commands
FORBIDDEN_ACTIONS = [
    "delete branch",
    "force push",
    "force-push",
    "merge to main",
    "merge to master",
    "drop table",
    "drop database",
    "rm -rf",
    "truncate table",
    "delete all",
    "wipe",
    "reset --hard",
    "push --force",
    "push -f",
    "--no-verify",
]

# Branches that can never be the target of direct commits
PROTECTED_BRANCHES = frozenset(["main", "master", "production", "prod", "release"])


class ConstraintViolation(Exception):
    """Raised when any hard safety constraint is violated."""


def assert_task_type_allowed(task_type: str, repo_allowed_tasks: list[str]) -> None:
    """
    Raise ConstraintViolation if task_type is not safe or not allowed for this repo.
    """
    if task_type not in SAFE_TASK_TYPES:
        raise ConstraintViolation(
            f"Task type {task_type!r} is not in SAFE_TASK_TYPES. "
            f"Allowed: {sorted(SAFE_TASK_TYPES)}"
        )
    if task_type not in repo_allowed_tasks:
        raise ConstraintViolation(
            f"Task type {task_type!r} is not in repo's allowed_tasks: {repo_allowed_tasks}"
        )


def assert_no_forbidden_action(text: str) -> None:
    """
    Raise ConstraintViolation if text contains any FORBIDDEN_ACTIONS substring.
    Checks task descriptions, commit messages, branch names, and any generated commands.
    """
    text_lower = text.lower()
    for forbidden in FORBIDDEN_ACTIONS:
        if forbidden.lower() in text_lower:
            raise ConstraintViolation(
                f"Forbidden action detected in text: {forbidden!r}\n"
                f"Full text (first 200 chars): {text[:200]}"
            )


def assert_branch_not_protected(branch: str) -> None:
    """Raise ConstraintViolation if attempting to commit directly to a protected branch."""
    branch_clean = branch.strip().lstrip("refs/heads/")
    if branch_clean in PROTECTED_BRANCHES:
        raise ConstraintViolation(
            f"Cannot commit directly to protected branch {branch!r}. "
            f"Create a feature branch instead."
        )


def assert_lines_within_limit(lines_changed: int, config_max: int) -> None:
    """Raise ConstraintViolation if lines changed exceeds both config and absolute limits."""
    effective_max = min(config_max, ABSOLUTE_MAX_LINES_CHANGED)
    if lines_changed > effective_max:
        raise ConstraintViolation(
            f"Lines changed ({lines_changed}) exceeds limit ({effective_max}). "
            f"Break this task into smaller chunks."
        )


def assert_files_within_limit(files_touched: int) -> None:
    """Raise ConstraintViolation if too many files are touched."""
    if files_touched > MAX_FILES_TOUCHED:
        raise ConstraintViolation(
            f"Files touched ({files_touched}) exceeds MAX_FILES_TOUCHED ({MAX_FILES_TOUCHED}). "
            f"Break this into smaller tasks."
        )


def validate_all(
    task_type: str,
    task_description: str,
    repo_allowed_tasks: list[str],
    target_branch: str,
    lines_changed: int = 0,
    files_touched: int = 0,
    config_max_lines: int = ABSOLUTE_MAX_LINES_CHANGED,
) -> None:
    """
    Run all constraint checks in sequence. First violation raises immediately.
    Call this before any code execution.
    """
    assert_task_type_allowed(task_type, repo_allowed_tasks)
    assert_no_forbidden_action(task_description)
    assert_branch_not_protected(target_branch)
    if lines_changed > 0:
        assert_lines_within_limit(lines_changed, config_max_lines)
    if files_touched > 0:
        assert_files_within_limit(files_touched)

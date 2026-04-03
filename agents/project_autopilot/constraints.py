"""
agents/project_autopilot/constraints.py — Safety constraints for project autopilot.

FORBIDDEN_ACTIONS are hard raises, not warnings.
Validates task types against repo allowed_tasks.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.config_loader import load_config

log = get_logger("project_autopilot")

# From SYSTEM_DESIGN.md Section 6
SAFE_TASK_TYPES = ["bugfix", "docs", "small_feature", "refactor", "test", "content_update"]
MAX_FILES_TOUCHED = 10

# These are HARD RAISES — never warnings
FORBIDDEN_ACTIONS = ["delete branch", "force push", "merge to main", "drop table"]


def check_forbidden_action(action: str) -> None:
    """
    Check if an action is forbidden. Raises ValueError immediately — never just a warning.

    Args:
        action: Action description string.

    Raises:
        ValueError: If the action is in FORBIDDEN_ACTIONS.
    """
    action_lower = action.lower()
    for forbidden in FORBIDDEN_ACTIONS:
        if forbidden in action_lower:
            msg = (
                f"FORBIDDEN ACTION BLOCKED: '{action}'\n"
                f"Matches forbidden pattern: '{forbidden}'\n"
                f"This action can never be performed by the autopilot."
            )
            log.error("forbidden_action_blocked", action=action, pattern=forbidden)
            raise ValueError(msg)


def validate_task_type(repo_name: str, task_type: str) -> None:
    """
    Validate that task_type is allowed for the given repo.

    Args:
        repo_name: Repository name from config.
        task_type: Task type string.

    Raises:
        ValueError: If task_type is not allowed.
    """
    cfg = load_config()

    # Find repo config
    repo_config = None
    for repo in cfg.project_automation.repos:
        if repo.name == repo_name:
            repo_config = repo
            break

    if not repo_config:
        raise ValueError(
            f"Repository '{repo_name}' is not in the allowed repos list.\n"
            f"Allowed repos: {[r.name for r in cfg.project_automation.repos]}"
        )

    allowed_tasks = repo_config.allowed_tasks
    if task_type not in allowed_tasks:
        raise ValueError(
            f"Task type '{task_type}' is not allowed for repo '{repo_name}'.\n"
            f"Allowed task types: {allowed_tasks}"
        )

    if task_type not in SAFE_TASK_TYPES:
        raise ValueError(
            f"Task type '{task_type}' is not in the global safe task list.\n"
            f"Safe task types: {SAFE_TASK_TYPES}"
        )

    log.info("task_validated", repo=repo_name, task_type=task_type)


def validate_change_size(lines_changed: int, repo_name: str) -> None:
    """
    Validate that change size is within repo limits.

    Raises:
        ValueError: If change exceeds limit.
    """
    cfg = load_config()

    for repo in cfg.project_automation.repos:
        if repo.name == repo_name:
            max_lines = repo.max_lines_changed_per_run
            if lines_changed > max_lines:
                raise ValueError(
                    f"Change size {lines_changed} lines exceeds limit of {max_lines} for '{repo_name}'."
                )
            return


def get_repo_config(repo_name: str) -> Any | None:
    """Get the config object for a specific repo."""
    cfg = load_config()
    for repo in cfg.project_automation.repos:
        if repo.name == repo_name:
            return repo
    return None

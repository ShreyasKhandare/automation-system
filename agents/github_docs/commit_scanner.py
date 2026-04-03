"""
agents/github_docs/commit_scanner.py — Scan commits for forbidden patterns.

FORBIDDEN_PATTERNS from SYSTEM_DESIGN.md Section 10 are checked before any commit.
Raises if secrets or personal data are found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger

log = get_logger("github_docs")

# From SYSTEM_DESIGN.md Section 10
FORBIDDEN_PATTERNS: list[re.Pattern] = [
    re.compile(r"sk-ant-[A-Za-z0-9\-_]+"),           # Anthropic API keys
    re.compile(r"AIza[A-Za-z0-9_\-]{35}"),            # Google API keys
    re.compile(r"Bearer [A-Za-z0-9_\-]{20,}"),        # Auth tokens
    re.compile(r"ghp_[A-Za-z0-9]{36,}"),              # GitHub personal access tokens
    re.compile(r"gho_[A-Za-z0-9]{36,}"),              # GitHub OAuth tokens
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),  # Email addresses
    re.compile(r"(?i)api[_\-]?key\s*=\s*['\"][A-Za-z0-9_\-]{10,}['\"]"),  # Generic API keys
    re.compile(r"(?i)password\s*=\s*['\"].+['\"]"),   # Passwords in code
    re.compile(r"(?i)secret\s*=\s*['\"][A-Za-z0-9_\-]{8,}['\"]"),  # Secrets
    re.compile(r"APOLLO_API_KEY\s*=\s*[A-Za-z0-9_\-]+"),   # Apollo key
    re.compile(r"HUNTER_API_KEY\s*=\s*[A-Za-z0-9_\-]+"),   # Hunter key
]

# File patterns that should never be committed
FORBIDDEN_FILES = [
    ".env",
    "*.key",
    "*secret*",
    "*password*",
    "*token*",
    "automation.sqlite",
    "*.sqlite",
]


def scan_content(content: str, source: str = "unknown") -> list[str]:
    """
    Scan text content for forbidden patterns.

    Args:
        content: Text to scan.
        source: Identifier for logging (e.g., filename).

    Returns:
        List of violation descriptions (empty = clean).
    """
    violations = []
    for pattern in FORBIDDEN_PATTERNS:
        matches = pattern.findall(content)
        if matches:
            # Redact the actual match in the violation message
            violations.append(
                f"FORBIDDEN PATTERN '{pattern.pattern[:40]}...' found in {source} "
                f"({len(matches)} match(es))"
            )
    return violations


def scan_file(file_path: Path) -> list[str]:
    """Scan a single file for forbidden patterns."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        return scan_content(content, source=str(file_path))
    except Exception as e:
        log.warning("scan_file_error", path=str(file_path), error=str(e))
        return []


def scan_diff(diff_text: str) -> list[str]:
    """Scan a git diff for forbidden patterns."""
    # Only scan added lines (starting with +)
    added_lines = "\n".join(
        line[1:] for line in diff_text.split("\n")
        if line.startswith("+") and not line.startswith("+++")
    )
    return scan_content(added_lines, source="git diff")


def is_forbidden_filename(filename: str) -> bool:
    """Check if a filename matches any forbidden file pattern."""
    import fnmatch
    name = Path(filename).name
    for pattern in FORBIDDEN_FILES:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def validate_before_commit(files: list[Path]) -> None:
    """
    Validate a list of files before committing. Raises if violations found.

    Args:
        files: List of file paths to check.

    Raises:
        ValueError: If any forbidden patterns or filenames are found.
    """
    all_violations = []

    for f in files:
        if is_forbidden_filename(str(f)):
            all_violations.append(f"FORBIDDEN FILE: {f.name} must never be committed")
            continue
        violations = scan_file(f)
        all_violations.extend(violations)

    if all_violations:
        violation_text = "\n".join(all_violations)
        log.error("commit_blocked", violations=len(all_violations))
        raise ValueError(
            f"Pre-commit scan FAILED — {len(all_violations)} violation(s):\n{violation_text}"
        )

    log.info("commit_scan_passed", files=len(files))


def get_recent_commits_text(repo_path: Path, limit: int = 20) -> str:
    """
    Get recent commit messages from a git repo as plain text.

    Args:
        repo_path: Path to the git repository.
        limit: Number of commits to fetch.

    Returns:
        Formatted commit history string.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={limit}", "--format=%H|%s|%an|%ci", "--no-merges"],
            capture_output=True, text=True, timeout=30,
            cwd=str(repo_path),
        )
        if result.returncode != 0:
            return ""

        lines = []
        for line in result.stdout.strip().split("\n"):
            if "|" in line:
                parts = line.split("|", 3)
                if len(parts) >= 2:
                    sha = parts[0][:7]
                    msg = parts[1]
                    lines.append(f"{sha}: {msg}")
        return "\n".join(lines)
    except Exception as e:
        log.warning("git_log_failed", error=str(e))
        return ""

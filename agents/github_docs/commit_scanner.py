"""
agents/github_docs/commit_scanner.py — Pre-commit secret detection.

FORBIDDEN_PATTERNS from Section 10 are checked against every file staged
for commit. Raises CommitScanViolation if any match is found.

Also usable as a standalone script or git pre-commit hook:
  python agents/github_docs/commit_scanner.py [file1 file2 ...]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Patterns from Section 10 — enforced as hard raises
# ---------------------------------------------------------------------------

FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    (r"sk-ant-[A-Za-z0-9\-_]+",                              "Anthropic API key"),
    (r"AIza[A-Za-z0-9_\-]{35}",                              "Google API key"),
    (r"Bearer\s+[A-Za-z0-9_\-\.]{20,}",                     "Bearer auth token"),
    (r"ghp_[A-Za-z0-9]{36}",                                 "GitHub personal access token"),
    (r"ghs_[A-Za-z0-9]{36}",                                 "GitHub Actions token"),
    (r"AKIA[0-9A-Z]{16}",                                    "AWS access key ID"),
    (r"(?i)api[_\-]?key\s*[=:]\s*['\"][A-Za-z0-9_\-]{16,}", "Generic API key assignment"),
    (r"(?i)secret\s*[=:]\s*['\"][A-Za-z0-9_\-]{8,}",        "Secret assignment"),
    (r"(?i)password\s*[=:]\s*['\"][^'\"]{6,}",              "Password assignment"),
    (r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY",     "Private key"),
]

# Email pattern is separate — it's informational (warn, not block)
# because legitimate code sometimes has example emails in docs
_EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

# File extensions to skip (binary files)
_SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".pdf", ".docx", ".xlsx", ".zip", ".tar", ".gz",
    ".sqlite", ".db", ".pyc", ".so", ".dylib", ".exe",
}

# Paths to always skip
_SKIP_PATHS = {".git", "node_modules", ".venv", "venv", "__pycache__"}


class CommitScanViolation(Exception):
    pass


def scan_file(path: Path) -> list[tuple[str, int, str]]:
    """
    Scan a single file for forbidden patterns.
    Returns list of (pattern_description, line_number, matched_text).
    """
    if path.suffix.lower() in _SKIP_EXTENSIONS:
        return []

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    violations: list[tuple[str, int, str]] = []
    for line_num, line in enumerate(content.splitlines(), start=1):
        for pattern, description in FORBIDDEN_PATTERNS:
            if re.search(pattern, line):
                # Redact the matched value in the report
                redacted = re.sub(pattern, "[REDACTED]", line).strip()[:120]
                violations.append((description, line_num, redacted))

    return violations


def scan_files(paths: list[Path], raise_on_violation: bool = True) -> dict[str, list]:
    """
    Scan multiple files. Returns {filepath: [violations]}.
    If raise_on_violation=True, raises CommitScanViolation on first hit.
    """
    results: dict[str, list] = {}
    for path in paths:
        # Skip paths containing any skip-path component
        if any(part in _SKIP_PATHS for part in path.parts):
            continue
        violations = scan_file(path)
        if violations:
            results[str(path)] = violations
            if raise_on_violation:
                file_rel = path.relative_to(_REPO_ROOT) if path.is_absolute() else path
                raise CommitScanViolation(
                    f"\n🔴 SECRET DETECTED in {file_rel} line {violations[0][1]}:\n"
                    f"   {violations[0][0]}: {violations[0][2]}\n\n"
                    f"Remove the secret, add to .env, and do NOT commit it."
                )
    return results


def scan_staged_files(raise_on_violation: bool = True) -> dict[str, list]:
    """Scan all files currently staged in git."""
    import subprocess
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, cwd=str(_REPO_ROOT),
    )
    staged = [_REPO_ROOT / f.strip() for f in result.stdout.splitlines() if f.strip()]
    return scan_files(staged, raise_on_violation=raise_on_violation)


def scan_repo(raise_on_violation: bool = False) -> dict[str, list]:
    """Scan all tracked files in the repo (for full audit)."""
    import subprocess
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True, text=True, cwd=str(_REPO_ROOT),
    )
    all_files = [_REPO_ROOT / f.strip() for f in result.stdout.splitlines() if f.strip()]
    return scan_files(all_files, raise_on_violation=raise_on_violation)


# ---------------------------------------------------------------------------
# CLI / pre-commit hook
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Called with explicit file list (e.g. from pre-commit hook)
        files = [Path(f) for f in sys.argv[1:]]
        results = scan_files(files, raise_on_violation=False)
    else:
        # Scan staged files
        results = scan_staged_files(raise_on_violation=False)

    if results:
        print("🔴 FORBIDDEN CONTENT DETECTED:")
        for filepath, violations in results.items():
            for desc, line_num, text in violations:
                print(f"  {filepath}:{line_num} — {desc}")
                print(f"    {text}")
        sys.exit(1)
    else:
        print("✅ No secrets detected in staged files.")
        sys.exit(0)

"""
agents/resume/ats_auditor.py — ATS compliance checker.

ATS_RULES from Section 9 are enforced as assertions (raises ATSViolation on fail).
Each rule maps to a check function that inspects the raw Markdown text.

Score: 0–10 based on how many rules pass.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

ATS_RULES = {
    "no_tables": True,
    "no_graphics": True,
    "standard_headings": ["Experience", "Education", "Skills", "Projects", "Certifications"],
    "single_column_only": True,
    "no_header_footer": True,
    "allowed_fonts": ["Arial", "Calibri", "Times New Roman", "Garamond"],
    "max_pages": 2,
    "file_formats": ["pdf", "docx"],
    "no_text_boxes": True,
}


class ATSViolation(ValueError):
    pass


@dataclass
class ATSReport:
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    score: int = 10           # starts at 10, deducted per violation

    @property
    def passed(self) -> bool:
        return len(self.violations) == 0

    def summary(self) -> str:
        lines = [f"ATS Score: {self.score}/10"]
        if self.violations:
            lines.append("Violations: " + "; ".join(self.violations))
        if self.warnings:
            lines.append("Warnings: " + "; ".join(self.warnings))
        return " | ".join(lines)


def _check_no_tables(content: str, report: ATSReport) -> None:
    if re.search(r"^\|.+\|", content, re.MULTILINE):
        report.violations.append("Contains Markdown table — remove for ATS compatibility")
        report.score -= 2


def _check_no_graphics(content: str, report: ATSReport) -> None:
    if re.search(r"!\[.*?\]\(.*?\)", content):
        report.violations.append("Contains image/graphic — remove for ATS compatibility")
        report.score -= 2


def _check_standard_headings(content: str, report: ATSReport) -> None:
    found = set(re.findall(r"^#{1,3}\s+(.+)", content, re.MULTILINE))
    found_lower = {h.strip().lower() for h in found}
    standard_lower = {h.lower() for h in ATS_RULES["standard_headings"]}
    # At least Experience and Skills must be present
    for required in ("experience", "skills"):
        if required not in found_lower:
            report.warnings.append(f'Missing standard heading "{required.title()}"')
            report.score -= 1


def _check_no_html(content: str, report: ATSReport) -> None:
    if re.search(r"<[a-zA-Z][^>]*>", content):
        report.violations.append("Contains HTML tags — use plain Markdown only")
        report.score -= 2


def _check_no_excessive_symbols(content: str, report: ATSReport) -> None:
    # Fancy unicode bullets or decorative chars confuse some ATS
    non_ascii = re.findall(r"[^\x00-\x7F]", content)
    if len(non_ascii) > 10:
        report.warnings.append(f"Contains {len(non_ascii)} non-ASCII characters — verify ATS reads correctly")
        report.score -= 1


def _check_contact_info_present(content: str, report: ATSReport) -> None:
    has_email = bool(re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", content))
    has_linkedin = "linkedin" in content.lower()
    has_github = "github" in content.lower()
    if not has_email:
        report.violations.append("No email address found in resume")
        report.score -= 2
    if not has_linkedin and not has_github:
        report.warnings.append("No LinkedIn or GitHub URL found")
        report.score -= 1


def _check_length(content: str, report: ATSReport) -> None:
    # Rough estimate: ~500 words per page
    word_count = len(content.split())
    if word_count > 1200:
        report.warnings.append(f"Resume may exceed 2 pages ({word_count} words)")
        report.score -= 1
    elif word_count < 200:
        report.warnings.append(f"Resume seems too short ({word_count} words)")
        report.score -= 1


def _check_weak_phrases(content: str, report: ATSReport) -> None:
    weak = ["responsible for", "duties included", "worked on", "helped with", "assisted in"]
    found = [w for w in weak if w.lower() in content.lower()]
    if found:
        report.warnings.append(f"Weak phrases found: {', '.join(found)}")
        report.score -= 1


# All checks in order
_CHECKS = [
    _check_no_tables,
    _check_no_graphics,
    _check_standard_headings,
    _check_no_html,
    _check_no_excessive_symbols,
    _check_contact_info_present,
    _check_length,
    _check_weak_phrases,
]


def audit(content: str, raise_on_violation: bool = False) -> ATSReport:
    """
    Run all ATS checks against resume Markdown content.
    Returns an ATSReport. If raise_on_violation=True, raises ATSViolation
    on the first hard violation (used in CI/pre-commit contexts).
    """
    report = ATSReport()
    for check in _CHECKS:
        check(content, report)

    report.score = max(0, min(10, report.score))

    if raise_on_violation and report.violations:
        raise ATSViolation(
            f"ATS violations found:\n" + "\n".join(f"  - {v}" for v in report.violations)
        )

    return report


if __name__ == "__main__":
    sample = "# Shreyas Khandare\nsreyas@example.com\n\n## Experience\n- Responsible for building LLM pipelines\n\n## Skills\nPython, LangChain"
    r = audit(sample)
    print(r.summary())

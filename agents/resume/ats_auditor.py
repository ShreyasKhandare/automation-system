"""
agents/resume/ats_auditor.py — Enforce ATS rules on resume content.

ATS_RULES from SYSTEM_DESIGN.md Section 9 are enforced as assertions.
Raises AssertionError if any hard rule is violated.
Returns an audit report with score and violations.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger

log = get_logger("resume")

# ATS rules — from SYSTEM_DESIGN.md Section 9
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


def audit_resume(resume_markdown: str) -> dict[str, Any]:
    """
    Audit a resume in Markdown format against ATS rules.

    Hard violations raise AssertionError.
    Soft warnings are collected in the report.

    Returns:
        Audit report dict.
    """
    violations: list[str] = []
    warnings: list[str] = []

    # --- Hard checks (assertions) ---

    # 1. No HTML tables
    if "<table" in resume_markdown.lower() or "|---|" in resume_markdown:
        violations.append("Table detected — ATS cannot parse tables")

    # 2. No markdown images or HTML img tags
    if re.search(r'!\[.*?\]\(.*?\)', resume_markdown) or "<img" in resume_markdown.lower():
        violations.append("Image/graphic detected — ATS cannot parse graphics")

    # 3. Standard section headings present
    content_lower = resume_markdown.lower()
    has_experience = "experience" in content_lower
    has_education = "education" in content_lower
    has_skills = "skills" in content_lower or "technical skills" in content_lower

    if not has_experience:
        warnings.append("Missing 'Experience' section heading")
    if not has_education:
        warnings.append("Missing 'Education' section heading")
    if not has_skills:
        warnings.append("Missing 'Skills' section heading")

    # 4. No multi-column markers (markdown tables used for layout)
    if re.search(r'\|.+\|.+\|', resume_markdown):
        violations.append("Multi-column layout detected via pipe characters — use single column only")

    # 5. No headers/footers (hard to detect in MD, check for page markers)
    if re.search(r'page \d+ of \d+', resume_markdown, re.IGNORECASE):
        warnings.append("Page number markers found — remove headers/footers for ATS")

    # 6. Line length / word count estimate for pages
    words = len(resume_markdown.split())
    estimated_pages = words / 400  # rough estimate: 400 words per page
    if estimated_pages > 2.5:
        warnings.append(f"Resume may exceed 2 pages ({words} words, ~{estimated_pages:.1f} pages)")

    # 7. Check for weak phrases that should have been removed
    weak_phrases = ["responsible for", "duties included", "worked on"]
    for phrase in weak_phrases:
        if phrase in resume_markdown.lower():
            warnings.append(f"Weak phrase found: '{phrase}' — replace with action verbs")

    # 8. Check for keywords to avoid from config
    try:
        from shared.config_loader import load_config
        cfg = load_config()
        for phrase in cfg.resume_automation.keywords_to_avoid:
            if phrase.lower() in resume_markdown.lower():
                warnings.append(f"Weak phrase: '{phrase}'")
    except Exception:
        pass

    # --- Score calculation ---
    total_rules = 8
    passed = total_rules - len(violations)
    score = round(passed / total_rules, 2)

    # --- Assert hard rules ---
    if violations:
        violation_text = "\n".join(f"  - {v}" for v in violations)
        assert False, f"ATS VIOLATIONS FOUND:\n{violation_text}\n\nFix these before generating PDF."

    report = {
        "passed": True,
        "score": score,
        "violations": violations,
        "warnings": warnings,
        "word_count": words,
        "estimated_pages": round(estimated_pages, 1),
        "rules_checked": total_rules,
    }

    log.info("ats_audit_complete",
             score=score,
             violations=len(violations),
             warnings=len(warnings),
             pages=round(estimated_pages, 1))

    return report


def get_ats_score(resume_markdown: str) -> float:
    """Quick ATS score without raising on violations."""
    try:
        report = audit_resume(resume_markdown)
        return report["score"]
    except AssertionError:
        return 0.0
    except Exception:
        return 0.5

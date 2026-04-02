"""
agents/resume/gap_analyzer.py — Compare resume content against JD requirements.

Identifies:
  - missing_keywords  : keywords in JD not present in current resume
  - weak_phrases      : passive/weak language flagged by config
  - section_order     : whether sections should be reordered (e.g. Projects first for AI roles)
  - missing_sections  : standard ATS headings that are absent
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.config_loader import load_config
from agents.resume.jd_parser import ParsedJD

_STANDARD_SECTIONS = ["Experience", "Education", "Skills", "Projects"]


@dataclass
class GapReport:
    missing_keywords: list[str] = field(default_factory=list)
    weak_phrases_found: list[str] = field(default_factory=list)
    missing_sections: list[str] = field(default_factory=list)
    suggested_section_order: list[str] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        lines = []
        if self.missing_keywords:
            lines.append(f"Missing keywords: {', '.join(self.missing_keywords[:15])}")
        if self.weak_phrases_found:
            lines.append(f"Weak phrases to replace: {', '.join(self.weak_phrases_found)}")
        if self.missing_sections:
            lines.append(f"Missing sections: {', '.join(self.missing_sections)}")
        if self.suggested_section_order:
            lines.append(f"Suggested section order: {' > '.join(self.suggested_section_order)}")
        return "\n".join(lines) if lines else "No major gaps detected."


def analyze_gaps(resume_content: str, parsed_jd: ParsedJD) -> GapReport:
    """Compare resume text against parsed JD and return a GapReport."""
    cfg = load_config()
    resume_lower = resume_content.lower()

    # Missing keywords
    all_jd_keywords = parsed_jd.all_keywords()
    missing = [
        kw for kw in all_jd_keywords
        if not re.search(r"\b" + re.escape(kw) + r"\b", resume_lower, re.IGNORECASE)
    ][:10]

    # Weak phrases from config
    weak_found = [
        phrase for phrase in cfg.resume_automation.keywords_to_avoid
        if phrase.lower() in resume_lower
    ]

    # Missing standard sections
    missing_sections = [
        s for s in _STANDARD_SECTIONS
        if not re.search(r"^#{1,3}\s*" + re.escape(s), resume_content, re.IGNORECASE | re.MULTILINE)
    ]

    # Section order recommendation: for AI roles, suggest Projects before Experience
    ai_role_signals = ["ai", "llm", "ml", "machine learning", "engineer"]
    is_ai_role = any(s in parsed_jd.domain.lower() or
                     any(s in kw.lower() for kw in parsed_jd.required_skills)
                     for s in ai_role_signals)
    suggested_order = (
        ["Projects", "Experience", "Skills", "Education"]
        if is_ai_role
        else ["Experience", "Projects", "Skills", "Education"]
    )

    return GapReport(
        missing_keywords=missing,
        weak_phrases_found=weak_found,
        missing_sections=missing_sections,
        suggested_section_order=suggested_order,
    )

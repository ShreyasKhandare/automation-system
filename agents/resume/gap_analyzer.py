"""
agents/resume/gap_analyzer.py — Compare resume vs JD requirements.

Identifies:
  - Missing keywords
  - Weak phrasing issues
  - Section ordering problems
  - Missing required skills
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.config_loader import load_config

log = get_logger("resume")


def analyze_gaps(
    resume_content: str,
    jd_parsed: dict[str, Any],
    keyword_list: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Compare resume against parsed JD to find gaps.

    Args:
        resume_content: Full resume markdown text.
        jd_parsed: Output from jd_parser.parse_jd().
        keyword_list: Output from keyword_analyzer.analyze_keywords().

    Returns:
        Gap analysis dict.
    """
    cfg = load_config()
    keywords_to_avoid = cfg.resume_automation.keywords_to_avoid

    resume_lower = resume_content.lower()

    # Check required skills presence
    required_skills = jd_parsed.get("required_skills", [])
    missing_required = [skill for skill in required_skills if skill.lower() not in resume_lower]

    # Check preferred skills
    preferred_skills = jd_parsed.get("preferred_skills", [])
    missing_preferred = [skill for skill in preferred_skills if skill.lower() not in resume_lower]

    # Check high-priority keywords
    high_priority_keywords = [k["keyword"] for k in keyword_list if k["priority"] == "HIGH"]
    missing_keywords = [kw for kw in high_priority_keywords if kw.lower() not in resume_lower]

    # Check for weak phrases
    weak_phrases_found = [phrase for phrase in keywords_to_avoid if phrase.lower() in resume_lower]

    # Check section ordering
    section_issues = _check_section_ordering(resume_content, jd_parsed)

    # Calculate a basic gap score (lower = more gaps)
    total_required = len(required_skills) or 1
    present_required = total_required - len(missing_required)
    gap_score = round(present_required / total_required, 2)

    result = {
        "missing_required_skills": missing_required,
        "missing_preferred_skills": missing_preferred[:5],
        "missing_high_priority_keywords": missing_keywords[:10],
        "weak_phrases_found": weak_phrases_found,
        "section_ordering_issues": section_issues,
        "gap_score": gap_score,
        "summary": _build_gap_summary(missing_required, missing_keywords, weak_phrases_found, gap_score),
    }

    log.info("gap_analysis_complete",
             missing_required=len(missing_required),
             missing_keywords=len(missing_keywords),
             weak_phrases=len(weak_phrases_found),
             gap_score=gap_score)
    return result


def _check_section_ordering(resume_content: str, jd_parsed: dict[str, Any]) -> list[str]:
    """Identify section ordering issues based on job type."""
    issues = []

    # Find section headers
    headers = re.findall(r'^#{1,3}\s+(.+)$', resume_content, re.MULTILINE)
    headers_lower = [h.lower() for h in headers]

    # For AI roles, Projects should come before Experience if experience is < 5 years
    tech_stack = jd_parsed.get("tech_stack", [])
    is_ai_role = any(kw in " ".join(tech_stack).lower() for kw in ["llm", "ai", "ml", "langchain", "pytorch"])

    if is_ai_role:
        proj_idx = next((i for i, h in enumerate(headers_lower) if "project" in h), None)
        exp_idx = next((i for i, h in enumerate(headers_lower) if "experience" in h), None)
        if proj_idx is not None and exp_idx is not None and proj_idx > exp_idx:
            issues.append("Consider moving Projects section before Experience for AI roles")

    return issues


def _build_gap_summary(
    missing_required: list[str],
    missing_keywords: list[str],
    weak_phrases: list[str],
    gap_score: float,
) -> str:
    """Build a human-readable gap summary for the tailor prompt."""
    parts = []

    if missing_required:
        parts.append(f"MISSING REQUIRED SKILLS: {', '.join(missing_required[:5])}")
    if missing_keywords:
        parts.append(f"MISSING HIGH-PRIORITY KEYWORDS: {', '.join(missing_keywords[:5])}")
    if weak_phrases:
        parts.append(f"WEAK PHRASES TO REMOVE: {', '.join(weak_phrases)}")
    if gap_score < 0.7:
        parts.append(f"LOW MATCH SCORE ({gap_score:.0%}) — significant tailoring needed")
    elif gap_score >= 0.9:
        parts.append(f"HIGH MATCH ({gap_score:.0%}) — minor keyword injection needed")

    return "\n".join(parts) if parts else "Resume is well-matched to this role."


def format_for_prompt(gap_analysis: dict[str, Any]) -> str:
    """Format gap analysis for use in the tailor prompt."""
    return gap_analysis.get("summary", "")

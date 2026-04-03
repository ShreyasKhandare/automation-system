"""
agents/resume/rewriter.py — Claude-powered resume tailoring.

Uses the exact system prompt from SYSTEM_DESIGN.md Section 9 (tailor.txt).
Returns the tailored resume text plus structured diff and keyword report.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger

log = get_logger("resume")

_PROMPT_PATH = Path(__file__).parent / "prompts" / "tailor.txt"


def _load_prompt_template() -> str:
    """Load the tailor.txt prompt template."""
    if not _PROMPT_PATH.exists():
        raise FileNotFoundError(f"Prompt template not found: {_PROMPT_PATH}")
    return _PROMPT_PATH.read_text(encoding="utf-8")


def rewrite_resume(
    base_resume: str,
    job_description: str,
    keyword_list: list[dict[str, Any]],
    gap_analysis: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Rewrite/tailor the resume using Claude API.

    Args:
        base_resume: Full base resume in Markdown.
        job_description: Full job description text.
        keyword_list: Output from keyword_analyzer.analyze_keywords().
        gap_analysis: Output from gap_analyzer.analyze_gaps().
        dry_run: If True, return placeholder without calling Claude.

    Returns:
        Dict with 'tailored_resume', 'diff', 'keyword_report'.
    """
    if dry_run:
        log.info("rewriter_dry_run")
        return {
            "tailored_resume": base_resume,
            "diff": {
                "added": ["[dry-run: no changes]"],
                "modified": [],
                "reasoning": "Dry run — no Claude API call made.",
            },
            "keyword_report": {
                "injected": [],
                "removed_weak": [],
                "ats_score_before": "N/A",
                "ats_score_after": "N/A",
            },
        }

    # Format keyword list for prompt
    from agents.resume.keyword_analyzer import format_keyword_list
    from agents.resume.gap_analyzer import format_for_prompt

    keyword_text = format_keyword_list(keyword_list)
    gap_text = format_for_prompt(gap_analysis)

    # Load and fill prompt template
    prompt_template = _load_prompt_template()
    user_content = prompt_template.format(
        base_resume_content=base_resume[:4000],
        job_description=job_description[:2000],
        keyword_list=keyword_text,
        gap_analysis=gap_text,
    )

    try:
        import anthropic
        from shared.secrets import get_secret

        client = anthropic.Anthropic(api_key=get_secret("ANTHROPIC_API_KEY"))

        system_prompt = (
            "You are a senior technical resume writer specializing in AI/ML engineering roles. "
            "Return only valid JSON matching the exact output format specified — no markdown, no explanation."
        )

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )

        raw = response.content[0].text.strip()

        # Strip code fences if present
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()

        result = json.loads(raw)

        # Validate expected keys
        if "tailored_resume" not in result:
            raise ValueError("Claude response missing 'tailored_resume' key")

        log.info("resume_rewrite_complete",
                 added=len(result.get("diff", {}).get("added", [])),
                 injected=len(result.get("keyword_report", {}).get("injected", [])))

        return result

    except Exception as e:
        log.error("resume_rewrite_failed", error=str(e))
        # Return base resume unchanged on error
        return {
            "tailored_resume": base_resume,
            "diff": {"added": [], "modified": [], "reasoning": f"Rewrite failed: {e}"},
            "keyword_report": {"injected": [], "removed_weak": [], "ats_score_before": "N/A", "ats_score_after": "N/A"},
            "error": str(e),
        }

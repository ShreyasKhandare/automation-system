"""
agents/resume/jd_parser.py — Parse job descriptions using Claude API.

Extracts:
  - required_skills: list of must-have skills
  - preferred_skills: list of nice-to-have skills
  - responsibilities: list of key job responsibilities
  - keywords: ranked list of important keywords
  - seniority_signals: experience level indicators
  - tech_stack: technologies mentioned
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


def parse_jd(job_description: str, job_title: str = "") -> dict[str, Any]:
    """
    Parse a job description using Claude API.

    Args:
        job_description: Full text of the job description.
        job_title: Optional job title for context.

    Returns:
        Dict with parsed JD components.
    """
    if not job_description or not job_description.strip():
        return {
            "required_skills": [],
            "preferred_skills": [],
            "responsibilities": [],
            "keywords": [],
            "seniority_signals": [],
            "tech_stack": [],
        }

    try:
        import anthropic
        from shared.secrets import get_secret

        client = anthropic.Anthropic(api_key=get_secret("ANTHROPIC_API_KEY"))

        system_prompt = """You are a technical recruiter and resume expert.
Parse the provided job description and extract structured information.
Return JSON only — no markdown, no explanation."""

        user_content = f"""Parse this job description for: {job_title or 'AI/ML Engineering Role'}

JOB DESCRIPTION:
{job_description[:3000]}

Return JSON with exactly these keys:
{{
  "required_skills": ["list of must-have technical skills"],
  "preferred_skills": ["list of nice-to-have skills"],
  "responsibilities": ["list of key responsibilities, 5-8 items"],
  "keywords": ["ranked list of important keywords for ATS, most important first"],
  "seniority_signals": ["experience level indicators like '3+ years', 'senior', 'lead'"],
  "tech_stack": ["specific technologies, frameworks, tools mentioned"]
}}"""

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()

        parsed = json.loads(raw)
        log.info("jd_parsed", title=job_title, keywords=len(parsed.get("keywords", [])))
        return parsed

    except Exception as e:
        log.error("jd_parse_failed", error=str(e))
        return {
            "required_skills": [],
            "preferred_skills": [],
            "responsibilities": [],
            "keywords": [],
            "seniority_signals": [],
            "tech_stack": [],
            "error": str(e),
        }

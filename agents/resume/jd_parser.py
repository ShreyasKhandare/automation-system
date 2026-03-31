"""
agents/resume/jd_parser.py — Extract structured requirements from a job description.

Uses Claude API to pull out:
  - required_skills       : must-have technical skills
  - preferred_skills      : nice-to-have skills
  - responsibilities      : key duties
  - keywords              : high-frequency terms for ATS matching
  - seniority_signals     : experience level cues (years, "senior", "lead", etc.)
  - domain                : FinTech | RegTech | HealthTech | General | etc.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.secrets import get_secret

log = get_logger("resume")

_SYSTEM_PROMPT = """\
You are a job description analyst. Extract structured information from the job description below.

OUTPUT FORMAT — respond ONLY with a valid JSON object:
{
  "required_skills": ["Python", "LangChain", ...],
  "preferred_skills": ["Kubernetes", "MLflow", ...],
  "responsibilities": ["Build RAG pipelines", ...],
  "keywords": ["LLM", "RAG", "multi-agent", ...],
  "seniority_signals": ["3+ years", "mid-level", ...],
  "domain": "FinTech"
}

No markdown. No other text.
"""


@dataclass
class ParsedJD:
    required_skills: list[str] = field(default_factory=list)
    preferred_skills: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    seniority_signals: list[str] = field(default_factory=list)
    domain: str = "General"

    def all_keywords(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for kw in self.keywords + self.required_skills + self.preferred_skills:
            k = kw.strip()
            if k and k.lower() not in seen:
                seen.add(k.lower())
                out.append(k)
        return out


def parse_jd(job_description: str) -> ParsedJD:
    """Call Claude to extract structured data from a job description."""
    import anthropic
    client = anthropic.Anthropic(api_key=get_secret("ANTHROPIC_API_KEY"))

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": job_description[:6000]}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = "\n".join(raw.split("\n")[:-1])

    data = json.loads(raw)
    return ParsedJD(
        required_skills=data.get("required_skills", []),
        preferred_skills=data.get("preferred_skills", []),
        responsibilities=data.get("responsibilities", []),
        keywords=data.get("keywords", []),
        seniority_signals=data.get("seniority_signals", []),
        domain=data.get("domain", "General"),
    )

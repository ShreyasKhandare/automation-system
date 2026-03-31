"""
agents/resume/rewriter.py — Claude API resume rewriting.

Loads the prompt template from agents/resume/prompts/tailor.txt,
fills in the placeholders, calls Claude, and parses the three-section output:
  1. Tailored resume Markdown
  2. JSON diff
  3. JSON keyword report
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

_PROMPT_PATH = Path(__file__).parent / "prompts" / "tailor.txt"
_SPLIT = "---JSON_SPLIT---"


@dataclass
class RewriteResult:
    tailored_md: str
    diff: dict = field(default_factory=dict)       # {"added": [], "modified": [], "reasoning": ""}
    keyword_report: dict = field(default_factory=dict)  # {"injected": [], "removed_weak": [], "ats_score": {}}
    tokens_used: int = 0


def rewrite(
    base_resume: str,
    job_description: str,
    keyword_list: list[str],
    gap_analysis_text: str,
) -> RewriteResult:
    """
    Call Claude with the tailor prompt. Returns a RewriteResult.
    Uses the exact prompt from agents/resume/prompts/tailor.txt.
    """
    import anthropic

    prompt_template = _PROMPT_PATH.read_text()
    filled_prompt = prompt_template.format(
        base_resume_content=base_resume[:6000],
        job_description=job_description[:4000],
        keyword_list=", ".join(keyword_list[:20]),
        gap_analysis=gap_analysis_text[:1000],
    )

    client = anthropic.Anthropic(api_key=get_secret("ANTHROPIC_API_KEY"))
    log.info("rewrite_start", keywords=len(keyword_list))

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=6000,
        messages=[{"role": "user", "content": filled_prompt}],
    )

    raw = response.content[0].text
    tokens = response.usage.input_tokens + response.usage.output_tokens
    log.info("rewrite_done", tokens=tokens)

    parts = raw.split(_SPLIT)
    if len(parts) < 3:
        # Graceful fallback — return raw text as resume, empty dicts
        log.warning("rewrite_parse_failed", parts=len(parts))
        return RewriteResult(tailored_md=raw.strip(), tokens_used=tokens)

    tailored_md = parts[0].strip()
    diff_raw = parts[1].strip()
    kw_raw = parts[2].strip()

    def _safe_json(text: str) -> dict:
        try:
            if text.startswith("```"):
                text = "\n".join(text.split("\n")[1:])
            if text.endswith("```"):
                text = "\n".join(text.split("\n")[:-1])
            return json.loads(text)
        except Exception:
            return {}

    return RewriteResult(
        tailored_md=tailored_md,
        diff=_safe_json(diff_raw),
        keyword_report=_safe_json(kw_raw),
        tokens_used=tokens,
    )

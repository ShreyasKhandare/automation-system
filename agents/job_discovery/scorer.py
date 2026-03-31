"""
agents/job_discovery/scorer.py — Claude API job scoring (0–10).

Sends all listings in batches to Claude with Shreyas's full profile context.
Claude returns a score (0–10) and reasoning for each listing.

Score interpretation:
  9–10 : Must apply today — immediate Telegram alert
  7–8  : Strong match — included in daily digest
  6    : Threshold match — included if above config.score_threshold
  <6   : Filtered out

All scoring is done in a single batched prompt per batch (efficient).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.secrets import get_secret
from shared.config_loader import load_config
from agents.job_discovery.scraper import JobListing

log = get_logger("job_discovery")

_BATCH_SIZE = 15  # listings per Claude call

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a job scoring assistant for Shreyas Khandare, an AI/LLM Engineer.

SHREYAS'S PROFILE:
- MS CS from Florida State University
- Currently: Systems Consultant at FDLE (state government, not technical AI work)
- Flagship project: FinOps Sentinel — LangGraph multi-agent compliance RAG system
- Primary stack: Python, LangChain, LangGraph, ChromaDB, FastAPI, Streamlit, RAG, Multi-Agent AI
- Learning: MCP servers, fine-tuning, multimodal LLMs
- Target seniority: Mid-level (2–5 years AI/LLM experience equivalent)
- Preferred: Remote-first, FinTech/RegTech/AI-native startups
- Salary range: $110K–$180K USD
- Location: Tallahassee FL (open to fully remote)
- Visa: US Authorized (no sponsorship needed)

SCORING CRITERIA (0–10):
  10 = Perfect match: AI/LLM role, LangChain/LangGraph/RAG stack, remote, FinTech/compliance, salary in range
   9 = Excellent: strong AI/LLM fit, most criteria met, minor gaps (e.g. hybrid or slightly different stack)
   8 = Strong: AI/ML role with relevant stack, good culture/mission fit
   7 = Good: ML/AI adjacent role, relevant skills, some gaps (location, seniority mismatch, etc.)
   6 = Threshold: AI-adjacent role, worth applying but not ideal
   5 = Weak: vaguely related, significant stack/seniority mismatch
  <5 = Poor: not relevant (data analyst, frontend, unrelated domain)

NEGATIVE SIGNALS (reduce score):
  - Requires 5+ years experience when Shreyas has 2–3 years AI equivalent
  - Requires active security clearance
  - Only onsite (no remote option)
  - Salary below $100K or clearly above $200K (staff/principal-only)
  - FAANG-only culture (Amazon, Meta warehouse-scale infra roles)
  - Pure data engineering / ETL roles without AI/LLM component

OUTPUT FORMAT — respond ONLY with a valid JSON array, one object per listing:
[
  {
    "id": "<listing_id>",
    "score": 8,
    "reasoning": "Strong LangChain + FastAPI match. Remote. FinTech domain. Salary unconfirmed but company size suggests range."
  },
  ...
]
No markdown fences. No other text.
"""


def _build_user_prompt(listings: list[JobListing]) -> str:
    parts = [f"Score these {len(listings)} job listings:\n"]
    for job in listings:
        tech = ", ".join(job.tech_stack[:8]) if job.tech_stack else "not specified"
        salary = ""
        if job.salary_min or job.salary_max:
            salary = f"${job.salary_min or '?'}–${job.salary_max or '?'}"
        parts.append(
            f"ID: {job.id}\n"
            f"Title: {job.title}\n"
            f"Company: {job.company}\n"
            f"Location: {job.location} | Remote: {'Yes' if job.remote else 'No'}\n"
            f"Salary: {salary or 'not listed'}\n"
            f"Tech stack: {tech}\n"
            f"Description: {job.description_snippet[:350]}\n"
        )
    return "\n---\n".join(parts)


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------

def _call_claude_batch(listings: list[JobListing]) -> list[dict]:
    import anthropic

    api_key = get_secret("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)

    user_prompt = _build_user_prompt(listings)
    log.info("claude_scoring_start", count=len(listings))

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = response.content[0].text.strip()
    tokens = response.usage.input_tokens + response.usage.output_tokens
    log.info("claude_scoring_done", tokens=tokens, count=len(listings))

    # Strip any accidental markdown fences
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = "\n".join(raw.split("\n")[:-1])

    return json.loads(raw)


def _fallback_scores(listings: list[JobListing]) -> list[dict]:
    return [{"id": j.id, "score": 5, "reasoning": "Claude unavailable — default score"} for j in listings]


# ---------------------------------------------------------------------------
# Main scoring entry point
# ---------------------------------------------------------------------------

def score_listings(
    listings: list[JobListing],
    dry_run: bool = False,
) -> list[JobListing]:
    """
    Score all listings via Claude API.
    Filters out listings below config.job_search_preferences.score_threshold.
    Returns scored listings sorted by score descending.
    In dry_run mode, assigns score=7 to all without calling Claude.
    """
    if not listings:
        return []

    cfg = load_config()
    threshold = cfg.job_search_preferences.score_threshold  # default 6

    id_map = {j.id: j for j in listings}
    all_scores: list[dict] = []

    if dry_run:
        log.info("dry_run_scoring", msg="Assigning default scores")
        all_scores = [{"id": j.id, "score": 7, "reasoning": "dry-run default"} for j in listings]
    else:
        for i in range(0, len(listings), _BATCH_SIZE):
            batch = listings[i:i + _BATCH_SIZE]
            try:
                scores = _call_claude_batch(batch)
                all_scores.extend(scores)
            except json.JSONDecodeError as e:
                log.error("claude_json_parse_failed", error=str(e))
                all_scores.extend(_fallback_scores(batch))
            except Exception as e:
                log.error("claude_scoring_failed", error=str(e), exc_info=True)
                all_scores.extend(_fallback_scores(batch))

    # Apply scores back to JobListing objects
    scored: list[JobListing] = []
    for s in all_scores:
        job = id_map.get(s.get("id", ""))
        if job is None:
            continue
        score = float(s.get("score", 0))
        if score < threshold:
            continue
        job.score = score
        job.score_reason = str(s.get("reasoning", ""))[:300]
        scored.append(job)

    # Sort by score descending
    scored.sort(key=lambda j: j.score or 0, reverse=True)

    log.info(
        "scoring_complete",
        total_in=len(listings),
        above_threshold=len(scored),
        threshold=threshold,
        urgent=sum(1 for j in scored if (j.score or 0) >= 9),
    )
    return scored


if __name__ == "__main__":
    from agents.job_discovery.scraper import scrape
    raw = scrape(dry_run=True)
    if raw:
        scored = score_listings(raw[:5], dry_run=True)
        for j in scored:
            print(f"  [{j.score}/10] {j.title} @ {j.company}")
    else:
        print("No listings to score")

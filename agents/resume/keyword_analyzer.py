"""
agents/resume/keyword_analyzer.py — Keyword frequency analysis across similar job postings.

Pulls recent jobs from SQLite that match the target role, extracts keywords,
and returns a ranked priority list for the rewriter.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.db import get_conn, get_db_path

log = get_logger("resume")

# High-value AI/ML keywords to boost in ranking
PRIORITY_KEYWORDS = {
    "langchain", "langgraph", "rag", "retrieval-augmented generation",
    "multi-agent", "llm", "large language model", "fastapi", "chromadb",
    "vector database", "embeddings", "fine-tuning", "prompt engineering",
    "python", "pytorch", "tensorflow", "huggingface", "transformers",
    "openai", "anthropic", "claude", "gpt", "streamlit", "mlflow",
    "kubernetes", "docker", "aws", "azure", "gcp", "redis", "postgresql",
    "microservices", "rest api", "graphql", "ci/cd", "github actions",
}


def analyze_keywords(
    job_description: str,
    similar_jobs_limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Analyze keyword frequency across recent similar jobs.

    Args:
        job_description: Current JD to extract initial keywords from.
        similar_jobs_limit: How many similar recent jobs to analyze.

    Returns:
        Ranked list of dicts: [{"keyword": str, "frequency": int, "priority": str}]
    """
    # Extract keywords from current JD
    current_kws = _extract_keywords(job_description)

    # Load recent similar jobs from DB
    similar_texts = _load_similar_job_descriptions(limit=similar_jobs_limit)

    # Count keyword frequency across all jobs
    counter: Counter = Counter()
    for text in similar_texts:
        for kw in _extract_keywords(text):
            counter[kw] += 1

    # Merge with current JD keywords
    for kw in current_kws:
        counter[kw] = counter.get(kw, 0) + 3  # boost current JD keywords

    # Build ranked list
    ranked = []
    for kw, freq in counter.most_common(40):
        priority = "HIGH" if kw.lower() in PRIORITY_KEYWORDS else ("MEDIUM" if freq >= 3 else "LOW")
        ranked.append({"keyword": kw, "frequency": freq, "priority": priority})

    log.info("keyword_analysis_complete", total=len(ranked), high=sum(1 for k in ranked if k["priority"] == "HIGH"))
    return ranked


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from job description text."""
    # Lowercase and tokenize
    text = text.lower()
    # Find multi-word technical terms first
    multi_word = re.findall(
        r'\b(?:large language model|retrieval.augmented generation|multi.agent|'
        r'natural language processing|machine learning|deep learning|'
        r'computer vision|reinforcement learning|transfer learning|'
        r'generative ai|production ml|mlops|vector database|'
        r'rest api|graph ql|ci\/cd|github actions)\b',
        text
    )
    # Single significant words
    single = re.findall(r'\b[a-z][a-z0-9\+\#\-\.]{2,}\b', text)

    # Filter stopwords
    stopwords = {
        "the", "and", "for", "with", "this", "that", "from", "will", "have",
        "are", "our", "you", "your", "we", "can", "able", "also", "work",
        "team", "role", "job", "help", "build", "use", "using", "used",
        "new", "all", "may", "must", "they", "their", "who", "what", "how",
        "when", "where", "such", "any", "not", "but", "more", "than",
        "experience", "years", "strong", "good", "great", "excellent",
        "knowledge", "skills", "ability", "understanding", "working",
    }

    keywords = [kw for kw in (multi_word + single) if kw not in stopwords and len(kw) > 2]
    return list(set(keywords))


def _load_similar_job_descriptions(limit: int = 20) -> list[str]:
    """Load recent job descriptions from SQLite."""
    try:
        with get_conn(get_db_path()) as conn:
            rows = conn.execute(
                "SELECT description_clean, description_raw FROM jobs "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        texts = []
        for row in rows:
            text = row["description_clean"] or row["description_raw"] or ""
            if text:
                texts.append(text)
        return texts
    except Exception as e:
        log.warning("load_similar_jobs_failed", error=str(e))
        return []


def format_keyword_list(ranked: list[dict[str, Any]]) -> str:
    """Format keyword list for use in the tailor prompt."""
    lines = []
    for item in ranked[:20]:  # Top 20 for prompt
        lines.append(f"- {item['keyword']} ({item['priority']}, freq={item['frequency']})")
    return "\n".join(lines)

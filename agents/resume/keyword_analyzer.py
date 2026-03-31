"""
agents/resume/keyword_analyzer.py — Frequency analysis across recent similar jobs.

Pulls the last N jobs from SQLite and counts keyword occurrence to build
a ranked priority list. This tells the rewriter which keywords matter most
across the current market (not just one JD).
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.db import get_conn, get_db_path

log = get_logger("resume")

_KNOWN_TECH = [
    "Python", "FastAPI", "LangChain", "LangGraph", "RAG", "LLM", "GPT", "Claude",
    "OpenAI", "Anthropic", "HuggingFace", "ChromaDB", "Pinecone", "Weaviate",
    "Qdrant", "pgvector", "Streamlit", "Docker", "Kubernetes", "AWS", "GCP",
    "Azure", "TypeScript", "JavaScript", "React", "PostgreSQL", "Redis", "MongoDB",
    "Spark", "Kafka", "MLflow", "Airflow", "PyTorch", "TensorFlow", "scikit-learn",
    "Pandas", "NumPy", "fine-tuning", "embeddings", "vector database",
    "multi-agent", "agent", "RAG pipeline", "retrieval", "prompt engineering",
    "MCP", "function calling", "tool use", "evaluation", "RAGAS",
    "compliance", "FinTech", "RegTech", "REST", "GraphQL", "CI/CD",
]


def analyze_keywords(job_ids: list[str] | None = None, limit: int = 20) -> list[str]:
    """
    Return a ranked list of the most frequent tech keywords
    across the last `limit` jobs in the DB (or from a specific list of job_ids).
    """
    try:
        with get_conn(get_db_path()) as conn:
            if job_ids:
                placeholders = ",".join("?" * len(job_ids))
                rows = conn.execute(
                    f"SELECT description_raw, tech_stack FROM jobs WHERE id IN ({placeholders})",
                    job_ids,
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT description_raw, tech_stack FROM jobs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
    except Exception as e:
        log.warning("keyword_analysis_db_failed", error=str(e))
        return _KNOWN_TECH[:15]

    counter: Counter = Counter()
    for row in rows:
        text = (row["description_raw"] or "") + " " + (row["tech_stack"] or "")
        for tech in _KNOWN_TECH:
            if re.search(r"\b" + re.escape(tech) + r"\b", text, re.IGNORECASE):
                counter[tech] += 1

    ranked = [kw for kw, _ in counter.most_common(20)]
    log.info("keyword_analysis_complete", top_keywords=ranked[:5], total=len(ranked))
    return ranked if ranked else _KNOWN_TECH[:15]

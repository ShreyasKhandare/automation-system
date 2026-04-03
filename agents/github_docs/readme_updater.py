"""
agents/github_docs/readme_updater.py — Update GitHub profile README.

Target: ShreyasKhandare/ShreyasKhandare/README.md (the profile README)
Uses GitHub API via GH_PAT to update the file.

Updates:
  - Latest project highlights
  - Current skills (from config)
  - Recent automation improvements
  - Links to live projects
"""

from __future__ import annotations

import base64
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.config_loader import load_config

log = get_logger("github_docs")

# Target repo for profile README — ONLY this repo, per SYSTEM_DESIGN.md
PROFILE_README_REPO = "ShreyasKhandare/ShreyasKhandare"
PROFILE_README_PATH = "README.md"


def _github_get(path: str, token: str) -> dict[str, Any]:
    """GET request to GitHub API."""
    import requests
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    resp = requests.get(f"https://api.github.com/{path}", headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _github_put(path: str, token: str, data: dict) -> dict[str, Any]:
    """PUT request to GitHub API."""
    import requests
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    resp = requests.put(f"https://api.github.com/{path}", headers=headers, json=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


def build_profile_readme(stats: dict[str, Any] | None = None) -> str:
    """
    Generate the profile README content.

    Args:
        stats: Optional stats dict from recent agent runs.

    Returns:
        Full README markdown string.
    """
    cfg = load_config()
    now = datetime.now().strftime("%B %d, %Y")
    skills_primary = " · ".join(cfg.profile.skills.primary)
    skills_secondary = " · ".join(cfg.profile.skills.secondary)
    skills_learning = " · ".join(cfg.profile.skills.learning)

    jobs_found = stats.get("jobs_found", 0) if stats else 0
    resumes_tailored = stats.get("resumes_tailored", 0) if stats else 0

    readme = f"""# Hi, I'm Shreyas Khandare 👋

> {cfg.profile.branding_statement.strip()}

**AI/LLM Engineer** · MS CS @ Florida State University · Based in {cfg.profile.location}

---

## 🛠 Tech Stack

**Core:** {skills_primary}

**Secondary:** {skills_secondary}

**Currently Learning:** {skills_learning}

---

## 🚀 Flagship Project

### [FinOps Sentinel](https://github.com/ShreyasKhandare/finops-sentinel) — LangGraph Multi-Agent Compliance RAG

- **Live demo:** [shreyas-finops-sentinel.streamlit.app](https://shreyas-finops-sentinel.streamlit.app)
- Production RAG pipeline with 413 document chunks, RAGAS score 1.0000
- Multi-agent orchestration with LangGraph, ChromaDB, FastAPI, Streamlit
- Designed for FinTech / RegTech compliance use cases

---

## 📊 What I'm Building

| Project | Status | Stack |
|---|---|---|
| FinOps Sentinel | Active | LangGraph, ChromaDB, FastAPI |
| Portfolio Website | In Progress | React, TypeScript, Vite |
| Automation System | Active | Python, Telegram, n8n |

---

## 🎯 What I'm Looking For

{' · '.join(cfg.profile.target_titles)} roles in {' · '.join(cfg.profile.target_industries)}

📧 {cfg.profile.email} · 💼 [LinkedIn]({cfg.profile.linkedin}) · 🌐 [Portfolio]({cfg.profile.portfolio})

---

*🤖 Profile last updated: {now}*
"""
    return readme


def update_profile_readme(dry_run: bool = False) -> str:
    """
    Update the GitHub profile README.

    Args:
        dry_run: If True, generate content but don't push to GitHub.

    Returns:
        Summary message string.
    """
    # Get recent stats for the README
    stats = _get_recent_stats()

    # Build new README content
    new_content = build_profile_readme(stats)

    if dry_run:
        log.info("readme_updater_dry_run")
        return f"README preview generated ({len(new_content)} chars). Dry run — not pushed."

    # Push to GitHub
    try:
        from shared.secrets import get_secret
        token = get_secret("GH_PAT")

        # Get current file SHA (required for update)
        try:
            current = _github_get(
                f"repos/{PROFILE_README_REPO}/contents/{PROFILE_README_PATH}",
                token
            )
            sha = current.get("sha")
        except Exception:
            sha = None  # File doesn't exist yet

        # Encode content
        content_b64 = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")

        data: dict[str, Any] = {
            "message": f"docs(profile): update GitHub README [{datetime.now().strftime('%Y-%m-%d')}]",
            "content": content_b64,
        }
        if sha:
            data["sha"] = sha

        _github_put(
            f"repos/{PROFILE_README_REPO}/contents/{PROFILE_README_PATH}",
            token,
            data,
        )

        log.info("profile_readme_updated", repo=PROFILE_README_REPO)
        return f"✅ Profile README updated: github.com/{PROFILE_README_REPO}"

    except Exception as e:
        log.error("profile_readme_update_failed", error=str(e))
        return f"❌ Profile README update failed: {e}"


def _get_recent_stats() -> dict[str, Any]:
    """Get recent stats from SQLite for README update."""
    try:
        from shared.db import get_conn, get_db_path
        with get_conn(get_db_path()) as conn:
            jobs = conn.execute("SELECT COUNT(*) as cnt FROM jobs").fetchone()
            resumes = conn.execute("SELECT COUNT(*) as cnt FROM resumes").fetchone()
            outreach = conn.execute("SELECT COUNT(*) as cnt FROM outreach WHERE status = 'sent'").fetchone()
        return {
            "jobs_found": jobs["cnt"] if jobs else 0,
            "resumes_tailored": resumes["cnt"] if resumes else 0,
            "emails_sent": outreach["cnt"] if outreach else 0,
        }
    except Exception:
        return {}

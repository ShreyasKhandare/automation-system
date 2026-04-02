"""
agents/github_docs/readme_updater.py — Update GitHub profile README.

Target: ShreyasKhandare/ShreyasKhandare/README.md (profile repo)
Updates via GitHub API — does NOT require a local clone of that repo.

Sections updated:
  - Current skills (from config)
  - Latest project highlights (from job/resume activity)
  - Recent automation improvements
  - Links to live projects
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.config_loader import load_config

log = get_logger("github_docs")


def _build_profile_readme(stats: dict) -> str:
    """Generate the full profile README content."""
    cfg = load_config()
    profile = cfg.profile
    now = datetime.now(timezone.utc)
    updated = now.strftime("%B %d, %Y")

    primary_skills = " · ".join(f"`{s}`" for s in profile.skills.primary)
    learning_skills = " · ".join(f"`{s}`" for s in profile.skills.learning)

    jobs_found = stats.get("jobs_discovered_total", 0)
    resumes = stats.get("resumes_tailored_total", 0)

    return f"""# Hi, I'm {profile.name} 👋

> {profile.bio.strip()}

---

## 🛠️ Stack

**Primary:** {primary_skills}

**Currently learning:** {learning_skills}

---

## 🚀 Flagship Project

**[FinOps Sentinel](https://github.com/ShreyasKhandare/finops-sentinel)** — LangGraph multi-agent compliance RAG system
- Production RAG pipeline with ChromaDB vector store
- Multi-agent orchestration (LangGraph)
- Live demo: [streamlit app](https://shreyas-finops-sentinel.streamlit.app/)

---

## 📊 Automation System Stats

| Metric | Count |
|---|---|
| Jobs tracked | {jobs_found} |
| Resume variants | {resumes} |
| Agents running | 8 |

---

## 🔗 Links

- 💼 [LinkedIn]({profile.linkedin})
- 🐙 [GitHub](https://github.com/ShreyasKhandare)
- 🌐 [{profile.portfolio}]({profile.portfolio})

---

*Last updated: {updated} by [automation-system](https://github.com/ShreyasKhandare/automation-system)*
"""


def update_profile_readme(stats: dict, dry_run: bool = False) -> bool:
    """
    Push updated profile README to ShreyasKhandare/ShreyasKhandare via GitHub API.
    Only touches README.md in the profile repo — nothing else.
    Returns True on success.
    """
    if dry_run:
        content = _build_profile_readme(stats)
        log.info("readme_dry_run", chars=len(content))
        return True

    try:
        import base64
        import requests
        from shared.secrets import get_secret

        token = get_secret("GITHUB_TOKEN")
        cfg = load_config()
        profile_repo = cfg.documentation_and_github.profile_readme_repo

        api_url = f"https://api.github.com/repos/{profile_repo}/{profile_repo}/contents/README.md"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

        # Get current SHA
        resp = requests.get(api_url, headers=headers, timeout=15)
        sha = resp.json().get("sha") if resp.ok else None

        content = _build_profile_readme(stats)
        encoded = base64.b64encode(content.encode()).decode()

        body = {
            "message": f"docs(profile): update GitHub README with latest stats [{datetime.now(timezone.utc).strftime('%Y-%m-%d')}]",
            "content": encoded,
        }
        if sha:
            body["sha"] = sha

        put_resp = requests.put(api_url, headers=headers, json=body, timeout=15)
        if put_resp.ok:
            log.info("profile_readme_updated")
            return True
        else:
            log.error("profile_readme_update_failed",
                      status=put_resp.status_code, body=put_resp.text[:200])
            return False

    except Exception as e:
        log.error("profile_readme_error", error=str(e))
        return False

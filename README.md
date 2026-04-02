# Shreyas Khandare — Automation System

> **Stack:** Claude Code · Cursor Pro · GitHub Actions · n8n · Telegram  
> **Owner:** Shreyas Khandare (AI/LLM Engineer)  
> **Version:** 1.0 | March 2026

Fully automated job search, resume tailoring, recruiter outreach, email triage, and project management system. Controlled entirely from a phone via Telegram. No manual daily effort required.

---

## What This Does

| Agent | Runs | What It Does |
|---|---|---|
| **Job Discovery** | Mon–Fri 7am EST | Scrapes Wellfound, Greenhouse, Otta, SerpAPI, Indeed — scores with Claude, sends ranked Telegram digest |
| **AI Radar** | Daily 1pm UTC | Monitors HN, HuggingFace Papers, arXiv, GitHub Trending — surfaces relevant AI tools and papers |
| **Email Triage** | Every 2 hours | Classifies Gmail using Claude, applies labels, sends alerts for interview/offer keywords |
| **Resume Agent** | On demand | Tailors resume to a specific job (JD gap analysis → Claude rewrite → ATS audit → PDF/DOCX) |
| **Recruiter Outreach** | On demand | Finds recruiters via Apollo, verifies email via Hunter, drafts personalized emails — requires approval before sending |
| **GitHub Docs** | Nightly 11pm EST | Updates CHANGELOG, generates weekly reports, auto-updates GitHub profile README |
| **Project Autopilot** | On demand | Runs bounded coding tasks on configured repos via Claude Code |
| **Market Research** | Sunday | Weekly market intelligence digest sent to Notion + Telegram |

---

## Quick Start

### 1. Clone and set up environment

```bash
git clone https://github.com/ShreyasKhandare/automation-system.git
cd automation-system
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # (created in Session 2+)
```

### 2. Configure secrets

```bash
cp .env.example .env
# Edit .env and fill in all required values
```

Required secrets:
- `ANTHROPIC_API_KEY` — Claude API
- `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` — Bot control
- `GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN` — Email access
- `SERPAPI_API_KEY` — Job search
- `APOLLO_API_KEY` + `HUNTER_API_KEY` — Outreach
- `GOOGLE_SHEETS_CREDENTIALS_JSON` + sheet IDs — Tracker
- `GITHUB_TOKEN` — Docs automation

See `.env.example` for the full list.

### 3. Validate setup

```bash
python -c "from shared.config_loader import load_config; c = load_config(); print('Config OK:', c.profile.name)"
python -c "from shared.db import init_db; init_db(); print('DB OK')"
python -c "from shared.secrets import validate_secrets; validate_secrets(); print('Secrets OK')"
```

### 4. Start the Telegram bot

```bash
python orchestrator/orchestrator.py
```

---

## Folder Structure

```
automation-system/
├── config/           ← config.yaml (master config) + JSON schema
├── orchestrator/     ← Telegram bot, command router, health checks
├── agents/           ← 8 specialist agents
│   ├── job_discovery/
│   ├── outreach/
│   ├── email_triage/
│   ├── project_autopilot/
│   ├── market_research/
│   ├── ai_radar/
│   ├── resume/
│   └── github_docs/
├── shared/           ← Config loader, DB, logger, secrets (used by all agents)
├── assets/           ← Master resume + tailored resume outputs
├── docs/             ← Auto-generated weekly reports and AI radar digests
├── logs/             ← Structured JSON logs (gitignored)
├── .github/workflows/← GitHub Actions cron jobs
└── n8n/workflows/    ← n8n workflow JSON exports
```

---

## Phone Commands (Telegram)

Send these commands to `@ShreyasAutomationBot`:

| Command | What It Does |
|---|---|
| `STATUS` | Full system health check |
| `HELP` | List all commands |
| `RUN_JOB_SWEEP` | Trigger job discovery now |
| `RUN_OUTREACH_SAFE` | Find recruiters + draft emails for approval |
| `PAUSE_OUTREACH duration_hours=24` | Pause outreach for N hours |
| `RUN_RESUME_TAILORING job_id=...` | Tailor resume for a specific job |
| `RESCAN_AI_TOOLS` | Run AI radar now |
| `RESCAN_MARKET` | Run market research now |
| `UPDATE_GITHUB_DOCS` | Generate and commit docs + reports |
| `START_PROJECT repo_name=... task_type=... description=...` | Run a coding task |
| `GENERATE_DAILY_DIGEST` | Send full digest now |

---

## Design Principles

- `config.yaml` is the single source of truth. Change one file, behavior changes everywhere.
- **Human-in-the-loop is required for:** sending emails, applying to jobs, force-pushing, deleting files, publishing content.
- Secrets live only in `.env` and GitHub Secrets — never in config.yaml or code.
- All agents log structured JSON to `logs/<agent>.log`.
- Rate limits and ethics rules are enforced in code, not just documented.

---

## Architecture

See [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) for the full specification including all agent behaviors, schemas, prompts, and implementation plan.

---

## Implementation Status

- [x] Session 1 — Foundation (folder structure, config, shared modules)
- [x] Session 2 — Telegram Bot + Orchestrator
- [x] Session 3 — AI Radar Agent
- [x] Session 4 — Job Discovery Agent
- [x] Session 5 — Email Triage Agent
- [x] Session 6 — Resume Agent
- [x] Session 7 — GitHub Docs Agent
- [x] Session 8 — n8n Workflows
- [x] Session 9 — Outreach Agent
- [x] Session 10 — Project Autopilot + Market Research

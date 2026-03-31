# Automation System — Usage Guide
> **Owner:** Shreyas Khandare | AI/LLM Engineer  
> **Repo:** `github.com/ShreyasKhandare/automation-system` (private)  
> **Version:** 1.0 | March 2026  
> **Purpose:** Complete setup, daily operations, risk management, and cost control reference.

---

## Table of Contents

1. [Pre-Setup Checklist](#1-pre-setup-checklist)
2. [Setup — Step by Step](#2-setup--step-by-step)
3. [Making Automations Live](#3-making-automations-live)
4. [Daily Operations Guide](#4-daily-operations-guide)
5. [Phone Command Reference](#5-phone-command-reference)
6. [Risk & Analysis](#6-risk--analysis)
7. [Cost Handling & Monitoring](#7-cost-handling--monitoring)
8. [Regular Maintenance Schedule](#8-regular-maintenance-schedule)

---

## 1. Pre-Setup Checklist

Complete all of these before touching any code. Each item is a dependency for something downstream.

### Accounts to Create (if not already done)

| Service | URL | Plan | Why Needed |
|---|---|---|---|
| Anthropic Console | console.anthropic.com | Pay-as-you-go | Claude API for all agent intelligence |
| Telegram | telegram.org | Free | Phone control + all notifications |
| Google Cloud Console | console.cloud.google.com | Free tier | Gmail API + Google Sheets API |
| Apollo.io | apollo.io | Free (50 credits/mo) | Recruiter discovery |
| Hunter.io | hunter.io | Free (25/mo) | Email verification fallback |
| SerpAPI | serpapi.com | Free (100/mo) | Google Jobs scraping |
| Notion | notion.so | Free | Market research output |
| Apify | apify.com | Free tier | LinkedIn scraping (optional, Week 2+) |

### Keys & Tokens to Generate (before any setup step)

Work through this list in order — some depend on others:

```
□ ANTHROPIC_API_KEY
    → console.anthropic.com → API Keys → Create Key
    → Set a $12/month hard spending limit immediately after (Settings → Limits)

□ TELEGRAM_BOT_TOKEN
    → Open Telegram → search @BotFather → /newbot
    → Name it: ShreyasAutomationBot
    → Copy the token it gives you

□ TELEGRAM_CHAT_ID
    → Open Telegram → search @userinfobot → /start
    → It replies with your numeric user ID — copy it

□ GMAIL_CLIENT_ID + GMAIL_CLIENT_SECRET
    → console.cloud.google.com → New Project → "shreyas-automation"
    → APIs & Services → Enable: Gmail API, Google Sheets API
    → APIs & Services → Credentials → Create OAuth2 Client ID
    → Application type: Desktop App
    → Download JSON → open it → copy client_id and client_secret

□ GMAIL_REFRESH_TOKEN
    → After adding CLIENT_ID and CLIENT_SECRET to .env:
    → Run: python -m shared.gmail_auth
    → Browser opens → sign in → approve → token saved to .env automatically

□ GOOGLE_SHEETS_CREDENTIALS_JSON
    → console.cloud.google.com → same project → Credentials
    → Create Service Account → name: "shreyas-sheets-bot"
    → Keys tab → Add Key → JSON → download the file
    → Store at: /path/to/service-account.json (NOT inside the repo)
    → The .gitignore already excludes *credentials*.json and service-account*.json

□ GOOGLE_SHEET_ID_JOBS + GOOGLE_SHEET_ID_OUTREACH
    → Go to sheets.google.com → create two sheets: "Job Tracker" and "Outreach CRM"
    → Share each with the service account email (from the JSON file, field: client_email)
    → Role: Editor
    → Copy the ID from each sheet URL: docs.google.com/spreadsheets/d/[THIS_PART]/edit

□ SERPAPI_API_KEY
    → serpapi.com → Dashboard → copy API key

□ APOLLO_API_KEY
    → apollo.io → Settings → API → copy key

□ HUNTER_API_KEY
    → hunter.io → Dashboard → API → copy key

□ GITHUB_TOKEN
    → github.com → Settings → Developer Settings → Fine-grained tokens
    → Generate new token → name: "automation-system-bot" → expiry: 90 days
    → Repository access: Only select → pick: automation-system, finops-sentinel, portfolio-website
    → Permissions: Contents (Read/Write), Pull requests (Read/Write), Issues (Read/Write), Metadata (Read)
    → Copy the token immediately — it's only shown once

□ NOTION_API_KEY + NOTION_DATABASE_ID_MARKET
    → notion.so → Settings → Connections → Develop or manage integrations
    → New integration → name: "shreyas-automation" → copy secret
    → Create a Notion page called "Market Research" → Share → Invite the integration
    → Copy the database ID from the URL (the 32-char hex string after the last slash)
```

---

## 2. Setup — Step by Step

### Step 1 — Clone the Repo Locally

```bash
# On your Windows machine in Git Bash:
cd /d/SHREYAS
git clone https://github.com/ShreyasKhandare/automation-system.git
cd automation-system
```

### Step 2 — Set Up Python Environment

```bash
python -m venv .venv
source .venv/Scripts/activate   # Git Bash on Windows
# or: .venv\Scripts\activate    # PowerShell on Windows

pip install --upgrade pip
pip install \
  anthropic \
  feedparser \
  requests \
  pyyaml \
  python-dotenv \
  jsonschema \
  beautifulsoup4 \
  google-api-python-client \
  google-auth \
  google-auth-httplib2 \
  python-telegram-bot \
  jinja2 \
  pandoc
```

### Step 3 — Create and Fill .env

```bash
cp .env.example .env
# Open .env in any text editor and fill in every value from Step 1 above
```

Verify it loaded correctly:

```bash
python -c "from shared.secrets import validate_secrets; validate_secrets(); print('All secrets OK')"
```

### Step 4 — Initialise the Database

```bash
python -c "from shared.db import init_db; init_db(); print('Database OK')"
```

Confirm the file was created:

```bash
ls automation.sqlite   # should exist now
```

### Step 5 — Validate the Config

```bash
python -c "from shared.config_loader import load_config; c = load_config(); print('Config OK:', c.profile.name)"
```

If this prints `Config OK: Shreyas Khandare` — you're good. Any error here means `config.yaml` has a typo or missing field.

### Step 6 — Generate Gmail Refresh Token (one-time)

```bash
python -m shared.gmail_auth
# Browser opens automatically
# Sign in with your Gmail account
# Click Allow
# Token is saved to .env as GMAIL_REFRESH_TOKEN
```

### Step 7 — Add GitHub Secrets (for GitHub Actions)

Every secret in your `.env` must also be added to GitHub Secrets so the Actions workflows can use them.

```bash
# Install GitHub CLI if not already installed: https://cli.github.com/
gh auth login

# Add each secret (replace values with your actual keys):
gh secret set ANTHROPIC_API_KEY --body "sk-ant-..."
gh secret set TELEGRAM_BOT_TOKEN --body "123456:ABC..."
gh secret set TELEGRAM_CHAT_ID --body "987654321"
gh secret set SERPAPI_API_KEY --body "..."
gh secret set APOLLO_API_KEY --body "..."
gh secret set HUNTER_API_KEY --body "..."
gh secret set GMAIL_CLIENT_ID --body "..."
gh secret set GMAIL_CLIENT_SECRET --body "..."
gh secret set GMAIL_REFRESH_TOKEN --body "..."
gh secret set GOOGLE_SHEET_ID_JOBS --body "..."
gh secret set GOOGLE_SHEET_ID_OUTREACH --body "..."
gh secret set GOOGLE_SHEETS_CREDENTIALS_JSON --body "$(cat /path/to/service-account.json)"
gh secret set GITHUB_TOKEN --body "github_pat_..."
gh secret set NOTION_API_KEY --body "secret_..."
gh secret set NOTION_DATABASE_ID_MARKET --body "..."
gh secret set APIFY_API_TOKEN --body "..."

# Verify all secrets are set:
gh secret list
```

### Step 8 — Add Your Base Resume

```bash
# Create your master resume as a Markdown file:
# Save it at: assets/resume_base.md
# Format: standard sections — Experience, Education, Skills, Projects
# Use plain text only — no tables, no images (ATS requirement)
```

### Step 9 — Dry-Run Every Agent

Run each agent in dry-run mode before enabling live sends. This verifies the full pipeline without spending credits or sending anything.

```bash
# AI Radar (safest to test first — no write ops)
python agents/ai_radar/notifier.py --dry-run --verbose

# Job Discovery
python agents/job_discovery/notifier.py --dry-run --verbose

# Telegram Bot (send /start from your phone while this runs)
python orchestrator/orchestrator.py --once

# Health check
python orchestrator/orchestrator.py --health
```

Check the output of each. If a dry-run passes without errors, that agent is ready to go live.

### Step 10 — Enable Remote Control (Phone Access)

```bash
# Verify Claude Code version
claude --version   # must be v2.1.51 or later
# Update if needed:
npm update -g @anthropic-ai/claude-code

# Enable Remote Control for all sessions permanently:
# Inside Claude Code, type: /config
# → Set "Enable Remote Control for all sessions" to true

# Start your first named session:
cd /d/SHREYAS/automation-system
claude remote-control --name "automation-main"
# → QR code appears → scan with Claude mobile app → you're connected
```

---

## 3. Making Automations Live

Enable in this exact order. Validate each one before enabling the next.

### Phase 1 — Days 1–2 (Zero Risk, Read-Only)

These agents only read data and send Telegram messages. No emails sent, no commits made.

```bash
# 1. AI Radar — enable GitHub Actions workflow
# Go to: github.com/ShreyasKhandare/automation-system → Actions
# Click "AI Radar Briefing" → Enable workflow
# Click "Run workflow" → dry_run: false → Run
# → Check Telegram for briefing within 3 minutes

# 2. Job Discovery — enable workflow
# Click "Job Discovery" → Enable workflow
# Click "Run workflow" → dry_run: false, stealth: false → Run
# → Check Telegram for job digest within 5 minutes
# → Check Google Sheet "Job Tracker" for new rows
```

**Validation checkpoint:** You should receive a Telegram message for each. If not, check the Actions run log for errors before proceeding.

### Phase 2 — Day 3 (Email Read Access)

```bash
# 3. Email Triage — enable workflow
# Click "Email Triage" → Enable workflow
# Runs automatically every 2 hours
# → Check Gmail for new AI/* labels after 2 hours
# → Check Telegram for evening digest at 6pm

# Test immediately:
python agents/email_triage/poller.py --dry-run --verbose
```

### Phase 3 — Day 4 (GitHub Write Access)

```bash
# 4. GitHub Docs — enable workflow
# Click "GitHub Docs" → Enable workflow
# Runs automatically at 11pm EST
# First commit will appear in your repo the next morning
```

### Phase 4 — Week 2 (Outreach — Requires Extra Validation)

Do NOT enable outreach until Phases 1–3 have been running error-free for at least 3 days.

```bash
# Before enabling outreach, verify the approval gate works:
python agents/outreach/finder.py --dry-run --verbose
# → Should find recruiters but NOT send anything
# → Should send a Telegram message with an Approve/Reject button
# → Tap Reject to confirm the gate works

# Only then enable the workflow:
# Start with max_contacts_per_day: 5 in config.yaml (warm-up week 1)
# Increase to 8 after one week with no issues
```

### Phase 5 — Week 2 (Remote Project Building)

```bash
# Test from your phone:
# Send via Telegram: START PROJECT finops-sentinel docs "update README with latest metrics"
# → Claude Code should start working on your local machine
# → You should receive a completion report within 10-20 minutes
```

---

## 4. Daily Operations Guide

### What Happens Automatically (You Do Nothing)

| Time | What Fires | What You Get |
|---|---|---|
| 7:00am EST (weekdays) | Job Discovery | Telegram: ranked job digest |
| 8:00am EST (daily) | AI Radar | Telegram: AI tools briefing |
| Every 2 hours | Email Triage | Gmail labels applied; Telegram alert if interview/offer detected |
| 6:00pm EST (daily) | Email Digest | Telegram: summary of today's emails |
| 9:00am EST (daily) | Health Check | Telegram: system status (green/yellow/red) |
| 11:00pm EST (daily) | GitHub Docs | Auto-commit of daily artifacts |
| Sunday 9:00am EST | Market Research | Telegram: weekly intelligence digest |

### What You Do (Manual Triggers from Phone)

**When you see a high-score job in the digest:**
```
RUN RESUME_TAILORING JOB_ID=job_20260330_sardine_ai_eng
→ Wait 3-5 minutes
→ Tailored resume appears in Google Sheet + GitHub
→ Open the job link and apply manually
```

**When you want to work on a project remotely:**
```
START PROJECT finops-sentinel bugfix "description of what to fix"
→ Claude Code executes on your PC at home
→ Completion report arrives on Telegram with PR link
→ You review the PR from your phone
```

**Morning routine (2 minutes):**
```
1. Read AI Radar briefing (auto-delivered at 8am)
2. Read job digest (auto-delivered at 7am)
3. Send: /health → confirm everything is green
4. If any yellow/red: send /errors → diagnose
```

**End of day (1 minute):**
```
1. Read 6pm email digest
2. Check for any unanswered Telegram alerts
3. Send: /costs → confirm you're on track for the month
```

---

## 5. Phone Command Reference

All commands sent via Telegram to `@ShreyasAutomationBot`. Bot only responds to your chat ID.

### System Commands

| Command | What It Does | When to Use |
|---|---|---|
| `/health` | Quick green/yellow/red per agent | Every morning |
| `/status` | Full health report with timestamps | When something feels off |
| `/errors` | All errors in last 24 hours | When health shows red |
| `/logs job_discovery` | Last 30 log lines for an agent | Debugging a specific agent |
| `/costs` | Claude API spend this month | Daily check |
| `/help` | List all commands | When you forget a command |

### Job Search Commands

| Command | What It Does |
|---|---|
| `RUN JOB_SWEEP` | Trigger immediate job discovery (outside normal 7am schedule) |
| `RUN JOB_SWEEP STEALTH` | Same but with lower rate limits (slower, safer) |
| `/jobs today` | Show today's job digest from cache |
| `RUN RESUME_TAILORING JOB_ID=...` | Tailor resume for a specific job ID |
| `/resumes list` | All tailored resumes created so far |

### Outreach Commands

| Command | What It Does |
|---|---|
| `RUN OUTREACH SAFE` | Find recruiters + draft emails → sends to Telegram for your approval |
| `PAUSE OUTREACH 24H` | Pause all outreach for 24 hours |
| `PAUSE OUTREACH 48H` | Pause for 48 hours |
| `RESUME OUTREACH` | Resume paused outreach |
| `/outreach status` | Stats: sent, replied, pending approval |
| `/outreach credits` | Apollo credits used this month vs budget |

### Project Commands

| Command | What It Does |
|---|---|
| `START PROJECT finops-sentinel bugfix "description"` | Run a coding task on FinOps Sentinel |
| `START PROJECT portfolio-website content_update "description"` | Update portfolio site |
| `/projects status` | Last commit, branch, test status per repo |
| `/commits` | Last 5 commits across all tracked repos |

### Intel & Research Commands

| Command | What It Does |
|---|---|
| `/briefing` | Today's AI tools briefing (if you missed 8am) |
| `RESCAN AI_TOOLS` | Run AI radar right now (outside normal schedule) |
| `RESCAN MARKET` | Run weekly market research right now |
| `UPDATE GITHUB_DOCS` | Generate and commit docs immediately |
| `GENERATE DAILY_DIGEST` | Send full digest right now |

---

## 6. Risk & Analysis

### 🔴 HIGH RISK — Act Immediately If These Occur

---

**RISK H1 — API Key Accidentally Committed to GitHub**

- Probability: Medium (happens to everyone eventually)
- Impact: Key stolen within minutes by automated scanners. Unauthorized API usage billed to you.
- Detection: GitHub secret scanning alert (enable this), or unexpected Anthropic bill spike
- Prevention:
  - `.gitignore` already excludes `.env`
  - `commit_scanner.py` scans for known key patterns before every commit
  - Enable GitHub Secret Scanning: repo → Settings → Code security → Secret scanning → Enable
- Fix if it happens:
  1. Rotate the exposed key immediately (takes 30 seconds on the provider's dashboard)
  2. Force-push to remove the commit from history: `git filter-branch` or `git rebase`
  3. Check provider's usage logs for unauthorized calls
  4. Update GitHub Secrets and local `.env` with new key

---

**RISK H2 — Gmail OAuth Token Leaked or Expired**

- Probability: Low (but high impact when it happens)
- Impact: Email triage stops silently. You miss interview invites and recruiter replies.
- Detection: Email triage workflow fails with `401 Unauthorized`. Health check shows red for `email_triage`.
- Prevention: Calendar reminder every 5 months to regenerate token
- Fix:
  ```bash
  python -m shared.gmail_auth   # regenerates token
  gh secret set GMAIL_REFRESH_TOKEN --body "$(grep GMAIL_REFRESH_TOKEN .env | cut -d= -f2)"
  ```

---

**RISK H3 — Outreach Bot Sends Emails Without Approval Gate Working**

- Probability: Low if setup correctly, but critical if it occurs
- Impact: Emails sent to wrong people, unpersonalized, or in bulk — damages professional reputation
- Prevention:
  - `mode: "assisted"` in config.yaml is the correct setting — never change to "auto"
  - Approval gate tested during Phase 4 setup before any live sends
  - Rate limits enforced in code: `get_today_send_count()` checked before every send
- Fix if it happens:
  1. Send `PAUSE OUTREACH 48H` immediately from phone
  2. Check `outreach` table in SQLite for unauthorized sends
  3. Review `logs/outreach.log` for what triggered it
  4. Revert any config.yaml changes that touched `mode` or `max_contacts_per_day`

---

**RISK H4 — Claude Code Remote Session Executes Destructive Command**

- Probability: Very low (Claude Code has safety rails)
- Impact: Files deleted, branches force-pushed, data lost
- Prevention:
  - `FORBIDDEN_ACTIONS` list in `constraints.py` blocks: delete branch, force push, merge to main, drop table
  - `require_pr: true` for finops-sentinel means nothing goes to main directly
  - `max_lines_changed_per_run: 200` limits blast radius
- Fix:
  1. `git reflog` to find the last good commit
  2. `git reset --hard <commit>` to restore
  3. GitHub preserves commit history — nothing is truly lost if pushed

---

### 🟡 MEDIUM RISK — Monitor Weekly, Fix Within 48 Hours

---

**RISK M1 — SerpAPI Free Tier Exhausted**

- Probability: High if running daily sweeps through all 6 target titles
- Impact: Job discovery returns zero results. You miss job postings.
- Detection: Job digest arrives but shows "0 jobs found". SerpAPI dashboard shows 0 credits.
- Monthly budget: 100 calls. Your usage: ~4 queries/day × 22 weekdays = 88 calls — right at the limit.
- Prevention:
  - `scraper.py` already caps title queries at `[:4]` — do not increase this
  - Reduce to 3 active target titles if credits run low mid-month
- Fix:
  - Disable `serpapi_google_jobs.enabled` in config.yaml until month resets
  - Fallback: Otta RSS + Greenhouse scrape + Indeed RSS still work (no credits needed)
  - Upgrade SerpAPI ($50/mo = 5,000 calls) if ROI justifies it

---

**RISK M2 — Apollo Credits Exhausted Mid-Month**

- Probability: High without credit tracking
- Impact: Outreach pipeline stalls. No new recruiter discovery.
- Detection: `/outreach credits` shows 45/45 used. Telegram alert fires automatically (built in).
- Prevention: The Apollo credit guard added in `finder.py` handles this automatically
- Fix when credits run out:
  - System auto-pauses Apollo and notifies you via Telegram
  - Fallback: Hunter.io email pattern guessing for known contacts
  - Manual: Add high-value targets to `company_list.csv` manually for next month

---

**RISK M3 — GitHub Actions Minutes Running Low**

- Probability: Low for normal usage, Medium if email triage hangs
- Impact: Scheduled workflows stop running. Job discovery, email triage, AI briefing all halt.
- Detection: GitHub → repo → Actions → Usage shows minutes consumed
- Monthly budget: 2,000 minutes. Normal usage: ~1,010 minutes (within budget)
- Prevention: All workflows have `timeout-minutes` set (15–20 min max per run)
- Fix if approaching 2,000:
  1. Disable email triage temporarily (highest frequency workflow)
  2. Switch email triage to every 4 hours instead of 2: change `'0 */2 * * *'` to `'0 */4 * * *'`
  3. Or upgrade to GitHub Pro ($4/mo = 3,000 minutes)

---

**RISK M4 — GitHub Fine-Grained PAT Expiry**

- Probability: Certain (it expires at 90 days by design)
- Impact: GitHub Docs agent cannot commit. No auto-documentation. Resume variants not committed.
- Detection: `github_docs` agent shows red in health check. Error: `401 Bad credentials`
- Prevention: Calendar reminder at day 80 to rotate
- Fix:
  ```bash
  # Generate new PAT on github.com → Settings → Developer Settings → Fine-grained tokens
  gh secret set GITHUB_TOKEN --body "github_pat_NEW_TOKEN_HERE"
  # Update local .env as well
  ```

---

**RISK M5 — Telegram Bot Stops Responding**

- Probability: Low
- Impact: No phone control. You can't trigger agents remotely. No notifications.
- Causes: Bot process crashed, network issue, Telegram API rate limit
- Detection: Send any command from phone — no response within 60 seconds
- Fix:
  ```bash
  # On your PC:
  python orchestrator/orchestrator.py   # restart the bot
  # Or from GitHub Actions: manually trigger any workflow to verify Actions still work
  # Bot token never expires — this is always a process/network issue
  ```

---

**RISK M6 — Notified of a Job but Resume Tailoring Fails**

- Probability: Low-Medium (Pandoc not installed, or Claude token limit hit)
- Impact: No tailored resume for a high-score job. You apply with generic resume.
- Detection: `RUN RESUME_TAILORING` returns an error message on Telegram
- Fix:
  1. Check `logs/resume.log` for the specific error
  2. If Pandoc not found: `choco install pandoc` (Windows) or `sudo apt install pandoc` (Linux)
  3. If Claude token limit: the JD is too long — truncate `description_raw` to 3,000 chars in `jd_parser.py`
  4. Fallback: apply `resume_base.md` manually and tailor it yourself

---

### 🟢 LOW RISK — Monitor Monthly, Fix When Noticed

---

**RISK L1 — Notion Token Disconnected**

- Impact: Market research output not written to Notion. Weekly report still commits to GitHub.
- Fix: notion.so → Settings → Connections → reconnect integration

**RISK L2 — Google Sheets Service Account Loses Access**

- Impact: Job Tracker and Outreach CRM not updated. SQLite still works (local backup).
- Fix: Re-share both sheets with the service account email (from the credentials JSON, field: `client_email`)

**RISK L3 — arXiv/HuggingFace RSS Structure Changes**

- Impact: Some AI Radar sources return 0 items
- Fix: Update feed URL in `aggregator.py`. These sources are stable but not guaranteed forever.

**RISK L4 — Greenhouse Changes Board API Structure**

- Impact: Greenhouse company scrape returns 0 jobs
- Fix: Update `_GH_BOARD_URL` format in `scraper.py` if Greenhouse changes their board URL pattern

**RISK L5 — Portfolio Website Deploy Breaks After Autopilot Edit**

- Impact: Portfolio site shows errors or blank page
- Prevention: `require_pr: false` for portfolio but edits are content-only (max 100 lines changed)
- Fix: `git revert HEAD` on the portfolio repo, redeploy

---

## 7. Cost Handling & Monitoring

### Monthly Cost Breakdown (Realistic)

| Resource | Free Tier | Your Normal Usage | Overage Risk | Monthly Cost |
|---|---|---|---|---|
| **Claude API** | None (pay-as-you-go) | ~1.5M tokens | Medium | ~$6–10 |
| **SerpAPI** | 100 calls | ~88 calls | Low-Medium | $0 (free) |
| **Apollo.io** | 50 credits | ~45 credits | High | $0 (managed) |
| **Hunter.io** | 25 searches | ~10 searches | Low | $0 (free) |
| **GitHub Actions** | 2,000 min | ~1,010 min | Low | $0 (free) |
| **Google APIs** | Very high limits | Minimal | Very Low | $0 (free) |
| **Telegram Bot** | Unlimited | — | None | $0 (free) |
| **Notion** | Unlimited personal | — | None | $0 (free) |
| **Total** | | | | **~$6–10/month** |

### The Only Variable That Can Spike: Claude API

Everything else is either free or rate-limited by design. Claude API is the only resource where unexpected usage patterns can cause bill surprises.

**What drives Claude API cost up:**

| Action | Tokens per call | Cost |
|---|---|---|
| Score 15 jobs (1 batch) | ~8,000 | ~$0.03 |
| AI Radar filter (30 items) | ~12,000 | ~$0.05 |
| Tailor one resume (deep) | ~10,000 | ~$0.04 |
| Classify 10 emails | ~3,000 | ~$0.01 |
| Natural language command fallback | ~1,500 | ~$0.005 |
| **Entire day of normal activity** | ~80,000 | ~$0.35 |
| **Full month (normal)** | ~1.5M | ~$6–10 |

**The safety net already in place:**
- Hard budget cap set at Anthropic Console ($12/month) — API stops working, not your card charged
- `/costs` command shows MTD spend on demand
- `log_health()` records token count per run in SQLite

### Daily Habit: The 10-Second Cost Check

Every evening before closing Telegram, send:

```
/costs
```

Expected output:
```
💰 Claude API Usage (this month)
Tokens used: ~420,000
Estimated cost: ~$1.47
Budget: $10.00/month
```

If you are more than 50% through the month AND more than 60% through the budget — reduce frequency:

```yaml
# config.yaml adjustment:
research_and_discovery:
  scan_frequency: "weekly"    # already weekly — good
  summary_max_items: 8        # reduce from 10 to 8 (saves ~20% AI Radar tokens)

job_search_preferences:
  score_threshold: 7          # raise from 6 to 7 (fewer jobs scored by Claude)
```

### Cost Escalation Thresholds

| MTD Spend | Action |
|---|---|
| Under $6 | All good. Normal usage. |
| $6–$8 | Normal for active outreach + resume tailoring week. Monitor daily. |
| $8–$10 | Slow down. Reduce `summary_max_items` and raise `score_threshold`. Pause non-essential on-demand commands. |
| Approaching $10 | Pause outreach agent (highest per-run cost). Let only scheduled agents run. |
| Hit $12 cap | Anthropic API returns 429. All agents fail. Rotate to next month — cap resets on billing date. |

### Free Tier Quota Tracker (Check These Weekly)

Keep this table updated. Add it to your Sunday market research review:

| Service | Monthly Limit | Used (Week 1) | Used (Week 2) | Used (Week 3) | Used (Week 4) | Action if >80% |
|---|---|---|---|---|---|---|
| SerpAPI | 100 calls | | | | | Reduce target_titles to 3 |
| Apollo | 45 credits (budgeted) | | | | | Auto-paused by code |
| Hunter | 25 searches | | | | | Switch to pattern guessing |
| GitHub Actions | 2,000 min | | | | | Reduce email triage frequency |
| Claude API | $10 budget | | | | | See escalation table above |

### If You Decide to Scale Up (Paid Tiers)

When outreach starts generating interviews, the ROI calculation changes:

| Upgrade | Cost | What It Unlocks |
|---|---|---|
| Apollo Basic | $49/mo | 480 credits — full outreach 5 days/week without worry |
| SerpAPI Starter | $50/mo | 5,000 calls — job discovery multiple times per day |
| Anthropic Max | $200/mo | 5x rate limits, priority access, 1M context |
| GitHub Pro | $4/mo | 3,000 Actions minutes — comfortable headroom |

**Recommended first upgrade:** Apollo Basic ($49/mo), only after you confirm outreach is generating replies. Everything else stays on free tier comfortably.

---

## 8. Regular Maintenance Schedule

### Every Day (2 minutes)

```
□ Read AI Radar briefing (8am Telegram — auto)
□ Read job digest (7am Telegram — auto)
□ Send /health → confirm green
□ Send /costs → confirm on budget
□ Act on any Telegram alerts (interview flags, approval requests)
```

### Every Week (10 minutes, Sunday)

```
□ Read market research digest (9am Telegram — auto)
□ Update the quota tracker table above with actual usage numbers
□ Review the Job Tracker Google Sheet — mark applied/rejected statuses
□ Review the Outreach CRM — any follow-ups due this week?
□ Check GitHub → Actions → all workflows passing?
□ Run: python orchestrator/orchestrator.py --health → print to terminal
□ Review assets/resumes/index.json — any old variants to archive?
```

### Every Month (30 minutes, first Monday)

```
□ Check all free tier quotas reset (SerpAPI, Apollo, Hunter)
□ Review Claude API bill on console.anthropic.com
□ Check GitHub Actions minutes used (repo → Settings → Billing)
□ Run all agents with --dry-run to confirm nothing is broken
□ Review config.yaml — do target_titles, salary range, or skills need updating?
□ Update assets/resume_base.md if you've done new projects or learned new skills
□ Run: git log --oneline -20 (confirm auto-commits are happening as expected)
```

### Every 80 Days (15 minutes — calendar reminder)

```
□ Rotate GitHub Fine-Grained PAT (expires at 90 days)
    → github.com → Settings → Developer Settings → Fine-grained tokens → Regenerate
    → gh secret set GITHUB_TOKEN --body "new_token"
    → Update local .env
□ Check Gmail OAuth token health (expires at 6 months)
    → python agents/email_triage/poller.py --dry-run
    → If 401 error: python -m shared.gmail_auth
```

### Every 5 Months (30 minutes — calendar reminder)

```
□ Regenerate Gmail OAuth Refresh Token
    → python -m shared.gmail_auth
    → gh secret set GMAIL_REFRESH_TOKEN --body "new_token"
□ Review and rotate any API keys in use for more than 90 days
    → Anthropic, Apollo, Hunter, SerpAPI, Notion
```

### When You Get a New Job / Major Life Change

```
□ Pause all outreach: PAUSE OUTREACH 720H (30 days)
□ Update config.yaml: set company_blacklist with your new employer
□ Update assets/resume_base.md with the new role
□ Update profile.bio and branding_statement in config.yaml
□ Update profile.target_titles if career direction shifts
□ Consider open-sourcing the automation-system repo (great portfolio piece)
```

---

*Keep this file in the root of your automation-system repo and update it as the system evolves.*  
*Last section to update after any config change: the quota tracker table in Section 7.*

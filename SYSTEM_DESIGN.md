# Job Search, Resume & Career Automation System
> **Owner:** Shreyas Khandare — AI/LLM Engineer  
> **Stack:** Claude Code + Cursor Pro + GitHub Actions + n8n + Telegram  
> **Repo:** `github.com/ShreyasKhandare/automation-system` (private)  
> **Version:** 1.0 | March 2026  
> **Status:** Implementation-ready specification — feed this file directly into Claude Code / Cursor to generate all code.

---

## Table of Contents

1. [System Overview & Philosophy](#1-system-overview--philosophy)
2. [Config Schema (config.yaml)](#2-config-schema-configyaml)
3. [Agent 1 — Job Discovery](#3-agent-1--job-discovery)
4. [Agent 2 — Recruiter & Cold Outreach](#4-agent-2--recruiter--cold-outreach)
5. [Agent 3 — Email Triage](#5-agent-3--email-triage)
6. [Agent 4 — Project Autopilot](#6-agent-4--project-autopilot)
7. [Agent 5 — Market & Profile Research](#7-agent-5--market--profile-research)
8. [Agent 6 — AI Tools Radar](#8-agent-6--ai-tools-radar)
9. [Agent 7 — Resume Optimization & Tailoring](#9-agent-7--resume-optimization--tailoring)
10. [Agent 8 — GitHub Docs & Profile Automation](#10-agent-8--github-docs--profile-automation)
11. [Scheduling, Triggers & Remote Control](#11-scheduling-triggers--remote-control)
12. [Mobile Command Vocabulary](#12-mobile-command-vocabulary)
13. [Data Storage & Logging](#13-data-storage--logging)
14. [Tooling Matrix](#14-tooling-matrix)
15. [Safety, ToS & Anti-Spam Rules](#15-safety-tos--anti-spam-rules)
16. [Sequence Diagrams](#16-sequence-diagrams)
17. [Folder Structure](#17-folder-structure)
18. [Implementation Plan for Claude Code & Cursor](#18-implementation-plan-for-claude-code--cursor)

---

## 1. System Overview & Philosophy

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    SHREYAS AUTOMATION SYSTEM v1.0                       │
│              Claude Code · Cursor Pro · GitHub Actions · n8n            │
├─────────────────────┬───────────────────────────────────────────────────┤
│  PHONE (Control)    │  Telegram Bot · Claude App Remote Control         │
├─────────────────────┼───────────────────────────────────────────────────┤
│  ORCHESTRATOR       │  orchestrator.py — routes commands to agents      │
│                     │  Reads config.yaml — all behavior driven from it  │
├─────────────────────┼───────────────────────────────────────────────────┤
│  AGENTS (8 total)   │  Job Discovery, Outreach, Email Triage,           │
│                     │  Project Autopilot, Market Research,              │
│                     │  AI Radar, Resume Tailoring, GitHub Docs          │
├─────────────────────┼───────────────────────────────────────────────────┤
│  INTELLIGENCE       │  Claude API (claude-sonnet-4-20250514)            │
│                     │  Scoring · Drafting · Classifying · Summarizing   │
├─────────────────────┼───────────────────────────────────────────────────┤
│  EXECUTION          │  Claude Code (local, via Remote Control)          │
│                     │  Cursor Automations (cloud, event/schedule-based) │
│                     │  GitHub Actions (cron, free tier)                 │
│                     │  n8n (API glue, webhooks, email routing)          │
├─────────────────────┼───────────────────────────────────────────────────┤
│  DATA               │  SQLite (local fast store)                        │
│                     │  Google Sheets (tracker, CRM, visible from phone) │
│                     │  Notion (project ideas, briefings)                │
│                     │  Private GitHub repo (logs, reports, docs)        │
└─────────────────────┴───────────────────────────────────────────────────┘
```

**Core design rules:**
- `config.yaml` is the single source of truth. Every agent reads it. Change one file, behavior changes everywhere.
- Claude Code = the reasoning and building brain. Runs locally, has full filesystem access.
- Cursor Automations = always-on cloud agents for event-driven tasks (PR triggers, Slack, GitHub events). Launched March 5, 2026. No local resources consumed.
- GitHub Actions = the free always-on scheduler for cron-based pipelines.
- n8n (self-hosted free tier) = the API glue layer. Connects Gmail, Telegram, webhooks, Slack without writing custom HTTP code.
- Telegram = your single notification + command pane on your phone.
- **Human-in-the-loop is required for:** sending emails, applying to jobs, committing code with `--force`, and any irreversible action.

---

## 2. Config Schema (config.yaml)

This is the master config. All agents import it at startup. It is version-controlled in the repo (with secrets stripped — secrets live in `.env` and GitHub Secrets only).

```yaml
# config.yaml — Shreyas Khandare Automation System
# Last updated: 2026-03-30
# NEVER commit secrets here. Use .env for keys.

profile:
  name: "Shreyas Khandare"
  email: "shreyas.khandare@outlook.com"
  linkedin: "https://linkedin.com/in/shreyas-khandare"
  github: "https://github.com/ShreyasKhandare"
  portfolio: "https://shreyaskhandare.dev"  # update when live
  location: "Tallahassee, FL (Open to Remote)"
  bio: >
    AI/LLM Engineer with MS in CS from Florida State University.
    Builds production RAG pipelines, multi-agent LLM systems, and
    LLM-powered APIs. Currently at FDLE (systems engineering).
    Flagship: FinOps Sentinel — LangGraph multi-agent compliance RAG.
  skills:
    primary: [LangChain, LangGraph, ChromaDB, FastAPI, Streamlit, Python, RAG, Multi-Agent AI]
    secondary: [C#, ASP.NET, SQL Server, JavaScript, TypeScript, SharePoint, Git]
    learning: [MCP servers, Fine-tuning, Multimodal LLMs]
  seniority: "Mid-level (2-5 years AI/LLM experience)"
  target_titles:
    - "AI Engineer"
    - "LLM Engineer"
    - "ML Engineer"
    - "GenAI Engineer"
    - "AI/ML Software Engineer"
    - "Applied AI Engineer"
  target_industries: [FinTech, RegTech, AI-native startups, Compliance Tech]
  resume_base_path: "assets/resume_base.md"
  branding_statement: >
    I ship production AI systems. FinOps Sentinel demonstrates RAG +
    multi-agent orchestration at production scale — not a tutorial project.

job_search_preferences:
  locations:
    - "Remote"
    - "Tallahassee, FL"
    - "Tampa, FL"
    - "Orlando, FL"
    - "Miami, FL"
  salary:
    min: 110000
    max: 180000
    currency: "USD"
  employment_type: ["full-time"]
  seniority_levels: ["mid", "senior"]
  company_blacklist: []  # add companies you'd never work for
  company_whitelist: []  # blank = consider all
  preferred_tech_stack: [Python, LangChain, FastAPI, RAG, LLM]
  company_size: ["startup", "series-a", "series-b", "mid-size"]  # not FAANG-only
  visa_constraints: "US Authorized"
  relocation: false
  remote_preference: "remote-first"
  score_threshold: 6  # only alert if Claude scores >= 6/10

platforms:
  wellfound:
    enabled: true
    method: "api"
  greenhouse:
    enabled: true
    method: "scrape"
  otta:
    enabled: true
    method: "rss"
  serpapi_google_jobs:
    enabled: true
    method: "api"
  linkedin_apify:
    enabled: false  # toggle when Apify credits available
    method: "apify_actor"
  indeed:
    enabled: true
    method: "rss"

recruiter_outreach:
  target_titles: ["Technical Recruiter", "Engineering Recruiter", "Talent Acquisition", "Hiring Manager"]
  target_seniority: ["individual contributor recruiter", "senior recruiter", "talent lead"]
  max_contacts_per_day: 15
  max_contacts_per_company: 2
  personalization_level: "high"  # low | medium | high
  mode: "assisted"  # assisted (you approve) | semi-auto (sends after 30min if no veto)
  follow_up_cadence_days: [5, 10]
  max_follow_ups: 2
  send_window:
    start_hour: 9
    end_hour: 11
    timezone: "America/New_York"
  warm_up:
    week_1_max: 5
    week_2_max: 10
    week_3_plus_max: 15

email_routing_rules:
  job_important_keywords: ["interview", "offer", "application", "recruiter", "role", "position", "opportunity", "screening", "hiring"]
  job_important_domains: ["greenhouse.io", "lever.co", "workday.com", "myworkdayjobs.com", "jobvite.com"]
  networking_keywords: ["reply", "following up", "coffee chat", "connect", "referral"]
  spam_keywords: ["unsubscribe", "sale", "deal", "% off", "newsletter", "digest"]
  send_daily_digest: true
  digest_time: "18:00"
  digest_timezone: "America/New_York"
  flag_keywords: ["interview scheduled", "offer extended", "next steps", "start date"]
  classification_confidence_threshold: 0.85

project_automation:
  repos:
    - name: "finops-sentinel"
      url: "https://github.com/ShreyasKhandare/finops-sentinel"
      local_path: "D:/SHREYAS/finops-sentinel"
      allowed_tasks: ["bugfix", "docs", "small_feature", "refactor", "test"]
      tech_stack: [Python, LangChain, LangGraph, FastAPI, Streamlit]
      max_lines_changed_per_run: 200
      require_pr: true
      require_tests: true
      ci_integration: false  # set true when CI is set up
    - name: "portfolio-website"
      url: "https://github.com/ShreyasKhandare/portfolio-website"
      local_path: "D:/SHREYAS/Portfolio-Website"
      allowed_tasks: ["content_update", "bugfix", "small_feature"]
      tech_stack: [React, TypeScript, Vite]
      max_lines_changed_per_run: 100
      require_pr: false  # direct commit ok for portfolio
      require_tests: false
  schedule: "manual"  # manual | daily_2am | weekly_sunday
  max_session_duration_minutes: 60

resume_automation:
  target_roles: ["AI Engineer", "LLM Engineer", "ML Engineer", "GenAI Engineer"]
  target_regions: ["United States", "Remote"]
  seniority: "mid-senior"
  allowed_templates: ["ats_single_column", "minimal_clean"]
  output_formats: ["pdf", "docx", "markdown"]
  customization_level: "deep"  # light | medium | deep
  ats_rules:
    no_tables: true
    no_graphics: true
    standard_section_names: true  # Experience, Education, Skills, Projects
    single_column: true
    no_headers_footers: true
    font_constraint: "standard"  # Arial, Calibri, Times New Roman only
  keywords_to_emphasize: [RAG, LangGraph, multi-agent, LangChain, FastAPI, compliance, FinTech]
  keywords_to_avoid: ["responsible for", "duties included", "worked on"]  # weak verbs
  tone: "quantified-achievement"
  benchmark_profiles: []  # paths to anonymized sample resumes for benchmarking
  output_dir: "assets/resumes/"

research_and_discovery:
  scan_frequency: "weekly"  # daily | weekly
  sources:
    github_trending: true
    huggingface_papers: true
    arxiv: true
    wellfound_jobs: true
    product_hunt: true
    reddit_ml: true
    hacker_news: true
  goals: ["productivity", "job_search", "learning", "portfolio_growth"]
  summary_style: "concise-bullets"
  summary_max_items: 10
  try_asap_threshold: 0.85  # Claude confidence score
  watch_threshold: 0.60

documentation_and_github:
  automation_repo: "automation-system"
  primary_repos: ["finops-sentinel", "portfolio-website", "automation-system"]
  docs_convention:
    changelog: "CHANGELOG.md"
    runbook: "RUNBOOK.md"
    weekly_report: "docs/reports/week_YYYY_WW.md"
  commit_frequency: "daily_aggregated"
  commit_style: "conventional"  # feat, fix, chore, docs
  committable_artifacts:
    - "weekly job search report"
    - "AI tools radar digest"
    - "project summaries"
    - "config snapshots (no secrets)"
    - "resume version index"
  never_commit:
    - "API keys or tokens"
    - "personal email addresses"
    - "raw job post content (ToS risk)"
    - "recruiter contact details"
    - "email contents"
  auto_update_readme: true
  profile_readme_repo: "ShreyasKhandare"  # github.com/ShreyasKhandare/ShreyasKhandare

constraints:
  daily_time_budget_minutes: 0  # fully async, no manual time needed
  rate_limits:
    linkedin_profile_views_per_day: 50
    cold_emails_per_day: 15
    apollo_api_calls_per_day: 40
    hunter_lookups_per_day: 20
    serpapi_calls_per_day: 30
    github_actions_minutes_per_month: 2000  # free tier limit
  anthropic_api_budget_usd_per_month: 10
  ethics:
    no_fake_personas: true
    always_include_unsubscribe: true
    honor_opt_outs_immediately: true
    no_purchased_lists: true
    no_direct_linkedin_scraping: true  # use Apify actor instead
  manual_approval_required:
    - "sending any email"
    - "applying to any job"
    - "force-pushing to main branch"
    - "deleting any file"
    - "publishing any public content"

mobile_commands:
  transport: "telegram"  # telegram | email | http_webhook
  telegram_bot_name: "@ShreyasAutomationBot"
  commands:
    RUN_JOB_SWEEP:
      agent: job_discovery
      params: []
      description: "Run full job discovery pipeline now"
    RUN_OUTREACH_SAFE:
      agent: recruiter_outreach
      params: []
      description: "Find recruiters and draft emails for approval"
    PAUSE_OUTREACH:
      agent: recruiter_outreach
      params: [duration_hours]
      description: "Pause outreach sending for N hours"
    RESUME_OUTREACH:
      agent: recruiter_outreach
      params: []
      description: "Resume paused outreach"
    START_PROJECT:
      agent: project_autopilot
      params: [repo_name, task_type, description]
      description: "Start a bounded coding task on a repo"
    RUN_RESUME_TAILORING:
      agent: resume_agent
      params: [job_id]
      description: "Tailor resume for a specific job from the tracker"
    GENERATE_DAILY_DIGEST:
      agent: orchestrator
      params: []
      description: "Generate and send today's full digest now"
    RESCAN_AI_TOOLS:
      agent: ai_radar
      params: []
      description: "Run AI tools radar scan now"
    RESCAN_MARKET:
      agent: market_research
      params: []
      description: "Run full market and profile research now"
    UPDATE_GITHUB_DOCS:
      agent: github_docs
      params: []
      description: "Generate and commit latest docs and reports"
    STATUS:
      agent: orchestrator
      params: []
      description: "Get full system health status"
    HELP:
      agent: orchestrator
      params: []
      description: "List all available commands"
```

---

## 3. Agent 1 — Job Discovery

**Responsibility:** Continuously find, normalize, score, and surface the most relevant job listings across all configured platforms.

**Inputs:**
- `config.job_search_preferences`
- `config.platforms`
- `config.profile.skills` and `config.profile.target_titles`

**Tasks:**
1. Pull raw listings from each enabled platform (Wellfound API, Greenhouse scrape, Otta RSS, SerpAPI, Indeed RSS, Apify LinkedIn actor)
2. Deduplicate by `(company, title, posted_date)` fingerprint
3. Normalize into a standard `JobListing` schema (see below)
4. Score each listing via Claude API against the full profile context (0–10)
5. Filter out listings below `score_threshold`
6. Write results to SQLite `jobs` table and Google Sheet "Job Tracker"
7. Send ranked digest to Telegram at scheduled time
8. Flag "must apply today" listings (score ≥ 9, posted < 24h) with immediate Telegram alert

**Standard JobListing Schema:**
```json
{
  "id": "job_20260330_sardine_ai_eng",
  "title": "AI Engineer",
  "company": "Sardine",
  "url": "https://jobs.wellfound.com/...",
  "source": "wellfound",
  "location": "Remote",
  "salary_min": 140000,
  "salary_max": 180000,
  "posted_date": "2026-03-29",
  "tech_stack": ["LangChain", "Python", "FastAPI"],
  "description_snippet": "...",
  "claude_score": 9,
  "claude_reasoning": "Strong LangChain + FinTech match. Remote. Salary in range.",
  "status": "new",
  "applied": false,
  "resume_variant": null
}
```

**Outputs:**
- SQLite `jobs` table (local)
- Google Sheet row (visible from phone)
- Telegram digest message
- Immediate alert for score ≥ 9 postings

**Tools used:**
- GitHub Actions: cron schedule (7am EST weekdays)
- Claude API: scoring and reasoning
- SerpAPI: Google Jobs search
- Apify: LinkedIn actor (when enabled)
- n8n: webhook to trigger manual sweep from Telegram command

---

## 4. Agent 2 — Recruiter & Cold Outreach

**Responsibility:** Find hiring managers and technical recruiters at target companies, draft hyper-personalized emails, send with human approval, and track all outreach.

**Inputs:**
- `config.recruiter_outreach`
- `config.profile`
- List of companies from job discovery results + manual additions
- Open roles at each company (fetched from job discovery agent)

**Tasks:**
1. **Find phase:** Query Apollo.io API for hiring managers/recruiters at target companies, filtered by title
2. **Verify phase:** Validate emails via Hunter.io (confidence ≥ 90%)
3. **Enrich phase:** Fetch recent company news (SerpAPI), open roles, tech stack (from job listings)
4. **Draft phase:** Claude API drafts personalized email per person using base prompt template
5. **Approve phase:** Send drafted email + context to Telegram for human approval (30-min veto window in semi-auto mode)
6. **Send phase:** Gmail API sends approved emails with staggered timing
7. **Track phase:** Log to SQLite `outreach` table and Google Sheet "Outreach CRM"
8. **Follow-up phase:** Auto-draft follow-ups at configured cadence for non-replies

**Standard Outreach Record Schema:**
```json
{
  "id": "out_20260330_sarah_sardine",
  "name": "Sarah Chen",
  "title": "Technical Recruiter",
  "company": "Sardine",
  "email": "sarah.chen@sardine.ai",
  "email_confidence": 0.94,
  "source": "apollo",
  "related_job_id": "job_20260330_sardine_ai_eng",
  "drafted_at": "2026-03-30T09:00:00",
  "approved_at": "2026-03-30T09:25:00",
  "sent_at": "2026-03-30T10:00:00",
  "subject": "AI Engineer with LangGraph + FinTech RAG experience",
  "status": "sent",
  "replied": false,
  "follow_up_due": "2026-04-04",
  "follow_ups_sent": 0
}
```

**Email Drafting Prompt (stored in `agents/outreach/prompts/base_email.txt`):**
```
You are writing a cold outreach email FROM Shreyas Khandare to {name}, {title} at {company}.

SHREYAS'S PROFILE:
- MS CS, Florida State University
- Systems Consultant at FDLE; building AI systems independently
- Flagship project: FinOps Sentinel — LangGraph multi-agent RAG, live at https://shreyas-finops-sentinel.streamlit.app/
- Stack: Python, LangChain, LangGraph, ChromaDB, FastAPI, Streamlit, GPT-4o-mini, Cohere
- GitHub: https://github.com/ShreyasKhandare
- Target: AI/LLM Engineer in FinTech/RegTech

RECIPIENT CONTEXT:
- Name: {name}, Title: {title}, Company: {company}
- Company tech stack: {tech_stack}
- Open roles at company: {open_roles}
- Recent company news: {recent_news}

CONSTRAINTS:
- Max 120 words total. Subject under 8 words.
- Sound like a peer, not a job beggar.
- Reference ONE specific thing about their company.
- Single low-friction CTA: 15-min call or just a reply.
- Banned phrases: "hope this finds you well", "I wanted to reach out", "exciting opportunity"
- End with: "Reply STOP if you'd prefer I don't reach out again."

OUTPUT: JSON with keys "subject" and "body" only. No markdown.
```

**Tools used:**
- Apollo.io API: recruiter discovery
- Hunter.io API: email verification
- Claude API: email drafting
- Gmail API: sending + tracking
- n8n: Telegram approval flow, staggered send queue
- Cursor Automation: optional — trigger on new high-score jobs found

---

## 5. Agent 3 — Email Triage

**Responsibility:** Classify every incoming email, apply Gmail labels, archive spam, and send a curated digest.

**Inputs:**
- `config.email_routing_rules`
- Gmail inbox (new messages only, polled every 2 hours)

**Tasks:**
1. Fetch new messages since last poll via Gmail API
2. For each email: send `(from, subject, snippet)` to Claude API for classification
3. Apply Gmail label based on classification
4. Archive emails classified as SPAM (never delete)
5. Immediate Telegram alert for `flag_keywords` matches (interview, offer, next steps)
6. Build daily digest at `digest_time`, send to Telegram

**Classification Labels:**
```
AI/JOB_OPPORTUNITY   → recruiter outreach, job alerts, job board emails
AI/APPLICATION       → ATS status updates (received, under review, rejected, interview)
AI/NETWORKING        → replies to your cold emails, referral mentions
AI/IMPORTANT         → anything with flag_keywords (interview, offer, start date)
AI/NEWSLETTER        → subscriptions, AI digests, blogs → skip inbox
AI/SPAM              → ads, promos, irrelevant → auto-archive
AI/OTHER             → unclassified, leave in inbox
```

**Tools used:**
- Gmail API: read, label, archive
- Claude API: classification
- n8n: poll trigger every 2 hours, webhook for immediate alerts
- GitHub Actions: daily digest generation at configured time
- Telegram: digest delivery + immediate alerts

---

## 6. Agent 4 — Project Autopilot

**Responsibility:** Execute bounded, pre-authorized coding tasks on specified repos when commanded from phone. Always through PR + tests. Never force-pushes to main.

**Inputs:**
- `config.project_automation`
- Task description (from Telegram command: `START_PROJECT finops-sentinel bugfix "fix cold start OOM issue"`)
- Repo state (current branch, recent commits, test status)

**Tasks:**
1. Receive task command via Telegram bot
2. Validate task type is in `allowed_tasks` for that repo
3. Validate estimated change size ≤ `max_lines_changed_per_run`
4. Start Claude Code session (via Remote Control) on specified repo
5. Claude Code implements the task
6. Run tests if `require_tests: true`
7. Create PR if `require_pr: true`, else commit directly
8. Report to Telegram: what was done, PR link, test results, next suggested task
9. Push to GitHub

**Task Constraints (enforced in code, not just config):**
```python
SAFE_TASK_TYPES = ["bugfix", "docs", "small_feature", "refactor", "test", "content_update"]
MAX_FILES_TOUCHED = 10
MAX_LINES_CHANGED = config.project_automation.max_lines_changed_per_run
FORBIDDEN_ACTIONS = ["delete branch", "force push", "merge to main", "drop table"]
```

**Tools used:**
- Claude Code: code reasoning and implementation (via Remote Control from phone)
- Cursor Automations: can be configured as a GitHub PR trigger for auto-review after Claude Code creates PR
- GitHub API: branch management, PR creation
- Telegram: task intake + result reporting
- pytest / existing test suite: validation

---

## 7. Agent 5 — Market & Profile Research

**Responsibility:** Weekly intelligence scan — what's trending in AI engineering, where to apply, what to build next, what skills are rising.

**Inputs:**
- `config.research_and_discovery`
- `config.profile` (for relevance filtering)
- Current project list and skill gaps

**Tasks:**
1. Scrape all enabled sources (GitHub Trending, HuggingFace Papers, arXiv, ProductHunt, Wellfound job postings, Reddit, HN)
2. Run keyword frequency analysis on last 100 AI engineer job postings → identify trending required skills
3. Claude API analysis: given your stack and profile, rank everything by: "what should Shreyas build next?", "where should he apply?", "what skill gaps are growing?"
4. Generate ranked "build next" list with effort estimates
5. Generate "apply here" list of companies actively hiring your stack
6. Write to Notion page + commit markdown report to GitHub
7. Send summary to Telegram every Sunday 9am

**Outputs:**
- Notion page: `Research / Week of YYYY-MM-DD`
- GitHub commit: `docs/reports/week_YYYY_WW.md`
- Telegram Sunday digest

**Tools used:**
- GitHub API (Trending)
- HuggingFace Papers API (unauthenticated, free)
- arXiv RSS (cs.AI, cs.LG)
- ProductHunt API or RSS
- Reddit API (PRAW, free tier)
- Algolia HN API (free)
- Claude API: synthesis and ranking
- Notion API: structured output
- GitHub Actions: weekly Sunday schedule

---

## 8. Agent 6 — AI Tools Radar

**Responsibility:** Daily morning briefing on new AI tools, models, and developments — filtered for relevance to your stack and goals.

**Inputs:**
- `config.research_and_discovery.sources`
- `config.profile.skills`

**Tasks:**
1. Aggregate from all RSS and API sources (HuggingFace, GitHub Trending, ProductHunt, TLDR AI RSS, The Rundown RSS, Ben's Bites RSS, arXiv, HN)
2. Claude API rates each item: `TRY_NOW (≥0.85) | WATCH (≥0.60) | IGNORE (<0.60)` based on relevance to your stack
3. Format and send Telegram briefing at 8am
4. Log all items to SQLite `ai_radar` table
5. Weekly rollup committed to GitHub as `docs/ai_tools_radar_YYYY_WW.md`

**Tools used:**
- RSS parser (feedparser Python library)
- HuggingFace Papers API
- Algolia HN API
- Claude API: classification and relevance scoring
- GitHub Actions: daily 8am schedule (1pm UTC cron)
- Telegram: delivery

---

## 9. Agent 7 — Resume Optimization & Tailoring

**Responsibility:** For every high-score job, automatically tailor the base resume using ATS best practices, keyword injection, and Claude-powered rewriting. Produce a diff for quick human review.

**Inputs:**
- `config.resume_automation`
- `assets/resume_base.md` — your master resume in Markdown
- `JobListing` record (from Agent 1) with full job description
- Batch of similar job postings (for keyword frequency analysis)

**Tasks:**
1. **Parse JD:** Extract required skills, preferred skills, responsibilities, keywords, and seniority signals from job description using Claude API
2. **Keyword analysis:** Run frequency analysis across last 20 similar job postings → ranked keyword priority list
3. **Gap analysis:** Compare current resume against JD requirements → identify missing keywords, weak phrasing, section ordering issues
4. **ATS audit:** Check resume against ATS rules (no tables, no graphics, standard headings, single column, no headers/footers)
5. **Rewrite:** Claude API rewrites/enhances bullet points — quantified achievements, strong action verbs, keyword injection
6. **Generate variant:** Produce `resume_ROLE_JOBID.md` tailored to this specific job
7. **Convert:** Pandoc (or Python-docx) converts `.md` → `.pdf` and `.docx`
8. **Diff report:** Generate human-readable diff: what changed and why
9. **Keyword report:** List added keywords, removed weak phrases, ATS score before/after
10. **Alert:** Send Telegram notification with diff summary and download links
11. **Log:** Record in SQLite `resumes` table and Google Sheet "Resume Versions"

**ATS Rules (enforced in code):**
```python
ATS_RULES = {
    "no_tables": True,
    "no_graphics": True,
    "standard_headings": ["Experience", "Education", "Skills", "Projects", "Certifications"],
    "single_column_only": True,
    "no_header_footer": True,
    "allowed_fonts": ["Arial", "Calibri", "Times New Roman", "Garamond"],
    "max_pages": 2,
    "file_formats": ["pdf", "docx"],
    "no_text_boxes": True,
}
```

**Resume Tailoring Prompt (stored in `agents/resume/prompts/tailor.txt`):**
```
You are a senior technical resume writer specializing in AI/ML engineering roles.

TASK: Tailor Shreyas Khandare's resume for this specific job.

BASE RESUME:
{base_resume_content}

JOB DESCRIPTION:
{job_description}

KEYWORD PRIORITY LIST (from frequency analysis of similar roles):
{keyword_list}

GAP ANALYSIS:
{gap_analysis}

RULES:
- Rewrite bullet points to use strong action verbs (Built, Deployed, Engineered, Designed, Optimized)
- Inject high-priority keywords naturally — no keyword stuffing
- Quantify achievements wherever possible (413 chunks, 95% accuracy, RAGAS 1.0000)
- Preserve all factual accuracy — never invent numbers or experiences
- ATS constraints: no tables, no graphics, standard headings, single column
- Reorder sections if needed for this role (e.g., Projects before Experience for AI roles)
- Do NOT change education facts, dates, or company names
- Tone: confident, quantified, technical — not corporate or passive

OUTPUT FORMAT:
1. Full tailored resume in Markdown
2. JSON diff: {"added": [...], "modified": [...], "reasoning": "..."}
3. Keyword report: {"injected": [...], "removed_weak": [...], "ats_score": "before/after"}
```

**File naming convention:**
```
assets/resumes/
├── resume_base.md                          # master, updated quarterly
├── resume_AI_Engineer_2026.md              # generic cleaned version
├── resume_sardine_job_20260330.md          # job-specific tailored
├── resume_sardine_job_20260330.pdf         # ATS-ready PDF
├── resume_sardine_job_20260330.docx        # Word version
└── index.json                              # all versions + metadata
```

**Tools used:**
- Claude API: JD parsing, keyword analysis, rewriting
- Claude Code: file generation, diff computation, markdown handling
- Cursor Automations: can trigger tailoring automatically when new high-score job appears in tracker
- Pandoc or python-docx: `.md` → `.pdf` / `.docx` conversion
- GitHub Actions: batch tailoring on demand or on new job discovery
- Telegram: notification with diff summary

---

## 10. Agent 8 — GitHub Docs & Profile Automation

**Responsibility:** Keep your GitHub profile, repos, and documentation continuously updated with meaningful, professional content that reflects your work and automation activity.

**Inputs:**
- `config.documentation_and_github`
- All agent outputs (job reports, outreach stats, resume versions, AI radar digests, project summaries)
- Git log of recent commits across tracked repos

**Tasks:**
1. **Daily:** Aggregate all outputs from agents into a daily summary
2. **Daily:** Commit non-sensitive artifacts to private automation repo
3. **Weekly:** Generate `docs/reports/week_YYYY_WW.md` — job search stats, projects completed, tools discovered
4. **Weekly:** Update `CHANGELOG.md` with notable automation improvements
5. **On project completion:** Auto-generate project README section and update main portfolio repo docs
6. **On resume creation:** Update `assets/resumes/index.json` with new version metadata
7. **Weekly:** Update GitHub profile README (`ShreyasKhandare/ShreyasKhandare/README.md`) with:
   - Latest project highlights
   - Current skills (from config)
   - Recent automation improvements
   - Links to live projects

**Commit message convention:**
```
chore(docs): update weekly job search report [Week 14, 2026]
docs(projects): add FinOps Sentinel phase 5 summary
feat(resume): add AI Engineer variant for FinTech roles
chore(radar): commit AI tools digest week 14
docs(profile): update GitHub README with latest projects
fix(outreach): log correction for March 28 sends
```

**What NEVER gets committed:**
```yaml
never_commit:
  - Any file matching: .env, *.key, *secret*, *password*, *token*
  - Raw recruiter names, emails, or personal contact info
  - Email contents or inbox data
  - Raw job posting content (ToS violation risk)
  - Anthropic/Google/Apollo/Hunter API keys
```

**Pre-commit check (enforced via git hook + script):**
```python
FORBIDDEN_PATTERNS = [
    r"sk-ant-[A-Za-z0-9]+",       # Anthropic keys
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}",  # emails
    r"AIza[A-Za-z0-9_-]{35}",     # Google API keys
    r"Bearer [A-Za-z0-9_-]{20,}", # Auth tokens
]
```

**Tools used:**
- Claude Code: generate markdown reports from structured data
- GitHub API: commit, push, update files
- Cursor Automations: trigger doc updates on GitHub PR merges or weekly schedule
- GitHub Actions: daily commit cron (11pm EST)

---

## 11. Scheduling, Triggers & Remote Control

### Schedule Overview

| Time | Trigger | Agent | Task |
|---|---|---|---|
| Daily 8:00am EST | GitHub Actions cron | AI Radar | Morning briefing → Telegram |
| Daily 9:00am EST | GitHub Actions cron | Orchestrator | System health status → Telegram |
| Daily 7:00am EST (Mon–Fri) | GitHub Actions cron | Job Discovery | Full job sweep → Telegram digest |
| Every 2 hours | GitHub Actions cron | Email Triage | Poll inbox, classify, label |
| Daily 6:00pm EST | GitHub Actions cron | Email Triage | Daily email digest → Telegram |
| Daily 11:00pm EST | GitHub Actions cron | GitHub Docs | Commit daily artifacts |
| Sunday 9:00am EST | GitHub Actions cron | Market Research | Weekly intelligence → Notion + Telegram |
| On demand | Telegram command | Any | Manual trigger of any agent |
| On new high-score job | n8n webhook | Resume Agent | Auto-trigger resume tailoring (assisted) |
| On GitHub PR created | Cursor Automation | Code Review | Auto-review PR (if Cursor Automation configured) |

### Cursor Automations Setup

Cursor Automations (launched March 5, 2026) uses a trigger-action model: events like GitHub PRs, Slack messages, or cron schedules automatically spin up cloud sandboxes where AI agents execute custom instructions — entirely in the cloud, without consuming local resources.

Configure these automations at `cursor.com/automations`:

**Automation 1: PR Code Review**
```
Trigger: GitHub PR created on finops-sentinel or portfolio-website
Instructions: Review this PR for: correctness, test coverage, potential bugs,
and security issues. Check that no secrets are committed. Post findings as
PR comment. Auto-approve if no critical issues found.
MCP Tools: GitHub
```

**Automation 2: Weekly Docs Update**
```
Trigger: Schedule — every Sunday 10am
Instructions: Pull latest logs from automation-system/logs/,
generate a weekly summary report in docs/reports/, update CHANGELOG.md,
commit with message "chore(docs): update weekly report [Week N]"
MCP Tools: GitHub
```

**Automation 3: Resume Trigger**
```
Trigger: GitHub issue created with label "resume-needed" (posted by Job Discovery agent)
Instructions: Read issue body (contains job_id and job description).
Run resume tailoring agent for this job. Commit tailored resume. Close issue.
MCP Tools: GitHub
```

### n8n Workflow Connections

n8n (self-hosted, free) handles all the API glue that GitHub Actions can't do natively:

```
Workflow 1: Telegram → Orchestrator
  Trigger: Telegram Bot message received
  Action: Parse command, route to correct Python agent via HTTP POST
  Return: Agent response back to Telegram

Workflow 2: Gmail → Email Triage
  Trigger: New Gmail message (Gmail trigger node)
  Action: POST to email_triage agent endpoint
  Return: Apply label, optionally send Telegram alert

Workflow 3: Apollo + Hunter → Outreach Queue
  Trigger: HTTP webhook (called by job_discovery after finding high-score jobs)
  Action: Apollo lookup → Hunter verify → add to outreach queue → Telegram approval

Workflow 4: Approval Gate
  Trigger: Telegram callback button (Approve / Reject)
  Action: If Approve → POST to sender.py → send email
         If Reject → log rejection, skip

Workflow 5: Resume Trigger
  Trigger: New row in "Job Tracker" Google Sheet with score ≥ 8
  Action: POST to resume_agent with job_id → start tailoring
```

---

## 12. Mobile Command Vocabulary

All commands sent via Telegram to `@ShreyasAutomationBot`. Bot is whitelisted to your Telegram user ID only.

```
GENERAL
/status                       → Full system health (all agents, last run times, errors)
/help                         → List all commands
/logs [agent]                 → Last 50 log lines for any agent

JOB SEARCH
/jobs today                   → Today's job digest
RUN JOB_SWEEP NOW             → Trigger immediate job sweep
RUN JOB_SWEEP STEALTH         → Sweep with lower rate limits

OUTREACH
RUN OUTREACH SAFE             → Find recruiters + draft emails for your approval
PAUSE OUTREACH 24H            → Pause for 24 hours
PAUSE OUTREACH 48H            → Pause for 48 hours
RESUME OUTREACH               → Resume paused outreach
/outreach status              → Stats: sent, replied, pending follow-up

EMAIL
/emails                       → Current inbox triage summary
GENERATE DAILY_DIGEST NOW     → Send email digest immediately

PROJECTS
START PROJECT finops-sentinel bugfix "description"
START PROJECT portfolio-website content_update "description"
/projects status              → Last commit, branch, test status per repo

RESUME
RUN RESUME_TAILORING JOB_ID=job_20260330_sardine_ai_eng
/resumes list                 → All current resume variants with metadata

RESEARCH & INTEL
RESCAN MARKET                 → Run market and profile research now
RESCAN AI_TOOLS               → Run AI tools radar now
/briefing                     → Today's AI briefing (if you missed the 8am send)

GITHUB
UPDATE GITHUB_DOCS            → Generate and commit latest docs now
/commits                      → Last 5 commits across tracked repos

SYSTEM
/health                       → Quick green/yellow/red status for every agent
/costs                        → Claude API spend month-to-date
/errors                       → All errors in last 24 hours
```

**Command parsing (in `orchestrator.py`):**
```python
# Commands are parsed via keyword matching + Claude API for natural language fallback
COMMAND_MAP = {
    "RUN JOB_SWEEP": job_discovery.run,
    "RUN OUTREACH SAFE": outreach.run_assisted,
    "PAUSE OUTREACH": outreach.pause,
    "START PROJECT": project_autopilot.run,
    "RUN RESUME_TAILORING": resume_agent.run,
    "RESCAN MARKET": market_research.run,
    "RESCAN AI_TOOLS": ai_radar.run,
    "UPDATE GITHUB_DOCS": github_docs.run,
    "GENERATE DAILY_DIGEST": orchestrator.generate_digest,
    "/status": orchestrator.get_status,
    "/health": orchestrator.get_health,
    "/costs": orchestrator.get_costs,
}
# Unrecognized command → Claude API parses intent → routes to best match
```

---

## 13. Data Storage & Logging

### Storage Architecture

```
Local SQLite (automation.db) — fast, private, no cloud dependency
├── jobs              → all discovered job listings
├── outreach          → all contact/email records
├── resumes           → resume version index + metadata
├── ai_radar          → all AI tools and news items
├── project_runs      → project autopilot task history
├── email_triage      → classified email log (subjects only, no content)
└── system_health     → agent run history, errors, metrics

Google Sheets (visible from phone, shared with no one)
├── "Job Tracker"       → jobs with status, score, apply notes
├── "Outreach CRM"      → recruiter contacts, email status, follow-up dates
├── "Resume Versions"   → all resume variants + job mapping
└── "Weekly Metrics"    → high-level stats per week

Notion (structured writing, project ideas)
├── Research/           → weekly market research pages
└── Project Backlog/    → ranked project ideas from Agent 5

Private GitHub Repo (automation-system)
├── docs/reports/       → weekly markdown reports
├── docs/ai_radar/      → AI tools radar digests
├── assets/resumes/     → all resume variants (no PII)
└── logs/               → sanitized run logs (no secrets, no email content)
```

### Logging Standards

```python
# Every agent logs in this format
LOG_FORMAT = {
    "timestamp": "ISO8601",
    "agent": "job_discovery",
    "run_id": "uuid4",
    "status": "success | failure | partial",
    "items_processed": 47,
    "items_output": 5,
    "duration_seconds": 23,
    "claude_api_calls": 5,
    "claude_tokens_used": 4200,
    "errors": [],
    "summary": "Found 47 jobs. Scored 5 above threshold. 1 urgent (score 9)."
}
```

### Metrics (reported in daily Telegram status)

```
Jobs found (daily/weekly/monthly)
Jobs applied to (manual, tracked)
Cold emails sent / reply rate
Resume variants created
GitHub commits (auto-generated)
Claude API cost ($) MTD
Agent error rate
```

### Error Handling

- All errors logged to SQLite `system_health` table
- Errors > 3 consecutive → agent auto-pauses and sends Telegram alert
- Daily error digest at 9am system status
- Each agent has a `--dry-run` flag for safe testing without side effects

---

## 14. Tooling Matrix

| Agent | Claude Code | Cursor Automations | GitHub Actions | n8n | Gmail API | Apollo/Hunter | SerpAPI | Telegram |
|---|---|---|---|---|---|---|---|---|
| Job Discovery | Scoring/ranking | — | Daily cron | Manual trigger | — | — | Google Jobs | Digest |
| Outreach | Email drafting | On new high-score job | Weekly | Approval gate | Sending | Lead finding | Company news | Approve/reject |
| Email Triage | Classification | — | 2-hr cron | Gmail trigger | Read/label | — | — | Alerts + digest |
| Project Autopilot | Code execution | PR review | — | Command routing | — | — | — | Task intake + report |
| Market Research | Analysis + synthesis | — | Weekly cron | — | — | — | Trends | Sunday digest |
| AI Radar | Relevance scoring | — | Daily cron | — | — | — | — | Morning briefing |
| Resume Agent | JD parsing + rewrite | On new job | On demand | Resume trigger | — | — | — | Diff notification |
| GitHub Docs | Report generation | Weekly docs update | Daily cron | — | — | — | — | — |

**Where Claude Code ends and external tools begin:**
- Claude Code handles: all reasoning, text generation, code writing, analysis, classification
- GitHub Actions handles: scheduling, environment setup, package installation, running scripts
- Cursor Automations handles: event-driven cloud tasks (PR triggers, scheduled docs)
- n8n handles: API glue, webhook routing, approval flows, multi-step HTTP chains
- Gmail/Apollo/Hunter/SerpAPI: data sources — Claude Code consumes their outputs

---

## 15. Safety, ToS & Anti-Spam Rules

### Email & Outreach Rules
```
✅ Max 15 cold emails per day
✅ 48-hour gap between contacts at same company
✅ Send window: 9–11am recipient timezone only
✅ Always include "Reply STOP to opt out" in every cold email
✅ Honor opt-outs within 1 hour — log permanently, never re-contact
✅ Plain text emails only (no HTML tracking pixels initially)
✅ Warm-up period: week 1 max 5/day, week 2 max 10/day
✅ Use your real Gmail — not throwaway accounts
❌ Never send to purchased or scraped email lists
❌ Never impersonate anyone
❌ Never send identical email body twice
❌ Never send more than 2 follow-ups per contact
```

### LinkedIn & Job Platform Rules
```
✅ Use Apify actor for LinkedIn — never direct scraping (violates ToS)
✅ Max 50 LinkedIn profile views per day
✅ Never automate clicking "Apply" on job boards
✅ Respect each platform's robots.txt
✅ Indeed/Otta/Wellfound: use official RSS/API only
✅ SerpAPI for Google Jobs: within API terms
```

### Resume & Content Rules
```
✅ Only rewrite your own content — no plagiarism from sample resumes
✅ Pattern-learn from examples (style, structure) — never copy text
✅ Never invent experiences, metrics, or credentials
✅ All quantified achievements must be verifiable (RAGAS 1.0000, 413 chunks, etc.)
✅ Resume variants are for personalization, not deception
```

### GitHub & Data Rules
```
✅ Pre-commit hook scans for secrets before every commit
✅ No raw email content committed anywhere
✅ No recruiter personal data in public or private repos
✅ Config committed without secrets (use .env for keys)
✅ Logs sanitized before commit (emails redacted, tokens removed)
❌ Never force-push to main branch
❌ Never commit .env files
```

### Manual Approval Required (never automated)
```
- Sending any outreach email
- Submitting any job application
- Publishing anything publicly
- Merging PRs to main
- Deleting any data or file
```

---

## 16. Sequence Diagrams

### Daily Job Sweep + Resume Tailoring + Digest

```
7:00am EST — GitHub Actions triggers job_discovery.py
    │
    ├─→ Scrape Wellfound, Otta, Greenhouse, SerpAPI
    │     Returns: 40-80 raw listings
    │
    ├─→ Deduplicate (fingerprint check vs SQLite)
    │     Returns: 15-30 new listings
    │
    ├─→ Claude API scores each listing (batch call)
    │     Returns: scored list, 5-8 above threshold
    │
    ├─→ Write to SQLite jobs table
    ├─→ Append rows to Google Sheet "Job Tracker"
    │
    ├─→ For each job with score ≥ 8:
    │     └─→ n8n webhook → resume_agent.py triggered
    │           ├─→ Claude API parses job description
    │           ├─→ Keyword frequency analysis
    │           ├─→ Gap analysis vs base resume
    │           ├─→ Claude API rewrites resume bullets
    │           ├─→ Pandoc converts md → pdf + docx
    │           ├─→ Commits resume variant to GitHub
    │           └─→ Telegram: "New resume ready: [job title] @ [company]"
    │                         "Changes: +6 keywords, 3 bullets strengthened"
    │                         "Download: [link] | Review: [google sheet link]"
    │
    └─→ 7:30am: Telegram job digest sent
          "🎯 JOB DIGEST — Monday March 30
           1. [9/10] AI Engineer @ Sardine | Remote | $140-180k
           2. [8/10] LLM Engineer @ Credal.ai | Remote | $130-160k
           ...
           📊 Full list: [Sheet link]"

    ── If score ≥ 9 and posted < 24h ──
    Immediate Telegram alert (no waiting for digest):
    "🔥 URGENT: Score 9/10 job posted 2hrs ago
     AI Engineer @ Sardine | Apply today"
```

### Project Autopilot Run + GitHub Docs Update

```
You (from phone, at office):
    Telegram: "START PROJECT finops-sentinel bugfix 'fix cold start OOM on Render'"
    │
    └─→ n8n receives Telegram message
          └─→ POST to orchestrator.py /command endpoint
                │
                ├─→ Parse command → route to project_autopilot.run()
                ├─→ Validate: "bugfix" ∈ allowed_tasks for finops-sentinel ✅
                ├─→ Validate: repo exists at local_path ✅
                │
                └─→ Claude Code (via Remote Control session "finops-sentinel")
                      ├─→ Read CLAUDE.md for project context
                      ├─→ Analyze current memory usage in requirements.txt
                      ├─→ Research Render OOM patterns
                      ├─→ Implement fix: slim requirements, lazy imports
                      ├─→ Run: python -m pytest tests/ → all pass
                      ├─→ git checkout -b fix/cold-start-oom
                      ├─→ git commit -m "fix(deploy): resolve cold start OOM via slim deps"
                      ├─→ git push origin fix/cold-start-oom
                      ├─→ gh pr create --title "fix: cold start OOM" --body "..."
                      └─→ Telegram report sent:
                            "✅ Task complete: finops-sentinel
                             Fixed: Render cold start OOM
                             Files changed: requirements.txt, app.py (3 files, 47 lines)
                             Tests: 10/10 passed
                             PR: github.com/ShreyasKhandare/finops-sentinel/pull/12
                             Next suggested task: Add SOC 2 corpus support"

11:00pm EST — GitHub Actions triggers github_docs.py
    │
    ├─→ Read today's logs from all agents (SQLite)
    ├─→ Claude API generates daily summary markdown
    ├─→ Append to CHANGELOG.md
    ├─→ Update docs/reports/week_2026_14.md with today's stats
    ├─→ Update assets/resumes/index.json with new resume variants
    ├─→ Pre-commit scan: zero secrets found ✅
    └─→ git commit -m "chore(docs): daily automation artifacts [2026-03-30]"
        git push origin main
```

---

## 17. Folder Structure

```
automation-system/              ← Private GitHub repo
├── README.md                   ← System overview + quick start
├── SYSTEM_DESIGN.md            ← This file (the spec)
├── CHANGELOG.md                ← Auto-updated by GitHub Docs agent
├── RUNBOOK.md                  ← Health check and repair procedures
├── .env.example                ← Template (no real values)
├── .gitignore                  ← .env, *.key, logs/raw/, *.sqlite (local only)
│
├── config/
│   ├── config.yaml             ← Master config (no secrets)
│   └── config.schema.json      ← JSON Schema for validation
│
├── orchestrator/
│   ├── orchestrator.py         ← Main router: commands → agents
│   ├── telegram_bot.py         ← Bot handler, auth, command parsing
│   ├── health.py               ← Status checks for all agents
│   └── digest.py               ← Daily digest aggregator
│
├── agents/
│   ├── job_discovery/
│   │   ├── scraper.py          ← Multi-source job scraper
│   │   ├── scorer.py           ← Claude API scoring
│   │   ├── sheet_writer.py     ← Google Sheets output
│   │   ├── notifier.py         ← Telegram digest
│   │   └── requirements.txt
│   │
│   ├── outreach/
│   │   ├── finder.py           ← Apollo.io recruiter lookup
│   │   ├── verifier.py         ← Hunter.io email verification
│   │   ├── drafter.py          ← Claude API email generation
│   │   ├── sender.py           ← Gmail API staggered sending
│   │   ├── tracker.py          ← SQLite + Sheets CRM
│   │   ├── follow_up.py        ← Auto follow-up scheduler
│   │   └── prompts/
│   │       ├── base_email.txt
│   │       └── follow_up.txt
│   │
│   ├── email_triage/
│   │   ├── poller.py           ← Gmail API fetch
│   │   ├── classifier.py       ← Claude API classification
│   │   ├── labeler.py          ← Apply Gmail labels
│   │   ├── digest.py           ← Daily email summary
│   │   └── notifier.py         ← Immediate alerts
│   │
│   ├── project_autopilot/
│   │   ├── runner.py           ← Task validation + Claude Code session manager
│   │   ├── git_ops.py          ← Branch, commit, PR operations
│   │   ├── reporter.py         ← Telegram result reporting
│   │   └── constraints.py      ← Safety limits enforcement
│   │
│   ├── market_research/
│   │   ├── scraper.py          ← Multi-source intelligence scraper
│   │   ├── analyzer.py         ← Claude API synthesis
│   │   ├── notion_writer.py    ← Write to Notion
│   │   └── reporter.py         ← Telegram Sunday digest
│   │
│   ├── ai_radar/
│   │   ├── aggregator.py       ← RSS + API aggregation
│   │   ├── filter.py           ← Claude API relevance classification
│   │   ├── formatter.py        ← Telegram message formatter
│   │   └── notifier.py         ← 8am Telegram delivery
│   │
│   ├── resume/
│   │   ├── resume_agent.py     ← Main orchestrator for resume tasks
│   │   ├── jd_parser.py        ← Extract requirements from JD
│   │   ├── keyword_analyzer.py ← Frequency analysis across job batch
│   │   ├── gap_analyzer.py     ← Compare resume vs JD requirements
│   │   ├── ats_auditor.py      ← ATS compliance checker
│   │   ├── rewriter.py         ← Claude API resume rewriting
│   │   ├── converter.py        ← md → pdf + docx (via Pandoc)
│   │   ├── diff_reporter.py    ← Human-readable change explanation
│   │   └── prompts/
│   │       └── tailor.txt
│   │
│   └── github_docs/
│       ├── docs_agent.py       ← Report generation + commit
│       ├── changelog_updater.py
│       ├── readme_updater.py   ← Profile README updater
│       ├── commit_scanner.py   ← Pre-commit secret detection
│       └── report_templates/
│           ├── weekly_report.md.jinja
│           └── project_summary.md.jinja
│
├── shared/
│   ├── config_loader.py        ← Load and validate config.yaml
│   ├── claude_client.py        ← Shared Claude API wrapper
│   ├── db.py                   ← SQLite connection and schema
│   ├── sheets.py               ← Google Sheets wrapper
│   ├── telegram.py             ← Telegram send/receive helpers
│   ├── logger.py               ← Structured logging for all agents
│   └── secrets.py              ← Load from .env (never from config.yaml)
│
├── assets/
│   ├── resume_base.md          ← Your master resume (update quarterly)
│   └── resumes/                ← All tailored variants + index.json
│
├── docs/
│   ├── reports/                ← Weekly markdown reports (auto-committed)
│   └── ai_radar/               ← AI tools digests (auto-committed)
│
├── logs/                       ← Sanitized run logs (gitignored locally)
│   └── .gitkeep
│
├── .github/
│   └── workflows/
│       ├── job_discovery.yml
│       ├── email_triage.yml
│       ├── ai_briefing.yml
│       ├── market_research.yml
│       ├── github_docs.yml
│       └── resume_batch.yml
│
└── n8n/
    └── workflows/              ← Exported n8n workflow JSON files
        ├── telegram_router.json
        ├── gmail_triage.json
        ├── outreach_approval.json
        ├── resume_trigger.json
        └── job_to_outreach.json
```

---

## 18. Implementation Plan for Claude Code & Cursor

### First Commands to Run in Claude Code

Open the `automation-system` repo in Claude Code and run these prompts in order.

**Session 1 — Foundation (Day 1, ~2 hours)**
```
Read SYSTEM_DESIGN.md thoroughly. Then:
1. Create the full folder structure as specified in Section 17
2. Generate config/config.schema.json that validates config.yaml
3. Generate config/config.yaml with Shreyas's actual values (use the example in Section 2)
4. Generate shared/config_loader.py — loads, validates, and returns config as typed dataclass
5. Generate shared/db.py — SQLite schema for all tables (jobs, outreach, resumes, ai_radar, project_runs, system_health)
6. Generate shared/logger.py — structured JSON logger used by all agents
7. Generate shared/secrets.py — loads from .env, raises clear error if missing
8. Generate .env.example with all required secret names (no values)
9. Generate .gitignore that excludes .env, *.sqlite, logs/raw/, __pycache__
10. Create initial README.md explaining what this repo is and how to use it
```

**Session 2 — Telegram Bot + Orchestrator (Day 1, ~1 hour)**
```
Read SYSTEM_DESIGN.md Section 12 (Mobile Commands) and Section 11 (Scheduling).
Generate:
1. orchestrator/telegram_bot.py — Telegram bot with user ID whitelist, command parser, Claude API fallback for unrecognized commands
2. orchestrator/orchestrator.py — main router that maps commands to agent functions
3. orchestrator/health.py — checks all agents, returns green/yellow/red status
4. Set up a /status and /health command that works end-to-end
Make sure the bot is secure: ONLY responds to TELEGRAM_CHAT_ID from .env
```

**Session 3 — AI Radar Agent (Day 1–2, easiest, highest daily value)**
```
Read SYSTEM_DESIGN.md Section 8.
Generate all files under agents/ai_radar/.
Use feedparser for RSS, requests for HuggingFace and HN Algolia APIs.
Claude API call should batch all items in one prompt for efficiency.
Output format should match the Telegram message example in Section 8.
Wire up the GitHub Actions workflow .github/workflows/ai_briefing.yml (1pm UTC cron).
Test with --dry-run flag first.
```

**Session 4 — Job Discovery Agent (Day 2)**
```
Read SYSTEM_DESIGN.md Section 3.
Generate all files under agents/job_discovery/.
Start with SerpAPI + Otta RSS + Greenhouse scrape (skip LinkedIn/Apify for now).
JobListing schema must match the JSON in Section 3 exactly.
Google Sheets writer should create headers if sheet is empty.
Telegram digest should match the format in Section 3.
Wire up .github/workflows/job_discovery.yml (7am EST Mon-Fri = 12pm UTC).
```

**Session 5 — Email Triage Agent (Day 2–3)**
```
Read SYSTEM_DESIGN.md Section 5.
Generate all files under agents/email_triage/.
Gmail API setup: use OAuth2 with offline access (generate refresh token once, store in .env).
Classification must use the exact label names in Section 5.
Immediate alert for flag_keywords must fire within the same run, not wait for digest.
Wire up .github/workflows/email_triage.yml (every 2 hours = '0 */2 * * *').
```

**Session 6 — Resume Agent (Day 3)**
```
Read SYSTEM_DESIGN.md Section 9 (Resume Agent) completely.
Generate all files under agents/resume/.
The Claude prompt is in Section 9 — use it exactly as the system prompt in rewriter.py.
ATS_RULES from Section 9 must be enforced as assertions in ats_auditor.py.
File naming convention must match Section 9 exactly.
Use pandoc (subprocess call) for md → pdf conversion. Fallback: python-docx for docx.
Output diff_report as a short Telegram message (max 200 chars summary + full JSON to file).
```

**Session 7 — GitHub Docs Agent (Day 3–4)**
```
Read SYSTEM_DESIGN.md Section 10.
Generate all files under agents/github_docs/.
commit_scanner.py must use the FORBIDDEN_PATTERNS regex list from Section 10.
Report templates in report_templates/ should use Jinja2.
GitHub Actions workflow at 11pm EST (4am UTC).
Profile README updater should only touch ShreyasKhandare/ShreyasKhandare/README.md.
```

**Session 8 — n8n Workflows (Day 4)**
```
Read SYSTEM_DESIGN.md Section 11 (n8n workflows).
Generate the n8n workflow JSON files for:
1. telegram_router.json — Telegram → orchestrator HTTP routing
2. gmail_triage.json — Gmail new message → email_triage agent
3. outreach_approval.json — Telegram approve/reject buttons → Gmail send
4. resume_trigger.json — New Google Sheet row with score ≥ 8 → resume agent
Import these into your n8n instance and configure credentials.
```

**Session 9 — Outreach Agent (Week 2, after validation)**
```
Read SYSTEM_DESIGN.md Section 4 completely.
Generate all files under agents/outreach/.
Start with finder.py (Apollo) + verifier.py (Hunter) first — no sending yet.
Test the full pipeline with --dry-run before enabling sender.py.
The approval gate via Telegram MUST work before any email can be sent.
Warm-up enforcement: check SQLite for today's send count before every send.
```

**Session 10 — Project Autopilot + Market Research (Week 2)**
```
Read SYSTEM_DESIGN.md Sections 6 and 7.
Generate project_autopilot/ and market_research/ agents.
Project autopilot must validate task type + line count before executing anything.
FORBIDDEN_ACTIONS list must be enforced as hard raises, not just warnings.
Market research: Notion API for structured output, GitHub commit for markdown version.
```

### Milestone 1 (Days 1–3) — Minimum Viable Slice
After sessions 1–6, you have:
- ✅ Telegram bot responding to commands from your phone
- ✅ Daily AI briefing at 8am
- ✅ Daily job digest at 7am (Mon-Fri)
- ✅ Email triage running every 2 hours
- ✅ Resume tailoring on demand (`RUN RESUME_TAILORING JOB_ID=...`)
- ✅ System health status on demand
- ✅ GitHub docs auto-committed nightly

This alone delivers 80% of the daily value. Everything after this is expanding and refining.

### Milestone 2 (Week 2) — Full Automation Stack
- ✅ Outreach agent live (with approval gate)
- ✅ Project autopilot from phone
- ✅ Market research Sunday digest
- ✅ n8n workflows connecting everything
- ✅ Cursor Automations for PR review and weekly docs

### Milestone 3 (Week 3–4) — Polish & Scale
- ✅ Fine-tune Claude prompts based on real output quality
- ✅ Add LinkedIn via Apify (when credits acquired)
- ✅ Batch resume tailoring for multiple high-score jobs at once
- ✅ Outreach reply tracking and follow-up automation
- ✅ GitHub profile README auto-updating weekly

---

*Feed this document into Claude Code with: "Read SYSTEM_DESIGN.md and begin Session 1 of the implementation plan." That's all it takes to start.*

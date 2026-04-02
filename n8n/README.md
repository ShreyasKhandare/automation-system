# n8n Workflows

Self-hosted n8n (free tier) handles all API glue between GitHub Actions agents,
Telegram, Gmail, Google Sheets, Apollo.io, and Hunter.io.

## Workflows

| File | Trigger | Purpose |
|---|---|---|
| `telegram_router.json` | Telegram Bot message | Routes all Telegram commands to the Python orchestrator via HTTP |
| `gmail_triage.json` | New Gmail INBOX message | Calls email_triage agent; fires Telegram alert for urgent emails |
| `outreach_approval.json` | HTTP webhook + Telegram callback | Approval gate: sends inline Approve/Reject buttons for each outreach draft |
| `job_to_outreach.json` | HTTP webhook (from job_discovery) | Apollo recruiter lookup → Hunter email verify → add to outreach queue |
| `resume_trigger.json` | New Google Sheet row (score ≥ 8) | Auto-triggers resume tailoring agent for high-score jobs |

## Setup

### 1. Install n8n (Docker)

```bash
docker run -d \
  --name n8n \
  -p 5678:5678 \
  -v ~/.n8n:/home/node/.n8n \
  -e N8N_BASIC_AUTH_ACTIVE=true \
  -e N8N_BASIC_AUTH_USER=admin \
  -e N8N_BASIC_AUTH_PASSWORD=<strong-password> \
  n8nio/n8n
```

### 2. Set environment variables in n8n

Go to **Settings → Environment Variables** and add:

| Variable | Description |
|---|---|
| `ORCHESTRATOR_URL` | URL where orchestrator.py HTTP server listens (e.g. `http://localhost:8080`) |
| `ORCHESTRATOR_SECRET` | Shared token for `X-Automation-Token` header |
| `TELEGRAM_CHAT_ID` | Your Telegram user ID (whitelist check) |
| `GOOGLE_SHEET_ID_JOBS` | Google Sheet ID for the Job Tracker sheet |
| `APOLLO_API_KEY` | Apollo.io API key |
| `HUNTER_API_KEY` | Hunter.io API key |

### 3. Create credentials in n8n

- **Telegram Bot** — Bot token from BotFather (`TELEGRAM_BOT_TOKEN`)
- **Gmail OAuth2** — OAuth2 client ID/secret + refresh token
- **Google Sheets** — Service account JSON or OAuth2

### 4. Import workflows

1. Open n8n UI at `http://localhost:5678`
2. Go to **Workflows → Import from File**
3. Import each JSON file from `n8n/workflows/`
4. Open each workflow, verify credentials are attached, and **Activate**

### 5. Configure Telegram webhook

Set the Telegram Bot webhook to point at n8n's Telegram Trigger webhook URL:

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<n8n-host>/webhook/telegram-router-webhook"
```

Or use n8n's built-in Telegram Trigger node (long-polling mode) — no webhook config needed.

### 6. Expose n8n externally (if needed)

For webhook triggers (outreach_approval, job_to_outreach), n8n needs a public URL.
Use ngrok for local dev or deploy to a VPS/cloud VM:

```bash
ngrok http 5678
```

Update `ORCHESTRATOR_URL` in each workflow to point at your ngrok/VPS URL.

## Workflow Details

### `telegram_router.json`
- Receives every Telegram message/callback
- Auth check: drops messages from IDs != `TELEGRAM_CHAT_ID`
- POSTs `{text, chat_id, update_type}` to `ORCHESTRATOR_URL/dispatch`
- Sends the response text back to Telegram

### `gmail_triage.json`
- Polls Gmail every minute for new INBOX messages
- POSTs email metadata to `ORCHESTRATOR_URL/agents/email_triage`
- If response contains `label: "flag_urgent"`, fires Telegram alert immediately

### `outreach_approval.json`
- **Webhook 1** (`/outreach-approval`): receives draft from outreach agent, sends Telegram inline keyboard
- **Webhook 2** (`/outreach-callback`): receives Telegram callback, routes Approve → `/agents/outreach/send?action=send` or Reject → `?action=reject`

### `job_to_outreach.json`
- Called by job_discovery agent after a high-score job is stored
- Apollo people search with recruiter/hiring-manager title filters (≤5 results)
- Hunter.io verifies each email, skips `status: invalid`
- Valid contacts queued via `/agents/outreach/queue`

### `resume_trigger.json`
- Google Sheets trigger fires on new row in Job Tracker
- Checks `Score >= 8` AND `Status != resume_tailored`
- POSTs `{job_id, score}` to `ORCHESTRATOR_URL/agents/resume`
- Timeout set to 120s (resume tailoring includes LLM calls)

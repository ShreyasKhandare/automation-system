"""
orchestrator/orchestrator.py — Main command router.

Maps incoming Telegram text commands to agent functions.
For unrecognized commands, falls back to Claude API for intent parsing.

Agent functions are imported lazily so missing dependencies for a specific
agent don't break the entire orchestrator.

Entrypoint for the bot:
    python orchestrator/orchestrator.py            # long-polling
    python orchestrator/orchestrator.py --once     # one-shot
    python orchestrator/orchestrator.py --health   # print health report and exit
    python orchestrator/orchestrator.py --status   # print status and exit
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Callable

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.config_loader import load_config

log = get_logger("orchestrator")

# ---------------------------------------------------------------------------
# Command registry
# ---------------------------------------------------------------------------

# Each entry: regex pattern → (handler_fn, help_text)
# Patterns are matched case-insensitively in order.
_COMMAND_REGISTRY: list[tuple[re.Pattern, Callable, str]] = []


def _register(pattern: str, help_text: str):
    """Decorator to register a command handler."""
    def decorator(fn: Callable) -> Callable:
        _COMMAND_REGISTRY.append((re.compile(pattern, re.IGNORECASE), fn, help_text))
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_kv(text: str) -> dict[str, str]:
    """Extract KEY=value pairs from command text."""
    return dict(re.findall(r'(\w+)=([^\s]+)', text))


def _agent_not_ready(name: str) -> str:
    return f"⚠️ Agent *{name}* not yet implemented (Session {_AGENT_SESSIONS.get(name, '?')})."


_AGENT_SESSIONS = {
    "ai_radar": 3,
    "job_discovery": 4,
    "email_triage": 5,
    "resume": 6,
    "github_docs": 7,
    "outreach": 9,
    "project_autopilot": 10,
    "market_research": 10,
}


def _try_import_agent(module_path: str, fn_name: str) -> Callable | None:
    """Lazily import an agent function. Returns None if not yet implemented."""
    import importlib
    try:
        mod = importlib.import_module(module_path)
        return getattr(mod, fn_name, None)
    except (ImportError, ModuleNotFoundError):
        return None


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

@_register(r'^/start$', "Start the bot")
def cmd_start(text: str) -> str:
    cfg = load_config()
    return (
        f"👋 *Shreyas Automation System* online.\n"
        f"Owner: {cfg.profile.name}\n\n"
        f"Type /help for all commands."
    )


@_register(r'^/help$|^HELP$', "List all available commands")
def cmd_help(text: str) -> str:
    lines = ["*Available Commands:*\n"]
    seen: set[str] = set()
    for _, fn, help_text in _COMMAND_REGISTRY:
        if fn.__name__ not in seen and help_text:
            lines.append(f"• `{fn.__name__.replace('cmd_', '').upper()}` — {help_text}")
            seen.add(fn.__name__)
    lines.append("\nSend any natural language and I'll try to figure it out.")
    return "\n".join(lines)


@_register(r'^/health$', "Quick green/yellow/red status per agent")
def cmd_health(text: str) -> str:
    from .health import run_health_check
    report = run_health_check()
    return report.to_short_message()


@_register(r'^/status$|^STATUS$', "Full system health status")
def cmd_status(text: str) -> str:
    from .health import run_health_check
    report = run_health_check()
    return report.to_telegram_message()


@_register(r'^/costs$|^/COSTS$', "Claude API spend month-to-date")
def cmd_costs(text: str) -> str:
    # Costs are tracked via the system_health table or a dedicated costs table (future).
    # For now, return an informative placeholder.
    from shared.db import get_conn, get_db_path
    try:
        with get_conn(get_db_path()) as conn:
            row = conn.execute(
                """
                SELECT SUM(CAST(json_extract(details, '$.tokens_used') AS INTEGER)) as total_tokens
                FROM system_health
                WHERE checked_at >= date('now', 'start of month')
                """
            ).fetchone()
            total_tokens = row[0] or 0
        est_cost = total_tokens / 1_000_000 * 3.0  # rough claude-sonnet estimate
        return (
            f"💰 *Claude API Usage (this month)*\n"
            f"Tokens used: ~{total_tokens:,}\n"
            f"Estimated cost: ~${est_cost:.2f}\n"
            f"_Budget: $10.00/month_"
        )
    except Exception as e:
        return f"⚠️ Could not fetch cost data: {e}"


@_register(r'^/errors$', "All errors in last 24 hours")
def cmd_errors(text: str) -> str:
    from shared.db import get_conn, get_db_path
    try:
        with get_conn(get_db_path()) as conn:
            rows = conn.execute(
                """
                SELECT agent_name, message, checked_at
                FROM system_health
                WHERE status = 'red'
                  AND checked_at >= datetime('now', '-24 hours')
                ORDER BY checked_at DESC
                LIMIT 20
                """
            ).fetchall()
        if not rows:
            return "✅ No errors in the last 24 hours."
        lines = ["🔴 *Errors (last 24h):*\n"]
        for r in rows:
            lines.append(f"• [{r['checked_at'][:16]}] *{r['agent_name']}*: {r['message']}")
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Could not fetch errors: {e}"


@_register(r'^/logs\s*(\w+)?$', "Last 50 log lines for an agent")
def cmd_logs(text: str) -> str:
    match = re.search(r'/logs\s*(\w+)?', text, re.IGNORECASE)
    agent = match.group(1) if match and match.group(1) else None
    log_dir = _REPO_ROOT / "logs"

    if agent:
        log_file = log_dir / f"{agent}.log"
        if not log_file.exists():
            return f"⚠️ No log file found for agent `{agent}`."
        with open(log_file) as f:
            lines = f.readlines()[-50:]
        return f"```\n{''.join(lines[-30:])}\n```"  # last 30 for Telegram limit
    else:
        files = sorted(log_dir.glob("*.log"))
        if not files:
            return "No log files found."
        return "Available logs:\n" + "\n".join(f"• `{f.stem}`" for f in files)


@_register(r'^/jobs\s*(today)?$', "Today's job digest")
def cmd_jobs(text: str) -> str:
    fn = _try_import_agent("agents.job_discovery.notifier", "get_today_digest")
    if fn:
        return fn()
    return _agent_not_ready("job_discovery")


@_register(r'^RUN\s+JOB[_\s]SWEEP(\s+STEALTH)?', "Run full job discovery pipeline now")
def cmd_job_sweep(text: str) -> str:
    stealth = bool(re.search(r'STEALTH', text, re.IGNORECASE))
    fn = _try_import_agent("agents.job_discovery.scraper", "run")
    if fn:
        return fn(stealth=stealth)
    return _agent_not_ready("job_discovery")


@_register(r'^RUN\s+OUTREACH\s+SAFE$', "Find recruiters and draft emails for approval")
def cmd_outreach_safe(text: str) -> str:
    fn = _try_import_agent("agents.outreach.finder", "run_assisted")
    if fn:
        return fn()
    return _agent_not_ready("outreach")


@_register(r'^PAUSE\s+OUTREACH\s*(\d+H)?', "Pause outreach for N hours")
def cmd_pause_outreach(text: str) -> str:
    match = re.search(r'(\d+)\s*H', text, re.IGNORECASE)
    hours = int(match.group(1)) if match else 24
    fn = _try_import_agent("agents.outreach.tracker", "pause")
    if fn:
        return fn(hours)
    return _agent_not_ready("outreach")


@_register(r'^RESUME\s+OUTREACH$', "Resume paused outreach")
def cmd_resume_outreach(text: str) -> str:
    fn = _try_import_agent("agents.outreach.tracker", "resume_outreach")
    if fn:
        return fn()
    return _agent_not_ready("outreach")


@_register(r'^/outreach\s+status$', "Outreach stats: sent, replied, pending")
def cmd_outreach_status(text: str) -> str:
    from shared.db import get_conn, get_db_path
    try:
        with get_conn(get_db_path()) as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status = 'sent') as sent,
                    COUNT(*) FILTER (WHERE status = 'replied') as replied,
                    COUNT(*) FILTER (WHERE status = 'pending_approval') as pending,
                    COUNT(*) FILTER (WHERE status = 'draft') as drafts
                FROM outreach
                """
            ).fetchone()
        return (
            f"📬 *Outreach Status*\n"
            f"• Sent: {row['sent']}\n"
            f"• Replied: {row['replied']}\n"
            f"• Pending approval: {row['pending']}\n"
            f"• Drafts: {row['drafts']}"
        )
    except Exception as e:
        return f"⚠️ {e}"


@_register(r'^/emails$', "Current inbox triage summary")
def cmd_emails(text: str) -> str:
    fn = _try_import_agent("agents.email_triage.digest", "get_summary")
    if fn:
        return fn()
    return _agent_not_ready("email_triage")


@_register(r'^GENERATE\s+DAILY[_\s]DIGEST(\s+NOW)?', "Generate and send today's full digest")
def cmd_daily_digest(text: str) -> str:
    from .digest import generate_digest
    return generate_digest()


@_register(r'^START\s+PROJECT\s+(\S+)\s+(\S+)\s+"?(.+)"?', "Start a bounded coding task on a repo")
def cmd_start_project(text: str) -> str:
    match = re.search(r'START\s+PROJECT\s+(\S+)\s+(\S+)\s+"?(.+?)"?\s*$', text, re.IGNORECASE)
    if not match:
        return "Usage: `START PROJECT <repo_name> <task_type> \"description\"`"
    repo, task_type, description = match.group(1), match.group(2), match.group(3)
    fn = _try_import_agent("agents.project_autopilot.runner", "run")
    if fn:
        return fn(repo_name=repo, task_type=task_type, description=description)
    return _agent_not_ready("project_autopilot")


@_register(r'^/projects\s+status$', "Last commit, branch, test status per repo")
def cmd_projects_status(text: str) -> str:
    fn = _try_import_agent("agents.project_autopilot.reporter", "get_status")
    if fn:
        return fn()
    return _agent_not_ready("project_autopilot")


@_register(r'^RUN\s+RESUME[_\s]TAILORING', "Tailor resume for a specific job")
def cmd_resume_tailoring(text: str) -> str:
    kv = _parse_kv(text)
    job_id = kv.get("JOB_ID") or kv.get("job_id")
    if not job_id:
        return "Usage: `RUN RESUME_TAILORING JOB_ID=job_20260330_company_title`"
    fn = _try_import_agent("agents.resume.resume_agent", "run")
    if fn:
        return fn(job_id=job_id)
    return _agent_not_ready("resume")


@_register(r'^/resumes\s+list$', "List all resume variants")
def cmd_resumes_list(text: str) -> str:
    from shared.db import get_conn, get_db_path
    try:
        with get_conn(get_db_path()) as conn:
            rows = conn.execute(
                "SELECT id, job_id, status, created_at FROM resumes ORDER BY created_at DESC LIMIT 10"
            ).fetchall()
        if not rows:
            return "No tailored resumes yet."
        lines = ["📄 *Recent Resume Variants:*\n"]
        for r in rows:
            lines.append(f"• `{r['id']}` → {r['job_id']} [{r['status']}]")
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ {e}"


@_register(r'^RESCAN\s+MARKET', "Run full market and profile research now")
def cmd_rescan_market(text: str) -> str:
    fn = _try_import_agent("agents.market_research.scraper", "run")
    if fn:
        return fn()
    return _agent_not_ready("market_research")


@_register(r'^RESCAN\s+AI[_\s]TOOLS', "Run AI tools radar scan now")
def cmd_rescan_ai_tools(text: str) -> str:
    fn = _try_import_agent("agents.ai_radar.aggregator", "run")
    if fn:
        return fn()
    return _agent_not_ready("ai_radar")


@_register(r'^/briefing$', "Today's AI briefing")
def cmd_briefing(text: str) -> str:
    fn = _try_import_agent("agents.ai_radar.notifier", "get_latest_briefing")
    if fn:
        return fn()
    return _agent_not_ready("ai_radar")


@_register(r'^UPDATE\s+GITHUB[_\s]DOCS', "Generate and commit latest docs and reports")
def cmd_update_github_docs(text: str) -> str:
    fn = _try_import_agent("agents.github_docs.docs_agent", "run")
    if fn:
        return fn()
    return _agent_not_ready("github_docs")


@_register(r'^/commits$', "Last 5 commits across tracked repos")
def cmd_commits(text: str) -> str:
    fn = _try_import_agent("agents.github_docs.docs_agent", "get_recent_commits")
    if fn:
        return fn()
    return _agent_not_ready("github_docs")


# ---------------------------------------------------------------------------
# Claude fallback for unrecognized commands
# ---------------------------------------------------------------------------

def _claude_fallback(text: str) -> str:
    """
    When no pattern matches, ask Claude to:
      1. Identify the best matching command
      2. Return either the matched command string or a helpful response
    """
    try:
        import anthropic
        from shared.secrets import get_secret

        api_key = get_secret("ANTHROPIC_API_KEY")
        client = anthropic.Anthropic(api_key=api_key)

        command_list = "\n".join(
            f"- {fn.__name__.replace('cmd_', '').upper()}: {help_text}"
            for _, fn, help_text in _COMMAND_REGISTRY
            if help_text
        )

        system = (
            "You are the command parser for Shreyas's job search automation system. "
            "The user sent a Telegram message that didn't match any known command. "
            "Your job: identify the best matching command from the list below and return ONLY "
            "the command string (e.g. 'RUN JOB_SWEEP') so it can be re-dispatched. "
            "If the message is conversational (not a command), respond helpfully in 1-2 sentences. "
            "If it's an ambiguous command, ask a clarifying question.\n\n"
            f"Available commands:\n{command_list}"
        )

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": text}],
        )
        parsed = response.content[0].text.strip()

        # If Claude returned a known command, re-dispatch it
        for pattern, fn, _ in _COMMAND_REGISTRY:
            if pattern.match(parsed):
                log.info("claude_fallback_matched", original=text, matched=parsed)
                return fn(parsed)

        # Otherwise return Claude's conversational response
        return parsed

    except Exception as e:
        log.error("claude_fallback_failed", error=str(e))
        return (
            f"❓ Unrecognized command: `{text[:80]}`\n"
            f"Type /help to see all available commands."
        )


# ---------------------------------------------------------------------------
# Main dispatch function (called by telegram_bot.py)
# ---------------------------------------------------------------------------

def dispatch(text: str) -> str:
    """
    Route a command string to the appropriate handler.
    Falls back to Claude for unrecognized input.
    """
    text = text.strip()
    if not text:
        return "❓ Empty message received."

    for pattern, fn, _ in _COMMAND_REGISTRY:
        if pattern.match(text):
            log.info("command_dispatched", command=fn.__name__, text=text[:80])
            try:
                return fn(text)
            except Exception as e:
                log.error("command_failed", command=fn.__name__, error=str(e), exc_info=True)
                return f"🔴 Command failed: {e}"

    log.info("command_unrecognized", text=text[:80])
    return _claude_fallback(text)


# ---------------------------------------------------------------------------
# Convenience functions used by GitHub Actions / digest.py
# ---------------------------------------------------------------------------

def get_status() -> str:
    return cmd_status("")


def get_health() -> str:
    return cmd_health("")


def get_costs() -> str:
    return cmd_costs("")


def generate_digest() -> str:
    from .digest import generate_digest as _gen
    return _gen()


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Shreyas Automation Orchestrator")
    parser.add_argument("--once", action="store_true", help="Process pending Telegram updates once and exit")
    parser.add_argument("--health", action="store_true", help="Print health report and exit")
    parser.add_argument("--status", action="store_true", help="Print full status and exit")
    args = parser.parse_args()

    if args.health:
        print(get_health())
        sys.exit(0)

    if args.status:
        print(get_status())
        sys.exit(0)

    from .telegram_bot import create_bot
    bot = create_bot(dispatch_fn=dispatch)

    if args.once:
        count = bot.run_once()
        print(f"Processed {count} update(s).")
    else:
        bot.run_polling()

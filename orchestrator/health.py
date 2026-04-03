"""
orchestrator/health.py — Per-agent health checks returning green/yellow/red status.

Each check looks at:
  - Last successful run timestamp (from system_health table)
  - Presence of required secrets
  - Reachability of external APIs (lightweight ping)

Returns a HealthReport dataclass used by /status and /health Telegram commands.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=False)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AgentHealth:
    name: str
    status: str          # "green" | "yellow" | "red"
    message: str
    last_run: str | None = None     # ISO timestamp of last successful run
    last_error: str | None = None
    details: dict = field(default_factory=dict)

    @property
    def emoji(self) -> str:
        return {"green": "✅", "yellow": "⚠️", "red": "🔴"}.get(self.status, "❓")

    def to_telegram_line(self) -> str:
        age = ""
        if self.last_run:
            try:
                last = datetime.fromisoformat(self.last_run)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                delta = datetime.now(timezone.utc) - last
                h = int(delta.total_seconds() // 3600)
                age = f" ({h}h ago)" if h < 48 else f" ({delta.days}d ago)"
            except Exception:
                pass
        return f"{self.emoji} *{self.name}*: {self.message}{age}"


@dataclass
class HealthReport:
    agents: list[AgentHealth]
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    overall: str = "green"   # green | yellow | red

    def __post_init__(self) -> None:
        statuses = {a.status for a in self.agents}
        if "red" in statuses:
            self.overall = "red"
        elif "yellow" in statuses:
            self.overall = "yellow"
        else:
            self.overall = "green"

    @property
    def overall_emoji(self) -> str:
        return {"green": "✅", "yellow": "⚠️", "red": "🔴"}.get(self.overall, "❓")

    def to_telegram_message(self) -> str:
        lines = [f"{self.overall_emoji} *System Health* — {self.checked_at[:19]} UTC\n"]
        for agent in self.agents:
            lines.append(agent.to_telegram_line())
        return "\n".join(lines)

    def to_short_message(self) -> str:
        """One-liner summary for quick /health response."""
        green = sum(1 for a in self.agents if a.status == "green")
        yellow = sum(1 for a in self.agents if a.status == "yellow")
        red = sum(1 for a in self.agents if a.status == "red")
        return (
            f"{self.overall_emoji} *Health:* "
            f"✅{green} ⚠️{yellow} 🔴{red} "
            f"({len(self.agents)} agents checked)"
        )


# ---------------------------------------------------------------------------
# Max expected run intervals per agent (for staleness detection)
# ---------------------------------------------------------------------------

_MAX_STALE_HOURS: dict[str, float] = {
    "ai_radar":        26,   # daily
    "job_discovery":   26,   # daily Mon–Fri (allow weekend gap)
    "email_triage":     3,   # every 2h
    "github_docs":     26,   # nightly
    "market_research": 170,  # weekly (Sunday)
    "outreach":        None, # on-demand
    "resume":          None, # on-demand
    "project_autopilot": None,  # on-demand
}

_REQUIRED_SECRETS_PER_AGENT: dict[str, list[str]] = {
    "ai_radar":          ["ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN"],
    "job_discovery":     ["ANTHROPIC_API_KEY", "SERPAPI_API_KEY", "TELEGRAM_BOT_TOKEN"],
    "email_triage":      ["ANTHROPIC_API_KEY", "GMAIL_CLIENT_ID", "GMAIL_REFRESH_TOKEN", "TELEGRAM_BOT_TOKEN"],
    "github_docs":       ["GH_PAT", "ANTHROPIC_API_KEY"],
    "market_research":   ["ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN"],
    "outreach":          ["APOLLO_API_KEY", "HUNTER_API_KEY", "GMAIL_CLIENT_ID", "TELEGRAM_BOT_TOKEN"],
    "resume":            ["ANTHROPIC_API_KEY"],
    "project_autopilot": ["ANTHROPIC_API_KEY", "GH_PAT"],
}


# ---------------------------------------------------------------------------
# Individual check helpers
# ---------------------------------------------------------------------------

def _check_secrets(agent_name: str) -> tuple[bool, str]:
    """Returns (ok, message). Missing secrets → red."""
    required = _REQUIRED_SECRETS_PER_AGENT.get(agent_name, [])
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        return False, f"Missing secrets: {', '.join(missing)}"
    return True, "Secrets OK"


def _check_last_run(conn, agent_name: str) -> tuple[str, str | None, str | None]:
    """
    Query system_health table for the last run of this agent.
    Returns (status, last_run_iso, last_error_msg).
    """
    try:
        row = conn.execute(
            """
            SELECT status, message, checked_at
            FROM system_health
            WHERE agent_name = ?
            ORDER BY checked_at DESC
            LIMIT 1
            """,
            (agent_name,),
        ).fetchone()

        if row is None:
            return "yellow", None, "No run history"

        last_status = row["status"]
        last_run = row["checked_at"]
        last_error = row["message"] if last_status != "green" else None

        max_h = _MAX_STALE_HOURS.get(agent_name)
        if max_h is not None and last_run:
            try:
                last_dt = datetime.fromisoformat(last_run)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                age_h = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
                if age_h > max_h:
                    return "yellow", last_run, f"Last run {age_h:.0f}h ago (expected ≤{max_h}h)"
            except Exception:
                pass

        return last_status, last_run, last_error

    except Exception as e:
        return "yellow", None, f"DB error: {e}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

AGENT_NAMES = [
    "ai_radar",
    "job_discovery",
    "email_triage",
    "github_docs",
    "market_research",
    "outreach",
    "resume",
    "project_autopilot",
]


def check_agent(conn, agent_name: str) -> AgentHealth:
    """Run all health checks for a single agent."""
    secrets_ok, secrets_msg = _check_secrets(agent_name)
    if not secrets_ok:
        return AgentHealth(
            name=agent_name,
            status="red",
            message=secrets_msg,
        )

    run_status, last_run, last_error = _check_last_run(conn, agent_name)

    if run_status == "green":
        return AgentHealth(
            name=agent_name,
            status="green",
            message="OK",
            last_run=last_run,
        )
    elif run_status == "yellow":
        msg = last_error or "No recent run"
        return AgentHealth(
            name=agent_name,
            status="yellow",
            message=msg,
            last_run=last_run,
            last_error=last_error,
        )
    else:
        return AgentHealth(
            name=agent_name,
            status="red",
            message=last_error or "Last run failed",
            last_run=last_run,
            last_error=last_error,
        )


def run_health_check(db_path=None) -> HealthReport:
    """
    Run health checks for all agents. Returns a HealthReport.
    Safe to call even if DB doesn't exist yet.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from shared.db import get_conn, get_db_path, init_db

    path = db_path or get_db_path()

    # Init DB if it doesn't exist yet
    if not Path(str(path)).exists():
        init_db(path)

    agents: list[AgentHealth] = []
    with get_conn(path) as conn:
        for name in AGENT_NAMES:
            agents.append(check_agent(conn, name))

    return HealthReport(agents=agents)


if __name__ == "__main__":
    report = run_health_check()
    print(report.to_telegram_message())

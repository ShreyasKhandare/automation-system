"""
shared/db.py — SQLite schema and connection management for all agents.

Tables:
  - jobs           : discovered job listings
  - outreach       : recruiter contact CRM
  - resumes        : tailored resume version index
  - ai_radar       : AI tools/papers digest items
  - project_runs   : project autopilot execution log
  - system_health  : per-agent health check history
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_DB_PATH = _REPO_ROOT / "automation.sqlite"

# --------------------------------------------------------------------------- #
# DDL                                                                          #
# --------------------------------------------------------------------------- #

_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ------------------------------------------------------------------ jobs ---
CREATE TABLE IF NOT EXISTS jobs (
    id                TEXT PRIMARY KEY,          -- e.g. job_20260330_sardine_ai_eng
    title             TEXT NOT NULL,
    company           TEXT NOT NULL,
    url               TEXT NOT NULL,
    source            TEXT NOT NULL,             -- wellfound | greenhouse | otta | serpapi | indeed | linkedin
    location          TEXT,
    salary_min        INTEGER,
    salary_max        INTEGER,
    salary_currency   TEXT DEFAULT 'USD',
    employment_type   TEXT,
    remote            INTEGER DEFAULT 0,         -- 0=false, 1=true
    tech_stack        TEXT,                      -- JSON array
    description_raw   TEXT,
    description_clean TEXT,
    posted_date       TEXT,                      -- ISO date
    score             REAL,                      -- 0-10 Claude score
    score_reason      TEXT,
    status            TEXT DEFAULT 'new',        -- new | reviewed | applied | rejected | archived
    applied_date      TEXT,
    notes             TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_posted_date ON jobs(posted_date DESC);

-- --------------------------------------------------------------- outreach ---
CREATE TABLE IF NOT EXISTS outreach (
    id                TEXT PRIMARY KEY,          -- e.g. out_20260330_jane_doe_sardine
    recruiter_name    TEXT NOT NULL,
    recruiter_title   TEXT,
    company           TEXT NOT NULL,
    email             TEXT,
    email_verified    INTEGER DEFAULT 0,
    linkedin_url      TEXT,
    source            TEXT,                      -- apollo | manual
    draft_subject     TEXT,
    draft_body        TEXT,
    status            TEXT DEFAULT 'draft',      -- draft | pending_approval | sent | replied | bounced | opted_out
    approved_at       TEXT,
    sent_at           TEXT,
    reply_received    INTEGER DEFAULT 0,
    reply_at          TEXT,
    follow_up_count   INTEGER DEFAULT 0,
    next_follow_up_at TEXT,
    job_id            TEXT REFERENCES jobs(id),
    notes             TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_outreach_status ON outreach(status);
CREATE INDEX IF NOT EXISTS idx_outreach_company ON outreach(company);
CREATE INDEX IF NOT EXISTS idx_outreach_sent_at ON outreach(sent_at DESC);

-- --------------------------------------------------------------- resumes ---
CREATE TABLE IF NOT EXISTS resumes (
    id                TEXT PRIMARY KEY,          -- e.g. resume_20260330_sardine_ai_eng_v1
    job_id            TEXT REFERENCES jobs(id),
    version           INTEGER NOT NULL DEFAULT 1,
    template          TEXT,
    output_md_path    TEXT,
    output_pdf_path   TEXT,
    output_docx_path  TEXT,
    keywords_added    TEXT,                      -- JSON array
    keywords_removed  TEXT,                      -- JSON array
    ats_score_before  REAL,
    ats_score_after   REAL,
    diff_summary      TEXT,
    status            TEXT DEFAULT 'generated',  -- generated | submitted | archived
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_resumes_job_id ON resumes(job_id);
CREATE INDEX IF NOT EXISTS idx_resumes_created_at ON resumes(created_at DESC);

-- --------------------------------------------------------------- ai_radar ---
CREATE TABLE IF NOT EXISTS ai_radar (
    id                TEXT PRIMARY KEY,          -- e.g. radar_20260330_hn_1234
    title             TEXT NOT NULL,
    url               TEXT,
    source            TEXT NOT NULL,             -- hn | huggingface | arxiv | github_trending | product_hunt
    category          TEXT,                      -- model | tool | framework | paper | tutorial | news
    relevance_score   REAL,                      -- 0-1 Claude relevance score
    action_tag        TEXT,                      -- TRY_ASAP | WATCH | IGNORE
    summary           TEXT,
    raw_content       TEXT,
    published_at      TEXT,
    included_in_digest TEXT,                     -- date of digest that included this item
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ai_radar_action_tag ON ai_radar(action_tag);
CREATE INDEX IF NOT EXISTS idx_ai_radar_source ON ai_radar(source);
CREATE INDEX IF NOT EXISTS idx_ai_radar_created_at ON ai_radar(created_at DESC);

-- --------------------------------------------------------- project_runs ---
CREATE TABLE IF NOT EXISTS project_runs (
    id                TEXT PRIMARY KEY,          -- e.g. run_20260330_finops_sentinel_bugfix
    repo_name         TEXT NOT NULL,
    task_type         TEXT NOT NULL,             -- bugfix | docs | small_feature | refactor | test | content_update
    description       TEXT,
    status            TEXT DEFAULT 'pending',    -- pending | running | completed | failed | cancelled
    triggered_by      TEXT DEFAULT 'manual',     -- manual | telegram | schedule
    branch_name       TEXT,
    pr_url            TEXT,
    lines_changed     INTEGER,
    files_changed     TEXT,                      -- JSON array of file paths
    error_message     TEXT,
    started_at        TEXT,
    completed_at      TEXT,
    duration_seconds  INTEGER,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_project_runs_repo ON project_runs(repo_name);
CREATE INDEX IF NOT EXISTS idx_project_runs_status ON project_runs(status);
CREATE INDEX IF NOT EXISTS idx_project_runs_created_at ON project_runs(created_at DESC);

-- ------------------------------------------------------- system_health ---
CREATE TABLE IF NOT EXISTS system_health (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name        TEXT NOT NULL,             -- job_discovery | outreach | email_triage | etc.
    status            TEXT NOT NULL,             -- green | yellow | red
    message           TEXT,
    details           TEXT,                      -- JSON blob
    checked_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_system_health_agent ON system_health(agent_name);
CREATE INDEX IF NOT EXISTS idx_system_health_checked_at ON system_health(checked_at DESC);

-- ------------------------------------------------- auto-update triggers ---
CREATE TRIGGER IF NOT EXISTS jobs_updated_at
    AFTER UPDATE ON jobs
    FOR EACH ROW
    BEGIN
        UPDATE jobs SET updated_at = datetime('now') WHERE id = NEW.id;
    END;

CREATE TRIGGER IF NOT EXISTS outreach_updated_at
    AFTER UPDATE ON outreach
    FOR EACH ROW
    BEGIN
        UPDATE outreach SET updated_at = datetime('now') WHERE id = NEW.id;
    END;
"""


# --------------------------------------------------------------------------- #
# Connection management                                                        #
# --------------------------------------------------------------------------- #

def get_db_path() -> Path:
    """Return the DB path, respecting DB_PATH env var override."""
    import os
    env_path = os.environ.get("DB_PATH")
    return Path(env_path) if env_path else _DEFAULT_DB_PATH


def init_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    """
    Create the SQLite file, run DDL, and return an open connection.
    Safe to call multiple times — all CREATE TABLE statements are idempotent.
    """
    path = Path(db_path) if db_path else get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    conn.commit()
    return conn


@contextmanager
def get_conn(db_path: str | Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager that yields a connected, auto-committed/rolled-back connection."""
    path = Path(db_path) if db_path else get_db_path()
    conn = sqlite3.connect(str(path), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Helper utilities                                                             #
# --------------------------------------------------------------------------- #

def upsert_job(conn: sqlite3.Connection, job: dict) -> None:
    """Insert or replace a job record."""
    cols = ", ".join(job.keys())
    placeholders = ", ".join(["?"] * len(job))
    sql = f"INSERT OR REPLACE INTO jobs ({cols}) VALUES ({placeholders})"
    conn.execute(sql, list(job.values()))


def upsert_outreach(conn: sqlite3.Connection, record: dict) -> None:
    """Insert or replace an outreach record."""
    cols = ", ".join(record.keys())
    placeholders = ", ".join(["?"] * len(record))
    sql = f"INSERT OR REPLACE INTO outreach ({cols}) VALUES ({placeholders})"
    conn.execute(sql, list(record.values()))


def upsert_ai_radar(conn: sqlite3.Connection, item: dict) -> None:
    """Insert or replace an AI radar item."""
    cols = ", ".join(item.keys())
    placeholders = ", ".join(["?"] * len(item))
    sql = f"INSERT OR REPLACE INTO ai_radar ({cols}) VALUES ({placeholders})"
    conn.execute(sql, list(item.values()))


def log_health(conn: sqlite3.Connection, agent_name: str, status: str, message: str = "", details: dict | None = None) -> None:
    """Insert a health check record."""
    import json
    conn.execute(
        "INSERT INTO system_health (agent_name, status, message, details) VALUES (?, ?, ?, ?)",
        (agent_name, status, message, json.dumps(details) if details else None),
    )


def get_today_send_count(conn: sqlite3.Connection) -> int:
    """Return count of outreach emails sent today (for warm-up enforcement)."""
    row = conn.execute(
        "SELECT COUNT(*) FROM outreach WHERE status = 'sent' AND date(sent_at) = date('now')"
    ).fetchone()
    return row[0] if row else 0


if __name__ == "__main__":
    conn = init_db()
    print("Database initialized successfully.")
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    print("Tables:", [t["name"] for t in tables])
    conn.close()

"""
shared/logger.py — Structured JSON logger used by all agents.

Usage:
    from shared.logger import get_logger
    log = get_logger("job_discovery")
    log.info("scrape_complete", jobs_found=42, source="wellfound")
    log.error("api_error", error=str(e), source="serpapi")
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent
_LOGS_DIR = _REPO_ROOT / "logs"


class _JsonFormatter(logging.Formatter):
    """Formats each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "agent": record.name,
            "event": record.getMessage(),
        }

        # Merge any extra fields set on the record
        for key, val in record.__dict__.items():
            if key.startswith("_extra_"):
                payload[key[7:]] = val  # strip _extra_ prefix

        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def get_logger(
    agent_name: str,
    *,
    log_to_file: bool = True,
    log_to_stdout: bool = True,
    level: int = logging.INFO,
) -> "StructuredLogger":
    """
    Return a StructuredLogger for the given agent.
    Creates logs/<agent_name>.log and also streams to stdout.
    """
    return StructuredLogger(
        agent_name=agent_name,
        log_to_file=log_to_file,
        log_to_stdout=log_to_stdout,
        level=level,
    )


class StructuredLogger:
    """
    Thin wrapper around stdlib logging that enforces structured JSON output
    and supports keyword-argument-based contextual fields.

    Example:
        log = StructuredLogger("job_discovery")
        log.info("found_jobs", count=5, source="wellfound")
        log.error("request_failed", url="...", status_code=429)
    """

    def __init__(
        self,
        agent_name: str,
        log_to_file: bool = True,
        log_to_stdout: bool = True,
        level: int = logging.INFO,
    ):
        self._agent_name = agent_name
        self._logger = logging.getLogger(agent_name)
        self._logger.setLevel(level)
        self._logger.propagate = False

        # Avoid duplicate handlers if called multiple times
        if self._logger.handlers:
            return

        formatter = _JsonFormatter()

        if log_to_stdout:
            sh = logging.StreamHandler(sys.stdout)
            sh.setFormatter(formatter)
            self._logger.addHandler(sh)

        if log_to_file:
            _LOGS_DIR.mkdir(exist_ok=True)
            log_file = _LOGS_DIR / f"{agent_name}.log"
            fh = logging.FileHandler(str(log_file), encoding="utf-8")
            fh.setFormatter(formatter)
            self._logger.addHandler(fh)

    # ------------------------------------------------------------------ #
    # Public logging methods                                               #
    # ------------------------------------------------------------------ #

    def info(self, event: str, **kwargs: Any) -> None:
        self._log(logging.INFO, event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, event, **kwargs)

    def error(self, event: str, exc_info: bool = False, **kwargs: Any) -> None:
        self._log(logging.ERROR, event, exc_info=exc_info, **kwargs)

    def debug(self, event: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, event, **kwargs)

    def critical(self, event: str, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, event, **kwargs)

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _log(
        self,
        level: int,
        event: str,
        exc_info: bool = False,
        **kwargs: Any,
    ) -> None:
        extra = {f"_extra_{k}": v for k, v in kwargs.items()}
        self._logger.log(
            level,
            event,
            exc_info=exc_info,
            extra=extra,
        )

    # ------------------------------------------------------------------ #
    # Context manager for run-level bookkeeping                           #
    # ------------------------------------------------------------------ #

    def run_start(self, run_id: str, **kwargs: Any) -> None:
        self.info("run_start", run_id=run_id, **kwargs)

    def run_end(self, run_id: str, status: str = "ok", **kwargs: Any) -> None:
        self.info("run_end", run_id=run_id, status=status, **kwargs)

    def run_error(self, run_id: str, error: str, **kwargs: Any) -> None:
        self.error("run_error", run_id=run_id, error=error, exc_info=True, **kwargs)


# --------------------------------------------------------------------------- #
# Module-level convenience logger for one-off usage                           #
# --------------------------------------------------------------------------- #

_system_logger: StructuredLogger | None = None


def system_log(event: str, level: str = "info", **kwargs: Any) -> None:
    """Quick system-level log without creating a named logger."""
    global _system_logger
    if _system_logger is None:
        _system_logger = get_logger("system")
    getattr(_system_logger, level)(event, **kwargs)


if __name__ == "__main__":
    log = get_logger("test_agent")
    log.info("logger_initialized", version="1.0")
    log.warning("rate_limit_approaching", remaining_calls=5, limit=30)
    log.error("api_timeout", url="https://api.example.com", timeout_ms=5000)
    print("Logger test complete. Check logs/test_agent.log")

"""
shared/secrets.py — Loads secrets from .env file.

NEVER import secrets from config.yaml.
All secret keys must be defined in REQUIRED_SECRETS below.
If any required secret is missing, a clear MissingSecretError is raised at startup.

Usage:
    from shared.secrets import secrets
    token = secrets.TELEGRAM_BOT_TOKEN
    key = secrets.ANTHROPIC_API_KEY
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Optional dotenv support — graceful fallback if not installed
try:
    from dotenv import load_dotenv
    _HAS_DOTENV = True
except ImportError:
    _HAS_DOTENV = False

_REPO_ROOT = Path(__file__).parent.parent
_ENV_PATH = _REPO_ROOT / ".env"

# --------------------------------------------------------------------------- #
# All required secret names                                                    #
# --------------------------------------------------------------------------- #

REQUIRED_SECRETS: list[str] = [
    "ANTHROPIC_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "GMAIL_CLIENT_ID",
    "GMAIL_CLIENT_SECRET",
    "GMAIL_REFRESH_TOKEN",
    "SERPAPI_API_KEY",
    "APOLLO_API_KEY",
    "HUNTER_API_KEY",
    "GOOGLE_SHEETS_CREDENTIALS_JSON",  # path to service account JSON file
    "GOOGLE_SHEET_ID_JOBS",
    "GOOGLE_SHEET_ID_OUTREACH",
    "NOTION_API_KEY",
    "NOTION_DATABASE_ID_MARKET",
    "GITHUB_TOKEN",
    "APIFY_API_TOKEN",               # optional — only needed when linkedin_apify enabled
]

# Secrets that are optional (missing won't raise at startup)
OPTIONAL_SECRETS: set[str] = {
    "APIFY_API_TOKEN",
    "NOTION_API_KEY",
    "NOTION_DATABASE_ID_MARKET",
}


# --------------------------------------------------------------------------- #
# Error type                                                                   #
# --------------------------------------------------------------------------- #

class MissingSecretError(RuntimeError):
    """Raised when a required secret is absent from the environment."""

    def __init__(self, key: str) -> None:
        super().__init__(
            f"\n\n[SECRETS ERROR] Required secret '{key}' is not set.\n"
            f"  1. Copy .env.example to .env\n"
            f"  2. Fill in the value for {key}\n"
            f"  3. NEVER commit .env to git\n"
        )
        self.key = key


# --------------------------------------------------------------------------- #
# Secrets container                                                            #
# --------------------------------------------------------------------------- #

@dataclass
class _Secrets:
    """Typed container for all secrets. Access via the module-level `secrets` singleton."""

    # Core
    ANTHROPIC_API_KEY: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Gmail
    GMAIL_CLIENT_ID: str = ""
    GMAIL_CLIENT_SECRET: str = ""
    GMAIL_REFRESH_TOKEN: str = ""

    # Job discovery
    SERPAPI_API_KEY: str = ""
    APIFY_API_TOKEN: str = ""

    # Outreach
    APOLLO_API_KEY: str = ""
    HUNTER_API_KEY: str = ""

    # Google Sheets
    GOOGLE_SHEETS_CREDENTIALS_JSON: str = ""
    GOOGLE_SHEET_ID_JOBS: str = ""
    GOOGLE_SHEET_ID_OUTREACH: str = ""

    # Notion
    NOTION_API_KEY: str = ""
    NOTION_DATABASE_ID_MARKET: str = ""

    # GitHub
    GITHUB_TOKEN: str = ""

    def get(self, key: str) -> str:
        """Get a secret by name. Raises MissingSecretError if not set."""
        val = getattr(self, key, None)
        if not val:
            raise MissingSecretError(key)
        return val


def _load_secrets() -> _Secrets:
    """Load .env file and populate the _Secrets dataclass."""
    if _HAS_DOTENV and _ENV_PATH.exists():
        load_dotenv(dotenv_path=_ENV_PATH, override=False)
    elif not _HAS_DOTENV:
        # Fall back to manual parsing
        if _ENV_PATH.exists():
            _manual_load_dotenv(_ENV_PATH)

    missing: list[str] = []
    kwargs: dict[str, str] = {}

    for key in REQUIRED_SECRETS:
        val = os.environ.get(key, "")
        if not val and key not in OPTIONAL_SECRETS:
            missing.append(key)
        kwargs[key] = val

    if missing:
        raise MissingSecretError(missing[0])

    return _Secrets(**kwargs)


def _manual_load_dotenv(path: Path) -> None:
    """Minimal .env parser used when python-dotenv is not installed."""
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def validate_secrets() -> None:
    """
    Validate that all required secrets are present.
    Call this at agent startup for a fast-fail with a clear error message.
    Does NOT raise for optional secrets.
    """
    if _HAS_DOTENV and _ENV_PATH.exists():
        load_dotenv(dotenv_path=_ENV_PATH, override=False)

    missing = [
        key for key in REQUIRED_SECRETS
        if key not in OPTIONAL_SECRETS and not os.environ.get(key)
    ]

    if missing:
        lines = "\n  - ".join(missing)
        raise MissingSecretError(
            f"Missing required secrets:\n  - {lines}\n\nCopy .env.example → .env and fill in values."
        )


def get_secret(key: str) -> str:
    """
    Get a single secret by name, loading .env if needed.
    Raises MissingSecretError if not set.
    """
    if _HAS_DOTENV and _ENV_PATH.exists():
        load_dotenv(dotenv_path=_ENV_PATH, override=False)

    val = os.environ.get(key, "")
    if not val:
        raise MissingSecretError(key)
    return val


# --------------------------------------------------------------------------- #
# Module-level singleton — lazy loaded                                        #
# --------------------------------------------------------------------------- #

_secrets_instance: _Secrets | None = None


class _SecretsProxy:
    """
    Lazy proxy: loads secrets on first attribute access.
    Use `from shared.secrets import secrets` and access as `secrets.ANTHROPIC_API_KEY`.
    """

    def __getattr__(self, name: str) -> str:
        global _secrets_instance
        if _secrets_instance is None:
            _secrets_instance = _load_secrets()
        return getattr(_secrets_instance, name)


secrets: _Secrets = _SecretsProxy()  # type: ignore[assignment]


if __name__ == "__main__":
    print("Checking secrets...")
    try:
        validate_secrets()
        print("All required secrets are present.")
    except MissingSecretError as e:
        print(f"WARNING: {e}")
        print("Create a .env file from .env.example to fix this.")

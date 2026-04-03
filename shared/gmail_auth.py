"""
shared/gmail_auth.py — Gmail OAuth2 token generator.

Launches a local browser-based OAuth flow using your GMAIL_CLIENT_ID and
GMAIL_CLIENT_SECRET from .env, then writes the resulting GMAIL_REFRESH_TOKEN
back into .env automatically.

Usage:
    python -m shared.gmail_auth
"""

from __future__ import annotations

import json
import os
import re
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv

# ── constants ────────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).parent.parent
_ENV_PATH = _REPO_ROOT / ".env"

REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}"
SCOPES = "https://mail.google.com/"

TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"

# ── helpers ──────────────────────────────────────────────────────────────────

def _load_env() -> tuple[str, str]:
    load_dotenv(dotenv_path=_ENV_PATH, override=False)
    client_id = os.environ.get("GMAIL_CLIENT_ID", "")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise RuntimeError(
            "GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET must be set in .env before running this script."
        )
    return client_id, client_secret


def _write_refresh_token(token: str) -> None:
    """Update GMAIL_REFRESH_TOKEN in .env in-place."""
    text = _ENV_PATH.read_text(encoding="utf-8")
    pattern = r"^(GMAIL_REFRESH_TOKEN=).*$"
    replacement = f"GMAIL_REFRESH_TOKEN={token}"
    new_text, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if count == 0:
        new_text = text.rstrip("\n") + f"\nGMAIL_REFRESH_TOKEN={token}\n"
    _ENV_PATH.write_text(new_text, encoding="utf-8")


def _exchange_code(code: str, client_id: str, client_secret: str) -> str:
    """Exchange auth code for refresh token via token endpoint."""
    body = urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode()
    req = Request(TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urlopen(req) as resp:
        data = json.loads(resp.read())
    refresh_token = data.get("refresh_token", "")
    if not refresh_token:
        raise RuntimeError(f"No refresh_token in response: {data}")
    return refresh_token


# ── local callback server ────────────────────────────────────────────────────

class _CallbackHandler(BaseHTTPRequestHandler):
    auth_code: str | None = None
    error: str | None = None

    def do_GET(self) -> None:
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            _CallbackHandler.auth_code = params["code"][0]
            body = b"<h2>Auth successful! You can close this tab.</h2>"
        else:
            _CallbackHandler.error = params.get("error", ["unknown"])[0]
            body = b"<h2>Auth failed. Check the terminal for details.</h2>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # silence default access log
        pass


def _run_server(server: HTTPServer) -> None:
    server.handle_request()  # handle exactly one request then stop


# ── main flow ────────────────────────────────────────────────────────────────

def main() -> None:
    client_id, client_secret = _load_env()

    # Build authorization URL
    params = urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",  # force refresh_token to be returned
    })
    auth_url = f"{AUTH_URL}?{params}"

    # Start local callback server
    server = HTTPServer(("localhost", REDIRECT_PORT), _CallbackHandler)
    t = threading.Thread(target=_run_server, args=(server,), daemon=True)
    t.start()

    print(f"\nOpening browser for Gmail OAuth...\n{auth_url}\n")
    webbrowser.open(auth_url)

    t.join(timeout=120)
    server.server_close()

    if _CallbackHandler.error:
        raise RuntimeError(f"OAuth error: {_CallbackHandler.error}")
    if not _CallbackHandler.auth_code:
        raise RuntimeError("No auth code received (timed out after 120s).")

    print("Auth code received. Exchanging for refresh token...")
    refresh_token = _exchange_code(_CallbackHandler.auth_code, client_id, client_secret)

    _write_refresh_token(refresh_token)
    print(f"\nGMAIL_REFRESH_TOKEN written to {_ENV_PATH}")
    print("All done — run validate_secrets() to confirm.")


if __name__ == "__main__":
    main()

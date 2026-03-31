"""
orchestrator/telegram_bot.py — Telegram bot handler.

Security model:
  - ONLY responds to the single TELEGRAM_CHAT_ID stored in .env
  - All other senders receive a silent ignore (no error message to avoid fingerprinting)
  - Bot token is loaded from .env, never hardcoded

Message flow:
  1. Receive update from Telegram long-poll or webhook
  2. Verify sender chat_id matches whitelist
  3. Parse command text → call orchestrator.dispatch()
  4. Send response back to Telegram

Usage (standalone / GitHub Actions):
    python orchestrator/telegram_bot.py          # long-polling mode
    python orchestrator/telegram_bot.py --once   # process one pending update and exit
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Bootstrap shared path
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from shared.secrets import get_secret

log = get_logger("telegram_bot")

# ---------------------------------------------------------------------------
# Telegram API helpers
# ---------------------------------------------------------------------------

_BASE_URL_TMPL = "https://api.telegram.org/bot{token}/{method}"


def _tg(token: str, method: str, payload: dict | None = None, timeout: int = 30) -> dict:
    """Call a Telegram Bot API method. Raises on HTTP errors."""
    url = _BASE_URL_TMPL.format(token=token, method=method)
    try:
        resp = requests.post(url, json=payload or {}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data.get('description', data)}")
        return data.get("result", {})
    except requests.RequestException as e:
        log.error("tg_request_failed", method=method, error=str(e))
        raise


def send_message(
    token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "Markdown",
    disable_notification: bool = False,
) -> None:
    """Send a text message to a chat."""
    # Telegram message limit is 4096 chars — chunk if needed
    max_len = 4000
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)]
    for chunk in chunks:
        _tg(token, "sendMessage", {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": parse_mode,
            "disable_notification": disable_notification,
        })


def send_typing(token: str, chat_id: str) -> None:
    """Send 'typing...' indicator."""
    try:
        _tg(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})
    except Exception:
        pass  # non-critical


def get_updates(token: str, offset: int = 0, timeout: int = 30) -> list[dict]:
    """Long-poll for new updates."""
    result = _tg(token, "getUpdates", {"offset": offset, "timeout": timeout, "allowed_updates": ["message"]}, timeout=timeout + 5)
    return result if isinstance(result, list) else []


def get_me(token: str) -> dict:
    """Get bot info."""
    return _tg(token, "getMe")


# ---------------------------------------------------------------------------
# Update parser
# ---------------------------------------------------------------------------

class TelegramUpdate:
    """Parsed incoming Telegram update."""

    def __init__(self, raw: dict) -> None:
        self.update_id: int = raw["update_id"]
        msg = raw.get("message", {})
        self.message_id: int = msg.get("message_id", 0)
        self.chat_id: str = str(msg.get("chat", {}).get("id", ""))
        self.user_id: str = str(msg.get("from", {}).get("id", ""))
        self.username: str = msg.get("from", {}).get("username", "")
        self.text: str = (msg.get("text") or "").strip()
        self.date: int = msg.get("date", 0)

    def __repr__(self) -> str:
        return f"TelegramUpdate(id={self.update_id}, chat={self.chat_id}, text={self.text!r})"


# ---------------------------------------------------------------------------
# Bot class
# ---------------------------------------------------------------------------

class TelegramBot:
    """
    Minimal Telegram bot that:
      - Whitelists a single TELEGRAM_CHAT_ID
      - Dispatches commands via the orchestrator
      - Falls back to Claude for unrecognized text
    """

    def __init__(self, token: str, allowed_chat_id: str, dispatch_fn=None) -> None:
        self.token = token
        self.allowed_chat_id = str(allowed_chat_id)
        self._dispatch = dispatch_fn  # set after orchestrator is imported
        self._offset = 0
        self._bot_info: dict = {}

    # ------------------------------------------------------------------ #
    # Auth
    # ------------------------------------------------------------------ #

    def _is_authorized(self, update: TelegramUpdate) -> bool:
        return update.chat_id == self.allowed_chat_id

    # ------------------------------------------------------------------ #
    # Core send
    # ------------------------------------------------------------------ #

    def reply(self, chat_id: str, text: str, parse_mode: str = "Markdown") -> None:
        try:
            send_message(self.token, chat_id, text, parse_mode=parse_mode)
        except Exception as e:
            log.error("reply_failed", chat_id=chat_id, error=str(e))

    # ------------------------------------------------------------------ #
    # Update handling
    # ------------------------------------------------------------------ #

    def handle_update(self, update: TelegramUpdate) -> None:
        if not self._is_authorized(update):
            log.warning(
                "unauthorized_message",
                chat_id=update.chat_id,
                user=update.username,
                text=update.text[:50],
            )
            return  # silent ignore

        if not update.text:
            return  # ignore non-text messages (photos, stickers, etc.)

        log.info("command_received", text=update.text[:100], chat_id=update.chat_id)
        send_typing(self.token, update.chat_id)

        try:
            if self._dispatch is None:
                self.reply(update.chat_id, "⚠️ Orchestrator not connected.")
                return
            response = self._dispatch(update.text)
            self.reply(update.chat_id, response or "✅ Done.")
        except Exception as e:
            log.error("dispatch_error", text=update.text, error=str(e), exc_info=True)
            self.reply(update.chat_id, f"🔴 Error: {e}")

    def process_updates(self, updates: list[dict]) -> None:
        for raw in updates:
            upd = TelegramUpdate(raw)
            self.handle_update(upd)
            self._offset = upd.update_id + 1

    # ------------------------------------------------------------------ #
    # Run modes
    # ------------------------------------------------------------------ #

    def run_once(self) -> int:
        """Fetch and process any pending updates, then exit. Returns count processed."""
        updates = get_updates(self.token, offset=self._offset, timeout=5)
        self.process_updates(updates)
        return len(updates)

    def run_polling(self, poll_interval: float = 1.0) -> None:
        """Long-polling loop. Runs until KeyboardInterrupt."""
        try:
            self._bot_info = get_me(self.token)
            log.info("bot_started", username=self._bot_info.get("username"), chat_id=self.allowed_chat_id)
            print(f"Bot @{self._bot_info.get('username')} listening. Ctrl+C to stop.")
        except Exception as e:
            log.error("bot_init_failed", error=str(e))
            raise

        while True:
            try:
                updates = get_updates(self.token, offset=self._offset, timeout=30)
                self.process_updates(updates)
            except KeyboardInterrupt:
                log.info("bot_stopped")
                break
            except Exception as e:
                log.error("polling_error", error=str(e))
                time.sleep(5)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_bot(dispatch_fn=None) -> TelegramBot:
    """Create a TelegramBot instance using secrets from .env."""
    token = get_secret("TELEGRAM_BOT_TOKEN")
    chat_id = get_secret("TELEGRAM_CHAT_ID")
    return TelegramBot(token=token, allowed_chat_id=chat_id, dispatch_fn=dispatch_fn)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Telegram bot for automation system")
    parser.add_argument("--once", action="store_true", help="Process pending updates once and exit")
    args = parser.parse_args()

    # Import here to avoid circular import at module level
    from orchestrator import dispatch as orchestrator_dispatch

    bot = create_bot(dispatch_fn=orchestrator_dispatch)

    if args.once:
        count = bot.run_once()
        print(f"Processed {count} update(s).")
    else:
        bot.run_polling()

"""
agents/email_triage/labeler.py — Apply Gmail labels and archive spam.

Uses Gmail API to:
  1. Create labels if they don't exist
  2. Apply the AI/* label to each classified message
  3. Archive messages classified as AI/SPAM (move to All Mail, remove INBOX)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger

log = get_logger("email_triage")

# Gmail label colors (optional — makes labels visually distinct)
_LABEL_COLORS = {
    "AI/JOB_OPPORTUNITY": {"backgroundColor": "#16a766", "textColor": "#ffffff"},
    "AI/APPLICATION": {"backgroundColor": "#4a86e8", "textColor": "#ffffff"},
    "AI/NETWORKING": {"backgroundColor": "#f6c026", "textColor": "#000000"},
    "AI/IMPORTANT": {"backgroundColor": "#e07798", "textColor": "#ffffff"},
    "AI/NEWSLETTER": {"backgroundColor": "#b99aff", "textColor": "#000000"},
    "AI/SPAM": {"backgroundColor": "#999999", "textColor": "#ffffff"},
    "AI/OTHER": {"backgroundColor": "#cccccc", "textColor": "#000000"},
}


def _get_or_create_label(service, label_name: str) -> str:
    """Return label ID, creating the label if it doesn't exist."""
    # List existing labels
    result = service.users().labels().list(userId="me").execute()
    for label in result.get("labels", []):
        if label["name"] == label_name:
            return label["id"]

    # Create the label
    color = _LABEL_COLORS.get(label_name)
    body: dict[str, Any] = {"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
    if color:
        body["color"] = color

    try:
        created = service.users().labels().create(userId="me", body=body).execute()
        log.info("gmail_label_created", label=label_name, id=created["id"])
        return created["id"]
    except Exception as e:
        log.warning("gmail_label_create_failed", label=label_name, error=str(e))
        return ""


def apply_label(service, message: dict[str, Any], label_cache: dict[str, str], dry_run: bool = False) -> bool:
    """
    Apply the AI/* label to a single message. Archive if spam.

    Args:
        service: Authenticated Gmail API service.
        message: Classified message dict (must have 'id' and 'label').
        label_cache: Dict mapping label names to Gmail label IDs (mutated in place).
        dry_run: If True, skip API calls.

    Returns:
        True if successful.
    """
    msg_id = message.get("id", "")
    label_name = message.get("label", "AI/OTHER")

    if not msg_id or not label_name:
        return False

    if dry_run:
        log.info("labeler_dry_run", msg_id=msg_id, label=label_name)
        return True

    # Resolve label ID
    if label_name not in label_cache:
        label_id = _get_or_create_label(service, label_name)
        label_cache[label_name] = label_id
    label_id = label_cache.get(label_name, "")

    if not label_id:
        log.warning("label_id_missing", label=label_name)
        return False

    try:
        if label_name == "AI/SPAM":
            # Archive: remove INBOX, add label
            service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"addLabelIds": [label_id], "removeLabelIds": ["INBOX"]},
            ).execute()
            log.info("email_archived_spam", msg_id=msg_id)
        else:
            # Apply label only
            service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"addLabelIds": [label_id]},
            ).execute()
            log.info("email_labeled", msg_id=msg_id, label=label_name)
        return True
    except Exception as e:
        log.error("label_apply_failed", msg_id=msg_id, label=label_name, error=str(e))
        return False


def apply_labels_batch(
    service,
    messages: list[dict[str, Any]],
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Apply labels to a batch of classified messages.

    Returns:
        Stats dict with 'labeled', 'archived', 'failed' counts.
    """
    label_cache: dict[str, str] = {}
    stats = {"labeled": 0, "archived": 0, "failed": 0}

    for msg in messages:
        ok = apply_label(service, msg, label_cache, dry_run=dry_run)
        if ok:
            if msg.get("label") == "AI/SPAM":
                stats["archived"] += 1
            else:
                stats["labeled"] += 1
        else:
            stats["failed"] += 1

    log.info("labeling_batch_complete", **stats)
    return stats

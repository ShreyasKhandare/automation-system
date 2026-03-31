"""
agents/email_triage/labeler.py — Apply Gmail labels and archive spam.

Label strategy:
  - Creates AI/* labels if they don't already exist (idempotent)
  - Applies the classified label to each message
  - Removes INBOX label for SPAM (archives it — never deletes)
  - Marks AI/IMPORTANT messages as starred for visibility
  - Does NOT remove UNREAD — user decides when to read

Label IDs are cached in memory per run to avoid repeated API calls.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger
from agents.email_triage.classifier import ClassifiedEmail, VALID_LABELS

log = get_logger("email_triage")

# ---------------------------------------------------------------------------
# Label definitions
# ---------------------------------------------------------------------------

# Map from our label name → Gmail display name
_LABEL_DEFINITIONS = {
    "AI/JOB_OPPORTUNITY": {"name": "AI/JOB_OPPORTUNITY", "labelListVisibility": "labelShow",    "messageListVisibility": "show"},
    "AI/APPLICATION":     {"name": "AI/APPLICATION",     "labelListVisibility": "labelShow",    "messageListVisibility": "show"},
    "AI/NETWORKING":      {"name": "AI/NETWORKING",      "labelListVisibility": "labelShow",    "messageListVisibility": "show"},
    "AI/IMPORTANT":       {"name": "AI/IMPORTANT",       "labelListVisibility": "labelShow",    "messageListVisibility": "show"},
    "AI/NEWSLETTER":      {"name": "AI/NEWSLETTER",      "labelListVisibility": "labelShowIfUnread", "messageListVisibility": "show"},
    "AI/SPAM":            {"name": "AI/SPAM",            "labelListVisibility": "labelHide",    "messageListVisibility": "hide"},
    "AI/OTHER":           {"name": "AI/OTHER",           "labelListVisibility": "labelShow",    "messageListVisibility": "show"},
}

# Special Gmail system label IDs
_INBOX_LABEL = "INBOX"
_STARRED_LABEL = "STARRED"


# ---------------------------------------------------------------------------
# Label ID resolution (creates labels that don't exist)
# ---------------------------------------------------------------------------

_label_id_cache: dict[str, str] = {}


def _get_or_create_label(service, label_name: str) -> str:
    """Return the Gmail label ID for label_name, creating it if needed."""
    if label_name in _label_id_cache:
        return _label_id_cache[label_name]

    # List all existing labels
    result = service.users().labels().list(userId="me").execute()
    for lbl in result.get("labels", []):
        _label_id_cache[lbl["name"]] = lbl["id"]

    if label_name in _label_id_cache:
        return _label_id_cache[label_name]

    # Create the label
    defn = _LABEL_DEFINITIONS.get(label_name, {"name": label_name})
    try:
        created = service.users().labels().create(
            userId="me", body=defn
        ).execute()
        label_id = created["id"]
        _label_id_cache[label_name] = label_id
        log.info("label_created", name=label_name, id=label_id)
        return label_id
    except Exception as e:
        log.error("label_create_failed", name=label_name, error=str(e))
        raise


def ensure_all_labels(service) -> None:
    """Pre-create all AI/* labels on first run."""
    for label_name in VALID_LABELS:
        try:
            _get_or_create_label(service, label_name)
        except Exception:
            pass  # non-fatal


# ---------------------------------------------------------------------------
# Apply labels to messages
# ---------------------------------------------------------------------------

def apply_label(
    service,
    classified: ClassifiedEmail,
    dry_run: bool = False,
) -> bool:
    """
    Apply the classified label to a single message.
    Archives (removes INBOX) if label is AI/SPAM.
    Stars if label is AI/IMPORTANT or flag_urgent=True.
    Returns True on success.
    """
    msg_id = classified.email.msg_id
    label_name = classified.label

    if dry_run:
        action = "archive" if label_name == "AI/SPAM" else "label"
        star = classified.flag_urgent or label_name == "AI/IMPORTANT"
        log.info(
            "dry_run_label",
            msg_id=msg_id,
            label=label_name,
            action=action,
            star=star,
            subject=classified.email.subject[:60],
        )
        return True

    try:
        label_id = _get_or_create_label(service, label_name)

        add_labels = [label_id]
        remove_labels = []

        # Archive spam (remove from INBOX — never delete)
        if label_name == "AI/SPAM":
            remove_labels.append(_INBOX_LABEL)

        # Star urgent / important messages
        if classified.flag_urgent or label_name == "AI/IMPORTANT":
            add_labels.append(_STARRED_LABEL)

        # Move newsletters out of inbox too
        if label_name == "AI/NEWSLETTER":
            remove_labels.append(_INBOX_LABEL)

        service.users().messages().modify(
            userId="me",
            id=msg_id,
            body={
                "addLabelIds": add_labels,
                "removeLabelIds": remove_labels,
            },
        ).execute()

        log.info(
            "label_applied",
            msg_id=msg_id,
            label=label_name,
            archived=label_name in ("AI/SPAM", "AI/NEWSLETTER"),
            starred=classified.flag_urgent,
        )
        return True

    except Exception as e:
        log.error("label_apply_failed", msg_id=msg_id, label=label_name, error=str(e))
        return False


def apply_labels_bulk(
    service,
    classified_emails: list[ClassifiedEmail],
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Apply labels to all classified emails.
    Returns stats dict with success/failure counts per label.
    """
    # Ensure labels exist before processing
    if not dry_run:
        ensure_all_labels(service)

    stats: dict[str, int] = {lbl: 0 for lbl in VALID_LABELS}
    stats["failed"] = 0

    for classified in classified_emails:
        success = apply_label(service, classified, dry_run=dry_run)
        if success:
            stats[classified.label] = stats.get(classified.label, 0) + 1
        else:
            stats["failed"] += 1
        if not dry_run:
            time.sleep(0.1)  # gentle rate limiting

    log.info("labels_applied_bulk", stats=stats)
    return stats


if __name__ == "__main__":
    print("labeler.py — run via notifier.py")
    print("Labels that will be created:", sorted(VALID_LABELS))

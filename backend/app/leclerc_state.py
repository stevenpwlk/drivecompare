from __future__ import annotations

from datetime import datetime, timezone
import os

from .db import delete_key_value, get_key_value, set_key_value

KEY_BLOCKED = "leclerc_blocked"
KEY_BLOCKED_URL = "leclerc_blocked_url"
KEY_LEGACY_UNBLOCK_URL = "leclerc_unblock_url"
KEY_BLOCKED_AT = "leclerc_blocked_at"
KEY_BLOCKED_JOB_ID = "leclerc_blocked_job_id"
KEY_GUI_ACTIVE = "leclerc_gui_active"
KEY_GUI_ACTIVE_AT = "leclerc_gui_active_at"
LECLERC_GUI_TTL_SECONDS = int(os.getenv("LECLERC_GUI_TTL_SECONDS", "300"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def set_blocked_state(
    blocked: bool,
    *,
    blocked_url: str | None = None,
    updated_at: str | None = None,
    blocked_job_id: str | None = None,
) -> None:
    set_key_value(KEY_BLOCKED, "1" if blocked else "0")
    set_key_value(KEY_BLOCKED_AT, updated_at or _utc_now())
    if blocked_url:
        set_key_value(KEY_BLOCKED_URL, blocked_url)
    elif not blocked:
        delete_key_value(KEY_BLOCKED_URL)
        delete_key_value(KEY_LEGACY_UNBLOCK_URL)
    if blocked_job_id:
        set_key_value(KEY_BLOCKED_JOB_ID, blocked_job_id)


def get_blocked_state() -> tuple[bool, str | None, str | None]:
    blocked_value = get_key_value(KEY_BLOCKED)
    blocked = blocked_value == "1"
    blocked_url = get_key_value(KEY_BLOCKED_URL)
    if not blocked_url:
        blocked_url = get_key_value(KEY_LEGACY_UNBLOCK_URL)
    updated_at = get_key_value(KEY_BLOCKED_AT)
    return blocked, blocked_url, updated_at


def clear_blocked_state() -> None:
    set_key_value(KEY_BLOCKED, "0")
    delete_key_value(KEY_BLOCKED_URL)
    delete_key_value(KEY_LEGACY_UNBLOCK_URL)
    delete_key_value(KEY_BLOCKED_AT)
    delete_key_value(KEY_BLOCKED_JOB_ID)


def set_gui_active(active: bool) -> None:
    set_key_value(KEY_GUI_ACTIVE, "1" if active else "0")
    if active:
        set_key_value(KEY_GUI_ACTIVE_AT, _utc_now())
    else:
        delete_key_value(KEY_GUI_ACTIVE_AT)


def is_gui_active() -> bool:
    if get_key_value(KEY_GUI_ACTIVE) != "1":
        return False
    updated_at = get_key_value(KEY_GUI_ACTIVE_AT)
    if not updated_at:
        return True
    try:
        active_at = datetime.fromisoformat(updated_at)
    except ValueError:
        return True
    if (datetime.now(timezone.utc) - active_at).total_seconds() > LECLERC_GUI_TTL_SECONDS:
        set_gui_active(False)
        return False
    return True


def get_blocked_job_id() -> str | None:
    return get_key_value(KEY_BLOCKED_JOB_ID)

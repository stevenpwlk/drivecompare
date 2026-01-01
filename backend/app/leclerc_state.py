from __future__ import annotations

from datetime import datetime, timezone

from .db import delete_key_value, get_key_value, set_key_value

DEFAULT_LECLERC_FALLBACK_URL = "https://fd6-courses.leclercdrive.fr/"

KEY_BLOCKED = "leclerc_blocked"
KEY_UNBLOCK_URL = "leclerc_unblock_url"
KEY_BLOCKED_AT = "leclerc_blocked_at"
KEY_BLOCKED_JOB_ID = "leclerc_blocked_job_id"
KEY_GUI_ACTIVE = "leclerc_gui_active"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def set_blocked_state(
    blocked: bool,
    *,
    unblock_url: str | None = None,
    updated_at: str | None = None,
    blocked_job_id: str | None = None,
) -> None:
    set_key_value(KEY_BLOCKED, "1" if blocked else "0")
    set_key_value(KEY_BLOCKED_AT, updated_at or _utc_now())
    if unblock_url:
        set_key_value(KEY_UNBLOCK_URL, unblock_url)
    elif not blocked:
        delete_key_value(KEY_UNBLOCK_URL)
    if blocked_job_id:
        set_key_value(KEY_BLOCKED_JOB_ID, blocked_job_id)


def get_blocked_state() -> tuple[bool, str | None, str | None]:
    blocked_value = get_key_value(KEY_BLOCKED)
    blocked = blocked_value == "1"
    unblock_url = get_key_value(KEY_UNBLOCK_URL)
    updated_at = get_key_value(KEY_BLOCKED_AT)
    return blocked, unblock_url, updated_at


def clear_blocked_state() -> None:
    set_key_value(KEY_BLOCKED, "0")
    delete_key_value(KEY_UNBLOCK_URL)
    delete_key_value(KEY_BLOCKED_AT)
    delete_key_value(KEY_BLOCKED_JOB_ID)


def set_gui_active(active: bool) -> None:
    set_key_value(KEY_GUI_ACTIVE, "1" if active else "0")


def is_gui_active() -> bool:
    return get_key_value(KEY_GUI_ACTIVE) == "1"


def get_blocked_job_id() -> str | None:
    return get_key_value(KEY_BLOCKED_JOB_ID)

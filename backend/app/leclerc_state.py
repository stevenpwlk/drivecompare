from __future__ import annotations

import os
from pathlib import Path

SESSIONS_DIR = Path(os.getenv("SESSIONS_DIR", "/sessions"))
BLOCKED_URL_PATH = SESSIONS_DIR / "leclerc_last_blocked_url.txt"
GUI_LOCK_PATH = SESSIONS_DIR / "leclerc_gui_active.lock"
DEFAULT_LECLERC_FALLBACK_URL = "https://fd6-courses.leclercdrive.fr/"


def _atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(value, encoding="utf-8")
    tmp_path.replace(path)


def set_blocked_url(url: str) -> None:
    if not url:
        return
    _atomic_write(BLOCKED_URL_PATH, url)


def get_blocked_url() -> str | None:
    try:
        if BLOCKED_URL_PATH.exists():
            return BLOCKED_URL_PATH.read_text(encoding="utf-8").strip() or None
    except Exception:
        return None
    return None


def clear_blocked_url() -> None:
    try:
        if BLOCKED_URL_PATH.exists():
            BLOCKED_URL_PATH.unlink()
    except Exception:
        return


def set_gui_active(active: bool) -> None:
    if active:
        _atomic_write(GUI_LOCK_PATH, "active")
        return
    try:
        if GUI_LOCK_PATH.exists():
            GUI_LOCK_PATH.unlink()
    except Exception:
        return


def is_gui_active() -> bool:
    try:
        return GUI_LOCK_PATH.exists()
    except Exception:
        return False

from __future__ import annotations

import argparse
import os
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SESSIONS_DIR = Path(os.getenv("SESSIONS_DIR", "/sessions"))
LECLERC_STORE_URL = os.getenv(
    "LECLERC_STORE_URL",
    "https://fd6-courses.leclercdrive.fr/magasin-175901-175901-seclin-lorival.aspx",
)


def wait_for_enter(timeout_s: int | None) -> None:
    done = threading.Event()

    def _wait() -> None:
        try:
            input("Appuyez sur Entrée pour terminer le bootstrap...\n")
        except EOFError:
            return
        done.set()

    thread = threading.Thread(target=_wait, daemon=True)
    thread.start()
    if timeout_s is None:
        done.wait()
        return
    done.wait(timeout=timeout_s)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap session Leclerc")
    parser.add_argument("--account", default="bot", help="Nom du compte (bot par défaut)")
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Temps max en secondes avant sauvegarde automatique (défaut: 300)",
    )
    parser.add_argument(
        "--slow-mo",
        type=int,
        default=0,
        help="Ralenti Playwright en ms (défaut: 0)",
    )
    args = parser.parse_args()

    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    storage_path = SESSIONS_DIR / f"leclerc_{args.account}.json"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=args.slow_mo)
        context = browser.new_context()
        page = context.new_page()
        page.goto(LECLERC_STORE_URL)
        print(
            "Session ouverte. Passez le captcha/choix magasin si nécessaire, "
            "puis revenez ici pour terminer."
        )
        timeout_s = args.timeout if args.timeout > 0 else None
        wait_for_enter(timeout_s)
        time.sleep(1)
        context.storage_state(path=str(storage_path))
        print(f"Bootstrap terminé, storage_state sauvegardé: {storage_path}")
        browser.close()


if __name__ == "__main__":
    main()

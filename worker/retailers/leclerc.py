from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

LOG_DIR = Path(os.getenv("LOG_DIR", "/logs"))
SESSIONS_DIR = Path(os.getenv("SESSIONS_DIR", "/sessions"))
DEFAULT_TIMEOUT_MS = int(os.getenv("LECLERC_TIMEOUT_MS", "10000"))
DEFAULT_RETRIES = int(os.getenv("LECLERC_RETRIES", "2"))
BASE_URL = os.getenv("LECLERC_BASE_URL", "https://www.e.leclerc/")


@dataclass
class BasketRecap:
    total: float
    loyalty_gain: float
    items: list[dict]


class LeclercRetailer:
    def __init__(
        self,
        page: Page,
        *,
        log_dir: Path | None = None,
        sessions_dir: Path | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        retries: int = DEFAULT_RETRIES,
    ) -> None:
        self.page = page
        self.log_dir = log_dir or LOG_DIR
        self.sessions_dir = sessions_dir or SESSIONS_DIR
        self.timeout_ms = timeout_ms
        self.retries = retries
        self.logger = logging.getLogger(__name__)

    def _timestamp(self) -> int:
        return int(time.time())

    def _ensure_dirs(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _is_logged_in(self) -> bool:
        try:
            return (
                self.page.locator("text=Se déconnecter").first.is_visible(timeout=2000)
                or self.page.locator("text=Mon compte").first.is_visible(timeout=2000)
            )
        except PlaywrightTimeoutError:
            return False
        except Exception:
            self.logger.exception("Leclerc login heuristic failed")
            return False

    def _capture_error_artifacts(self, label: str, error: Exception) -> None:
        self._ensure_dirs()
        timestamp = self._timestamp()
        screenshot_path = self.log_dir / f"leclerc_error_{timestamp}.png"
        html_path = self.log_dir / f"leclerc_error_{timestamp}.html"
        try:
            self.page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception:
            self.logger.exception("Failed to capture Leclerc screenshot")
        try:
            html_path.write_text(self.page.content(), encoding="utf-8")
        except Exception:
            self.logger.exception("Failed to capture Leclerc HTML")
        self.logger.error("Leclerc error during %s: %s", label, error)

    @contextmanager
    def _network_capture(self) -> Iterator[Path]:
        self._ensure_dirs()
        log_path = self.log_dir / f"leclerc_network_{self._timestamp()}.jsonl"
        log_file = log_path.open("a", encoding="utf-8")

        def handle_response(response) -> None:
            try:
                request = response.request
                if request.resource_type not in {"xhr", "fetch"}:
                    return
                content_type = response.headers.get("content-type", "")
                body = response.body()
                size = len(body)
                excerpt = None
                if content_type.startswith("text/") or "json" in content_type:
                    excerpt = body.decode(errors="replace")[:500]
                entry = {
                    "url": response.url,
                    "status": response.status,
                    "method": request.method,
                    "content_type": content_type,
                    "size": size,
                    "excerpt": excerpt,
                }
                log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
                log_file.flush()
            except Exception:
                self.logger.exception("Failed to log Leclerc network response")

        self.page.on("response", handle_response)
        try:
            yield log_path
        finally:
            self.page.off("response", handle_response)
            log_file.close()

    def login(self, account_type: str = "bot") -> dict[str, Any]:
        self._ensure_dirs()
        storage_path = self.sessions_dir / f"leclerc_{account_type}.json"
        if storage_path.exists():
            try:
                data = json.loads(storage_path.read_text(encoding="utf-8"))
                cookies = data.get("cookies", [])
                if cookies:
                    self.page.context.add_cookies(cookies)
                self.logger.info("Loaded Leclerc storage_state for %s", account_type)
            except Exception:
                self.logger.exception("Failed to load Leclerc storage_state")
        try:
            self.page.goto(BASE_URL, timeout=self.timeout_ms)
        except Exception as error:
            self._capture_error_artifacts("login", error)
            return {"status": "error", "message": str(error)}

        if self._is_logged_in():
            self.page.context.storage_state(path=str(storage_path))
            return {"status": "restored", "storage_state": str(storage_path)}

        self.logger.info("TODO: implement Leclerc login selectors for %s", account_type)
        # TODO: navigate to the login form and complete authentication.
        # TODO: fill email/password selectors once identified.

        try:
            self.page.context.storage_state(path=str(storage_path))
        except Exception:
            self.logger.exception("Failed to save Leclerc storage_state")
        return {"status": "pending", "storage_state": str(storage_path)}

    def search(self, query: str) -> list[dict[str, Any]]:
        self._ensure_dirs()
        for attempt in range(1, self.retries + 2):
            with self._network_capture():
                try:
                    self.page.goto(BASE_URL, timeout=self.timeout_ms)
                    self.logger.info("TODO: implement Leclerc search selectors")
                    search_input = self.page.locator("input[type='search']").first
                    search_input.fill(query, timeout=2000)
                    search_input.press("Enter")
                    self.page.wait_for_timeout(2000)
                    return []
                except Exception as error:
                    self._capture_error_artifacts("search", error)
                    if attempt <= self.retries:
                        self.logger.warning("Retrying Leclerc search (%s/%s)", attempt, self.retries)
                        continue
                    return []
        return []

    def clear_basket(self) -> dict[str, Any]:
        self.logger.info("TODO: implement Leclerc clear basket")
        return {"status": "not_implemented"}

    def fill_basket(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        self._ensure_dirs()
        for attempt in range(1, self.retries + 2):
            with self._network_capture():
                try:
                    self.logger.info("TODO: implement Leclerc fill basket")
                    self.page.wait_for_timeout(500)
                    return {"status": "not_implemented", "items": items}
                except Exception as error:
                    self._capture_error_artifacts("fill_basket", error)
                    if attempt <= self.retries:
                        self.logger.warning(
                            "Retrying Leclerc fill_basket (%s/%s)", attempt, self.retries
                        )
                        continue
                    return {"status": "error", "message": str(error)}
        return {"status": "not_implemented", "items": items}

    def read_recap(self) -> dict[str, Any]:
        self.logger.info("TODO: implement Leclerc recap parsing")
        recap = BasketRecap(total=0.0, loyalty_gain=0.0, items=[])
        return asdict(recap)


def login(page: Page, account_type: str = "bot") -> dict[str, Any]:
    return LeclercRetailer(page).login(account_type)


def search(page: Page, query: str) -> list[dict[str, Any]]:
    return LeclercRetailer(page).search(query)


def clear_basket(page: Page) -> dict[str, Any]:
    return LeclercRetailer(page).clear_basket()


def fill_basket(page: Page, items: list[dict[str, Any]]) -> dict[str, Any]:
    return LeclercRetailer(page).fill_basket(items)


def read_recap(page: Page) -> dict[str, Any]:
    return LeclercRetailer(page).read_recap()

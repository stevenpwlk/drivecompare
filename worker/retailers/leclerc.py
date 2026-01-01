from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

LOG_DIR = Path(os.getenv("LOG_DIR", "/logs"))
DEFAULT_TIMEOUT_MS = int(os.getenv("LECLERC_TIMEOUT_MS", "15000"))
LECLERC_CDP_URL = os.getenv("LECLERC_CDP_URL", "http://leclerc-browser:9222")
LECLERC_STORE_URL = os.getenv(
    "LECLERC_STORE_URL",
    "https://fd6-courses.leclercdrive.fr/magasin-175901-175901-seclin-lorival.aspx",
)
LECLERC_STORE_LABEL = os.getenv("LECLERC_STORE_LABEL", "Leclerc")


def is_datadome_block(page_html: str, url: str | None = None, title: str | None = None) -> bool:
    lowered = page_html.lower()
    checks = [
        "captcha-delivery.com",
        "datadome",
        "access blocked",
        "unusual activity",
        "captcha",
        "service indisponible",
    ]
    if any(token in lowered for token in checks):
        return True
    if url and any(token in url.lower() for token in ("captcha", "datadome")):
        return True
    if title and any(token in title.lower() for token in ("captcha", "accès bloqué")):
        return True
    return False


class SharedLeclercBrowser:
    def __init__(self, cdp_url: str = LECLERC_CDP_URL) -> None:
        self.cdp_url = cdp_url
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self.logger = logging.getLogger(__name__)

    def _ensure_playwright(self):
        if self._playwright is None:
            self._playwright = sync_playwright().start()
        return self._playwright

    def _ensure_browser(self):
        if self._browser and self._browser.is_connected():
            return self._browser
        playwright = self._ensure_playwright()
        self._browser = playwright.chromium.connect_over_cdp(self.cdp_url)
        self._context = None
        self._page = None
        return self._browser

    def _ensure_context(self):
        browser = self._ensure_browser()
        if self._context and self._context.pages is not None:
            return self._context
        self._context = browser.contexts[0] if browser.contexts else browser.new_context()
        return self._context

    def ensure_page(self) -> Page:
        context = self._ensure_context()
        if self._page and not self._page.is_closed():
            return self._page
        for page in context.pages:
            if not page.is_closed():
                self._page = page
                return page
        self._page = context.new_page()
        return self._page

    def open_unblock_page(self, url: str | None) -> None:
        page = self.ensure_page()
        if url:
            try:
                page.goto(url, timeout=DEFAULT_TIMEOUT_MS)
            except Exception:
                self.logger.exception("Failed to open unblock URL")


_shared_browser = SharedLeclercBrowser()


def ensure_page() -> Page:
    return _shared_browser.ensure_page()


def open_unblock_page(url: str | None) -> None:
    _shared_browser.open_unblock_page(url)


class LeclercBlocked(RuntimeError):
    def __init__(self, reason: str, blocked_url: str | None, artifacts: dict[str, str]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.blocked_url = blocked_url
        self.artifacts = artifacts


@dataclass
class SearchResult:
    items: list[dict[str, Any]]
    debug: dict[str, Any]


class LeclercRetailer:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.logger = logging.getLogger(__name__)
        self.log_dir = LOG_DIR / "leclerc"
        self._network_entries: list[dict[str, Any]] = []
        self._network_handlers: dict[str, Any] = {}

    def _timestamp(self) -> int:
        return int(time.time())

    def _ensure_dirs(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _start_network_capture(self) -> None:
        self._network_entries = []

        def on_response(response) -> None:
            try:
                request = response.request
                self._network_entries.append(
                    {
                        "url": response.url,
                        "status": response.status,
                        "method": request.method,
                        "resource_type": request.resource_type,
                        "ok": response.ok,
                    }
                )
            except Exception:
                self.logger.debug("Failed to capture response", exc_info=True)

        def on_request_failed(request) -> None:
            try:
                self._network_entries.append(
                    {
                        "url": request.url,
                        "status": None,
                        "method": request.method,
                        "resource_type": request.resource_type,
                        "ok": False,
                        "failure": request.failure,
                    }
                )
            except Exception:
                self.logger.debug("Failed to capture request failure", exc_info=True)

        self.page.on("response", on_response)
        self.page.on("requestfailed", on_request_failed)
        self._network_handlers = {
            "response": on_response,
            "requestfailed": on_request_failed,
        }

    def _stop_network_capture(self) -> None:
        if not self._network_handlers:
            return
        for event, handler in self._network_handlers.items():
            try:
                self.page.off(event, handler)
            except Exception:
                self.logger.debug("Failed to detach network handler", exc_info=True)
        self._network_handlers = {}

    def _build_network_summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "total_entries": len(self._network_entries),
            "by_status": {},
            "by_resource": {},
            "entries": self._network_entries[-200:],
        }
        for entry in self._network_entries:
            status = entry.get("status")
            resource = entry.get("resource_type")
            summary["by_status"][str(status)] = summary["by_status"].get(str(status), 0) + 1
            summary["by_resource"][str(resource)] = summary["by_resource"].get(str(resource), 0) + 1
        return summary

    def _capture_artifacts(self, label: str) -> dict[str, str]:
        self._ensure_dirs()
        stamp = self._timestamp()
        screenshot_path = self.log_dir / f"leclerc_{label}_{stamp}.png"
        html_path = self.log_dir / f"leclerc_{label}_{stamp}.html"
        network_path = self.log_dir / f"leclerc_{label}_{stamp}_network.json"
        try:
            self.page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception:
            self.logger.exception("Failed to capture screenshot")
        try:
            html_path.write_text(self.page.content(), encoding="utf-8")
        except Exception:
            self.logger.exception("Failed to capture HTML")
        try:
            network_path.write_text(
                json.dumps(self._build_network_summary(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            self.logger.exception("Failed to capture network summary")
        payload = {"screenshot": str(screenshot_path), "html": str(html_path)}
        try:
            payload["url"] = self.page.url
        except Exception:
            payload["url"] = None
        payload["network"] = str(network_path)
        return payload

    def _handle_cookie_banner(self) -> None:
        buttons = [
            "button:has-text('Tout accepter')",
            "button:has-text('Accepter')",
            "button:has-text(\"J'accepte\")",
        ]
        for selector in buttons:
            try:
                button = self.page.locator(selector).first
                if button.is_visible(timeout=1500):
                    button.click(timeout=1500)
                    self.page.wait_for_timeout(500)
                    return
            except PlaywrightTimeoutError:
                continue
            except Exception:
                self.logger.debug("Cookie accept failed", exc_info=True)

    def _extract_price(self, text: str) -> tuple[str | None, float | None]:
        import re

        match = re.search(r"(\d+[,.]\d{2})\s*€", text)
        if not match:
            return None, None
        price_text = match.group(1).replace(",", ".")
        try:
            return price_text, float(price_text)
        except ValueError:
            return price_text, None

    def _parse_product_card(self, card, base_url: str) -> dict[str, Any] | None:
        try:
            title_locator = card.locator(
                "h3, h2, .product-title, .product__title, [data-testid*='title'], a[title]"
            ).first
            title = title_locator.inner_text().strip() if title_locator.count() else None
        except Exception:
            title = None

        try:
            raw_text = card.inner_text()
        except Exception:
            raw_text = ""

        price_text, price_value = self._extract_price(raw_text)
        if not title or not price_text:
            return None

        url = None
        try:
            href = card.locator("a").first.get_attribute("href")
            if href:
                url = href if href.startswith("http") else f"{base_url}{href}"
        except Exception:
            url = None

        return {
            "title": title,
            "price": price_value if price_value is not None else price_text,
            "url": url,
            "store": LECLERC_STORE_LABEL,
        }

    def _parse_search_results(self, limit: int, base_url: str) -> list[dict[str, Any]]:
        selectors = [
            "article[data-product-id]",
            "div[data-product-id]",
            ".product",
            ".product-item",
            ".product-card",
        ]
        locator = self.page.locator(",".join(selectors))
        items: list[dict[str, Any]] = []
        count = locator.count()
        for index in range(min(count, limit)):
            card = locator.nth(index)
            item = self._parse_product_card(card, base_url)
            if item:
                items.append(item)
        return items

    def _search_with_input(self, query: str) -> bool:
        selectors = (
            "input[type='search'],"
            "input[placeholder*='Recher'],"
            "input[aria-label*='Recher']"
        )
        try:
            search_input = self.page.locator(selectors).first
            search_input.wait_for(timeout=2000)
            search_input.fill(query, timeout=2000)
            search_input.press("Enter")
            self.page.wait_for_timeout(2000)
            return True
        except Exception:
            self.logger.debug("Search input failed", exc_info=True)
            return False

    def search(self, query: str, limit: int = 20) -> SearchResult:
        self._ensure_dirs()
        self._start_network_capture()
        self.page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        try:
            self.page.goto(LECLERC_STORE_URL, wait_until="domcontentloaded")
            self._handle_cookie_banner()
            try:
                self.page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                self.page.wait_for_timeout(1000)

            html = self.page.content()
            url = self.page.url
            title = None
            try:
                title = self.page.title()
            except Exception:
                title = None
            if is_datadome_block(html, url, title):
                artifacts = self._capture_artifacts("blocked")
                raise LeclercBlocked("DATADOME_BLOCKED", url, artifacts)

            used_input = self._search_with_input(query)
            if not used_input:
                parsed = urlparse(LECLERC_STORE_URL)
                base = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else LECLERC_STORE_URL
                search_url = f"{base}/recherche.aspx?Texte={quote_plus(query)}"
                self.page.goto(search_url, wait_until="domcontentloaded")

            self._handle_cookie_banner()
            html = self.page.content()
            url = self.page.url
            try:
                title = self.page.title()
            except Exception:
                title = None
            if is_datadome_block(html, url, title):
                artifacts = self._capture_artifacts("blocked")
                raise LeclercBlocked("DATADOME_BLOCKED", url, artifacts)

            parsed = urlparse(LECLERC_STORE_URL)
            base_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else LECLERC_STORE_URL
            items = self._parse_search_results(limit, base_url)
            debug = {
                "final_url": url,
                "page_title": title,
            }
            if not items:
                debug.update(self._capture_artifacts("noresults"))
            return SearchResult(items=items, debug=debug)
        except LeclercBlocked:
            raise
        except Exception:
            self._capture_artifacts("error")
            self.logger.exception("Leclerc search failed")
            raise
        finally:
            self._stop_network_capture()


__all__ = [
    "LeclercRetailer",
    "LeclercBlocked",
    "ensure_page",
    "open_unblock_page",
]

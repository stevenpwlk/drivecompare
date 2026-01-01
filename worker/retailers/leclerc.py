from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote_plus, urlparse

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

LOG_DIR = Path(os.getenv("LOG_DIR", "/logs"))
SESSIONS_DIR = Path(os.getenv("SESSIONS_DIR", "/sessions"))
DEFAULT_TIMEOUT_MS = int(os.getenv("LECLERC_TIMEOUT_MS", "10000"))
DEFAULT_RETRIES = int(os.getenv("LECLERC_RETRIES", "2"))
BASE_URL = os.getenv("LECLERC_BASE_URL", "https://www.e.leclerc/")
LECLERC_PROFILE_DIR = Path(
    os.getenv("LECLERC_PROFILE_DIR", str(SESSIONS_DIR / "leclerc_profile"))
)
LECLERC_CDP_URL = os.getenv("LECLERC_CDP_URL", "http://leclerc-gui:9222")
LECLERC_BACKEND_URL = os.getenv("LECLERC_BACKEND_URL", "http://backend:8000")
LECLERC_STORE_URL = os.getenv(
    "LECLERC_STORE_URL",
    "https://fd6-courses.leclercdrive.fr/magasin-175901-175901-seclin-lorival.aspx",
)


def is_datadome_block(page_html: str) -> bool:
    lowered = page_html.lower()
    return (
        "captcha-delivery.com" in lowered
        or "datadome" in lowered
        or "access blocked" in lowered
        or "unusual activity" in lowered
        or "captcha" in lowered
    )


def persistent_profile_exists(profile_dir: Path = LECLERC_PROFILE_DIR) -> bool:
    return profile_dir.exists()


def notify_backend_blocked(blocked_url: str | None, job_id: int | None = None) -> None:
    payload = {"blocked_url": blocked_url, "job_id": job_id}
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{LECLERC_BACKEND_URL}/leclerc/unblock/blocked",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        response.read()


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


_shared_browser = SharedLeclercBrowser()


def ensure_page() -> Page:
    return _shared_browser.ensure_page()


class LeclercBlocked(RuntimeError):
    def __init__(self, reason: str, artifacts: dict[str, str]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.artifacts = artifacts


def remove_listener_safe(emitter: Any, event_name: str, handler: Any) -> None:
    remover = getattr(emitter, "remove_listener", None)
    if callable(remover):
        try:
            remover(event_name, handler)
        except Exception:
            return
        return
    off = getattr(emitter, "off", None)
    if callable(off):
        try:
            off(event_name, handler)
        except Exception:
            return


def build_search_url(query: str, store_url: str = LECLERC_STORE_URL) -> str:
    parsed = urlparse(store_url)
    base = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else store_url.rstrip("/")
    encoded = quote_plus(query)
    return f"{base}/recherche.aspx?Texte={encoded}"


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
        blocked_job_id: int | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        retries: int = DEFAULT_RETRIES,
    ) -> None:
        self.page = page
        self.log_dir = log_dir or LOG_DIR
        self.sessions_dir = sessions_dir or SESSIONS_DIR
        self.timeout_ms = timeout_ms
        self.retries = retries
        self.profile_dir = Path(
            os.getenv("LECLERC_PROFILE_DIR", str(self.sessions_dir / "leclerc_profile"))
        )
        self.use_persistent_profile = persistent_profile_exists(self.profile_dir)
        self.logger = logging.getLogger(__name__)
        self.blocked_job_id = blocked_job_id

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

    def _capture_error_artifacts(self, label: str, error: Exception) -> dict[str, str]:
        self._ensure_dirs()
        timestamp = self._timestamp()
        screenshot_path = self.log_dir / f"leclerc_error_{timestamp}.png"
        html_path = self.log_dir / f"leclerc_error_{timestamp}.html"
        trace_path = self.log_dir / f"leclerc_trace_{timestamp}.zip"
        try:
            self.page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception:
            self.logger.exception("Failed to capture Leclerc screenshot")
        try:
            html_path.write_text(self.page.content(), encoding="utf-8")
        except Exception:
            self.logger.exception("Failed to capture Leclerc HTML")
        try:
            self.page.context.tracing.stop(path=str(trace_path))
        except Exception:
            trace_path = None
        self.logger.error("Leclerc error during %s: %s", label, error)
        payload = {"error_png": str(screenshot_path), "error_html": str(html_path)}
        if trace_path:
            payload["trace_zip"] = str(trace_path)
        return payload

    def _capture_blocked_artifacts(self, page_html: str) -> dict[str, str]:
        self._ensure_dirs()
        timestamp = self._timestamp()
        screenshot_path = self.log_dir / f"leclerc_blocked_{timestamp}.png"
        html_path = self.log_dir / f"leclerc_blocked_{timestamp}.html"
        try:
            blocked_url = self.page.url
        except Exception:
            blocked_url = None
        try:
            self.page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception:
            self.logger.exception("Failed to capture Leclerc blocked screenshot")
        try:
            html_path.write_text(page_html, encoding="utf-8")
        except Exception:
            self.logger.exception("Failed to capture Leclerc blocked HTML")
        payload = {"blocked_png": str(screenshot_path), "blocked_html": str(html_path)}
        if blocked_url:
            payload["blocked_url"] = blocked_url
        return payload

    @contextmanager
    def _network_capture(self, metadata: dict[str, Any] | None = None) -> Iterator[Path]:
        self._ensure_dirs()
        log_path = self.log_dir / f"leclerc_network_{self._timestamp()}.jsonl"
        log_file = log_path.open("a", encoding="utf-8")
        header = {
            "event": "start",
            "timestamp": self._timestamp(),
            "metadata": metadata or {},
        }
        log_file.write(json.dumps(header, ensure_ascii=False) + "\n")
        log_file.flush()

        def handle_response(response) -> None:
            try:
                request = response.request
                if request.resource_type not in {"xhr", "fetch", "document"}:
                    return
                content_type = response.headers.get("content-type", "")
                body = response.body()
                size = len(body)
                excerpt = None
                if request.resource_type in {"xhr", "fetch"}:
                    if content_type.startswith("text/") or "json" in content_type:
                        excerpt = body.decode(errors="replace")[:500]
                elif "text/html" in content_type:
                    excerpt = body.decode(errors="replace")[:300]
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
            remove_listener_safe(self.page, "response", handle_response)
            log_file.close()

    def _handle_cookie_banner(self) -> None:
        buttons = [
            "button:has-text('Tout accepter')",
            "button:has-text('Accepter tout')",
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
                self.logger.debug("Leclerc cookie accept attempt failed", exc_info=True)

        try:
            close_button = self.page.locator("button:has-text('Fermer')").first
            if close_button.is_visible(timeout=1000):
                close_button.click(timeout=1000)
        except Exception:
            self.logger.debug("Leclerc cookie close attempt failed", exc_info=True)

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
            self.logger.debug("Leclerc fallback search input failed", exc_info=True)
            return False

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

    def _extract_unit_price(self, text: str) -> str | None:
        import re

        match = re.search(r"(\d+[,.]\d{2}\s*€\s*/\s*\w+)", text)
        if match:
            return match.group(1).replace(",", ".")
        match = re.search(r"(\d+[,.]\d{2}\s*€/[\w]+)", text)
        if match:
            return match.group(1).replace(",", ".")
        return None

    def _parse_product_card(self, card, base_url: str) -> dict[str, Any] | None:
        try:
            title = None
            title_locator = card.locator(
                "h3, h2, .product-title, .product__title, [data-testid*='title'], "
                "a[title], [class*='libelle'], [class*='title'], [data-qa*='title']"
            ).first
            if title_locator.count():
                title = title_locator.inner_text().strip()
            if not title:
                link_text = card.locator("a").first.inner_text().strip()
                if link_text:
                    title = link_text
        except Exception:
            title = None

        try:
            raw_text = card.inner_text()
        except Exception:
            raw_text = ""

        price_text, price_value = self._extract_price(raw_text)
        if not price_text:
            try:
                price_locator = card.locator(
                    ".price, .product-price, [data-testid*='price']"
                ).first
                price_text = price_locator.inner_text().strip()
                _, price_value = self._extract_price(price_text)
            except Exception:
                price_text = None
        if not price_text:
            try:
                price_locator = card.locator("span:has-text('€'), div:has-text('€')").first
                price_text = price_locator.inner_text().strip()
                _, price_value = self._extract_price(price_text)
            except Exception:
                price_text = None

        if not title or not price_text:
            return None

        url = None
        try:
            href = card.locator("a").first.get_attribute("href")
            if href:
                if href.startswith("http"):
                    url = href
                else:
                    url = f"{base_url}{href}"
        except Exception:
            url = None

        retailer_product_id = None
        for attr in ("data-product-id", "data-productid", "data-id"):
            try:
                value = card.get_attribute(attr)
            except Exception:
                value = None
            if value:
                retailer_product_id = value
                break

        unit_price = self._extract_unit_price(raw_text)

        return {
            "title": title,
            "price": price_value if price_value is not None else price_text,
            "url": url,
            "retailer_product_id": retailer_product_id,
            "price_per_unit": unit_price,
        }

    def _parse_search_results(self, limit: int, base_url: str) -> list[dict[str, Any]]:
        selectors = [
            "article[data-product-id]",
            "article[data-testid*='product']",
            "div[data-product-id]",
            "li[data-product-id]",
            ".product",
            ".product-item",
            ".product-card",
            ".liste-produit",
            ".product-list",
            ".grid-produits",
            ".bloc-produit",
            ".product__item",
            "[class*='produit']",
        ]
        locator = self.page.locator(",".join(selectors))
        items: list[dict[str, Any]] = []
        count = locator.count()
        for index in range(min(count, limit)):
            card = locator.nth(index)
            item = self._parse_product_card(card, base_url)
            if item:
                items.append(item)

        if items:
            return items

        fallback_locator = self.page.locator("a:has-text('€')")
        fallback_count = fallback_locator.count()
        for index in range(min(fallback_count, limit)):
            link = fallback_locator.nth(index)
            try:
                text = link.inner_text()
            except Exception:
                continue
            price_text, price_value = self._extract_price(text)
            if not price_text:
                continue
            title = text.split("€")[0].strip()
            if not title:
                continue
            href = link.get_attribute("href")
            url = None
            if href:
                url = href if href.startswith("http") else f"{base_url}{href}"
            items.append(
                {
                    "title": title,
                    "price": price_value if price_value is not None else price_text,
                    "url": url,
                    "retailer_product_id": None,
                }
            )
        if items:
            return items

        price_locator = self.page.locator(r"text=/\d+[,.]\d{2}\s*€/").locator(
            "xpath=ancestor-or-self::*[.//a][1]"
        )
        price_count = price_locator.count()
        for index in range(min(price_count, limit)):
            container = price_locator.nth(index)
            try:
                raw_text = container.inner_text()
            except Exception:
                continue
            price_text, price_value = self._extract_price(raw_text)
            if not price_text:
                continue
            link_locator = container.locator("a").first
            title = None
            url = None
            try:
                title_locator = container.locator(
                    "a[title], [class*='libelle'], [class*='title'], [data-qa*='title']"
                ).first
                if title_locator.count():
                    title = title_locator.inner_text().strip()
            except Exception:
                title = None
            if not title:
                try:
                    title = link_locator.inner_text().strip()
                except Exception:
                    title = None
            try:
                href = link_locator.get_attribute("href")
                if href:
                    url = href if href.startswith("http") else f"{base_url}{href}"
            except Exception:
                url = None
            if not title:
                continue
            items.append(
                {
                    "title": title,
                    "price": price_value if price_value is not None else price_text,
                    "url": url,
                    "retailer_product_id": None,
                }
            )
        return items

    def _load_storage_state(self, account_type: str) -> Path | None:
        self._ensure_dirs()
        if self.use_persistent_profile:
            return None
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
        return storage_path

    def login(self, account_type: str = "bot") -> dict[str, Any]:
        self._ensure_dirs()
        storage_path = self._load_storage_state(account_type)
        try:
            self.page.goto(BASE_URL, timeout=self.timeout_ms)
        except Exception as error:
            self._capture_error_artifacts("login", error)
            return {"status": "error", "message": str(error)}

        if self._is_logged_in():
            if storage_path:
                self.page.context.storage_state(path=str(storage_path))
            return {"status": "restored", "storage_state": str(storage_path) if storage_path else None}

        self.logger.info("TODO: implement Leclerc login selectors for %s", account_type)
        # TODO: navigate to the login form and complete authentication.
        # TODO: fill email/password selectors once identified.

        if storage_path:
            try:
                self.page.context.storage_state(path=str(storage_path))
            except Exception:
                self.logger.exception("Failed to save Leclerc storage_state")
        return {"status": "pending", "storage_state": str(storage_path) if storage_path else None}

    def search(
        self, query: str, *, account_type: str = "bot", limit: int = 20
    ) -> dict[str, Any]:
        self._ensure_dirs()
        storage_path = self._load_storage_state(account_type)
        error_paths: dict[str, str] | None = None
        for attempt in range(1, self.retries + 2):
            with self._network_capture(
                {"query": query, "account_type": account_type, "limit": limit}
            ) as network_log:
                try:
                    store_url = LECLERC_STORE_URL
                    self.page.goto(
                        store_url,
                        timeout=self.timeout_ms,
                        wait_until="domcontentloaded",
                    )
                    self._handle_cookie_banner()
                    try:
                        self.page.wait_for_load_state("networkidle", timeout=4000)
                    except Exception:
                        self.page.wait_for_timeout(1000)
                    html = self.page.content()
                    if is_datadome_block(html):
                        blocked_paths = self._capture_blocked_artifacts(html)
                        blocked_url = blocked_paths.get("blocked_url")
                        try:
                            notify_backend_blocked(blocked_url, self.blocked_job_id)
                        except Exception:
                            self.logger.exception("Failed to notify Leclerc blocked state")
                        blocked_paths["network_log"] = str(network_log)
                        blocked_paths["instruction"] = (
                            "Ouvrir Leclerc GUI pour créer/rafraîchir la session."
                        )
                        raise LeclercBlocked("DATADOME_BLOCKED", blocked_paths)
                    used_input = self._search_with_input(query)
                    if not used_input:
                        search_url = build_search_url(query, store_url)
                        self.page.goto(
                            search_url,
                            timeout=self.timeout_ms,
                            wait_until="domcontentloaded",
                        )
                    self._handle_cookie_banner()
                    html = self.page.content()
                    if is_datadome_block(html):
                        blocked_paths = self._capture_blocked_artifacts(html)
                        blocked_url = blocked_paths.get("blocked_url")
                        try:
                            notify_backend_blocked(blocked_url, self.blocked_job_id)
                        except Exception:
                            self.logger.exception("Failed to notify Leclerc blocked state")
                        blocked_paths["network_log"] = str(network_log)
                        blocked_paths["instruction"] = (
                            "Ouvrir Leclerc GUI pour créer/rafraîchir la session."
                        )
                        raise LeclercBlocked("DATADOME_BLOCKED", blocked_paths)
                    try:
                        parsed = urlparse(store_url)
                        base_url = (
                            f"{parsed.scheme}://{parsed.netloc}"
                            if parsed.netloc
                            else store_url.rstrip("/")
                        )
                        items = self._parse_search_results(limit, base_url)
                    except Exception as error:
                        error_paths = self._capture_error_artifacts("search_parse", error)
                        items = []
                    noresults_paths: dict[str, str] | None = None
                    if not items:
                        self._ensure_dirs()
                        timestamp = self._timestamp()
                        noresults_png = self.log_dir / f"leclerc_noresults_{timestamp}.png"
                        noresults_html = self.log_dir / f"leclerc_noresults_{timestamp}.html"
                        try:
                            self.page.screenshot(path=str(noresults_png), full_page=True)
                        except Exception:
                            self.logger.exception("Failed to capture Leclerc noresults screenshot")
                        try:
                            noresults_html.write_text(self.page.content(), encoding="utf-8")
                        except Exception:
                            self.logger.exception("Failed to capture Leclerc noresults HTML")
                        noresults_paths = {
                            "noresults_png": str(noresults_png),
                            "noresults_html": str(noresults_html),
                        }
                    try:
                        final_url = self.page.url
                    except Exception:
                        final_url = None
                    try:
                        page_title = self.page.title()
                    except Exception:
                        page_title = None
                    if storage_path:
                        try:
                            self.page.context.storage_state(path=str(storage_path))
                        except Exception:
                            self.logger.exception("Failed to save Leclerc storage_state")
                    return {
                        "items": items,
                        "debug": {
                            "network_log": str(network_log),
                            "error_png": (error_paths or {}).get("error_png"),
                            "error_html": (error_paths or {}).get("error_html"),
                            "trace_zip": (error_paths or {}).get("trace_zip"),
                            "noresults_png": (noresults_paths or {}).get("noresults_png"),
                            "noresults_html": (noresults_paths or {}).get("noresults_html"),
                            "final_url": final_url,
                            "page_title": page_title,
                        },
                    }
                except LeclercBlocked:
                    raise
                except Exception as error:
                    error_paths = self._capture_error_artifacts("search", error)
                    try:
                        final_url = self.page.url
                    except Exception:
                        final_url = None
                    try:
                        page_title = self.page.title()
                    except Exception:
                        page_title = None
                    if attempt <= self.retries:
                        self.logger.warning("Retrying Leclerc search (%s/%s)", attempt, self.retries)
                        continue
                    return {
                        "items": [],
                        "debug": {
                            "network_log": str(network_log),
                            "error_png": (error_paths or {}).get("error_png"),
                            "error_html": (error_paths or {}).get("error_html"),
                            "trace_zip": (error_paths or {}).get("trace_zip"),
                            "noresults_png": None,
                            "noresults_html": None,
                            "final_url": final_url,
                            "page_title": page_title,
                        },
                    }
        return {
            "items": [],
            "debug": {
                "network_log": None,
                "error_png": None,
                "error_html": None,
                "trace_zip": None,
                "noresults_png": None,
                "noresults_html": None,
                "final_url": None,
                "page_title": None,
            },
        }

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


def search(page: Page, query: str, account_type: str = "bot", limit: int = 20) -> dict[str, Any]:
    return LeclercRetailer(page).search(query, account_type=account_type, limit=limit)


def clear_basket(page: Page) -> dict[str, Any]:
    return LeclercRetailer(page).clear_basket()


def fill_basket(page: Page, items: list[dict[str, Any]]) -> dict[str, Any]:
    return LeclercRetailer(page).fill_basket(items)


def read_recap(page: Page) -> dict[str, Any]:
    return LeclercRetailer(page).read_recap()

import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from playwright.sync_api import Page, sync_playwright

from db import (
    clear_unblock_state,
    fetch_next_job,
    mark_job_blocked,
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
)
from retailers.leclerc import LeclercRetailer, ensure_page
from leclerc_search import make_search_url

LOG_DIR = os.getenv("LOG_DIR", "/logs")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))
LECLERC_CDP_URL = os.getenv("LECLERC_CDP_URL", "http://127.0.0.1:9222")
LECLERC_STORE_URL = os.getenv("LECLERC_STORE_URL", "")
WORKER_HEALTH_PORT = int(os.getenv("WORKER_HEALTH_PORT", "9000"))
DEFAULT_LIMIT = int(os.getenv("LECLERC_SEARCH_LIMIT", "20"))
PLAYWRIGHT_LOCK = threading.Lock()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _json_response(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: int = 200):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def check_cdp_health() -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": None, "version": None}
    try:
        with urllib.request.urlopen(f"{LECLERC_CDP_URL}/json/version", timeout=3) as response:
            raw = response.read().decode("utf-8")
        payload["version"] = json.loads(raw) if raw else None
        payload["ok"] = True
    except Exception as error:
        payload["error"] = f"{error.__class__.__name__}: {error}"
    return payload


def _extract_leclerc_items(page: Page, limit: int) -> list[dict[str, Any]]:
    primary_items = page.evaluate(
        """
        (limit) => {
          const selectors = [
            "article",
            "li",
            "div[data-product]",
            "div[data-product-id]",
            "div[class*='product']",
            "div[class*='Produit']",
            "div[class*='produit']",
            "div[data-testid*='product']"
          ];
          const nodes = [];
          selectors.forEach(sel => {
            document.querySelectorAll(sel).forEach(el => nodes.push(el));
          });
          const uniqueNodes = Array.from(new Set(nodes));
          const seen = new Set();
          const items = [];
          for (const el of uniqueNodes) {
            if (items.length >= limit) break;
            const text = (el.innerText || "").replace(/\\s+/g, " ").trim();
            if (!text.includes("€")) continue;
            const linkEl = el.querySelector("a[href]");
            if (!linkEl) continue;
            const url = linkEl.href;
            if (seen.has(url)) continue;
            const nameEl = el.querySelector("h3, h2, .product-name, .product-title, a");
            const name = (nameEl ? nameEl.textContent : linkEl.textContent || "").trim();
            if (!name) continue;
            const priceMatch = text.match(/(\\d+[,.]\\d{2})\\s*€/);
            const unitMatch = text.match(/(\\d+[,.]\\d{2})\\s*€\\s*\\/\\s*[^\\s]+/i);
            const imgEl = el.querySelector("img");
            items.push({
              name,
              price: priceMatch ? priceMatch[0] : "",
              unit_price: unitMatch ? unitMatch[0] : "",
              url,
              img: imgEl ? imgEl.src : ""
            });
            seen.add(url);
          }
          return items.slice(0, limit);
        }
        """,
        limit,
    )
    if primary_items:
        return primary_items

    fallback_items = page.evaluate(
        """
        (limit) => {
          const items = [];
          const seen = new Set();
          const links = Array.from(document.querySelectorAll("a[href]"));
          for (const link of links) {
            if (items.length >= limit) break;
            const text = (link.textContent || "").replace(/\\s+/g, " ").trim();
            if (text.length < 3) continue;
            const container = link.closest("article, li, div");
            const containerText = (container ? container.innerText : link.textContent || "")
              .replace(/\\s+/g, " ").trim();
            if (!containerText.includes("€")) continue;
            const url = link.href;
            if (seen.has(url)) continue;
            const priceMatch = containerText.match(/(\\d+[,.]\\d{2})\\s*€/);
            const unitMatch = containerText.match(/(\\d+[,.]\\d{2})\\s*€\\s*\\/\\s*[^\\s]+/i);
            const imgEl = container ? container.querySelector("img") : null;
            items.push({
              name: text,
              price: priceMatch ? priceMatch[0] : "",
              unit_price: unitMatch ? unitMatch[0] : "",
              url,
              img: imgEl ? imgEl.src : ""
            });
            seen.add(url);
          }
          return items.slice(0, limit);
        }
        """,
        limit,
    )
    return fallback_items or []


def _dedupe_items(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        key = (item.get("url") or item.get("name") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def _safe_page_title(page: Page) -> str:
    try:
        return page.title()
    except Exception:
        return ""


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/health":
                _json_response(self, {"ok": True})
                return
            if parsed.path == "/ready":
                _json_response(self, {"ok": True, "cdp": check_cdp_health()})
                return
            if parsed.path == "/leclerc/search":
                self._handle_leclerc_search(parsed)
                return
            _json_response(self, {"ok": False, "message": "Not found"}, status=404)
        except Exception as error:
            _json_response(
                self,
                {"ok": False, "error": f"{error.__class__.__name__}: {error}"},
                status=200,
            )

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _handle_leclerc_search(self, parsed: urllib.parse.ParseResult) -> None:
        query_params = urllib.parse.parse_qs(parsed.query)
        query = (query_params.get("q") or [""])[0].strip()
        if not query:
            _json_response(self, {"ok": False, "message": "Missing query parameter: q"}, status=400)
            return
        limit_raw = (query_params.get("limit") or [str(DEFAULT_LIMIT)])[0]
        try:
            limit = max(1, min(int(limit_raw), 50))
        except ValueError:
            limit = DEFAULT_LIMIT

        if not LECLERC_STORE_URL:
            _json_response(self, {"ok": False, "message": "LECLERC_STORE_URL is not configured"}, status=500)
            return

        search_url = make_search_url(LECLERC_STORE_URL, query)
        start = time.monotonic()
        title = ""

        with PLAYWRIGHT_LOCK:
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.connect_over_cdp(LECLERC_CDP_URL)
                    context = browser.contexts[0] if browser.contexts else browser.new_context()
                    page = context.new_page()
                    page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(1200)
                    items = _extract_leclerc_items(page, limit)
                    title = _safe_page_title(page)
                    page.close()
                    browser.close()
            except Exception as error:
                _json_response(
                    self,
                    {
                        "ok": False,
                        "message": f"CDP unavailable: {error.__class__.__name__}: {error}",
                        "url": search_url,
                    },
                    status=503,
                )
                return

        unique_items = _dedupe_items(items, limit)
        timing_ms = int((time.monotonic() - start) * 1000)
        payload = {
            "ok": True,
            "query": query,
            "url": search_url,
            "count": len(unique_items),
            "items": unique_items,
            "debug": {"title": title, "timing_ms": timing_ms},
        }
        _json_response(self, payload)


def start_health_server():
    server = ThreadingHTTPServer(("0.0.0.0", WORKER_HEALTH_PORT), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logging.info("Worker health server on %s", WORKER_HEALTH_PORT)


def handle_leclerc_job(job: dict[str, Any]) -> None:
    job_id = int(job["id"])
    query = job["query"]
    retailer = None
    page = None
    try:
        with PLAYWRIGHT_LOCK:
            page = ensure_page()
            retailer = LeclercRetailer(
                page,
                job_id,
                on_block=lambda reason, url: mark_job_blocked(
                    job_id,
                    reason,
                    result={"reason": reason, "blocked_url": url},
                ),
                on_resume=lambda: mark_job_running(job_id),
            )
            result = retailer.search(query)
            mark_job_succeeded(job_id, {"items": result.items, "debug": result.debug})
            clear_unblock_state(job_id)
    except Exception as error:
        logging.exception("Leclerc search failed")
        if retailer:
            retailer.capture_artifacts("worker_error")
        mark_job_failed(job_id, str(error))


def handle_job(job: dict[str, Any]) -> None:
    retailer = (job["retailer"] or "").lower()
    if retailer != "leclerc":
        mark_job_failed(int(job["id"]), f"Unsupported retailer: {retailer}")
        return
    mark_job_running(int(job["id"]))
    handle_leclerc_job(job)


def job_loop() -> None:
    logging.info("Worker started")
    while True:
        job = fetch_next_job()
        if job:
            handle_job(job)
        else:
            time.sleep(POLL_INTERVAL)


def main() -> None:
    start_health_server()
    job_loop()


if __name__ == "__main__":
    main()

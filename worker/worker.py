import json
import logging
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from db import (
    clear_unblock_state,
    fetch_next_job,
    mark_job_blocked,
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
)
from retailers.leclerc import LeclercRetailer, ensure_page

LOG_DIR = os.getenv("LOG_DIR", "/logs")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))
LECLERC_CDP_URL = os.getenv("LECLERC_CDP_URL", "http://127.0.0.1:9222")
WORKER_HEALTH_PORT = int(os.getenv("WORKER_HEALTH_PORT", "9000"))

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


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if self.path not in {"/health", "/ready"}:
                _json_response(self, {"ok": False, "message": "Not found"}, status=404)
                return
            payload = {"ok": True}
            if self.path == "/ready":
                payload["cdp"] = check_cdp_health()
            _json_response(self, payload)
        except Exception as error:
            _json_response(
                self,
                {"ok": False, "error": f"{error.__class__.__name__}: {error}"},
                status=200,
            )

    def log_message(self, format: str, *args: Any) -> None:
        return


def start_health_server():
    server = HTTPServer(("0.0.0.0", WORKER_HEALTH_PORT), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logging.info("Worker health server on %s", WORKER_HEALTH_PORT)


def handle_leclerc_job(job: dict[str, Any]) -> None:
    job_id = int(job["id"])
    query = job["query"]
    retailer = None
    page = None
    try:
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

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from db import (
    clear_unblock_state,
    fetch_next_job,
    get_unblock_state,
    mark_job_blocked,
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
)
from retailers.leclerc import LeclercBlocked, LeclercRetailer, ensure_page, open_unblock_page

LOG_DIR = os.getenv("LOG_DIR", "/logs")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))
LECLERC_BACKEND_URL = os.getenv("LECLERC_BACKEND_URL", "http://backend:8000")
LECLERC_CDP_URL = os.getenv("LECLERC_CDP_URL", "http://leclerc-browser:9222")
UNBLOCK_POLL_INTERVAL = int(os.getenv("UNBLOCK_POLL_INTERVAL", "3"))
UNBLOCK_TIMEOUT = int(os.getenv("UNBLOCK_TIMEOUT", "900"))
MAX_BLOCK_RETRIES = int(os.getenv("MAX_BLOCK_RETRIES", "2"))
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
    payload: dict[str, Any] = {"ok": False, "message": "CDP unreachable", "version": None}
    try:
        with urllib.request.urlopen(f"{LECLERC_CDP_URL}/json/version", timeout=3) as response:
            raw = response.read().decode("utf-8")
        payload["version"] = json.loads(raw) if raw else None
        payload["ok"] = True
        payload["message"] = "CDP reachable"
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as error:
        payload["message"] = f"{error.__class__.__name__}: {error}"
    return payload


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in {"/health", "/ready"}:
            _json_response(self, {"ok": False, "message": "Not found"}, status=404)
            return
        payload = {"ok": True}
        if self.path == "/ready":
            payload["cdp"] = check_cdp_health()
        _json_response(self, payload)

    def log_message(self, format: str, *args: Any) -> None:
        return


def start_health_server():
    server = HTTPServer(("0.0.0.0", WORKER_HEALTH_PORT), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logging.info("Worker health server on %s", WORKER_HEALTH_PORT)


def notify_backend_blocked(job_id: int, url: str | None, reason: str) -> None:
    payload = json.dumps({"job_id": job_id, "url": url, "reason": reason}).encode("utf-8")
    request = urllib.request.Request(
        f"{LECLERC_BACKEND_URL}/leclerc/unblock/blocked",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        response.read()


def poll_unblock_status(job_id: int) -> bool:
    try:
        with urllib.request.urlopen(
            f"{LECLERC_BACKEND_URL}/leclerc/unblock/status", timeout=3
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("job_id") == job_id and payload.get("done") is True
    except Exception:
        state = get_unblock_state(job_id)
        return bool(state and state.get("done"))


def wait_for_unblock_done(job_id: int) -> bool:
    logging.info("Waiting for unblock done for job %s", job_id)
    deadline = time.time() + UNBLOCK_TIMEOUT
    while time.time() < deadline:
        if poll_unblock_status(job_id):
            return True
        time.sleep(UNBLOCK_POLL_INTERVAL)
    return False


def handle_leclerc_job(job: dict[str, Any]) -> None:
    job_id = int(job["id"])
    query = job["query"]
    block_attempts = 0
    while block_attempts <= MAX_BLOCK_RETRIES:
        try:
            page = ensure_page()
            retailer = LeclercRetailer(page)
            result = retailer.search(query)
            mark_job_succeeded(job_id, {"items": result.items, "debug": result.debug})
            clear_unblock_state(job_id)
            return
        except LeclercBlocked as error:
            block_attempts += 1
            logging.warning("Leclerc blocked on job %s", job_id)
            mark_job_blocked(
                job_id,
                error.reason,
                result={
                    "reason": error.reason,
                    "blocked_url": error.blocked_url,
                    "artifacts": error.artifacts,
                },
            )
            open_unblock_page(error.blocked_url)
            try:
                notify_backend_blocked(job_id, error.blocked_url, error.reason)
            except Exception:
                logging.exception("Failed to notify backend of blocked state")
            if not wait_for_unblock_done(job_id):
                mark_job_failed(job_id, "UNBLOCK_TIMEOUT", {"reason": "timeout"})
                return
            mark_job_running(job_id)
            continue
        except Exception as error:
            logging.exception("Leclerc search failed")
            mark_job_failed(job_id, str(error))
            return
    mark_job_failed(job_id, "BLOCK_RETRY_LIMIT")


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

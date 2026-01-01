import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import schedule
from playwright.sync_api import sync_playwright

from db import (
    delete_key_value,
    enqueue_job,
    fetch_all,
    fetch_one,
    get_key_value,
    mark_job_retrying,
    mark_job_running,
    set_key_value,
    update_job,
    update_job_blocked,
    utc_now,
)
from retailers import auchan, leclerc

LOG_DIR = Path(os.getenv("LOG_DIR", "/logs"))
SESSIONS_DIR = Path(os.getenv("SESSIONS_DIR", "/sessions"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))
JOB_RETRIES = int(os.getenv("JOB_RETRIES", "2"))
LECLERC_CDP_URL = os.getenv("LECLERC_CDP_URL", "http://127.0.0.1:9222")
LECLERC_CDP_VERSION_URL = f"{LECLERC_CDP_URL}/json/version"
LECLERC_CDP_HEALTH_PATH = SESSIONS_DIR / "leclerc_cdp_health.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _write_cdp_health(payload: dict[str, Any]) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = LECLERC_CDP_HEALTH_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(LECLERC_CDP_HEALTH_PATH)


def check_leclerc_cdp_health() -> tuple[bool, dict[str, Any]]:
    payload: dict[str, Any] = {
        "ok": False,
        "checked_at": int(time.time()),
        "message": "CDP health check not started",
        "version": None,
    }
    try:
        with urllib.request.urlopen(LECLERC_CDP_VERSION_URL, timeout=3) as response:
            raw = response.read().decode("utf-8")
        payload["version"] = json.loads(raw) if raw else None
        payload["ok"] = True
        payload["message"] = "CDP reachable"
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as error:
        payload["message"] = f"{error.__class__.__name__}: {error}"
    except Exception as error:
        payload["message"] = f"{error.__class__.__name__}: {error}"
    _write_cdp_health(payload)
    return payload["ok"], payload


def capture_artifacts(context, job_id: int, error: Exception):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time())
    trace_path = LOG_DIR / f"trace_{job_id}_{timestamp}.zip"
    screenshot_path = LOG_DIR / f"error_{job_id}_{timestamp}.png"
    try:
        context.tracing.stop(path=str(trace_path))
    except Exception:
        logging.exception("Failed to stop tracing")
    try:
        page = context.pages[0] if context.pages else None
        if page:
            page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception:
        logging.exception("Failed to capture screenshot")
    logging.error("Job %s failed: %s", job_id, error)


def compute_compare_result(basket_id: int):
    items = fetch_all(
        """
        SELECT bi.quantity, p.name, p.id AS product_id
        FROM basket_items bi
        JOIN products p ON p.id = bi.product_id
        WHERE bi.basket_id = ?
        """,
        (basket_id,),
    )
    stores = fetch_all("SELECT id, code, name FROM stores")
    totals = {store["code"]: {"total": 0.0, "loyalty_gain": 0.0} for store in stores}
    diffs = []

    for item in items:
        for store in stores:
            sp = fetch_one(
                """
                SELECT price, loyalty_gain
                FROM store_products
                WHERE store_id = ? AND product_id = ?
                """,
                (store["id"], item["product_id"]),
            )
            price = (sp["price"] if sp else 0.0) * item["quantity"]
            loyalty = (sp["loyalty_gain"] if sp else 0.0) * item["quantity"]
            totals[store["code"]]["total"] += price
            totals[store["code"]]["loyalty_gain"] += loyalty
        if len(stores) >= 2:
            sp_a = fetch_one(
                """
                SELECT price FROM store_products
                WHERE store_id = ? AND product_id = ?
                """,
                (stores[0]["id"], item["product_id"]),
            )
            sp_b = fetch_one(
                """
                SELECT price FROM store_products
                WHERE store_id = ? AND product_id = ?
                """,
                (stores[1]["id"], item["product_id"]),
            )
            diff = (sp_b["price"] if sp_b else 0.0) - (sp_a["price"] if sp_a else 0.0)
            diffs.append({"product": item["name"], "diff": diff})

    top_diffs = sorted(diffs, key=lambda d: abs(d["diff"]), reverse=True)[:8]

    summary = []
    for store in stores:
        total = totals[store["code"]]["total"]
        loyalty = totals[store["code"]]["loyalty_gain"]
        summary.append(
            {
                "store_code": store["code"],
                "store_name": store["name"],
                "total": round(total, 2),
                "loyalty_gain": round(loyalty, 2),
                "net_cost": round(total - loyalty, 2),
            }
        )

    return {"summary": summary, "top_diffs": top_diffs}


def handle_compare(job):
    result = compute_compare_result(job["payload"]["basket_id"])
    update_job(job["id"], "DONE", result=result)


def handle_refresh_product(job):
    product_id = job["payload"]["product_id"]
    update_job(job["id"], "DONE", result={"product_id": product_id, "status": "mocked"})


def handle_refresh_basket(job):
    basket_id = job["payload"]["basket_id"]
    update_job(job["id"], "DONE", result={"basket_id": basket_id, "status": "mocked"})


def handle_push_basket(job):
    basket_id = job["payload"]["basket_id"]
    store_code = job["payload"]["store_code"]
    update_job(
        job["id"],
        "DONE",
        result={"basket_id": basket_id, "store_code": store_code, "status": "mocked"},
    )


def handle_retailer_search(job):
    payload = job["payload"]
    store = (payload.get("store") or "").upper()
    if store != "LECLERC":
        update_job(job["id"], "FAILED", error=f"Unsupported store: {store}")
        return
    query = (payload.get("query") or "").strip()
    if not query:
        update_job(job["id"], "FAILED", error="Query is required")
        return
    account_type = payload.get("account_type") or "bot"
    limit = int(payload.get("limit") or 20)
    result: dict[str, Any] = {"items": [], "debug": {}}
    error_message: str | None = None
    blocked = False

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    if get_key_value("leclerc_gui_active") == "1":
        result = {
            "items": [],
            "reason": "GUI_ACTIVE",
            "debug": {
                "instruction": "Fermez l'onglet GUI puis cliquez sur 'J'ai terminé'.",
            },
        }
        update_job(job["id"], "FAILED", result=result, error="GUI_ACTIVE")
        return

    leclerc.LECLERC_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    cdp_ok, cdp_payload = check_leclerc_cdp_health()
    if not cdp_ok:
        logging.error("Leclerc CDP unavailable: %s", cdp_payload.get("message"))
        result = {
            "items": [],
            "reason": "LECLERC_CDP_UNAVAILABLE",
            "debug": {
                "instruction": "Ouvrir Leclerc (déblocage).",
                "cdp_health": cdp_payload,
            },
        }
        update_job(
            job["id"],
            "FAILED",
            result=result,
            error="Leclerc GUI/CDP non prêt",
        )
        return
    ws_endpoint = None
    if cdp_payload.get("version"):
        ws_endpoint = cdp_payload["version"].get("webSocketDebuggerUrl")
    logging.info("CDP ready%s", f" (ws: {ws_endpoint})" if ws_endpoint else "")
    page = leclerc.ensure_page()
    try:
        retailer = leclerc.LeclercRetailer(
            page,
            log_dir=LOG_DIR,
            sessions_dir=SESSIONS_DIR,
            blocked_job_id=job["id"],
        )
        result = retailer.search(query, account_type=account_type, limit=limit)
    except leclerc.LeclercBlocked as error:
        logging.warning("Leclerc blocked: %s", error.reason)
        blocked = True
        result = {
            "items": [],
            "reason": error.reason,
            "debug": error.artifacts,
        }
        error_message = error.reason
    except Exception as error:
        logging.exception("Leclerc search failed")
        error_message = str(error)

    if error_message:
        status = "BLOCKED" if error_message == "DATADOME_BLOCKED" else "FAILED"
        if status == "BLOCKED":
            blocked_url = (result.get("debug") or {}).get("blocked_url")
            blocked_at = utc_now()
            update_job_blocked(
                job["id"],
                error_message,
                blocked_url,
                blocked_at,
                result=result,
                error=error_message,
            )
            set_key_value("leclerc_blocked_job_id", str(job["id"]))
            if blocked_url:
                set_key_value("leclerc_unblock_url", blocked_url)
            set_key_value("leclerc_blocked", "1")
            set_key_value("leclerc_blocked_reason", error_message)
            set_key_value("leclerc_blocked_at", blocked_at)
        else:
            update_job(job["id"], status, result=result, error=error_message)
    else:
        update_job(job["id"], "DONE", result=result)
        set_key_value("leclerc_blocked", "0")
        delete_key_value("leclerc_unblock_url")
        delete_key_value("leclerc_blocked_reason")
        delete_key_value("leclerc_blocked_at")


def process_job(job):
    handlers = {
        "COMPARE_BASKET": handle_compare,
        "REFRESH_PRODUCT": handle_refresh_product,
        "REFRESH_BASKET": handle_refresh_basket,
        "PUSH_BASKET": handle_push_basket,
        "RETAILER_SEARCH": handle_retailer_search,
    }
    handler = handlers.get(job["type"])
    if not handler:
        update_job(job["id"], "FAILED", error="Unknown job type")
        return
    handler(job)


def run_playwright_job(job, runner):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=runner.storage_state)
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        try:
            page = context.new_page()
            runner(page)
        except Exception as error:
            capture_artifacts(context, job["id"], error)
            update_job(job["id"], "FAILED", error=str(error))
        else:
            update_job(job["id"], "DONE", result={"status": "completed"})
        finally:
            browser.close()


def job_loop():
    while True:
        retry_jobs = fetch_all(
            """
            SELECT id, type, payload
            FROM jobs
            WHERE retry_requested = 1
              AND status IN ('BLOCKED', 'FAILED')
            ORDER BY updated_at ASC
            LIMIT 5
            """
        )
        for job in retry_jobs:
            payload = json.loads(job["payload"])
            job["payload"] = payload
            mark_job_retrying(job["id"])
            attempt = 0
            while attempt <= JOB_RETRIES:
                try:
                    process_job(job)
                    break
                except Exception as error:
                    logging.exception("Retry job failed (attempt %s)", attempt + 1)
                    attempt += 1
                    if attempt > JOB_RETRIES:
                        update_job(job["id"], "FAILED", error=str(error))

        pending = fetch_all(
            """
            SELECT id, type, payload
            FROM jobs
            WHERE status = 'PENDING'
            ORDER BY created_at ASC
            LIMIT 5
            """
        )
        for job in pending:
            payload = json.loads(job["payload"])
            job["payload"] = payload
            mark_job_running(job["id"])
            attempt = 0
            while attempt <= JOB_RETRIES:
                try:
                    process_job(job)
                    break
                except Exception as error:
                    logging.exception("Job failed (attempt %s)", attempt + 1)
                    attempt += 1
                    if attempt > JOB_RETRIES:
                        update_job(job["id"], "FAILED", error=str(error))
        schedule.run_pending()
        time.sleep(POLL_INTERVAL)


def schedule_daily_refresh():
    def enqueue_refresh():
        six_months_ago = fetch_one(
            """
            SELECT datetime('now', '-6 months') as cutoff
            """
        )["cutoff"]
        products = fetch_all(
            """
            SELECT id FROM products
            WHERE updated_at IS NULL OR updated_at >= ?
            """,
            (six_months_ago,),
        )
        for product in products:
            enqueue_job("REFRESH_PRODUCT", {"product_id": product["id"]})

    schedule.every().day.at("05:00").do(enqueue_refresh)


def main():
    schedule_daily_refresh()
    logging.info("Worker started")
    job_loop()


if __name__ == "__main__":
    main()

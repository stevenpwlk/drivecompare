import json
import logging
import os
import time
from pathlib import Path

import schedule
from playwright.sync_api import sync_playwright

from db import enqueue_job, fetch_all, fetch_one, mark_job_running, update_job
from retailers import auchan, leclerc

LOG_DIR = Path(os.getenv("LOG_DIR", "/logs"))
SESSIONS_DIR = Path(os.getenv("SESSIONS_DIR", "/sessions"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))
JOB_RETRIES = int(os.getenv("JOB_RETRIES", "2"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


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


def process_job(job):
    handlers = {
        "COMPARE_BASKET": handle_compare,
        "REFRESH_PRODUCT": handle_refresh_product,
        "REFRESH_BASKET": handle_refresh_basket,
        "PUSH_BASKET": handle_push_basket,
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

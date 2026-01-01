import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .db import execute, fetch_all, fetch_one, insert_job
from .leclerc_state import (
    DEFAULT_LECLERC_FALLBACK_URL,
    clear_blocked_url,
    get_blocked_url,
    is_gui_active,
    set_gui_active,
)

app = FastAPI()
app.mount("/static", StaticFiles(directory="backend/app/static"), name="static")
templates = Jinja2Templates(directory="backend/app/templates")

LECLERC_STORE_URL = os.getenv(
    "LECLERC_STORE_URL",
    "https://fd6-courses.leclercdrive.fr/magasin-175901-175901-seclin-lorival.aspx",
)
LECLERC_PROFILE_DIR = Path(os.getenv("LECLERC_PROFILE_DIR", "/sessions/leclerc_profile"))


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    baskets = fetch_all(
        """
        SELECT b.id, b.name, b.created_at, COUNT(bi.id) AS item_count
        FROM baskets b
        LEFT JOIN basket_items bi ON bi.basket_id = b.id
        GROUP BY b.id
        ORDER BY b.created_at DESC
        """
    )
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "baskets": baskets,
        },
    )


@app.get("/products/search")
def search_products(q: str = ""):
    if not q:
        return []
    like = f"%{q.lower()}%"
    products = fetch_all(
        """
        SELECT p.id, p.name, p.brand, p.size, p.unit
        FROM products p
        WHERE lower(p.name) LIKE ? OR lower(p.brand) LIKE ?
        ORDER BY p.name
        LIMIT 30
        """,
        (like, like),
    )
    return JSONResponse(products)


@app.post("/baskets")
def create_basket(payload: dict[str, Any]):
    name = payload.get("name") or "Panier"
    items = payload.get("items", [])
    basket_id = execute(
        "INSERT INTO baskets (name, created_at) VALUES (?, datetime('now'))",
        (name,),
    )
    if items:
        from .db import execute_many

        insert_rows = [
            (
                basket_id,
                item.get("product_id"),
                item.get("quantity", 1),
            )
            for item in items
        ]
        execute_many(
            """
            INSERT INTO basket_items (basket_id, product_id, quantity)
            VALUES (?, ?, ?)
            """,
            insert_rows,
        )
    return {"id": basket_id, "name": name}


@app.post("/baskets/form")
def create_basket_form(
    name: str = Form("Panier"),
    product_id: int = Form(...),
    quantity: int = Form(1),
):
    basket_id = execute(
        "INSERT INTO baskets (name, created_at) VALUES (?, datetime('now'))",
        (name,),
    )
    execute(
        """
        INSERT INTO basket_items (basket_id, product_id, quantity)
        VALUES (?, ?, ?)
        """,
        (basket_id, product_id, quantity),
    )
    return RedirectResponse(url=f"/baskets/{basket_id}", status_code=303)


@app.get("/baskets")
def list_baskets():
    baskets = fetch_all(
        """
        SELECT b.id, b.name, b.created_at, COUNT(bi.id) AS item_count
        FROM baskets b
        LEFT JOIN basket_items bi ON bi.basket_id = b.id
        GROUP BY b.id
        ORDER BY b.created_at DESC
        """
    )
    return JSONResponse(baskets)


@app.get("/baskets/{basket_id}", response_class=HTMLResponse)
def get_basket(basket_id: int, request: Request):
    basket = fetch_one("SELECT id, name, created_at FROM baskets WHERE id = ?", (basket_id,))
    if not basket:
        raise HTTPException(status_code=404, detail="Basket not found")
    items = fetch_all(
        """
        SELECT bi.id, bi.quantity, p.name, p.brand, p.size, p.unit
        FROM basket_items bi
        JOIN products p ON p.id = bi.product_id
        WHERE bi.basket_id = ?
        ORDER BY p.name
        """,
        (basket_id,),
    )
    jobs = fetch_all(
        """
        SELECT id, type, status, created_at, updated_at
        FROM jobs
        WHERE json_extract(payload, '$.basket_id') = ?
        ORDER BY created_at DESC
        """,
        (basket_id,),
    )
    compare_job = fetch_one(
        """
        SELECT result
        FROM jobs
        WHERE json_extract(payload, '$.basket_id') = ?
          AND type = 'COMPARE_BASKET'
          AND status = 'DONE'
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (basket_id,),
    )
    compare_result = json.loads(compare_job["result"]) if compare_job else None
    return templates.TemplateResponse(
        "basket.html",
        {
            "request": request,
            "basket": basket,
            "items": items,
            "jobs": jobs,
            "compare_result": compare_result,
        },
    )


@app.post("/jobs/compare/{basket_id}")
def compare_basket(basket_id: int):
    basket = fetch_one("SELECT id FROM baskets WHERE id = ?", (basket_id,))
    if not basket:
        raise HTTPException(status_code=404, detail="Basket not found")
    job_id = insert_job("COMPARE_BASKET", {"basket_id": basket_id})
    return {"job_id": job_id}


@app.post("/jobs/push/{basket_id}")
async def push_basket(basket_id: int, request: Request, store_code: str | None = None):
    if not store_code:
        form = await request.form()
        store_code = form.get("store_code")
    if not store_code:
        raise HTTPException(status_code=400, detail="store_code is required")
    job_id = insert_job("PUSH_BASKET", {"basket_id": basket_id, "store_code": store_code})
    return {"job_id": job_id}


@app.post("/jobs/refresh/product/{product_id}")
def refresh_product(product_id: int):
    job_id = insert_job("REFRESH_PRODUCT", {"product_id": product_id})
    return {"job_id": job_id}


@app.post("/jobs/retailer-search")
def retailer_search(payload: dict[str, Any]):
    query = (payload.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    job_payload = {
        "store": "LECLERC",
        "account_type": "bot",
        "query": query,
        "limit": 20,
    }
    job_id = insert_job("RETAILER_SEARCH", job_payload)
    return {"job_id": job_id, "status": "PENDING"}


@app.get("/jobs/{job_id}")
def get_job(job_id: int):
    job = fetch_one(
        """
        SELECT id, type, status, payload, result, error, created_at, updated_at
        FROM jobs
        WHERE id = ?
        """,
        (job_id,),
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job["payload"] = json.loads(job["payload"] or "{}")
    job["result"] = json.loads(job["result"] or "{}")
    return JSONResponse(job)


@app.post("/jobs/{job_id}/retry")
def retry_job(job_id: int):
    job = fetch_one(
        """
        SELECT id, type, status, payload
        FROM jobs
        WHERE id = ?
        """,
        (job_id,),
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] not in {"FAILED", "BLOCKED"}:
        raise HTTPException(status_code=409, detail="Job is not retryable")
    payload = json.loads(job["payload"] or "{}")
    new_job_id = insert_job(job["type"], payload)
    return {"job_id": new_job_id, "status": "PENDING"}


@app.get("/leclerc/unblock")
def leclerc_unblock():
    try:
        blocked_url = get_blocked_url()
        target_url = blocked_url or LECLERC_STORE_URL or DEFAULT_LECLERC_FALLBACK_URL
        return RedirectResponse(target_url, status_code=302)
    except Exception:
        fallback = LECLERC_STORE_URL or DEFAULT_LECLERC_FALLBACK_URL
        return RedirectResponse(fallback, status_code=302)


@app.post("/leclerc/gui/active")
def set_leclerc_gui_active(payload: dict[str, Any]):
    active = bool(payload.get("active"))
    LECLERC_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    set_gui_active(active)
    return {"active": active}


@app.post("/leclerc/unblock/done")
def leclerc_unblock_done():
    clear_blocked_url()
    set_gui_active(False)
    return {"ok": True}


@app.post("/leclerc/blocked/clear")
def clear_leclerc_blocked():
    clear_blocked_url()
    return {"cleared": True}


@app.get("/leclerc/gui/status")
def get_leclerc_gui_status():
    return {"active": is_gui_active(), "blocked_url": get_blocked_url()}

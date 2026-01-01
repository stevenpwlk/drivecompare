import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .db import (
    create_job,
    fetch_job,
    get_active_unblock_state,
    mark_unblock_done,
    set_unblock_state,
)

app = FastAPI()
app.mount("/static", StaticFiles(directory="backend/app/static"), name="static")
templates = Jinja2Templates(directory="backend/app/templates")

LECLERC_GUI_PORT = int(os.getenv("LECLERC_GUI_PORT", "5801"))


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "leclerc_gui_port": LECLERC_GUI_PORT,
        },
    )

@app.get("/leclerc/unblock", response_class=HTMLResponse)
def leclerc_unblock_page(request: Request):
    return templates.TemplateResponse(
        "unblock.html",
        {
            "request": request,
            "leclerc_gui_port": LECLERC_GUI_PORT,
        },
    )


@app.post("/jobs/leclerc-search")
def leclerc_search(payload: dict[str, Any]):
    query = (payload.get("query") or payload.get("q") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    job_id = create_job("leclerc", query)
    return {"job_id": job_id, "status": "QUEUED"}


@app.get("/jobs/{job_id}")
def get_job(job_id: int):
    job = fetch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(job)


@app.post("/leclerc/unblock/blocked")
def leclerc_unblock_blocked(payload: dict[str, Any]):
    job_id = payload.get("job_id")
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    url = payload.get("url") or payload.get("blocked_url")
    reason = payload.get("reason") or payload.get("blocked_reason")
    set_unblock_state(int(job_id), url, reason, active=True, done=False)
    return {"ok": True}


@app.post("/leclerc/unblock/done")
def leclerc_unblock_done(payload: dict[str, Any]):
    job_id = payload.get("job_id")
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    mark_unblock_done(int(job_id))
    return {"ok": True, "job_id": job_id}


@app.get("/leclerc/unblock/status")
def leclerc_unblock_status():
    state = get_active_unblock_state()
    if not state:
        return {
            "blocked": False,
            "job_id": None,
            "unblock_url": None,
            "reason": None,
            "done": False,
            "updated_at": None,
        }
    return {
        "blocked": bool(state["active"]),
        "job_id": state["job_id"],
        "unblock_url": state["url"],
        "reason": state["reason"],
        "done": bool(state["done"]),
        "updated_at": state["updated_at"],
    }


@app.get("/health")
def health():
    return {"ok": True}

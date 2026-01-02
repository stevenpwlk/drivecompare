import os
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

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
PUBLIC_HOST = os.getenv("PUBLIC_HOST")


class UnblockPayload(BaseModel):
    job_id: int | None = None
    reason: str | None = None
    blocked_url: str | None = None


def _normalize_host(host: str | None) -> str | None:
    if not host:
        return None
    if ":" in host:
        return host.split(":")[0]
    return host


def _build_gui_url(request: Request | None) -> str:
    host = None
    if PUBLIC_HOST:
        parsed = urlparse(PUBLIC_HOST)
        if parsed.scheme and parsed.hostname:
            host = parsed.hostname
        else:
            host = PUBLIC_HOST
    if not host and request is not None:
        host = (
            request.headers.get("x-forwarded-host")
            or request.headers.get("host")
            or request.url.hostname
        )
    host = _normalize_host(host) or "localhost"
    return f"https://{host}:{LECLERC_GUI_PORT}"


def _build_unblock_response(state: dict[str, Any] | None, request: Request | None) -> dict[str, Any]:
    gui_url = _build_gui_url(request) if request is not None else _build_gui_url(None)
    if not state:
        return {
            "blocked": False,
            "job_id": None,
            "unblock_url": gui_url,
            "blocked_url": None,
            "reason": None,
            "done": False,
            "updated_at": None,
        }
    return {
        "blocked": bool(state["active"]),
        "job_id": state["job_id"],
        "unblock_url": gui_url,
        "blocked_url": state.get("url"),
        "reason": state.get("reason"),
        "done": bool(state["done"]),
        "updated_at": state["updated_at"],
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "leclerc_gui_url": _build_gui_url(request),
        },
    )


@app.get("/leclerc/unblock", response_class=HTMLResponse)
def leclerc_unblock_page(request: Request):
    state = get_active_unblock_state()
    return templates.TemplateResponse(
        "unblock.html",
        {
            "request": request,
            "leclerc_gui_url": _build_gui_url(request),
            "blocked_url": state["url"] if state else None,
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
def leclerc_unblock_blocked(payload: UnblockPayload | None = None):
    payload = payload or UnblockPayload()
    job_id = payload.job_id
    state = get_active_unblock_state()
    if not job_id and state:
        job_id = state["job_id"]
    if not job_id:
        return _build_unblock_response(state, None)
    url = payload.blocked_url or (state.get("url") if state else None)
    reason = payload.reason or (state.get("reason") if state else None)
    set_unblock_state(int(job_id), url, reason, active=True, done=False)
    return _build_unblock_response(get_active_unblock_state(), None)


@app.post("/leclerc/unblock/done")
def leclerc_unblock_done(payload: dict[str, Any] | None = None):
    payload = payload or {}
    job_id = payload.get("job_id")
    state = get_active_unblock_state()
    if not job_id and state:
        job_id = state["job_id"]
    if job_id:
        mark_unblock_done(int(job_id))
    return _build_unblock_response(get_active_unblock_state(), None)


@app.get("/leclerc/unblock/status")
def leclerc_unblock_status(request: Request):
    state = get_active_unblock_state()
    return _build_unblock_response(state, request)


@app.get("/health")
def health():
    return {"ok": True}

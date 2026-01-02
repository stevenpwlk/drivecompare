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
    get_unblock_state,
    init_db,
    reset_unblock_state,
    set_blocked,
    set_done,
)

app = FastAPI()
app.mount("/static", StaticFiles(directory="backend/app/static"), name="static")
templates = Jinja2Templates(directory="backend/app/templates")

LECLERC_GUI_PORT = int(os.getenv("LECLERC_GUI_PORT", "5801"))
LECLERC_GUI_SCHEME = os.getenv("LECLERC_GUI_SCHEME", "http")
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
    return f"{LECLERC_GUI_SCHEME}://{host}:{LECLERC_GUI_PORT}"


def _build_unblock_response(
    state: dict[str, Any] | None, request: Request | None
) -> dict[str, Any]:
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
    blocked = bool(state.get("blocked")) and bool(state.get("active"))
    unblock_url = gui_url if request is not None else state.get("unblock_url") or gui_url
    return {
        "blocked": blocked,
        "job_id": state.get("job_id"),
        "unblock_url": unblock_url,
        "blocked_url": state.get("blocked_url"),
        "reason": state.get("reason"),
        "done": bool(state.get("done")),
        "updated_at": state.get("updated_at"),
    }


@app.on_event("startup")
def startup() -> None:
    init_db()
    reset_unblock_state()


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
    state = get_unblock_state()
    return templates.TemplateResponse(
        "unblock.html",
        {
            "request": request,
            "leclerc_gui_url": _build_gui_url(request),
            "blocked_url": state.get("blocked_url") if state else None,
        },
    )


@app.post("/jobs/leclerc-search")
def leclerc_search(payload: dict[str, Any]):
    query = (payload.get("query") or payload.get("q") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    reset_unblock_state()
    job_id = create_job("leclerc", query)
    return {"job_id": job_id, "status": "QUEUED"}


@app.get("/jobs/{job_id}")
def get_job(job_id: int):
    job = fetch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(job)


@app.post("/leclerc/unblock/blocked")
def leclerc_unblock_blocked(request: Request, payload: UnblockPayload | None = None):
    payload = payload or UnblockPayload()
    if not payload.job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    gui_url = _build_gui_url(request)
    set_blocked(
        int(payload.job_id),
        payload.reason,
        payload.blocked_url,
        gui_url,
    )
    return _build_unblock_response(get_unblock_state(), request)


@app.post("/leclerc/unblock/done")
def leclerc_unblock_done(request: Request):
    set_done()
    return _build_unblock_response(get_unblock_state(), request)


@app.get("/leclerc/unblock/status")
def leclerc_unblock_status(request: Request):
    state = get_unblock_state()
    return _build_unblock_response(state, request)


@app.get("/health")
def health():
    return {"ok": True}
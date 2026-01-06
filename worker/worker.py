import json
import os
import time
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from retailers.leclerc import LeclercRetailer, ensure_page, CaptchaRequired


def _job_id() -> int:
    return int(time.time() * 1000)


def _leclerc():
    page = ensure_page()
    jid = _job_id()
    retailer = LeclercRetailer(page=page, job_id=jid)
    return retailer, page, jid


class HealthHandler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format, *args):
        return

    def do_GET(self):
        if self.path.startswith("/ready"):
            try:
                page = ensure_page()
                self._json(200, {"ok": True, "cdp": {"ok": True, "page_url": getattr(page, "url", None)}})
            except Exception as e:
                self._json(503, {"ok": False, "cdp": {"ok": False, "error": str(e)}})
            return

        if self.path.startswith("/leclerc/search"):
            self._handle_leclerc_search()
            return

        self._json(404, {"ok": False, "message": "not_found"})

    def do_POST(self):
        if self.path.startswith("/leclerc/login"):
            self._handle_leclerc_login()
            return
        self._json(404, {"ok": False, "message": "not_found"})

    def _handle_leclerc_search(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            query = (qs.get("q", [""])[0] or "").strip()
            limit = int(qs.get("limit", ["20"])[0])

            if not query:
                self._json(400, {"ok": False, "message": "missing_q"})
                return

            retailer, _page, jid = _leclerc()
            res = retailer.search(query=query, limit=limit)

            # The retailer may return either a SearchResult-like object or a plain dict.
            # Be explicit to avoid traps like dict.items (method) vs {"items": ...} (key).
            if isinstance(res, dict):
                items = res.get("items") or []
                debug = res.get("debug") or {}
            else:
                items = getattr(res, "items", []) or []
                debug = getattr(res, "debug", {}) or {}

            if not isinstance(items, list):
                debug = dict(debug or {})
                debug["warning"] = "items_not_a_list"
                debug["items_type"] = str(type(items))
                items = []
            self._json(200, {"ok": True, "query": query, "count": len(items), "items": items, "debug": debug, "job_id": jid})

        except CaptchaRequired as e:
            self._json(
                200,
                {
		    "ok": False,
       		    "message": "captcha_required",
   		    "stage": e.stage,
      	   	    "blocked_url": e.blocked_url,
        	    "unblock_url": e.unblock_url,
 	            "artifacts": e.artifacts,
	            "job_id": jid,
                },
            )
        except Exception as e:
            self._json(500, {"ok": False, "message": str(e), "trace": traceback.format_exc()})

    def _handle_leclerc_login(self):
        try:
            length = int(self.headers.get("content-length", "0") or "0")
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._json(400, {"ok": False, "message": "invalid_json"})
                return

            email = (data.get("email") or "").strip()
            password = data.get("password") or ""
            auth_url = data.get("auth_url")
            verify_url = data.get("verify_url")
            save_storage_state = bool(data.get("save_storage_state", True))

            if not email or not password:
                self._json(400, {"ok": False, "message": "missing_email_or_password"})
                return

            retailer, _page, jid = _leclerc()
            res = retailer.login(
                email=email,
                password=password,
                auth_url=auth_url,
                verify_url=verify_url,
                save_storage_state=save_storage_state,
            )
            res["job_id"] = jid
            self._json(200, res)

        except CaptchaRequired as e:
            self._json(
                200,
                {
                    "ok": False,
                    "message": "captcha_required",
                    "blocked_url": e.blocked_url,
                    "unblock_url": e.unblock_url,
                    "stage": getattr(e, "stage", None),
                    "artifacts": getattr(e, "artifacts", None),
                    "job_id": jid,
                },
            )
        except Exception as e:
            self._json(500, {"ok": False, "message": str(e), "trace": traceback.format_exc()})


def main():
    host = "0.0.0.0"
    port = int(os.getenv("WORKER_HEALTH_PORT", "9000"))
    httpd = HTTPServer((host, port), HealthHandler)
    print(f"[worker] listening on {host}:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()

import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from .db import init_db, get_unblock_state, reset_unblock_state, utcnow_iso

LECLERC_STORE_URL = os.getenv("LECLERC_STORE_URL", "")
LECLERC_STORE_LABEL = os.getenv("LECLERC_STORE_LABEL", "Leclerc")

app = FastAPI(title="DriveCompare API (POC)")

@app.on_event("startup")
def _startup():
    init_db()

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/leclerc/unblock", response_class=HTMLResponse)
def leclerc_unblock_page():
    # Page visible dans le navigateur GUI : l'utilisateur peut résoudre DataDome / captcha ici.
    html = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Leclerc – Unblock</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; padding: 24px; max-width: 900px; margin: auto; }}
    code {{ background: #f2f2f2; padding: 2px 6px; border-radius: 4px; }}
    .box {{ border: 1px solid #ddd; border-radius: 10px; padding: 16px; margin: 16px 0; }}
    a {{ word-break: break-all; }}
  </style>
</head>
<body>
  <h1>Leclerc – Déblocage (POC)</h1>
  <div class="box">
    <p>Ouvre le site Leclerc dans cet onglet, et résous le blocage (captcha / DataDome) si besoin.</p>
    <p><b>Magasin:</b> {LECLERC_STORE_LABEL}</p>
    <p><b>URL:</b> <a href="{LECLERC_STORE_URL}">{LECLERC_STORE_URL}</a></p>
    <p>Ensuite laisse cet onglet ouvert. Le worker se connecte à ce même navigateur via CDP.</p>
  </div>
  <div class="box">
    <p>État DB:</p>
    <pre id="state">chargement...</pre>
  </div>
  <script>
    async function refresh() {{
      const r = await fetch('/api/unblock/state');
      const j = await r.json();
      document.getElementById('state').textContent = JSON.stringify(j, null, 2);
    }}
    refresh();
    setInterval(refresh, 3000);
  </script>
</body>
</html>"""
    return HTMLResponse(html)

@app.get("/api/unblock/state")
def api_state():
    return get_unblock_state()

@app.post("/api/unblock/reset")
def api_reset():
    return reset_unblock_state()

@app.post("/api/unblock/active")
def api_set_active(active: bool = True):
    # endpoint pratique pour tests
    from .db import connect
    with connect() as con:
        con.execute("UPDATE leclerc_unblock_state SET active=?, updated_at=? WHERE id=1", (1 if active else 0, utcnow_iso()))
        con.commit()
    return get_unblock_state()

@app.get("/", include_in_schema=False)
def home():
    return HTMLResponse(
        """
        <!doctype html>
        <html><head><meta charset="utf-8"><title>DriveCompare</title></head>
        <body style="font-family:system-ui;max-width:900px;margin:40px auto;padding:0 16px">
          <h1>DriveCompare POC</h1>
          <ul>
            <li><a href="/docs">API Docs (Swagger)</a></li>
            <li><a href="/health">Health</a></li>
          </ul>
          <p>GUI Leclerc : http://&lt;HOST&gt;:5801/ (ou :5800)</p>
        </body></html>
        """
    )

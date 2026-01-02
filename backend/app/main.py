import json
import os
import urllib.error
import urllib.parse
import urllib.request
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from .db import init_db, get_unblock_state, reset_unblock_state, utcnow_iso
from .leclerc_search import make_search_url

LECLERC_STORE_URL = os.getenv("LECLERC_STORE_URL", "")
LECLERC_STORE_LABEL = os.getenv("LECLERC_STORE_LABEL", "Leclerc")
LECLERC_WORKER_URL = os.getenv("LECLERC_WORKER_URL", "http://worker:9000")

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
            <li><a href="/leclerc">Recherche Leclerc</a></li>
          </ul>
          <p>GUI Leclerc : http://&lt;HOST&gt;:5801/ (ou :5800)</p>
        </body></html>
        """
    )


@app.get("/api/leclerc/search")
def api_leclerc_search(q: str, limit: int = 20):
    if not q:
        raise HTTPException(status_code=400, detail="Missing query parameter: q")
    params = urllib.parse.urlencode({"q": q, "limit": limit})
    url = f"{LECLERC_WORKER_URL}/leclerc/search?{params}"
    try:
        with urllib.request.urlopen(url, timeout=45) as response:
            raw = response.read().decode("utf-8")
            payload = json.loads(raw) if raw else {}
            return JSONResponse(payload, status_code=response.status)
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8") if error.fp else ""
        payload = json.loads(raw) if raw else {"ok": False, "message": "Worker error"}
        return JSONResponse(payload, status_code=error.code)
    except Exception as error:
        return JSONResponse(
            {"ok": False, "message": f"Worker unavailable: {error}"},
            status_code=503,
        )


@app.get("/leclerc", response_class=HTMLResponse, include_in_schema=False)
def leclerc_search_page():
    search_url = make_search_url(LECLERC_STORE_URL, "coca") if LECLERC_STORE_URL else ""
    html = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Leclerc – Recherche</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; padding: 24px; max-width: 1100px; margin: auto; }}
    form {{ display: flex; gap: 12px; flex-wrap: wrap; }}
    input[type="text"] {{ flex: 1 1 320px; padding: 10px 12px; font-size: 16px; }}
    button {{ padding: 10px 16px; font-size: 16px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
    th, td {{ border-bottom: 1px solid #eee; padding: 8px; text-align: left; vertical-align: top; }}
    .error {{ background: #ffe3e3; border: 1px solid #f5b5b5; padding: 12px; margin: 16px 0; }}
    .meta {{ color: #666; font-size: 14px; margin-top: 8px; }}
  </style>
</head>
<body>
  <h1>Recherche magasin Leclerc</h1>
  <p class="meta">Magasin: <strong>{LECLERC_STORE_LABEL}</strong></p>
  <p class="meta">URL de base: <a href="{LECLERC_STORE_URL}">{LECLERC_STORE_URL}</a></p>
  <p class="meta">Exemple URL de recherche: <a href="{search_url}">{search_url}</a></p>

  <form id="search-form">
    <input type="text" id="query" name="q" placeholder="Ex: coca" required />
    <button type="submit">Rechercher</button>
  </form>

  <div id="status"></div>

  <table id="results" style="display:none;">
    <thead>
      <tr>
        <th>Produit</th>
        <th>Prix</th>
        <th>Prix/unité</th>
        <th>Lien</th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>

  <script>
    const form = document.getElementById('search-form');
    const status = document.getElementById('status');
    const table = document.getElementById('results');
    const tbody = table.querySelector('tbody');

    function setStatus(message, isError=false) {{
      status.innerHTML = message ? `<div class="${{isError ? 'error' : 'meta'}}">${{message}}</div>` : '';
    }}

    function renderItems(items) {{
      tbody.innerHTML = '';
      items.forEach(item => {{
        const row = document.createElement('tr');
        row.innerHTML = `
          <td>${{item.name || ''}}</td>
          <td>${{item.price || ''}}</td>
          <td>${{item.unit_price || ''}}</td>
          <td>${{item.url ? `<a href=\"${{item.url}}\" target=\"_blank\" rel=\"noopener\">ouvrir</a>` : ''}}</td>
        `;
        tbody.appendChild(row);
      }});
      table.style.display = items.length ? 'table' : 'none';
    }}

    form.addEventListener('submit', async (event) => {{
      event.preventDefault();
      const query = document.getElementById('query').value.trim();
      if (!query) return;
      setStatus('Recherche en cours...');
      renderItems([]);
      try {{
        const response = await fetch(`/api/leclerc/search?q=${{encodeURIComponent(query)}}`);
        const data = await response.json();
        if (!response.ok || !data.ok) {{
          setStatus(data.message || 'Erreur lors de la recherche', true);
          return;
        }}
        renderItems(data.items || []);
        setStatus(`Résultats: ${{data.count ?? 0}} – ${{
          data.debug && data.debug.timing_ms ? `temps ${{
            data.debug.timing_ms
          }} ms` : 'OK'
        }}`);
      }} catch (err) {{
        setStatus(`Erreur réseau: ${{err}}`, true);
      }}
    }});
  </script>
</body>
</html>"""
    return HTMLResponse(html)

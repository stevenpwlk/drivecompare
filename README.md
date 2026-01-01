# DriveCompare

DriveCompare est une application LAN pour lancer une recherche produit Leclerc via un worker Playwright **avec navigateur partagé**. Quand Leclerc bloque (DataDome/captcha), l'utilisateur ouvre un navigateur distant **HTTPS** pour résoudre le blocage, puis le job reprend automatiquement.

## Architecture

- **backend (FastAPI)**: API + UI simple (recherche, statut job, actions de déblocage).
- **worker (Playwright)**: exécute la recherche Leclerc, détecte les blocages, attend le "J'ai terminé".
- **leclerc-browser**: Chromium avec GUI noVNC HTTPS + CDP (port 9222). Le worker pilote **le même profil**.
- **SQLite**: base persistée dans `./data`.

## Comment ça marche (flow unblock)

1. L'utilisateur lance une recherche Leclerc.
2. Le worker démarre la navigation et détecte un éventuel blocage DataDome/captcha.
3. En cas de blocage:
   - le job passe en `BLOCKED`,
   - l'UI affiche "Blocage Leclerc: action requise",
   - le worker ouvre l'URL bloquée dans le navigateur partagé.
4. L'utilisateur ouvre `https://<IP>:5801`, résout le captcha/login.
5. L'utilisateur clique **"J'ai terminé"** dans l'UI.
6. Le worker reprend la navigation, collecte les résultats et passe le job en `SUCCEEDED`.

## Prérequis

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker
```

## Démarrage rapide

```bash
cp .env.example .env

docker compose run --rm backend python backend/init_db.py

docker compose up -d --build
```

UI: `http://<IP>:8000`

GUI Leclerc (HTTPS): `https://<IP>:5801`

## Endpoints principaux

- `POST /jobs/retailer-search` `{ retailer: "leclerc", query: "coca" }`
- `GET /jobs/{id}`
- `POST /leclerc/unblock/blocked` `{ job_id, url, reason }`
- `POST /leclerc/unblock/done` `{ job_id }`
- `GET /leclerc/unblock/status`
- `GET /health`

## Debug / Observabilité

- Logs worker: `./logs`
  - `leclerc_blocked_*.png/html` lors de blocage
  - `leclerc_noresults_*.png/html` si aucune carte produit
- Health checks:
  - `GET http://<IP>:8000/health`
  - `GET http://<IP>:9000/ready`
  - `GET http://<IP>:8000/leclerc/unblock/status`

## Smoke test

```bash
./tools/smoke_test.sh
```

## Configuration (extraits)

- `LECLERC_STORE_URL`: URL du magasin Leclerc cible.
- `LECLERC_STORE_LABEL`: label affiché dans les résultats.
- `LECLERC_GUI_PORT`: port HTTPS noVNC (par défaut 5801).
- `LECLERC_CDP_URL`: URL CDP interne (par défaut `http://leclerc-browser:9222`).
- `UNBLOCK_TIMEOUT`: délai d'attente max après "J'ai terminé".

## Dépannage rapide

- **CDP injoignable**: vérifiez que `leclerc-browser` est up et que le healthcheck est vert.
- **HTTPS seulement**: utilisez toujours `https://<IP>:5801`.
- **Blocage répété**: refaites la résolution captcha/login via la GUI.

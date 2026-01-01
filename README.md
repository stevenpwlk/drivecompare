# DriveCompare

DriveCompare est une application LAN pour lancer une recherche produit Leclerc via un worker Playwright **avec navigateur partagé**. Quand Leclerc bloque (DataDome/captcha), l'utilisateur ouvre un navigateur distant **HTTPS** pour résoudre le blocage, puis le job reprend automatiquement.

## Architecture

- **backend (FastAPI)**: API + UI simple (recherche, statut job, actions de déblocage).
- **worker (Playwright)**: exécute la recherche Leclerc, détecte les blocages, attend le "J'ai terminé".
- **leclerc-gui**: Chromium avec GUI noVNC HTTPS + CDP (port 9222). Le worker pilote **le même profil** (`/sessions/leclerc-profile`).
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
6. Le worker reprend la navigation, collecte les résultats et passe le job en `SUCCESS`.

## Prérequis

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker
```

## Install / run

```bash
cp .env.example .env

docker compose run --rm backend python backend/init_db.py

docker compose up -d --build
```

UI: `http://<IP>:8000`

GUI Leclerc (HTTPS uniquement): `https://<IP>:5801`

Sessions partagées: profil Chromium persisté dans `./sessions` (monté sur `/sessions/leclerc-profile`).

## Endpoints principaux

- `POST /jobs/leclerc-search` `{ query: "coca" }`
- `GET /jobs/{id}`
- `GET /leclerc/unblock` (page HTML)
- `POST /leclerc/unblock/blocked` `{ job_id, url, reason }`
- `POST /leclerc/unblock/done` `{ job_id }`
- `GET /leclerc/unblock/status`
- `GET /health`

## Debug / Observabilité

- Logs worker: `./logs/leclerc`
  - `leclerc_blocked_*.png/html` lors de blocage
  - `leclerc_noresults_*.png/html` si aucune carte produit
  - `leclerc_*_network.json` résumé réseau par échec
- Health checks:
  - `GET http://<IP>:8000/health`
  - `GET http://<IP>:9000/ready`
  - `GET http://<IP>:8000/leclerc/unblock/status`

## Diagnostic

```bash
./tools/status_services.sh
./tools/gui_https.sh
./tools/debug_cdp.sh
./tools/unblock_status.sh
```

## Smoke test

```bash
./tools/smoke_test.sh
```

## Résolution port conflict

Si un port est déjà utilisé sur la machine hôte :

1. Stoppez les services en conflit.
2. Ou modifiez le mapping dans `docker-compose.yml` (ex: `5801:5801` ➜ `5802:5801`).
3. Mettez à jour vos URL d'accès en conséquence.

## Configuration (extraits)

- `LECLERC_STORE_URL`: URL du magasin Leclerc cible.
- `LECLERC_STORE_LABEL`: label affiché dans les résultats.
- `LECLERC_GUI_PORT`: port HTTPS noVNC (par défaut 5801).
- `LECLERC_CDP_URL`: URL CDP interne (par défaut `http://leclerc-gui:9222`).
- `UNBLOCK_TIMEOUT`: délai d'attente max après "J'ai terminé".

## Comment débloquer DataDome

1. Lancez une recherche dans l'UI.
2. Quand le job passe en `BLOCKED`, ouvrez `https://<IP>:5801`.
3. Résolvez le captcha/login dans la GUI Leclerc.
4. Revenez sur l'UI et cliquez **"J'ai terminé"** (ou utilisez `/leclerc/unblock`).
5. Le worker relance automatiquement la collecte sur le même job.

## Dépannage rapide

- **CDP injoignable**: vérifiez que `leclerc-gui` est up et que le healthcheck est vert.
- **HTTPS seulement**: utilisez toujours `https://<IP>:5801` (pas d'accès HTTP).
- **Blocage répété**: refaites la résolution captcha/login via la GUI.

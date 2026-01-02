# DriveCompare

DriveCompare est une application LAN pour lancer une recherche produit Leclerc via un worker Playwright **avec navigateur partagé**. Quand Leclerc bloque (DataDome/captcha), l'utilisateur ouvre un navigateur distant **HTTPS** pour résoudre le blocage, puis le job reprend automatiquement.

## Architecture

- **backend (FastAPI)**: API + UI simple (recherche, statut job, actions de déblocage).
- **worker (Playwright)**: exécute la recherche Leclerc, détecte les blocages, attend le "J'ai débloqué".
- **leclerc-gui**: Chromium avec GUI HTTPS + CDP (port 9222) pour partager la session Leclerc (CDP accessible uniquement en localhost du conteneur).
- **SQLite**: base persistée dans `./data`.

## Comment ça marche (flow unblock)

1. L'utilisateur lance une recherche Leclerc.
2. Le worker démarre la navigation et détecte un éventuel blocage DataDome/captcha.
3. En cas de blocage:
   - l'UI affiche "Blocage Leclerc: action requise",
   - l'utilisateur ouvre la GUI et débloque DataDome.
4. L'utilisateur ouvre `https://<IP>:5801`, résout le captcha/login.
5. L'utilisateur clique **"J'ai débloqué"** dans l'UI.
6. Le worker reprend la navigation, collecte les résultats et passe le job en `SUCCESS`.

## Prérequis

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker
```

## Démarrage

1) `docker compose down --remove-orphans`
2) `docker compose up -d --build --remove-orphans`
3) ouvrir `http://<IP_LXC>:8000`
4) si bloqué, ouvrir `https://<IP_LXC>:5801` puis cliquer "J’ai débloqué"

## Endpoints principaux

- `POST /jobs/leclerc-search` `{ query: "coca" }`
- `GET /jobs/{id}`
- `GET /leclerc/unblock` (page HTML)
- `POST /leclerc/unblock/blocked` `{ job_id, blocked_url, reason }`
- `POST /leclerc/unblock/done` (aucun body requis)
- `GET /leclerc/unblock/status`
- `GET /health`

## Debug / Observabilité

- Logs worker: `./logs/leclerc/<job_id>`
  - `leclerc_blocked_*.png/html` lors de blocage
  - `leclerc_noresults_*.png/html` si aucune carte produit
  - `leclerc_*_network.json` résumé réseau par échec
- Health checks:
  - `GET http://<IP>:8000/health`
  - `GET http://<IP>:9000/ready`
  - `GET http://<IP>:8000/leclerc/unblock/status`
  - Depuis un conteneur: `curl http://127.0.0.1:9222/json/version` (dans `leclerc-gui`/`worker`)
  - Depuis l'hôte: pas besoin d'exposer le port 9222 (le CDP reste interne).

## Diagnostic

```bash
./tools/status_services.sh
./tools/gui_https.sh
./tools/debug_cdp.sh
./tools/unblock_status.sh
```

## Plan de test (5 commandes max)

```bash
./tools/status_services.sh
./tools/gui_https.sh
./tools/debug_cdp.sh
curl -sX POST http://localhost:8000/jobs/leclerc-search -H "Content-Type: application/json" -d '{"query":"coca"}'
./tools/unblock_status.sh
```

## Résolution port conflict

Si un port est déjà utilisé sur la machine hôte :

1. Stoppez les services en conflit.
2. Ou modifiez le mapping dans `docker-compose.yml` (ex: `5801:3001` ➜ `5802:3001`).
3. Mettez à jour vos URL d'accès en conséquence.

## Configuration (extraits)

- `LECLERC_STORE_URL`: URL du magasin Leclerc cible.
- `LECLERC_STORE_LABEL`: label affiché dans les résultats.
- `LECLERC_GUI_PORT`: port HTTPS noVNC (par défaut 5801).
- `LECLERC_CDP_URL`: URL CDP interne (par défaut `http://127.0.0.1:9222`).
- `UNBLOCK_TIMEOUT`: délai d'attente max après "J'ai débloqué".
- `PUBLIC_HOST`: host public utilisé pour générer l'URL noVNC (`https://<PUBLIC_HOST>:5801`).

## Comment débloquer DataDome

1. Lancez une recherche dans l'UI.
2. Quand l'UI signale un blocage, ouvrez `https://<IP>:5801`.
3. Résolvez le captcha/login dans la GUI Leclerc.
4. Revenez sur l'UI et cliquez **"J'ai débloqué"** (ou utilisez `/leclerc/unblock`).
5. Le worker relance automatiquement la collecte sur le même job.

## Dépannage rapide

- **CDP injoignable**: vérifiez que `leclerc-gui` est up et que le healthcheck est vert.
- **HTTPS seulement**: utilisez toujours `https://<IP>:5801` (pas d'accès HTTP).
- **Blocage répété**: refaites la résolution captcha/login via la GUI.

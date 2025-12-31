# drive-compare

Application locale (LAN) pour comparer les prix entre le drive Leclerc Seclin Lorival et Auchan Faches-Thumesnil.

## Fonctionnalités MVP

- Recherche produits + ajout panier local.
- Historique des paniers et comparaison.
- Jobs en base (COMPARE_BASKET, REFRESH_PRODUCT, REFRESH_BASKET, PUSH_BASKET).
- Worker Playwright (headless) avec scheduler quotidien à 05:00 (image Playwright officielle).
- SQLite en mode WAL.
- Sessions Playwright persistées dans `/sessions`.

## Pré-requis (Debian/Ubuntu/LXC Proxmox)

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker
```

## Démarrage rapide

1. Créez le fichier `.env` (ou copiez `.env.example`) et ajustez `PUBLIC_HOST` à l'IP LAN du serveur.

```bash
cp .env.example .env
```

2. Initialisez la base (SQLite).

```bash
docker compose run --rm backend python backend/init_db.py
```

3. Lancez les services.

```bash
docker compose up --build
```

4. Accédez à l'UI:

- http://localhost:8000/

## Notes

- Le docker-compose.yml n'utilise plus de clé `version:` (obsolète avec compose v2).

- Le worker utilise Playwright headless, avec des stubs pour les retailers.
- Les erreurs Playwright génèrent une capture d’écran + trace dans `/logs`.
- Les comptes bots/main sont gérés via `.env` (aucun secret dans le code).
- Leclerc nécessite un `LECLERC_STORE_URL` pointant vers le drive cible (par défaut Seclin Lorival).

## Debug Leclerc

Pour déclencher une recherche Leclerc via l'IHM :

1. Démarrez les services (`docker compose up --build`).
2. Ouvrez l'UI: `http://localhost:8000/`.
3. Lancez une recherche "Recherche produit" (ex: `coca`, `lait`, `pâtes`).

Où récupérer les artefacts (volume `/logs`) :

- Réseau: `/logs/leclerc_network_*.jsonl` (document + XHR/Fetch).
- Pas de résultats: `/logs/leclerc_noresults_*.png` et `/logs/leclerc_noresults_*.html`.
- Erreurs Playwright: `/logs/leclerc_error_*.png` et `/logs/leclerc_error_*.html`.

Le store Leclerc est configurable via `LECLERC_STORE_URL` (ex: autre drive en changeant l'URL dans `.env`).

## Leclerc: protection anti-bot (DataDome)

Leclerc peut renvoyer une page de blocage DataDome (`Access blocked` / `captcha-delivery.com`).
Dans ce cas, la recherche échoue en `FAILED` avec la raison `DATADOME_BLOCKED` et des artefacts sont générés:

- `/logs/leclerc_blocked_*.html`
- `/logs/leclerc_blocked_*.png`

### Session Leclerc via GUI (mobile-first)

Le worker reste en mode headless pour les recherches quotidiennes. Pour créer une session valide sur mobile (LAN):

A) Ouvrir DriveCompare sur mobile (`http://<IP>:8000`).

B) Cliquer sur **"Ouvrir Leclerc (session)"** (ouvre `http://<IP>:5800`).

C) Dans le navigateur distant:
   - Aller sur `LECLERC_STORE_URL`.
   - Accepter les cookies.
   - Passer DataDome si nécessaire.
   - Se connecter / choisir le magasin.

D) Fermer l’onglet, revenir sur DriveCompare et relancer la recherche.

La session est persistée dans `./sessions/leclerc_profile` et réutilisée par Playwright headless.

### Configuration leclerc-gui (Chromium)

Le service `leclerc-gui` expose une interface web sur `http://<IP>:5800`.
Pour éviter un accès libre sur le LAN, l'image `jlesage/chromium` supporte:

- `WEB_AUTHENTICATION=1`
- `WEB_AUTHENTICATION_USERNAME`
- `WEB_AUTHENTICATION_PASSWORD`

L'URL du bouton dans l'IHM est construite avec `PUBLIC_HOST` (ou `BACKEND_PUBLIC_BASE_URL` si défini).

Voir `.env.example` pour les variables disponibles.

### Dépannage

- Si DataDome réapparaît, refaire l'étape **Session Leclerc via GUI**.
- Si `http://<IP>:5800` n'est pas accessible, vérifiez:
  - que `leclerc-gui` est démarré (`docker compose ps`),
  - que `PUBLIC_HOST` pointe vers l'IP LAN du serveur,
  - que le port 5800 est ouvert sur le LAN.

### Validité

Si Leclerc rebloque l'accès, relancez simplement la session via le GUI pour régénérer la session.

## How to test manually

1. Démarrez les services avec `docker compose up --build`.
2. Ouvrez l'UI: `http://<IP>:8000`.
3. Lancez une recherche Leclerc (ex: "coca 1.5L").
4. Vérifiez que le job passe en SUCCESS et qu'au moins un produit est listé.
5. En cas d'échec, inspectez les artefacts Playwright dans `./logs` (captures et HTML).

## Test POC Leclerc

1. Démarrez les services.

```bash
docker compose up -d --build
```

2. Ouvrez l'UI: `http://<IP>:8000`.

3. Lancez une recherche "coca" via le formulaire "Recherche produit".

4. Vérifiez les logs réseau:

```bash
ls -lah ./logs
```

Le fichier `leclerc_network_*.jsonl` est créé dans `./logs` (volume Docker).

## Sanity checks

```bash
docker compose build --no-cache worker
docker compose up -d --build
docker compose ps
docker compose logs -f worker
```

## Structure

```
.
├── backend/            # FastAPI + templates
├── worker/             # Worker Playwright + scheduler
├── data/               # SQLite (volume local)
├── logs/               # traces/screenhots
├── sessions/           # storage_state JSON + profil Leclerc (leclerc_profile)
└── docker-compose.yml
```

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

1. Créez le fichier `.env` (ou copiez `.env.example`).

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

## Debug Leclerc

- Les captures réseau XHR/Fetch sont écrites dans `/logs/leclerc_network_*.jsonl`.
- En cas d'erreur, les fichiers `/logs/leclerc_error_*.png` et `/logs/leclerc_error_*.html` contiennent la capture d'écran et le HTML de la page.

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
├── sessions/           # storage_state JSON Playwright
└── docker-compose.yml
```

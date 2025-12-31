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
- Leclerc nécessite un `LECLERC_STORE_URL` pointant vers le drive cible (par défaut Seclin Lorival).

## Debug Leclerc

- Les captures réseau XHR/Fetch sont écrites dans `/logs/leclerc_network_*.jsonl`.
- En cas d'erreur, les fichiers `/logs/leclerc_error_*.png` et `/logs/leclerc_error_*.html` contiennent la capture d'écran et le HTML de la page.
- Le store Leclerc est configurable via `LECLERC_STORE_URL` (ex: autre drive en changeant l'URL dans `.env`).

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
├── sessions/           # storage_state JSON Playwright
└── docker-compose.yml
```

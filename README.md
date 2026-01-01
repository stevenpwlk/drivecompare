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

1. Créez le fichier `.env` (ou copiez `.env.example`) et ajustez au besoin `LECLERC_STORE_URL`.

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
Dans ce cas, la recherche échoue en `BLOCKED` avec la raison `DATADOME_BLOCKED` et des artefacts sont générés:

- `/logs/leclerc_blocked_*.html`
- `/logs/leclerc_blocked_*.png`

### Session Leclerc via GUI (mobile-first)

Le worker pilote **le même navigateur** que l'UI Leclerc (Chromium) via CDP. Pour créer une session valide sur mobile (LAN):

1. Ouvrir DriveCompare sur mobile (`http://<IP>:8000`).
2. Lancer une recherche Leclerc.
3. Si DataDome bloque, l'app affiche des liens pour ouvrir `http://<IP>:5800` (HTTP) ou `https://<IP>:5801` (HTTPS) dans le navigateur distant.
4. Tapez **Ouvrir Leclerc (déblocage)** pour ouvrir le navigateur distant (tap utilisateur requis sur mobile).
5. Dans le navigateur distant:
   - Passer le captcha/login.
   - Sélectionner le magasin si demandé (l'URL par défaut est `LECLERC_STORE_URL`).
6. Revenir sur DriveCompare et cliquer **J'ai terminé** pour libérer le verrou, effacer l'URL bloquée et relancer la recherche automatiquement.

La session est persistée dans `./sessions/leclerc_profile` et réutilisée par le worker via CDP.
Si le verrou `GUI_ACTIVE` est actif, le worker refuse le job Leclerc pour éviter la corruption du profil.
L'état Leclerc est stocké dans des fichiers `/sessions`:

- `leclerc_gui_active.lock`
- `leclerc_last_blocked_url.txt`

> Note: le presse-papier automatique peut nécessiter HTTPS côté navigateur distant. Sinon, utilisez le panneau clipboard si présent.

### Configuration leclerc-gui (Chromium)

Le service `leclerc-gui` expose une interface web sur `https://<IP>:5801` (HTTPS) et `http://<IP>:5800` (HTTP).
Il démarre en mode "app" sur `/leclerc/unblock`, qui redirige automatiquement vers la dernière URL bloquée
DataDome ou vers `LECLERC_STORE_URL`. Un port CDP interne est activé (9222) pour que le worker pilote le même navigateur.
Pour éviter un accès libre sur le LAN, l'image `lscr.io/linuxserver/chromium` supporte:

- `CUSTOM_USER`
- `PASSWORD`

Laissez ces variables absentes si vous ne souhaitez pas activer l'authentification.
Voir `.env.example` pour les variables disponibles.

### Fix leclerc-gui 500 (permissions /config)

Si `https://<IP>:5801` renvoie `Internal Server Error`, les permissions du profil Chromium sont
probablement incorrectes. Exécutez:

```bash
mkdir -p sessions/leclerc_profile
sudo chown -R 1000:1000 sessions/leclerc_profile
```

Ou utilisez le script:

```bash
./tools/fix_permissions.sh
```

### Diagnostic CDP

Vérifier que Chromium écoute bien sur le port CDP (9222) dans le conteneur:

```bash
docker compose exec leclerc-gui ss -lntp | grep 9222
docker compose exec leclerc-gui curl -s http://127.0.0.1:9222/json/version
```

### Dépannage

- Si DataDome réapparaît, refaire l'étape **Session Leclerc via GUI**.
- Si `https://<IP>:5801` n'est pas accessible, vérifiez:
  - que `leclerc-gui` est démarré (`docker compose ps`),
  - que le port 5801 est ouvert sur le LAN.

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
